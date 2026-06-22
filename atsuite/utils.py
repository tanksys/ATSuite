import os
import subprocess
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

OUT_DIR = Path("url_results")


def run(cmd: List[str], *, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def _coerce_trace_value(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _coerce_trace_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_coerce_trace_value(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return v
        if s[0] in "[{":
            try:
                parsed = json.loads(s)
                return _coerce_trace_value(parsed)
            except json.JSONDecodeError:
                return v
        if s in ("true", "false", "null"):
            return json.loads(s)
        if s.isdigit() or (s.startswith("-") and len(s) > 1 and s[1:].isdigit()):
            try:
                return int(s)
            except ValueError:
                pass
        return v
    return v


def parse_arguments(input, uid: str) -> dict:
    if not input:
        return {"uid": uid}

    out: Dict[str, Any] = {}
    for k, v in input.items():
        # bool 是 int 子类，得早于 int 判断
        if isinstance(v, (bool, int, float, str)):
            out[k] = v
        elif isinstance(v, (dict, list)):
            out[k] = _coerce_trace_value(v)
        else:
            out[k] = v
    out["uid"] = uid
    return out


def cleaner(
    provider: str,
    bucket_name: str,
    toclean: set,
    uid: str,
    *,
    url_map: Optional[Dict[str, Any]] = None,
    bench_name: str = "",
) -> float:
    provider = normalize_provider_storage(provider)
    size = 0.0
    if provider == "ali":
        bucket_name = "atsuite11"
        from atsuite.ali.oss import AliOSS
        oss = AliOSS(bucket_name)
        for service_name in toclean:
            size += oss.getobjsize(f"{service_name}/{uid}.json")
            oss.deleteobj(f"{service_name}/{uid}.json")
    elif provider == "gcp":
        from atsuite.gcp.gcp import GCP
        gcp = GCP()
        storage = gcp.get_storage_client()
        for service_name in toclean:
            size += storage.getobjsize(bucket_name, f"{service_name}/{uid}.json")
            storage.deleteobj(bucket_name, f"{service_name}/{uid}.json")
    elif provider == "aws":
        import boto3
        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        for service_name in toclean:
            key = f"{service_name}/{uid}.json"
            try:
                resp = s3.head_object(Bucket=bucket_name, Key=key)
                size += resp["ContentLength"] / (1024 ** 3)
            except Exception:
                pass
            try:
                s3.delete_object(Bucket=bucket_name, Key=key)
            except Exception as e:
                print(f"[cleaner] Error deleting s3://{bucket_name}/{key}: {e}")
    else:
        print(f"{provider} storage clean is not implemented yet.")

    return size


def load_json(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"JSON file not found: {path}") from None
    except IsADirectoryError:
        raise SystemExit(f"Expected JSON file but found directory: {path}") from None
    except OSError as exc:
        raise SystemExit(f"Failed to read JSON file {path}: {exc}") from exc

    if not raw.strip():
        raise SystemExit(f"Invalid JSON in {path}: file is empty")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Invalid JSON in {path}: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from None


def resolve_benchmark_root(config_path: Path) -> Path:
    parent = config_path.parent
    if parent.name == "config":
        return parent.parent
    return parent


def resolve_trace_path(bench_root: Path, trace_file: str) -> Path:
    raw = str(trace_file or "").strip()
    if not raw:
        raise SystemExit("Missing trace_file in config")
    if raw.startswith("./"):
        raw = raw[2:]
    path = Path(raw)
    if not path.is_absolute():
        path = bench_root / path
    return path.resolve()


def resolve_node_dir(bench_root: Path, entry: Dict[str, Any]) -> Path:
    node_dir = entry.get("dir")
    if node_dir:
        return (bench_root / node_dir).resolve()
    return (bench_root / "nodes" / entry["name"]).resolve()


def normalize_node_name(name: str) -> str:
    return name.replace(".", "_").lower()


def get_service_name(tool_name: str) -> str:
    pos = tool_name.find('_')
    if pos != -1:
        return tool_name[:pos]
    return tool_name


def normalize_provider_storage(provider: str) -> str:
    key = str(provider).strip().lower()
    if key.startswith("ali"):
        return "ali"
    if key.startswith("gcp"):
        return "gcp"
    if key.startswith("aws"):
        return "aws"
    return key


def write_url_map(config_path: Path, payload: Dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUT_DIR / config_path.name
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return output_path


def _create_scaling_configs(provider: str, function_name: str, num: int = 1) -> None:
    if normalize_provider_storage(provider) != "ali":
        return
    try:
        from atsuite.ali.ali import Ali

        ali = Ali()
        client = ali.get_fc_client()
        ali.create_scalingconfig(client, function_name.lower(), num)
    except Exception as e:
        print(f"[invoker] Scaling config create failed: {e}")


def _cleanup_scaling_configs(provider: str, function_name: str) -> None:
    if normalize_provider_storage(provider) != "ali":
        return
    try:
        from atsuite.ali.ali import Ali

        ali = Ali()
        client = ali.get_fc_client()
        ali.delete_scalingconfig(client, function_name.lower())
    except Exception as e:
        print(f"[invoker] Scaling config cleanup failed: {e}")
