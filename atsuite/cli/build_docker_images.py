#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from atsuite.pipeline import (
    CliOverrides,
    get_provider_spec,
    is_sandbox_config,
    resolve_benchmark,
    target_image_tag,
)
from atsuite.utils import run


def _repo_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "dockerfiles").is_dir() and (cwd / "benchmarks").is_dir():
        return cwd
    return Path(__file__).resolve().parents[2]


ROOT_DIR = _repo_root()
DOCKERFILES_DIR = ROOT_DIR / "dockerfiles"
DEFAULT_EXTRA_REQUIREMENTS = ["fastmcp", "mcp", "pydantic", "google-cloud-storage"]
DEFAULT_PIP_INDEX_URL = os.environ.get("ATSUITE_PIP_INDEX_URL", "https://mirrors.aliyun.com/pypi/simple/")
DEFAULT_PIP_TRUSTED_HOST = os.environ.get("ATSUITE_PIP_TRUSTED_HOST", "mirrors.aliyun.com")
CLOUD_DOCKER_PROVIDERS_WITH_PIP_BUILD_ARGS = {"ali", "aws_lambda", "aws_agentcore", "gcp", "mcp_gateway"}


def normalize_python_version(version: str, provider: str) -> str:
    """
    对于 aws_lambda 和 aws_agentcore，只取前两位版本号
    其他 provider 直接使用原始版本号
    """
    if provider in ("aws_lambda", "aws_agentcore"):
        parts = version.split(".")
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
    return version


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def read_requirements(path: Path) -> List[str]:
    if not path.exists():
        return []
    lines: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle.readlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    return lines


def default_pip_source_options() -> List[str]:
    index_url = DEFAULT_PIP_INDEX_URL.strip()
    trusted_host = DEFAULT_PIP_TRUSTED_HOST.strip()
    if not trusted_host and index_url:
        trusted_host = urlparse(index_url).hostname or ""

    options: List[str] = []
    if index_url:
        options.append(f"--index-url {index_url}")
    if trusted_host:
        options.append(f"--trusted-host {trusted_host}")
    return options


def has_pip_source_config(entries: Iterable[str]) -> bool:
    source_flags = ("--index-url ", "-i ", "--extra-index-url ", "--no-index", "--find-links ")
    return any(entry.startswith(source_flags) for entry in entries)


def write_requirements(dest: Path, base: Iterable[str]) -> None:
    unique: List[str] = []
    seen = set()
    entries = list(base)
    if not has_pip_source_config(entries):
        entries = [*default_pip_source_options(), *entries]
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        unique.append(entry)
    dest.write_text("\n".join(unique) + "\n", encoding="utf-8")


def pip_build_args_for_provider(docker_provider: str) -> tuple[Optional[str], Optional[str]]:
    if docker_provider not in CLOUD_DOCKER_PROVIDERS_WITH_PIP_BUILD_ARGS:
        return None, None
    return DEFAULT_PIP_INDEX_URL, DEFAULT_PIP_TRUSTED_HOST


def docker_buildx_available() -> bool:
    try:
        subprocess.run(
            ["docker", "buildx", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def build_node_image(
    tag: str,
    context_dir: Path,
    dockerfile: Path,
    *,
    python_version: str,
    provider: str,
    base_image: str,
    module_name: Optional[str] = None,
    name: Optional[str] = None,
    no_cache: bool = False,
    platform: Optional[str] = None,
    entrypoint: Optional[str] = None,
    pip_index_url: Optional[str] = None,
    pip_trusted_host: Optional[str] = None,
) -> None:
    # aws_agentcore prefers buildx for cross-platform ARM64 images, but some
    # Docker installs do not ship the buildx plugin. Fall back to docker build
    # because modern Docker still supports --platform in the classic command.
    wants_buildx = provider == "aws_agentcore"
    use_buildx = wants_buildx and docker_buildx_available()
    if wants_buildx and not use_buildx:
        print(
            "[build] docker buildx is unavailable; falling back to "
            "docker build --platform. Install buildx for more reliable "
            "cross-platform AWS AgentCore builds.",
            file=sys.stderr,
        )

    if use_buildx:
        cmd = ["docker", "buildx", "build", "-f", str(dockerfile)]
        if platform:
            cmd.extend(["--platform", platform])
    else:
        cmd = ["docker", "build", "-f", str(dockerfile)]
        # 必须传入 --platform，否则在 Apple Silicon 上默认 arm64，推到 Cloud Run（amd64）会 exec format error
        if platform:
            cmd.extend(["--platform", platform])

    if no_cache:
        cmd.append("--no-cache")
    if python_version:
        cmd.extend(["--build-arg", f"VERSION={python_version}"])
    if module_name:
        cmd.extend(["--build-arg", f"ATSUITE_NODE_MODULE={module_name}"])
    if name:
        cmd.extend(["--build-arg", f"ATSUITE_MCP_NAME={name}"])
    if base_image:
        cmd.extend(["--build-arg", f"BASE_IMAGE={base_image}"])
    if pip_index_url:
        cmd.extend(["--build-arg", f"PIP_INDEX_URL={pip_index_url}"])
    if pip_trusted_host:
        cmd.extend(["--build-arg", f"PIP_TRUSTED_HOST={pip_trusted_host}"])
    if entrypoint:
        cmd.extend(["--build-arg", f"ENTRYPOINT={entrypoint}"])
    cmd.extend(["--build-arg", f"PROVIDER={provider}"])
    cmd.extend(["-t", tag])
    if use_buildx:
        cmd.extend(["--load", str(context_dir)])
    else:
        cmd.append(str(context_dir))

    run(cmd)


def copy_runtime_support(target_dir: Path, docker_provider: str) -> None:
    shutil.copytree(ROOT_DIR / "atsuite_sdk", target_dir / "atsuite_sdk")
    if docker_provider == "ali":
        shutil.copy(
            ROOT_DIR / "atsuite" / "ali" / "oss.py", target_dir / "atsuite_sdk" / "oss.py"
        )
    elif docker_provider in ("aws_lambda", "aws_agentcore"):
        shutil.copy(ROOT_DIR / "atsuite" / "aws" / "s3.py", target_dir / "atsuite_sdk" / "s3.py")


IGNORE_NAMES = {"__pycache__", "sandbox-config.json"}


def copy_node_source(node_dir: Path, target_dir: Path) -> None:
    for item in node_dir.iterdir():
        if item.name in IGNORE_NAMES:
            continue
        destination = target_dir / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)


def build_resolved_targets(
    config_path: Path,
    provider: str,
    output: str,
    *,
    no_cache: bool = False,
    platform: Optional[str] = None,
    python_version: Optional[str] = None,
) -> None:
    overrides = CliOverrides(python_version=python_version)
    resolved = resolve_benchmark(config_path, provider, overrides)
    spec = resolved.provider
    platform = platform or spec.default_platform
    output_root = ROOT_DIR / output / resolved.bench_name
    output_root.mkdir(parents=True, exist_ok=True)

    bench_data_dir = resolved.bench_root / "data"
    if bench_data_dir.exists():
        shutil.copytree(bench_data_dir, output_root / "data", dirs_exist_ok=True)

    for target in resolved.targets.values():
        target_dir = output_root / target.name
        ensure_clean_dir(target_dir)
        pip_index_url, pip_trusted_host = pip_build_args_for_provider(
            spec.docker_provider
        )

        if target.family == "faas":
            node = resolved.nodes[target.node_names[0]]
            copy_node_source(node.dir, target_dir)
            copy_runtime_support(target_dir, spec.docker_provider)
            requirements = read_requirements(target_dir / "requirements.txt")
            if spec.docker_provider == "gcp":
                requirements.append("google-cloud-storage")
            elif spec.docker_provider == "ali":
                requirements.append("alibabacloud-oss-v2")
            elif spec.docker_provider in ("aws_lambda", "aws_agentcore"):
                requirements.append("boto3")
            requirements.append("pydantic")
            write_requirements(target_dir / "requirements.txt", requirements)
            manifest = {"allowed_tools": list(target.allowed_tools)}
            (target_dir / "atsuite-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if (target_dir / "init.sh").exists():
                env = dict(os.environ)
                env["ATSUITE_DATA_PATH"] = str(output_root / "data")
                run(
                    ["/bin/bash", str(target_dir / "init.sh"), str(target_dir)],
                    cwd=target_dir,
                    env=env,
                )
            dockerfile = (
                DOCKERFILES_DIR / spec.docker_provider / "function" / "Dockerfile"
            )
            normalized_version = normalize_python_version(
                target.build.python_version, provider
            )
            build_node_image(
                target_image_tag(resolved.bench_name, target),
                target_dir,
                dockerfile,
                python_version=normalized_version,
                provider=spec.runtime_provider,
                base_image=spec.base_image(normalized_version),
                module_name="implementation",
                name=target.name,
                no_cache=no_cache,
                platform=platform,
                pip_index_url=pip_index_url,
                pip_trusted_host=pip_trusted_host,
            )
        else:
            mcp_root = target_dir / "mcp"
            mcp_root.mkdir(parents=True, exist_ok=True)
            all_requirements = set(DEFAULT_EXTRA_REQUIREMENTS)
            if spec.docker_provider in ("aws_lambda", "aws_agentcore"):
                all_requirements.add("boto3")
            for node_name in target.node_names:
                node = resolved.nodes[node_name]
                node_target_dir = mcp_root / node.name
                node_target_dir.mkdir(parents=True, exist_ok=True)
                copy_node_source(node.dir, node_target_dir)
                all_requirements.update(
                    read_requirements(node.dir / "requirements.txt")
                )
                if (node_target_dir / "init.sh").exists():
                    env = dict(os.environ)
                    env["ATSUITE_DATA_PATH"] = str(output_root / "data")
                    run(
                        [
                            "/bin/bash",
                            str(node_target_dir / "init.sh"),
                            str(node_target_dir),
                        ],
                        cwd=node_target_dir,
                        env=env,
                    )
            write_requirements(
                target_dir / "requirements.txt", sorted(all_requirements)
            )
            allowed_tools = sorted(
                {
                    resolved.nodes[node_name].tool_name_for_trace(trace_name)
                    for node_name in target.node_names
                    for trace_name in resolved.nodes[node_name].trace_names
                }
            )
            (target_dir / "atsuite-manifest.json").write_text(
                json.dumps(
                    {"allowed_tools": allowed_tools}, ensure_ascii=False, indent=2
                )
                + "\n",
                encoding="utf-8",
            )
            copy_runtime_support(target_dir, spec.docker_provider)
            dockerfile = DOCKERFILES_DIR / spec.docker_provider / "mcp" / "Dockerfile"
            normalized_version = normalize_python_version(
                target.build.python_version, provider
            )
            build_node_image(
                target_image_tag(resolved.bench_name, target),
                target_dir,
                dockerfile,
                python_version=normalized_version,
                provider=spec.runtime_provider,
                base_image=spec.base_image(normalized_version),
                module_name="implementation",
                name=target.name,
                no_cache=no_cache,
                platform=platform,
                pip_index_url=pip_index_url,
                pip_trusted_host=pip_trusted_host,
            )

        print(f"Built image: {target_image_tag(resolved.bench_name, target)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build benchmark docker images from unified config."
    )
    parser.add_argument("--config", required=True, help="Build config JSON path")
    parser.add_argument(
        "--provider",
        required=True,
        choices=[
            "ali_fc",
            "aws_lambda",
            "gcp_faas",
            "ali_agentrun",
            "aws_agentcore",
            "gcp_mcp",
            "mcp_gateway",
        ],
        help="Provider name",
    )
    parser.add_argument(
        "--output", default="dist", help="Output directory name under repo root"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Pass --no-cache to docker build"
    )
    parser.add_argument(
        "--platform", default=None, help="Target platform for docker build"
    )
    parser.add_argument(
        "--python-version", default=None, help="Override python version"
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    if is_sandbox_config(config_path):
        raise SystemExit("Sandbox configs are no longer supported; use an external MCP-Gateway target instead")

    build_resolved_targets(
        config_path,
        args.provider,
        args.output,
        no_cache=args.no_cache,
        platform=args.platform,
        python_version=args.python_version,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc.cmd}", file=sys.stderr)
        raise SystemExit(exc.returncode)
