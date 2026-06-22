from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TextIO

from atsuite.pipeline import CliOverrides, is_sandbox_config, read_url_map, resolve_benchmark
from atsuite.runtime import InvocationRequest, RuntimeAdapter, RuntimeSession, RuntimeTarget, create_runtime_adapter
from atsuite.scheduler import AccessScheduler, ToolAccess
from atsuite.state_snapshot import (
    maybe_attach_agentcore_state_snapshot,
    seed_lambda_state_snapshot_for_uid,
)
from atsuite.utils import (
    _cleanup_scaling_configs,
    _create_scaling_configs,
    cleaner,
    parse_arguments,
)

BUCKET_NAME = "atsuite"

logging.basicConfig(level=logging.INFO)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


class _TeeWriter:
    """Writes to both the original stream and a log file simultaneously."""

    def __init__(self, original: TextIO, log_file: TextIO):
        self._original = original
        self._log_file = log_file

    def write(self, data: str) -> int:
        self._original.write(data)
        self._log_file.write(data)
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        self._log_file.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _create_analyzer(
    config_path: Path,
    resolved,
    *,
    trace_name: str = "",
    endpoint_map: Optional[Dict[str, Any]] = None,
    runtime: Optional[RuntimeAdapter] = None,
):
    try:
        from atsuite.analyzer import Analyzer

        runtime_observability = ""
        if runtime is not None:
            runtime_observability = runtime.capabilities().observability
        observability_provider = (
            resolved.provider.observability_provider
            or runtime_observability
            or resolved.provider.name
        )
        targets = {
            name: {
                "family": target.family,
                "nodes": list(target.node_names),
                "trace_names": list(target.trace_names),
                "runtime": target.runtime.to_dict(),
                "allowed_tools": list(target.allowed_tools),
            }
            for name, target in resolved.targets.items()
        }
        print(
            f"[invoker] Analyzer enabled: {config_path}, "
            f"provider={resolved.provider.name}, observability={observability_provider}"
        )
        return Analyzer(
            config_path,
            resolved.provider.name,
            observability_provider=observability_provider,
            family=resolved.family,
            bench_name=resolved.bench_name,
            trace_name=trace_name,
            targets=targets,
            endpoint_map=endpoint_map or {},
        )
    except Exception as e:
        print(f"[invoker] Analyzer disabled: {e}")
        return None


def _runtime_targets(resolved, url_map: Dict[str, Any]) -> Dict[str, RuntimeTarget]:
    targets = {}
    raw_targets = url_map.get("targets", {})
    for target_name, target in resolved.targets.items():
        raw = raw_targets.get(target_name)
        if raw is None:
            raise ValueError(f"Missing URL for target: {target_name}")
        if isinstance(raw, str):
            endpoint = raw
            resources = target.runtime.to_dict()
            manifest = {}
        elif isinstance(raw, dict):
            endpoint = str(raw.get("endpoint") or raw.get("url") or "")
            resources = dict(raw.get("resources") or raw.get("runtime") or target.runtime.to_dict())
            manifest = dict(raw.get("tool_manifest") or {})
        else:
            raise ValueError(f"Invalid endpoint map entry for target: {target_name}")
        targets[target_name] = RuntimeTarget(
            target_id=target_name,
            family=target.family,
            endpoint=endpoint.rstrip("/"),
            resources=resources,
            tool_manifest=manifest,
        )
    return targets


def run_node(
    node_id: int,
    incoming_params: Dict[str, Any],
    visited: set[int],
    node_by_id: Dict[int, Any],
    sleep_fn: Callable[[float], None],
    uid: str,
    toclean: set[str],
    stateful_tool_num: list[int],
    analyzer: Optional[Any],
    resolved,
    runtime: RuntimeAdapter,
    runtime_targets: Dict[str, RuntimeTarget],
    *,
    max_workers: Optional[int] = None,
    state_snapshot_bundle: Optional[Dict[str, Any]] = None,
) -> None:
    if visited:
        return

    def get_reachable_nodes(start_id: int) -> set[int]:
        reachable: set[int] = set()
        q_reachable = deque([start_id])
        while q_reachable:
            n_id = q_reachable.popleft()
            if n_id in reachable:
                continue
            reachable.add(n_id)
            if n_id in node_by_id:
                for edge in node_by_id[n_id].edge_to:
                    q_reachable.append(edge.target_id)
        return reachable

    reachable_nodes = get_reachable_nodes(node_id)
    in_degree = {n_id: 0 for n_id in node_by_id}
    node_incoming_params = {n_id: {} for n_id in node_by_id}
    ready_nodes = deque()
    analyzer_lock = threading.Lock()
    session_lock = threading.Lock()
    state_lock = threading.Lock()
    print_lock = threading.Lock()
    seeded_targets: set[str] = set()
    sessions: Dict[str, RuntimeSession] = {}
    node_access: Dict[int, ToolAccess] = {}
    access_scheduler = AccessScheduler(enabled=resolved.family == "faas")

    for node in node_by_id.values():
        if node.node_id not in reachable_nodes:
            continue
        if node.node_type == "tool_use":
            route = resolved.routes[node.name]
            node_access[node.node_id] = route.tool_access
        for edge in node.edge_to:
            target_id = edge.target_id
            if target_id in reachable_nodes:
                in_degree[target_id] += 1

    for n_id in node_by_id:
        if in_degree[n_id] == 0 and n_id in reachable_nodes:
            ready_nodes.append(n_id)
            node_incoming_params[n_id] = incoming_params

    def analyzer_call(method_name: str, *args, **kwargs):
        if not analyzer:
            return None
        with analyzer_lock:
            return getattr(analyzer, method_name)(*args, **kwargs)

    def session_for_target(target_name: str, current_node_id: int, current_node_name: str) -> RuntimeSession:
        with session_lock:
            existing = sessions.get(target_name)
            if existing is not None:
                return existing
            session = runtime.open_session(runtime_targets[target_name], uid)
            sessions[target_name] = session
            analyzer_call(
                "record_session_open",
                target_id=target_name,
                runtime_name=target_name,
                provider_session_id=session.provider_session_id,
                initialize_request_id=str(session.metadata.get("initialize_request_id") or ""),
                metadata=session.metadata,
            )
            return session

    def execute_node(current_node_id: int) -> None:
        current_incoming_params = node_incoming_params[current_node_id]
        params = current_incoming_params or {}
        current_node = node_by_id[current_node_id]
        runtime_name = ""
        runtime_config: Dict[str, Any] = {}
        analyzer_node_type = current_node.node_type

        if current_node.node_type == "tool_use":
            route = resolved.routes[current_node.name]
            target = resolved.targets[route.target_name]
            runtime_name = target.name
            runtime_config = target.runtime.to_dict()
            analyzer_node_type = "function" if target.family == "faas" else "mcp"
            analyzer_target_id = target.name
            analyzer_family = target.family
        else:
            analyzer_target_id = ""
            analyzer_family = ""

        analyzer_call(
            "start_node",
            current_node_id,
            current_node.name,
            analyzer_node_type,
            runtime_name=runtime_name,
            runtime_config=runtime_config,
            target_id=analyzer_target_id,
            family=analyzer_family,
        )

        if current_node.node_type == "logic":
            elapsed_ms = current_node.time_ms
            analyzer_call("end_node", current_node_id)
        elif current_node.node_type == "llm":
            sleep_fn(current_node.time_ms)
            elapsed_ms = current_node.time_ms
            analyzer_call("end_node", current_node_id)
        elif current_node.node_type == "sandbox":
            raise RuntimeError("Sandbox trace nodes are no longer supported; route them through MCP-Gateway")
        elif current_node.node_type == "tool_use":
            route = resolved.routes[current_node.name]
            target = resolved.targets[route.target_name]
            input_value = params.get("input", "")
            args = parse_arguments(input_value, uid)
            with state_lock:
                args = maybe_attach_agentcore_state_snapshot(
                    args,
                    provider=resolved.provider.name,
                    target_name=target.name,
                    uid=uid,
                    state_snapshot_bundle=state_snapshot_bundle,
                    seeded_targets=seeded_targets,
                )

            call_id = f"{uid}_{current_node_id}_{int(time.time() * 1e6)}"
            session = session_for_target(target.name, current_node_id, current_node.name)
            client_start_time = time.time()
            result = runtime.invoke(
                InvocationRequest(
                    target_id=target.name,
                    tool_name=route.tool_name,
                    args=args,
                    uid=uid,
                    call_id=call_id,
                    session=session,
                    timeout=target.runtime.timeout,
                )
            )
            elapsed_ms = result.client_elapsed_ms
            if result.status != "ok":
                analyzer_call(
                    "record_invocation",
                    node_id=current_node_id,
                    node_name=current_node.name,
                    target_id=target.name,
                    runtime_name=target.name,
                    family=target.family,
                    tool_name=route.tool_name,
                    call_id=call_id,
                    status=result.status,
                    provider_request_id=result.provider_request_id,
                    provider_session_id=session.provider_session_id,
                    client_start_time=client_start_time,
                    client_elapsed_ms=elapsed_ms,
                    error=result.error,
                    provider_metadata=result.provider_metadata,
                )
                analyzer_call("end_node", current_node_id)
                raise RuntimeError(result.error or f"Invocation failed for {current_node.name}")

            is_stateful = route.tool_access.is_stateful or bool(result.provider_metadata.get("is_stateful"))
            if target.family == "faas" and is_stateful:
                with state_lock:
                    stateful_tool_num[0] += 1
                    toclean.add(target.name)

            session_id = result.provider_metadata.get("session_id")
            analyzer_call(
                "record_invocation",
                node_id=current_node_id,
                node_name=current_node.name,
                target_id=target.name,
                runtime_name=target.name,
                family=target.family,
                tool_name=route.tool_name,
                call_id=call_id,
                status=result.status,
                provider_request_id=result.provider_request_id,
                provider_session_id=str(session_id or session.provider_session_id or ""),
                client_start_time=client_start_time,
                client_elapsed_ms=elapsed_ms,
                provider_metadata=result.provider_metadata,
            )
            analyzer_call("end_node", current_node_id)
        else:
            elapsed_ms = 0.0
            analyzer_call("end_node", current_node_id)

        with print_lock:
            print(
                f"Running node: {current_node_id}, name: {current_node.name}, "
                f"type: {current_node.node_type}, time: {elapsed_ms}"
            )

    worker_count = max(1, min(32, len(reachable_nodes)))
    if max_workers is not None:
        worker_count = max(1, min(max_workers, len(reachable_nodes)))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending: Dict[Any, int] = {}

        def submit_node(n_id: int):
            if n_id not in reachable_nodes or n_id in visited:
                return None
            access = node_access.get(n_id, ToolAccess())
            access_scheduler.start(access)
            visited.add(n_id)
            future = executor.submit(execute_node, n_id)
            pending[future] = n_id
            return future

        def schedule_ready_nodes() -> None:
            scheduled = True
            while scheduled:
                scheduled = False
                for n_id in sorted(list(ready_nodes)):
                    access = node_access.get(n_id, ToolAccess())
                    if not access_scheduler.can_start(access):
                        continue
                    ready_nodes.remove(n_id)
                    submit_node(n_id)
                    scheduled = True

        schedule_ready_nodes()

        while pending or ready_nodes:
            if not pending:
                schedule_ready_nodes()
                if not pending:
                    break
            done, _ = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
            for future in done:
                current_node_id = pending.pop(future)
                access_scheduler.finish(node_access.get(current_node_id, ToolAccess()))
                future.result()
                current_node = node_by_id[current_node_id]

                for edge in current_node.edge_to:
                    sleep_fn(edge.interval_ms)
                    target_id = edge.target_id
                    if target_id not in reachable_nodes:
                        continue
                    if edge.params and "input" in edge.params:
                        if "input" not in node_incoming_params[target_id]:
                            node_incoming_params[target_id]["input"] = edge.params["input"]
                        elif isinstance(node_incoming_params[target_id]["input"], dict) and isinstance(edge.params["input"], dict):
                            node_incoming_params[target_id]["input"].update(edge.params["input"])
                    in_degree[target_id] -= 1
                    if in_degree[target_id] == 0 and target_id in reachable_nodes:
                        ready_nodes.append(target_id)
            schedule_ready_nodes()


def run_trace(
    config_path: Path,
    url_map_path: Path,
    uid: str,
    *,
    provider: str,
    trace_file: Optional[str] = None,
    skip_sleep: bool = False,
    max_workers: Optional[int] = None,
    state_snapshot_bundle: Optional[Dict[str, Any]] = None,
    llm_time_scale: float = 1.0,
    skip_analyzer: bool = False,
    skip_scaling_config: bool = False,
    analyzer: Optional[Any] = None,
) -> Dict[str, Any]:
    if is_sandbox_config(config_path):
        raise SystemExit("Sandbox configs are no longer supported; use an external MCP-Gateway target instead")

    def sleep_ms(time_ms: float) -> None:
        if skip_sleep:
            return
        time.sleep((float(time_ms) * float(llm_time_scale)) / 1000.0)

    overrides = CliOverrides(trace_file=trace_file)
    resolved = resolve_benchmark(config_path, provider, overrides)
    url_map = read_url_map(url_map_path)
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    selected_trace_file = trace_file if trace_file is not None else config.get("trace_file", "")

    if url_map.get("provider") and url_map["provider"] != provider:
        raise SystemExit(f"URL map provider {url_map['provider']} does not match CLI provider {provider}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("results") / provider / resolved.bench_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{ts}.log"
    _log_file = open(log_path, "w", encoding="utf-8")
    _original_stdout = sys.stdout
    sys.stdout = _TeeWriter(_original_stdout, _log_file)

    toclean: set[str] = set()
    stateful_tool_num = [0]
    node_by_id = {n.node_id: n for n in resolved.trace.nodes}
    toclean.update(
        seed_lambda_state_snapshot_for_uid(
            provider=provider,
            uid=uid,
            state_snapshot_bundle=state_snapshot_bundle,
        )
    )

    if resolved.family == "session" and provider == "ali_agentrun" and not skip_scaling_config:
        for target in resolved.targets.values():
            _create_scaling_configs(provider, f"{target.name}-mcp")
        time.sleep(30)

    runtime = create_runtime_adapter(resolved.provider.name, resolved.family)
    runtime.connect(url_map)
    runtime_targets = _runtime_targets(resolved, url_map)

    if analyzer is None and not skip_analyzer:
        analyzer = _create_analyzer(
            config_path,
            resolved,
            trace_name=Path(str(selected_trace_file)).stem,
            endpoint_map=url_map,
            runtime=runtime,
        )
    if analyzer:
        analyzer.start(uid=uid)

    trace_start_time = time.time()
    trace_end_time = 0.0
    analyzer_report = None
    result: Dict[str, Any] = {
        "run": {
            "uid": uid,
            "provider": provider,
            "benchmark": resolved.bench_name,
            "trace": Path(str(selected_trace_file)).stem,
            "family": resolved.family,
        },
        "summary": {},
        "report_path": "",
        "evidence_path": "",
    }

    try:
        run_node(
            0,
            {},
            set(),
            node_by_id,
            sleep_ms,
            uid,
            toclean,
            stateful_tool_num,
            analyzer,
            resolved,
            runtime,
            runtime_targets,
            max_workers=max_workers,
            state_snapshot_bundle=state_snapshot_bundle,
        )
        trace_end_time = time.time()
        result["summary"]["run_user_e2e_ms"] = (trace_end_time - trace_start_time) * 1000
    finally:
        try:
            cleanup_started_at = time.time()
            size = cleaner(
                provider,
                BUCKET_NAME,
                toclean,
                uid,
                url_map=url_map,
                bench_name=resolved.bench_name,
            )
            runtime.cleanup_run(uid)

            if analyzer:
                analyzer.record_state_cleanup(
                    provider=resolved.provider.storage_provider,
                    services=toclean,
                    size_gb=float(size or 0.0),
                    operation_count=stateful_tool_num[0] + len(toclean),
                    started_at=cleanup_started_at,
                    ended_at=time.time(),
                    metadata={"bucket": BUCKET_NAME},
                )

            if resolved.family == "session" and provider == "ali_agentrun" and not skip_scaling_config:
                for target in resolved.targets.values():
                    _cleanup_scaling_configs(provider, f"{target.name}-mcp")

            if analyzer:
                analyzer_report = analyzer.end(
                    end_time=trace_end_time or time.time(),
                    wait_for_ingestion=True,
                    timestamp=ts,
                )
                analyzer.print_stats()
                result["run"] = analyzer_report.run
                result["summary"] = analyzer_report.summary
                result["report_path"] = analyzer_report.report_path
                result["evidence_path"] = analyzer_report.evidence_path
                result["events_path"] = analyzer.events_path
            else:
                result["summary"].setdefault(
                    "run_user_e2e_ms",
                    ((trace_end_time or time.time()) - trace_start_time) * 1000,
                )
                result["summary"].setdefault("total_compute_time_ms", 0.0)
                result["summary"].setdefault("total_idle_time_ms", 0.0)
                result["summary"].setdefault("total_price", 0.0)
        finally:
            sys.stdout = _original_stdout
            _log_file.close()
            print(f"[export] Log: {log_path}")
    return result
