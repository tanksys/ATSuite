from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from atsuite_sdk.workflow import Trace
from atsuite.scheduler import STATELESS_ACCESS, ToolAccess, VALID_ACCESS_MODES
from atsuite.utils import load_json, resolve_benchmark_root, resolve_trace_path


TRACE_TOOL_TYPES = {"tool_use"}
LEGACY_TRACE_TOOL_TYPES = {"tool", "mcp", "function", "sandbox"}
DEFAULT_RUNTIME_CONFIG = {"cpu": 1, "memory": 1024, "disk": 512, "timeout": 30}


@dataclass(frozen=True)
class RuntimeConfig:
    cpu: int = 1
    memory: int = 1024
    disk: int = 512
    timeout: int = 30

    @classmethod
    def from_dict(cls, payload: Optional[Mapping[str, Any]], fallback: Optional["RuntimeConfig"] = None) -> "RuntimeConfig":
        base = fallback or cls()
        data = dict(payload or {})
        return cls(
            cpu=int(data.get("cpu", base.cpu)),
            memory=int(data.get("memory", base.memory)),
            disk=int(data.get("disk", base.disk)),
            timeout=int(data.get("timeout", base.timeout)),
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "cpu": self.cpu,
            "memory": self.memory,
            "disk": self.disk,
            "timeout": self.timeout,
        }


@dataclass(frozen=True)
class BuildConfig:
    python_version: str = ""

    @classmethod
    def from_dict(cls, payload: Optional[Mapping[str, Any]], fallback: Optional["BuildConfig"] = None) -> "BuildConfig":
        base = fallback or cls()
        data = dict(payload or {})
        python_version = str(data.get("python_version", base.python_version)).strip() or base.python_version
        return cls(python_version=python_version)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    family: str
    docker_provider: str
    analyzer_provider: str
    storage_provider: str
    runtime_provider: str
    observability_provider: str = ""
    default_platform: Optional[str] = None

    def base_image(self, python_version: str) -> str:
        if self.docker_provider == "ali":
            return f"alibaba-cloud-linux-3-registry.cn-hangzhou.cr.aliyuncs.com/alinux3/python:{python_version}"
        if self.docker_provider == "aws_lambda":
            return f"public.ecr.aws/lambda/python:{python_version}"
        if self.docker_provider in {"gcp", "aws_agentcore", "mcp_gateway"}:
            return f"python:{python_version}-slim"
        raise ValueError(f"Unsupported docker provider: {self.docker_provider}")


@dataclass(frozen=True)
class NodeDefinition:
    name: str
    dir: Path
    trace_names: tuple[str, ...]
    trace_to_tool: Dict[str, str]
    trace_access: Dict[str, ToolAccess]
    build: BuildConfig
    function_build: BuildConfig
    mcp_build: BuildConfig
    function_defaults: Dict[str, RuntimeConfig]
    mcp_defaults: RuntimeConfig

    def has_trace_name(self, trace_name: str) -> bool:
        return trace_name in self.trace_names

    def tool_name_for_trace(self, trace_name: str) -> str:
        return self.trace_to_tool[trace_name]

    def is_stateful_trace(self, trace_name: str) -> bool:
        return self.access_for_trace(trace_name).is_stateful

    def access_for_trace(self, trace_name: str) -> ToolAccess:
        return self.trace_access.get(trace_name, ToolAccess())


@dataclass(frozen=True)
class ResolvedTarget:
    name: str
    family: str
    node_names: tuple[str, ...]
    trace_names: tuple[str, ...]
    build: BuildConfig
    runtime: RuntimeConfig
    allowed_tools: tuple[str, ...]

    @property
    def image_kind(self) -> str:
        return "function" if self.family == "faas" else "mcp"


@dataclass(frozen=True)
class TraceRoute:
    trace_name: str
    node_name: str
    target_name: str
    family: str
    tool_name: str
    domain: str = ""
    access: str = STATELESS_ACCESS

    @property
    def tool_access(self) -> ToolAccess:
        return ToolAccess.from_values(self.domain, self.access)


@dataclass(frozen=True)
class ResolvedBenchmark:
    config_path: Path
    bench_root: Path
    bench_name: str
    trace_path: Path
    trace: Trace
    provider: ProviderSpec
    nodes: Dict[str, NodeDefinition]
    targets: Dict[str, ResolvedTarget]
    routes: Dict[str, TraceRoute]

    @property
    def family(self) -> str:
        return self.provider.family


def normalize_tool_name(name: str) -> str:
    return name.replace(".", "_").lower()


def is_sandbox_config(config_path: Path) -> bool:
    config = load_json(config_path)
    nodes = config.get("nodes") or []
    return any(str(node.get("type", "")).strip() == "sandbox" for node in nodes if isinstance(node, dict))


PROVIDERS: Dict[str, ProviderSpec] = {
    "ali_fc": ProviderSpec(
        name="ali_fc",
        family="faas",
        docker_provider="ali",
        analyzer_provider="ali",
        storage_provider="ali",
        runtime_provider="ali_fc",
        observability_provider="ali_sls",
    ),
    "aws_lambda": ProviderSpec(
        name="aws_lambda",
        family="faas",
        docker_provider="aws_lambda",
        analyzer_provider="aws_lambda",
        storage_provider="aws_lambda",
        runtime_provider="aws_lambda",
        observability_provider="aws_lambda_cloudwatch",
    ),
    "gcp_faas": ProviderSpec(
        name="gcp_faas",
        family="faas",
        docker_provider="gcp",
        analyzer_provider="gcp",
        storage_provider="gcp",
        runtime_provider="gcp_faas",
        observability_provider="gcp_cloud_logging",
        default_platform="linux/amd64",
    ),
    "ali_agentrun": ProviderSpec(
        name="ali_agentrun",
        family="session",
        docker_provider="ali",
        analyzer_provider="ali",
        storage_provider="ali",
        runtime_provider="ali_agentrun",
        observability_provider="ali_sls",
    ),
    "aws_agentcore": ProviderSpec(
        name="aws_agentcore",
        family="session",
        docker_provider="aws_agentcore",
        analyzer_provider="aws_agentcore",
        storage_provider="aws_agentcore",
        runtime_provider="aws_agentcore",
        observability_provider="aws_agentcore_cloudwatch",
        default_platform="linux/arm64",
    ),
    "gcp_mcp": ProviderSpec(
        name="gcp_mcp",
        family="session",
        docker_provider="gcp",
        analyzer_provider="gcp",
        storage_provider="gcp",
        runtime_provider="gcp_mcp",
        observability_provider="gcp_cloud_logging",
        default_platform="linux/amd64",
    ),
    "mcp_gateway": ProviderSpec(
        name="mcp_gateway",
        family="session",
        docker_provider="mcp_gateway",
        analyzer_provider="",
        storage_provider="mcp_gateway",
        runtime_provider="mcp_gateway",
        observability_provider="mcp_gateway",
    ),
}


def get_provider_spec(provider: str) -> ProviderSpec:
    key = str(provider).strip().lower()
    if key not in PROVIDERS:
        raise SystemExit(f"Unsupported provider: {provider}")
    return PROVIDERS[key]


def provider_storage_name(provider: str) -> str:
    key = str(provider).strip().lower()
    if key.startswith("ali"):
        return "ali"
    if key.startswith("gcp"):
        return "gcp"
    if key.startswith("aws"):
        return "aws"
    if key == "mcp_gateway":
        return "mcp_gateway"
    return key


def provider_cloud_name(provider: str) -> str:
    key = str(provider).strip().lower()
    if key.startswith("ali"):
        return "ali"
    if key.startswith("gcp"):
        return "gcp"
    if key.startswith("aws"):
        return "aws"
    if key == "mcp_gateway":
        return "mcp_gateway"
    return key


@dataclass(frozen=True)
class CliOverrides:
    trace_file: Optional[str] = None
    python_version: Optional[str] = None
    cpu: Optional[int] = None
    memory: Optional[int] = None
    disk: Optional[int] = None
    timeout: Optional[int] = None

    def build(self, fallback: BuildConfig) -> BuildConfig:
        if self.python_version:
            return BuildConfig(python_version=self.python_version)
        return fallback

    def runtime(self, fallback: RuntimeConfig) -> RuntimeConfig:
        return RuntimeConfig(
            cpu=int(self.cpu if self.cpu is not None else fallback.cpu),
            memory=int(self.memory if self.memory is not None else fallback.memory),
            disk=int(self.disk if self.disk is not None else fallback.disk),
            timeout=int(self.timeout if self.timeout is not None else fallback.timeout),
        )


def _read_runtime(payload: Optional[Mapping[str, Any]], fallback: Optional[RuntimeConfig] = None) -> RuntimeConfig:
    return RuntimeConfig.from_dict(payload, fallback=fallback)


def _read_build(payload: Optional[Mapping[str, Any]], fallback: Optional[BuildConfig] = None) -> BuildConfig:
    return BuildConfig.from_dict(payload, fallback=fallback)


def _load_function_defaults(node_dir: Path) -> tuple[BuildConfig, Dict[str, RuntimeConfig]]:
    path = node_dir / "function-config.json"
    if not path.exists():
        return BuildConfig(), {}
    data = load_json(path)
    build = BuildConfig(python_version=str(data.get("python-version", "")).strip())
    defaults: Dict[str, RuntimeConfig] = {}
    for entry in data.get("functions") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        defaults[name] = RuntimeConfig(
            cpu=int(entry.get("cpu", DEFAULT_RUNTIME_CONFIG["cpu"])),
            memory=int(entry.get("memory", DEFAULT_RUNTIME_CONFIG["memory"])),
            disk=int(entry.get("disk", DEFAULT_RUNTIME_CONFIG["disk"])),
            timeout=int(entry.get("timeout", DEFAULT_RUNTIME_CONFIG["timeout"])),
        )
    return build, defaults


def _load_mcp_defaults(node_dir: Path) -> tuple[BuildConfig, RuntimeConfig]:
    path = node_dir / "mcp-config.json"
    if not path.exists():
        return BuildConfig(), RuntimeConfig()
    data = load_json(path)
    build = BuildConfig(python_version=str(data.get("python-version", "")).strip())
    runtime = RuntimeConfig(
        cpu=int(data.get("cpu", DEFAULT_RUNTIME_CONFIG["cpu"])),
        memory=int(data.get("memory", DEFAULT_RUNTIME_CONFIG["memory"])),
        disk=int(data.get("disk", DEFAULT_RUNTIME_CONFIG["disk"])),
        timeout=int(data.get("timeout", DEFAULT_RUNTIME_CONFIG["timeout"])),
    )
    return build, runtime


def _nodes_from_tools(config_file: Path, bench_root: Path, tools: Any) -> List[Dict[str, Any]]:
    if not isinstance(tools, list) or not tools:
        return []
    grouped: Dict[str, Dict[str, Any]] = {}
    for raw in tools:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid tool entry in {config_file}: {raw}")
        trace_name = str(raw.get("trace_name") or raw.get("name") or "").strip()
        if not trace_name:
            raise SystemExit(f"Tool entry is missing trace_name in {config_file}: {raw}")
        tool_name = str(raw.get("tool_name") or raw.get("tool") or "").strip() or normalize_tool_name(trace_name)
        impl_dir = str(raw.get("impl_dir") or raw.get("dir") or "").strip()
        node_name = str(raw.get("node") or raw.get("node_name") or "").strip()
        if not node_name:
            if impl_dir:
                node_name = Path(impl_dir).name
            else:
                node_name = normalize_tool_name(tool_name.split(".")[0])
        entry = grouped.setdefault(
            node_name,
            {
                "name": node_name,
                "dir": impl_dir or f"./nodes/{node_name}",
                "trace_names": [],
            },
        )
        trace_entry = {
            "name": trace_name,
            "tool": tool_name,
            "domain": str(raw.get("domain", "")).strip(),
            "access": str(raw.get("access", STATELESS_ACCESS)).strip().lower(),
        }
        if "stateful" in raw and "access" not in raw:
            trace_entry["stateful"] = bool(raw.get("stateful", False))
            trace_entry.pop("access", None)
        entry["trace_names"].append(trace_entry)
    return list(grouped.values())


@lru_cache(maxsize=None)
def resolve_benchmark(config_path: str | Path, provider: str, overrides: Optional[CliOverrides] = None) -> ResolvedBenchmark:
    config_file = Path(config_path).resolve()
    spec = get_provider_spec(provider)
    overrides = overrides or CliOverrides()
    config = load_json(config_file)
    bench_root = resolve_benchmark_root(config_file)
    bench_name = bench_root.name
    trace_file = str(overrides.trace_file or config.get("trace_file", "")).strip()
    if not trace_file:
        raise SystemExit(f"Missing trace_file in {config_file}")
    trace_path = resolve_trace_path(bench_root, trace_file)
    trace = Trace.from_file(trace_path)

    if is_sandbox_config(config_file):
        raise SystemExit("Sandbox configs are no longer supported; use an external MCP-Gateway target instead")

    raw_nodes = config.get("nodes")
    if not raw_nodes and config.get("tools"):
        raw_nodes = _nodes_from_tools(config_file, bench_root, config.get("tools"))
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise SystemExit(f"Missing nodes in {config_file}")

    resolved_nodes: Dict[str, NodeDefinition] = {}
    trace_owner: Dict[str, str] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid node entry in {config_file}: {raw}")
        node_name = str(raw.get("name", "")).strip()
        if not node_name:
            raise SystemExit(f"Node name is required in {config_file}")
        if node_name in resolved_nodes:
            raise SystemExit(f"Duplicate node name '{node_name}' in {config_file}")
        node_dir_value = raw.get("dir")
        if not node_dir_value:
            node_dir = (bench_root / "nodes" / node_name).resolve()
        else:
            node_dir = (bench_root / str(node_dir_value)).resolve()
        if not node_dir.exists():
            raise SystemExit(f"Node directory not found: {node_dir}")
        trace_names = raw.get("trace_names")
        if not isinstance(trace_names, list) or not trace_names:
            raise SystemExit(f"Node '{node_name}' must define non-empty trace_names in {config_file}")
        trace_bindings: Dict[str, str] = {}
        trace_access: Dict[str, ToolAccess] = {}
        for item in trace_names:
            if isinstance(item, str):
                trace_name = item.strip()
                tool_name = normalize_tool_name(trace_name)
                access_info = ToolAccess()
            elif isinstance(item, dict):
                trace_name = str(item.get("name", "")).strip()
                tool_name = str(item.get("tool", "")).strip() or normalize_tool_name(trace_name)
                raw_access = item.get("access")
                if raw_access is None:
                    raw_access = "rw" if bool(item.get("stateful", False)) else STATELESS_ACCESS
                access = str(raw_access or STATELESS_ACCESS).strip().lower()
                if access not in VALID_ACCESS_MODES:
                    raise SystemExit(
                        f"Invalid access mode '{access}' for trace '{trace_name}' in {config_file}"
                    )
                domain = str(item.get("domain", "")).strip()
                if access != STATELESS_ACCESS and not domain:
                    domain = node_name
                access_info = ToolAccess.from_values(domain, access)
            else:
                raise SystemExit(f"Invalid trace name binding for node '{node_name}' in {config_file}: {item}")
            if not trace_name:
                raise SystemExit(f"Empty trace name binding for node '{node_name}' in {config_file}")
            trace_bindings[trace_name] = tool_name
            trace_access[trace_name] = access_info
        normalized_trace_names = tuple(trace_bindings.keys())
        if not normalized_trace_names:
            raise SystemExit(f"Node '{node_name}' has empty trace_names in {config_file}")
        for trace_name in normalized_trace_names:
            owner = trace_owner.get(trace_name)
            if owner and owner != node_name:
                raise SystemExit(f"Trace name '{trace_name}' is mapped by both '{owner}' and '{node_name}'")
            trace_owner[trace_name] = node_name
        node_build = _read_build(raw.get("build"), fallback=BuildConfig())
        function_build, function_defaults = _load_function_defaults(node_dir)
        mcp_build, mcp_defaults = _load_mcp_defaults(node_dir)
        resolved_nodes[node_name] = NodeDefinition(
            name=node_name,
            dir=node_dir,
            trace_names=normalized_trace_names,
            trace_to_tool=trace_bindings,
            trace_access=trace_access,
            build=node_build,
            function_build=function_build,
            mcp_build=mcp_build,
            function_defaults=function_defaults,
            mcp_defaults=mcp_defaults,
        )

    tool_use_names = [node.name for node in trace.nodes if node.node_type in TRACE_TOOL_TYPES]
    legacy_names = [node.name for node in trace.nodes if node.node_type in LEGACY_TRACE_TOOL_TYPES]
    if legacy_names:
        raise SystemExit(
            f"Legacy trace node types {sorted({node.node_type for node in trace.nodes if node.node_type in LEGACY_TRACE_TOOL_TYPES})} "
            f"found in {trace_path}; migrate them to 'tool_use'"
        )
    missing_trace_names = sorted({name for name in tool_use_names if name not in trace_owner})
    if missing_trace_names:
        raise SystemExit(
            f"Trace names missing from config {config_file}: {', '.join(missing_trace_names)}"
        )

    pipeline = config.get("pipeline") or config.get("realizations")
    if not isinstance(pipeline, dict):
        raise SystemExit(f"Missing pipeline block in {config_file}")

    cli = overrides or CliOverrides()
    if spec.family == "faas":
        targets, routes = _resolve_faas_targets(config_file, resolved_nodes, pipeline.get("faas"), cli)
    else:
        session_payload = pipeline.get("session")
        if session_payload is None:
            session_payload = pipeline.get("mcp_serverless")
        targets, routes = _resolve_mcp_targets(config_file, resolved_nodes, session_payload, cli)

    missing_routes = sorted({name for name in tool_use_names if name not in routes})
    if missing_routes:
        raise SystemExit(
            f"Trace names not routed by selected provider '{provider}' in {config_file}: {', '.join(missing_routes)}"
        )

    return ResolvedBenchmark(
        config_path=config_file,
        bench_root=bench_root,
        bench_name=bench_name,
        trace_path=trace_path,
        trace=trace,
        provider=spec,
        nodes=resolved_nodes,
        targets=targets,
        routes=routes,
    )


def _resolve_faas_targets(
    config_path: Path,
    nodes: Dict[str, NodeDefinition],
    payload: Any,
    cli: CliOverrides,
) -> tuple[Dict[str, ResolvedTarget], Dict[str, TraceRoute]]:
    if not isinstance(payload, dict):
        raise SystemExit(f"Config {config_path} does not define pipeline.faas")
    family_build_payload = payload.get("build")
    family_build = _read_build(family_build_payload, fallback=BuildConfig()) if family_build_payload is not None else BuildConfig()
    units = payload.get("units")
    if not isinstance(units, list) or not units:
        raise SystemExit(f"pipeline.faas.units must be a non-empty list in {config_path}")

    targets: Dict[str, ResolvedTarget] = {}
    routes: Dict[str, TraceRoute] = {}
    for raw in units:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid FaaS unit in {config_path}: {raw}")
        target_name = str(raw.get("name", "")).strip()
        node_name = str(raw.get("node", "")).strip()
        trace_names = tuple(str(item).strip() for item in raw.get("trace_names") or [] if str(item).strip())
        if not target_name or not node_name or not trace_names:
            raise SystemExit(f"Invalid FaaS unit in {config_path}: {raw}")
        if target_name in targets:
            raise SystemExit(f"Duplicate FaaS target '{target_name}' in {config_path}")
        node = nodes.get(node_name)
        if node is None:
            raise SystemExit(f"Unknown node '{node_name}' in FaaS unit '{target_name}'")
        for trace_name in trace_names:
            if trace_name not in node.trace_names:
                raise SystemExit(
                    f"FaaS unit '{target_name}' references trace '{trace_name}' outside node '{node_name}'"
                )
            if trace_name in routes:
                raise SystemExit(f"Trace '{trace_name}' is routed by multiple FaaS units in {config_path}")

        build_fallback = node.build if node.build.python_version else node.function_build
        explicit_build_payload = raw.get("build") if raw.get("build") is not None else family_build_payload
        if explicit_build_payload is not None:
            build = cli.build(_read_build(explicit_build_payload, fallback=build_fallback))
        else:
            build = cli.build(build_fallback)
        if not build.python_version:
            build = cli.build(BuildConfig(python_version="3.10"))

        unit_deploy = raw.get("deploy")
        if unit_deploy is None:
            raise SystemExit(
                f"FaaS unit '{target_name}' must define deploy config in {config_path}"
            )
        runtime = cli.runtime(_read_runtime(unit_deploy, fallback=RuntimeConfig()))

        allowed_tools = tuple(node.tool_name_for_trace(name) for name in trace_names)
        target = ResolvedTarget(
            name=target_name,
            family="faas",
            node_names=(node_name,),
            trace_names=trace_names,
            build=build,
            runtime=runtime,
            allowed_tools=allowed_tools,
        )
        targets[target_name] = target
        for trace_name in trace_names:
            access_info = node.access_for_trace(trace_name)
            routes[trace_name] = TraceRoute(
                trace_name=trace_name,
                node_name=node_name,
                target_name=target_name,
                family="faas",
                tool_name=node.tool_name_for_trace(trace_name),
                domain=access_info.domain,
                access=access_info.access,
            )
    return targets, routes


def _resolve_mcp_targets(
    config_path: Path,
    nodes: Dict[str, NodeDefinition],
    payload: Any,
    cli: CliOverrides,
) -> tuple[Dict[str, ResolvedTarget], Dict[str, TraceRoute]]:
    if not isinstance(payload, dict):
        raise SystemExit(f"Config {config_path} does not define pipeline.session or pipeline.mcp_serverless")
    family_build_payload = payload.get("build")
    family_build = _read_build(family_build_payload, fallback=BuildConfig()) if family_build_payload is not None else BuildConfig()
    servers = payload.get("servers")
    if not isinstance(servers, list) or not servers:
        raise SystemExit(f"pipeline.session.servers must be a non-empty list in {config_path}")

    targets: Dict[str, ResolvedTarget] = {}
    routes: Dict[str, TraceRoute] = {}
    claimed_nodes: Dict[str, str] = {}
    for raw in servers:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid MCP server in {config_path}: {raw}")
        target_name = str(raw.get("name", "")).strip()
        node_names = tuple(str(item).strip() for item in raw.get("nodes") or [] if str(item).strip())
        if not target_name or not node_names:
            raise SystemExit(f"Invalid MCP server in {config_path}: {raw}")
        if target_name in targets:
            raise SystemExit(f"Duplicate MCP server '{target_name}' in {config_path}")
        trace_names: List[str] = []
        build_candidates: List[BuildConfig] = []
        for node_name in node_names:
            node = nodes.get(node_name)
            if node is None:
                raise SystemExit(f"Unknown node '{node_name}' in MCP server '{target_name}'")
            owner = claimed_nodes.get(node_name)
            if owner and owner != target_name:
                raise SystemExit(f"Node '{node_name}' is assigned to both MCP servers '{owner}' and '{target_name}'")
            claimed_nodes[node_name] = target_name
            trace_names.extend(node.trace_names)
            build_candidates.append(node.build if node.build.python_version else node.mcp_build)
        explicit_build_payload = raw.get("build") if raw.get("build") is not None else family_build_payload
        if explicit_build_payload is not None:
            build = cli.build(_read_build(explicit_build_payload, fallback=family_build))
        else:
            python_versions = {candidate.python_version for candidate in build_candidates if candidate.python_version}
            if len(python_versions) > 1:
                raise SystemExit(
                    f"MCP server '{target_name}' combines nodes with different python versions and needs pipeline.build"
                )
            python_version = python_versions.pop() if python_versions else "3.10"
            build = cli.build(BuildConfig(python_version=python_version))

        server_deploy = raw.get("deploy")
        if server_deploy is None:
            raise SystemExit(
                f"MCP server '{target_name}' must define deploy config in {config_path}"
            )
        runtime = cli.runtime(_read_runtime(server_deploy, fallback=RuntimeConfig()))

        target = ResolvedTarget(
            name=target_name,
            family="session",
            node_names=node_names,
            trace_names=tuple(trace_names),
            build=build,
            runtime=runtime,
            allowed_tools=tuple(),
        )
        targets[target_name] = target
        for node_name in node_names:
            for trace_name in nodes[node_name].trace_names:
                if trace_name in routes:
                    raise SystemExit(f"Trace '{trace_name}' is routed by multiple MCP servers in {config_path}")
                access_info = nodes[node_name].access_for_trace(trace_name)
                routes[trace_name] = TraceRoute(
                    trace_name=trace_name,
                    node_name=node_name,
                    target_name=target_name,
                    family="session",
                    tool_name=nodes[node_name].tool_name_for_trace(trace_name),
                    domain=access_info.domain,
                    access=access_info.access,
                )
    return targets, routes


def target_image_tag(bench_name: str, target: ResolvedTarget) -> str:
    kind = "function" if target.family == "faas" else "mcp"
    return f"atsuite-{kind}-{bench_name.lower()}-{target.name.lower()}"


def read_url_map(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if isinstance(data.get("targets"), dict):
        return data
    return {"provider": "", "family": "", "targets": data}


def tool_trace_names(trace: Trace) -> List[str]:
    return [node.name for node in trace.nodes if node.node_type in TRACE_TOOL_TYPES]
