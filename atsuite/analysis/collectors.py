from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Protocol
from urllib.parse import unquote, urlparse

from atsuite.analysis.model import (
    CollectionResult,
    EvidenceRecord,
    InvocationObservation,
    NodeObservation,
    ProviderMetric,
    RunContext,
    SessionObservation,
)


class ProviderCollector(Protocol):
    observability_provider: str
    default_ingestion_delay_s: float

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        ...


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _epochish_to_ns(value: Any) -> int:
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 0
    if raw <= 0:
        return 0
    if raw >= 1e17:
        return int(raw)
    if raw >= 1e14:
        return int(raw * 1_000)
    if raw >= 1e11:
        return int(raw * 1_000_000)
    if raw >= 1e8:
        return int(raw * 1_000_000_000)
    return 0


def _datetime_text_to_ns(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return _epochish_to_ns(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return _epochish_to_ns(float(text))
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return int(dt.timestamp() * 1_000_000_000)


def _duration_ms_to_ns(value: Any) -> int:
    try:
        return int(round(float(value) * 1_000_000))
    except (TypeError, ValueError):
        return 0


def _log_event_timestamp_ns(event: Dict[str, Any]) -> int:
    for key in ("timestamp", "@timestamp", "time", "eventTime"):
        if key in event:
            parsed = _datetime_text_to_ns(event.get(key))
            if parsed:
                return parsed
    return 0


def _max_log_event_timestamp_ns(logs: Iterable[Dict[str, Any]]) -> int:
    return max((_log_event_timestamp_ns(event) for event in logs), default=0)


_BREAKDOWN_FIELDS = {
    "app_e2e_ms",
    "tool_exec_ms",
    "state_sync_overhead_ms",
    "framework_overhead_ms",
    "pre_tool_ms",
    "post_tool_ms",
    "request_wall_ns",
    "request_start_wall_ns",
    "request_end_wall_ns",
    "tool_start_wall_ns",
    "tool_end_wall_ns",
    "timestamp_ms",
    "service_name",
    "status",
    "tool_name",
    "trace_id",
}

_BREAKDOWN_EVENT_NAMES = {
    "atsuite_function_breakdown",
    "atsuite_mcp_breakdown",
    "uaib_function_breakdown",
    "uaib_mcp_breakdown",
}


def _normalise_breakdown_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    fields = {k: v for k, v in payload.items() if k in _BREAKDOWN_FIELDS and v is not None}
    explicit_wall = any(
        _coerce_int(fields.get(name)) > 0
        for name in (
            "request_start_wall_ns",
            "request_end_wall_ns",
            "tool_start_wall_ns",
            "tool_end_wall_ns",
        )
    )
    derived = False
    request_start_ns = _coerce_int(fields.get("request_start_wall_ns")) or _coerce_int(
        fields.get("request_wall_ns")
    )
    if request_start_ns and not fields.get("request_start_wall_ns"):
        fields["request_start_wall_ns"] = request_start_ns
        derived = True
    request_end_ns = _coerce_int(fields.get("request_end_wall_ns"))
    tool_start_ns = _coerce_int(fields.get("tool_start_wall_ns"))
    tool_end_ns = _coerce_int(fields.get("tool_end_wall_ns"))

    if request_start_ns and not request_end_ns and _coerce_float(fields.get("app_e2e_ms")) > 0:
        request_end_ns = request_start_ns + _duration_ms_to_ns(fields.get("app_e2e_ms"))
        fields["request_end_wall_ns"] = request_end_ns
        derived = True
    if request_start_ns and not tool_start_ns and fields.get("pre_tool_ms") is not None:
        tool_start_ns = request_start_ns + _duration_ms_to_ns(fields.get("pre_tool_ms"))
        fields["tool_start_wall_ns"] = tool_start_ns
        derived = True
    if tool_start_ns and not tool_end_ns and _coerce_float(fields.get("tool_exec_ms")) > 0:
        tool_end_ns = tool_start_ns + _duration_ms_to_ns(fields.get("tool_exec_ms"))
        fields["tool_end_wall_ns"] = tool_end_ns
        derived = True
    if request_end_ns and not tool_end_ns and _coerce_float(fields.get("post_tool_ms")) > 0:
        tool_end_ns = max(0, request_end_ns - _duration_ms_to_ns(fields.get("post_tool_ms")))
        fields["tool_end_wall_ns"] = tool_end_ns
        derived = True
    if tool_end_ns and not tool_start_ns and _coerce_float(fields.get("tool_exec_ms")) > 0:
        fields["tool_start_wall_ns"] = max(
            0,
            tool_end_ns - _duration_ms_to_ns(fields.get("tool_exec_ms")),
        )
        derived = True

    if explicit_wall:
        fields.setdefault("time_source", "sdk_wall_clock")
        fields.setdefault("confidence", "sdk_wall_clock")
    elif derived:
        fields.setdefault("time_source", "derived_from_duration")
        fields.setdefault("confidence", "estimated")
    return fields


def _add_provider_duration_from_response(
    fields: Dict[str, Any],
    *,
    response_wall_ns: int,
    duration_ms: Any,
    confidence: str,
) -> None:
    duration_ns = _duration_ms_to_ns(duration_ms)
    if response_wall_ns <= 0 or duration_ns <= 0:
        return
    fields.setdefault("provider_duration_ms", _coerce_float(duration_ms))
    fields.setdefault("provider_response_wall_ns", response_wall_ns)
    fields.setdefault("provider_receive_wall_ns", max(0, response_wall_ns - duration_ns))
    fields.setdefault("provider_time_source", "provider_log")
    fields.setdefault("provider_confidence", confidence)


def _memory_from_node(node: Optional[NodeObservation]) -> float:
    if node is None:
        return 0.0
    raw = node.runtime_config.get("memory") or node.runtime_config.get("memory_mb")
    return _coerce_float(raw, 0.0)


def _cpu_from_node(node: Optional[NodeObservation]) -> float:
    if node is None:
        return 0.0
    return _coerce_float(node.runtime_config.get("cpu"), 0.0)


def _disk_from_node(node: Optional[NodeObservation]) -> float:
    if node is None:
        return 512.0
    return _coerce_float(node.runtime_config.get("disk"), 512.0)


def _metric_from_invocation(
    provider: str,
    source: str,
    invocation: InvocationObservation,
    node: Optional[NodeObservation],
    fields: Optional[Dict[str, Any]] = None,
    evidence_refs: Optional[List[str]] = None,
) -> ProviderMetric:
    merged = {
        "elapsed_time_ms": float(invocation.client_elapsed_ms or 0.0),
        "client_e2e_ms": float(invocation.client_elapsed_ms or 0.0),
        "status": invocation.status,
        "error": invocation.error,
        "cpu": _cpu_from_node(node),
        "memory": _memory_from_node(node),
        "memory_usage_mb": _memory_from_node(node),
        "disk": _disk_from_node(node),
        "is_cold_start": "false",
        "time_source": "client_only",
        "confidence": "client_only",
    }
    merged.update(dict(fields or {}))
    if "duration_ms" in merged and "elapsed_time_ms" not in merged:
        merged["elapsed_time_ms"] = merged["duration_ms"]
    return ProviderMetric(
        metric_id=f"{source}:{invocation.call_id or invocation.provider_request_id}",
        provider=provider,
        source=source,
        node_id=invocation.node_id,
        invocation_call_id=invocation.call_id,
        provider_request_id=invocation.provider_request_id,
        fields=merged,
        evidence_refs=list(evidence_refs or []),
    )


class NoopCollector:
    observability_provider = "none"
    default_ingestion_delay_s = 0.0

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        metrics = [
            _metric_from_invocation(
                context.observability_provider or context.provider,
                "runtime",
                invocation,
                nodes.get(invocation.node_id),
            )
            for invocation in invocations
        ]
        return CollectionResult(metrics=metrics)


class AliSLSCollector:
    observability_provider = "ali_sls"
    default_ingestion_delay_s = 61.0

    def __init__(self, project: str = "atsuite", location: str = "us-east-1"):
        self.project = project
        self.location = location
        self._sls = None
        self._sls_clients: Dict[str, Any] = {}
        self._log_destinations: Dict[str, tuple[str, str]] = {}

    @property
    def sls(self):
        if self._sls is None:
            from atsuite.ali.sls import AliSLS

            self._sls = AliSLS(project=self.project, location=self.location)
        return self._sls

    def _sls_for_project(self, project: str):
        project = project or self.project
        if project == self.project:
            return self.sls
        if project not in self._sls_clients:
            from atsuite.ali.sls import AliSLS

            self._sls_clients[project] = AliSLS(project=project, location=self.location)
        return self._sls_clients[project]

    def _logstore(self, context: RunContext, node: Optional[NodeObservation]) -> str:
        if node is None:
            return context.benchmark.lower()
        runtime_name = node.runtime_name or node.target_id or node.node_name or context.benchmark
        kind = "mcp" if node.node_type in ("mcp", "tool") else "function"
        return f"{runtime_name.lower()}-{kind}"

    def _log_destination(self, logstore: str) -> tuple[str, str]:
        if logstore in self._log_destinations:
            return self._log_destinations[logstore]
        destination = (self.project, logstore)
        try:
            from alibabacloud_fc20230330 import models as fc_models
            from alibabacloud_tea_util import models as util_models
            from atsuite.ali.ali import Ali

            response = Ali().get_fc_client().get_function_with_options(
                logstore,
                fc_models.GetFunctionRequest(),
                {},
                util_models.RuntimeOptions(),
            )
            body = response.body.to_map() if hasattr(response.body, "to_map") else response.body
            log_config = {}
            if isinstance(body, dict):
                log_config = body.get("logConfig") or body.get("log_config") or {}
            if isinstance(log_config, dict):
                destination = (
                    str(log_config.get("project") or self.project),
                    str(log_config.get("logstore") or logstore),
                )
        except Exception:
            destination = (self.project, logstore)
        self._log_destinations[logstore] = destination
        return destination

    def _breakdowns_for_logstore(
        self,
        project: str,
        logstore: str,
        from_time: int,
        to_time: int,
        result: CollectionResult,
    ) -> Dict[str, Dict[str, Any]]:
        records: Dict[str, Dict[str, Any]] = {}
        try:
            payloads = self._sls_for_project(project).getbreakdownlogs(
                logstore,
                from_time,
                to_time,
                "app_e2e_ms",
            )
        except Exception as exc:
            result.diagnostics.append(
                {
                    "kind": "collector_error",
                    "provider": "ali_sls",
                    "project": project,
                    "logstore": logstore,
                    "source": "breakdown",
                    "error": str(exc),
                }
            )
            return records
        for payload in payloads or []:
            if not isinstance(payload, dict):
                continue
            event_name = str(payload.get("event") or "")
            if event_name not in _BREAKDOWN_EVENT_NAMES:
                continue
            fields = _normalise_breakdown_fields(payload)
            for key in (
                payload.get("request_id"),
                payload.get("client_request_id"),
                payload.get("jsonrpc_id"),
            ):
                key = str(key or "")
                if key:
                    records[key] = dict(fields)
        return records

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        result = CollectionResult()
        from_time = int(context.start_time or time.time())
        to_time = int((context.end_time or time.time()) + 120)
        breakdowns_by_logstore: Dict[tuple[str, str], Dict[str, Dict[str, Any]]] = {}
        for index, invocation in enumerate(invocations, start=1):
            node = nodes.get(invocation.node_id)
            request_id = invocation.provider_request_id or invocation.call_id
            if not request_id:
                result.metrics.append(
                    _metric_from_invocation("ali", "runtime", invocation, node)
                )
                result.diagnostics.append(
                    {"kind": "missing_request_id", "call_id": invocation.call_id}
                )
                continue
            query = (
                "* | SELECT durationMs, memoryUsageMB, isColdStart, coldStartLatencyMs, "
                "invokeFunctionLatencyMs, prepareCodeLatencyMs, runtimeInitializationMs, "
                "scheduleLatencyMs, invokeFunctionStartTimestamp FROM log "
                f"WHERE requestId = '{request_id}' AND operation = 'InvokeFunction'"
            )
            default_logstore = self._logstore(context, node)
            sls_project, logstore = self._log_destination(default_logstore)
            metrics = None
            try:
                metrics = self._sls_for_project(sls_project).getlogs(
                    logstore,
                    from_time,
                    to_time,
                    query,
                )
            except Exception as exc:
                result.diagnostics.append(
                    {
                        "kind": "collector_error",
                        "provider": "ali_sls",
                        "project": sls_project,
                        "logstore": logstore,
                        "request_id": request_id,
                        "error": str(exc),
                    }
                )
            evidence_id = f"ali_sls:{index}"
            result.evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    provider="ali",
                    source="sls",
                    query={
                        "configured_project": self.project,
                        "project": sls_project,
                        "location": self.location,
                        "logstore": logstore,
                        "from": from_time,
                        "to": to_time,
                        "query": query,
                        "request_id": request_id,
                    },
                    raw=metrics,
                )
            )
            if metrics:
                fields = dict(metrics)
                fields.setdefault("elapsed_time_ms", fields.get("duration_ms"))
                fields["client_e2e_ms"] = invocation.client_elapsed_ms
                duration_ms = fields.get("duration_ms") or fields.get("durationms")
                provider_start_ns = _epochish_to_ns(
                    fields.get("invokeFunctionStartTimestamp")
                )
                if provider_start_ns and duration_ms:
                    fields.setdefault("provider_receive_wall_ns", provider_start_ns)
                    fields.setdefault("provider_dispatch_wall_ns", provider_start_ns)
                    fields.setdefault(
                        "provider_response_wall_ns",
                        provider_start_ns + _duration_ms_to_ns(duration_ms),
                    )
                    fields.setdefault("provider_duration_ms", _coerce_float(duration_ms))
                    fields.setdefault("provider_time_source", "provider_log")
                    fields.setdefault("provider_confidence", "provider_log")
                destination_key = (sls_project, logstore)
                if destination_key not in breakdowns_by_logstore:
                    breakdowns_by_logstore[destination_key] = self._breakdowns_for_logstore(
                        sls_project,
                        logstore,
                        from_time,
                        to_time,
                        result,
                    )
                breakdowns = breakdowns_by_logstore.get(destination_key, {})
                fields.update(breakdowns.get(invocation.call_id, {}))
                fields.update(breakdowns.get(request_id, {}))
                result.metrics.append(
                    _metric_from_invocation(
                        "ali",
                        "sls",
                        invocation,
                        node,
                        fields,
                        [evidence_id],
                    )
                )
            else:
                destination_key = (sls_project, logstore)
                if destination_key not in breakdowns_by_logstore:
                    breakdowns_by_logstore[destination_key] = self._breakdowns_for_logstore(
                        sls_project,
                        logstore,
                        from_time,
                        to_time,
                        result,
                    )
                fallback_fields = {}
                breakdowns = breakdowns_by_logstore.get(destination_key, {})
                fallback_fields.update(breakdowns.get(invocation.call_id, {}))
                fallback_fields.update(breakdowns.get(request_id, {}))
                result.metrics.append(
                    _metric_from_invocation(
                        "ali",
                        "runtime",
                        invocation,
                        node,
                        fallback_fields,
                        evidence_refs=[evidence_id],
                    )
                )
                result.diagnostics.append(
                    {
                        "kind": "unmatched_request_id",
                        "provider": "ali_sls",
                        "request_id": request_id,
                        "call_id": invocation.call_id,
                    }
                )
        return result


class AWSCloudWatchCollector:
    observability_provider = "aws_lambda_cloudwatch"
    default_ingestion_delay_s = 30.0

    def __init__(self, *, agentcore: bool = False, region: Optional[str] = None):
        self.agentcore = agentcore
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._cloudwatch = None
        self.observability_provider = (
            "aws_agentcore_cloudwatch" if agentcore else "aws_lambda_cloudwatch"
        )
        self.default_ingestion_delay_s = 1800.0 if agentcore else 30.0

    @property
    def cloudwatch(self):
        if self._cloudwatch is None:
            from atsuite.aws.CloudWatch import AWSCloudWatch

            self._cloudwatch = AWSCloudWatch(region=self.region)
        return self._cloudwatch

    def _resource_name(self, context: RunContext, node: Optional[NodeObservation]) -> str:
        if node is None:
            return context.benchmark.lower()
        runtime_name = node.runtime_name or node.target_id or node.node_name or context.benchmark
        return runtime_name.lower()

    @staticmethod
    def _endpoint_for_target(context: RunContext, target_id: str) -> str:
        targets = (context.endpoint_map or {}).get("targets") or {}
        entry = targets.get(target_id) if isinstance(targets, dict) else None
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return str(entry.get("endpoint") or entry.get("url") or "")
        return ""

    @staticmethod
    def _agentcore_runtime_id_from_endpoint(endpoint: str) -> str:
        decoded = unquote(str(endpoint or ""))
        if not decoded:
            return ""
        candidates = [decoded, urlparse(decoded).path]
        for candidate in candidates:
            marker = "runtime/"
            if marker not in candidate:
                continue
            runtime_id = candidate.split(marker, 1)[1]
            runtime_id = runtime_id.split("?", 1)[0].split("#", 1)[0].split("/", 1)[0]
            if runtime_id:
                return runtime_id
        return ""

    @staticmethod
    def _agentcore_runtime_prefix(runtime_name: str) -> str:
        normalized = str(runtime_name or "").lower().replace("-", "_")
        if normalized.startswith("atsuite_"):
            return normalized
        return f"atsuite_{normalized}" if normalized else ""

    @staticmethod
    def _read_float_env(env_name: str, default: float) -> float:
        raw = os.environ.get(env_name)
        if raw in (None, ""):
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _agentcore_time_window(context: RunContext) -> tuple[datetime, datetime]:
        start = datetime.fromtimestamp((context.start_time or time.time()) - 300)
        end = datetime.fromtimestamp((context.end_time or time.time()) + 300)
        return start, end

    @staticmethod
    def _agentcore_usage_end(base_end: datetime) -> datetime:
        delayed_log_end = datetime.fromtimestamp(time.time() + 300)
        return max(base_end, delayed_log_end)

    def _agentcore_runtime_id(
        self,
        context: RunContext,
        *,
        target_id: str,
        runtime_name: str,
    ) -> str:
        endpoint_runtime_id = self._agentcore_runtime_id_from_endpoint(
            self._endpoint_for_target(context, target_id)
        )
        if endpoint_runtime_id:
            return endpoint_runtime_id

        prefix = self._agentcore_runtime_prefix(runtime_name or target_id)
        discover = getattr(self.cloudwatch, "_discover_agentcore_runtime_id", None)
        if callable(discover) and prefix:
            try:
                discovered = discover(prefix)
            except Exception:
                discovered = None
            if discovered:
                return str(discovered)
        return prefix or runtime_name or target_id

    def _agentcore_session_rows(
        self,
        sessions: List[SessionObservation],
        invocations: List[InvocationObservation],
        result: Optional[CollectionResult] = None,
    ) -> List[Dict[str, str]]:
        session_rows: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for session in sessions:
            sid = str(session.provider_session_id or "")
            if not sid:
                if result is not None:
                    result.diagnostics.append(
                        {
                            "kind": "missing_agentcore_session_id",
                            "provider": self.observability_provider,
                            "target_id": session.target_id,
                            "runtime_name": session.runtime_name,
                        }
                    )
                continue
            key = (session.target_id, sid)
            if key not in seen:
                seen.add(key)
                session_rows.append(
                    {
                        "target_id": session.target_id,
                        "runtime_name": session.runtime_name or session.target_id,
                        "session_id": sid,
                    }
                )

        for invocation in invocations:
            sid = str(
                invocation.provider_session_id
                or invocation.provider_metadata.get("session_id")
                or ""
            )
            if not sid:
                continue
            key = (invocation.target_id, sid)
            if key in seen:
                continue
            seen.add(key)
            session_rows.append(
                {
                    "target_id": invocation.target_id,
                    "runtime_name": invocation.runtime_name or invocation.target_id,
                    "session_id": sid,
                }
            )
        return session_rows

    def wait_for_ingestion(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> None:
        if not self.agentcore:
            delay = float(self.default_ingestion_delay_s or 0.0)
            if delay > 0:
                time.sleep(delay)
            return

        session_rows = self._agentcore_session_rows(sessions, invocations)
        if not session_rows:
            return

        timeout_s = self._read_float_env(
            "ATSUITE_AGENTCORE_USAGE_WAIT_TIMEOUT_S",
            1800.0,
        )
        poll_interval_s = max(
            1.0,
            self._read_float_env("ATSUITE_AGENTCORE_USAGE_POLL_INTERVAL_S", 60.0),
        )
        deadline = None if timeout_s <= 0 else time.monotonic() + timeout_s
        start, base_end = self._agentcore_time_window(context)
        attempt = 0

        while True:
            attempt += 1
            ready = 0
            missing: List[str] = []
            usage_end = self._agentcore_usage_end(base_end)
            for row in session_rows:
                runtime_id = self._agentcore_runtime_id(
                    context,
                    target_id=row["target_id"],
                    runtime_name=row["runtime_name"],
                )
                sid = row["session_id"]
                try:
                    usage = self.cloudwatch.get_agentcore_usage_from_logs(
                        runtime_id,
                        sid,
                        start,
                        usage_end,
                    )
                except Exception as exc:
                    usage = {"error": str(exc)}

                if (
                    usage
                    and not usage.get("missing_log_group")
                    and _coerce_int(usage.get("log_entries")) > 0
                ):
                    ready += 1
                else:
                    missing.append(f"{row['runtime_name']}:{sid}")

            if ready == len(session_rows):
                print(
                    f"[analysis] AgentCore usage logs ready after {attempt} poll(s): "
                    f"{ready}/{len(session_rows)} session(s)"
                )
                return

            if deadline is not None and time.monotonic() >= deadline:
                print(
                    f"[analysis] AgentCore usage log wait timed out after {timeout_s:.0f}s: "
                    f"{ready}/{len(session_rows)} session(s) ready; missing={missing}"
                )
                return

            sleep_s = poll_interval_s
            if deadline is not None:
                sleep_s = min(sleep_s, max(1.0, deadline - time.monotonic()))
            print(
                f"[analysis] Waiting for AgentCore usage logs: "
                f"{ready}/{len(session_rows)} session(s) ready; "
                f"next poll in {sleep_s:.0f}s; missing={missing}"
            )
            time.sleep(sleep_s)

    @staticmethod
    def _parse_json_breakdowns(logs: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        records: Dict[str, Dict[str, Any]] = {}
        for event in logs:
            msg = str(event.get("message", ""))
            for line in msg.splitlines():
                if "atsuite_" not in line:
                    continue
                start = line.find("{")
                if start < 0:
                    continue
                try:
                    payload = json.loads(line[start:])
                except Exception:
                    continue
                event_name = str(payload.get("event", ""))
                if event_name not in _BREAKDOWN_EVENT_NAMES:
                    continue
                key = str(payload.get("request_id") or payload.get("client_request_id") or payload.get("jsonrpc_id") or "")
                if not key:
                    continue
                records[key] = _normalise_breakdown_fields(payload)
        return records

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        result = CollectionResult()
        start = datetime.fromtimestamp((context.start_time or time.time()) - 300)
        end = datetime.fromtimestamp((context.end_time or time.time()) + 300)
        if self.agentcore:
            self._collect_agentcore_invocations(context, nodes, invocations, start, end, result)
            result.evidence.extend(
                self._collect_agentcore_session_usage(
                    context,
                    sessions,
                    invocations,
                    start,
                    end,
                    result,
                )
            )
            return result

        resource_type = "lambda"
        for index, invocation in enumerate(invocations, start=1):
            node = nodes.get(invocation.node_id)
            resource_name = self._resource_name(context, node)
            request_id = invocation.provider_request_id or invocation.call_id
            logs: List[Dict[str, Any]] = []
            parsed: Dict[str, Any] = {}
            try:
                logs = self.cloudwatch.get_logs(
                    resource_type,
                    resource_name,
                    start,
                    end,
                    request_id=request_id if request_id else None,
                )
                if logs:
                    parsed = self.cloudwatch.parse_logs("lambda", logs)
            except Exception as exc:
                result.diagnostics.append(
                    {
                        "kind": "collector_error",
                        "provider": self.observability_provider,
                        "request_id": request_id,
                        "error": str(exc),
                    }
                )
            evidence_id = f"{self.observability_provider}:{index}"
            result.evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    provider="aws_lambda",
                    source="cloudwatch",
                    query={
                        "region": self.region,
                        "resource_type": resource_type,
                        "resource_name": resource_name,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "request_id": request_id,
                    },
                    raw=logs,
                )
            )
            fields: Dict[str, Any] = {
                "client_e2e_ms": invocation.client_elapsed_ms,
                "elapsed_time_ms": invocation.client_elapsed_ms,
            }
            if parsed:
                duration = parsed.get("duration_ms")
                if duration is not None:
                    fields["duration_ms"] = duration
                    fields["elapsed_time_ms"] = duration
                    _add_provider_duration_from_response(
                        fields,
                        response_wall_ns=_max_log_event_timestamp_ns(logs),
                        duration_ms=duration,
                        confidence="estimated_from_report_timestamp",
                    )
                fields["billed_duration_ms"] = parsed.get("billed_duration_ms")
                fields["memory_usage_mb"] = parsed.get("memory_used_mb")
                fields["memory"] = parsed.get("memory_limit_mb") or _memory_from_node(node)
                fields["memory_limit_mb"] = parsed.get("memory_limit_mb")
                fields["init_duration_ms"] = parsed.get("init_duration_ms")
                fields["is_cold_start"] = "true" if parsed.get("is_cold_start") else "false"
            breakdowns = self._parse_json_breakdowns(logs)
            fields.update(breakdowns.get(request_id, {}))
            fields.update(breakdowns.get(invocation.call_id, {}))
            result.metrics.append(
                _metric_from_invocation(
                    "aws_lambda",
                    "cloudwatch",
                    invocation,
                    node,
                    fields,
                    [evidence_id],
                )
            )
            if not logs:
                result.diagnostics.append(
                    {
                        "kind": "unmatched_request_id",
                        "provider": self.observability_provider,
                        "request_id": request_id,
                        "call_id": invocation.call_id,
                    }
                )
        return result

    def _collect_agentcore_invocations(
        self,
        context: RunContext,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        start: datetime,
        end: datetime,
        result: CollectionResult,
    ) -> None:
        grouped: Dict[str, List[InvocationObservation]] = {}
        runtime_names: Dict[str, str] = {}
        for invocation in invocations:
            node = nodes.get(invocation.node_id)
            runtime_name = self._resource_name(context, node)
            runtime_id = self._agentcore_runtime_id(
                context,
                target_id=invocation.target_id,
                runtime_name=runtime_name,
            )
            grouped.setdefault(runtime_id, []).append(invocation)
            runtime_names.setdefault(runtime_id, runtime_name)

        evidence_by_runtime: Dict[str, str] = {}
        breakdowns_by_runtime: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for index, (runtime_id, runtime_invocations) in enumerate(grouped.items(), start=1):
            logs: List[Dict[str, Any]] = []
            try:
                logs = self.cloudwatch.get_logs(
                    "agentcore",
                    runtime_id,
                    start,
                    end,
                    request_id=None,
                )
            except Exception as exc:
                result.diagnostics.append(
                    {
                        "kind": "collector_error",
                        "provider": self.observability_provider,
                        "runtime_id": runtime_id,
                        "error": str(exc),
                    }
                )
            evidence_id = f"{self.observability_provider}:runtime:{index}"
            evidence_by_runtime[runtime_id] = evidence_id
            result.evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    provider="aws_agentcore",
                    source="cloudwatch",
                    query={
                        "region": self.region,
                        "resource_type": "agentcore",
                        "resource_name": runtime_names.get(runtime_id, ""),
                        "runtime_id": runtime_id,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "request_id": None,
                    },
                    raw=logs,
                )
            )
            breakdowns_by_runtime[runtime_id] = self._parse_json_breakdowns(logs)
            if not logs:
                result.diagnostics.append(
                    {
                        "kind": "unmatched_runtime_logs",
                        "provider": self.observability_provider,
                        "runtime_id": runtime_id,
                        "invocation_count": len(runtime_invocations),
                    }
                )

        for invocation in invocations:
            node = nodes.get(invocation.node_id)
            runtime_name = self._resource_name(context, node)
            runtime_id = self._agentcore_runtime_id(
                context,
                target_id=invocation.target_id,
                runtime_name=runtime_name,
            )
            evidence_id = evidence_by_runtime.get(runtime_id, "")
            request_id = invocation.provider_request_id or invocation.call_id
            session_id = str(
                invocation.provider_session_id
                or invocation.provider_metadata.get("session_id")
                or ""
            )
            fields: Dict[str, Any] = {
                "client_e2e_ms": invocation.client_elapsed_ms,
                "duration_ms": invocation.client_elapsed_ms,
                "elapsed_time_ms": invocation.client_elapsed_ms,
                "is_cold_start": "false",
            }
            if session_id:
                fields["session_id"] = session_id

            matched = False
            candidate_keys = [
                invocation.call_id,
                invocation.provider_request_id,
                str(invocation.provider_metadata.get("request_id") or ""),
                str(invocation.provider_metadata.get("client_request_id") or ""),
                str(invocation.provider_metadata.get("jsonrpc_id") or ""),
            ]
            runtime_breakdowns = breakdowns_by_runtime.get(runtime_id, {})
            for key in candidate_keys:
                if key and key in runtime_breakdowns:
                    fields.update(runtime_breakdowns[key])
                    matched = True
                    break

            result.metrics.append(
                _metric_from_invocation(
                    "aws_agentcore",
                    "cloudwatch",
                    invocation,
                    node,
                    fields,
                    [evidence_id] if evidence_id else [],
                )
            )
            if not matched:
                result.diagnostics.append(
                    {
                        "kind": "unmatched_request_id",
                        "provider": self.observability_provider,
                        "request_id": request_id,
                        "call_id": invocation.call_id,
                        "runtime_id": runtime_id,
                    }
                )

    def _collect_agentcore_session_usage(
        self,
        context: RunContext,
        sessions: List[SessionObservation],
        invocations: List[InvocationObservation],
        start: datetime,
        end: datetime,
        result: CollectionResult,
    ) -> List[EvidenceRecord]:
        evidence: List[EvidenceRecord] = []
        session_rows = self._agentcore_session_rows(sessions, invocations, result)
        usage_end = self._agentcore_usage_end(end)

        for index, session in enumerate(session_rows, start=1):
            sid = session["session_id"]
            runtime_name = session["runtime_name"]
            usage = {}
            runtime_id = self._agentcore_runtime_id(
                context,
                target_id=session["target_id"],
                runtime_name=runtime_name,
            )
            try:
                if runtime_id:
                    usage = self.cloudwatch.get_agentcore_usage_from_logs(
                        runtime_id,
                        sid,
                        start,
                        usage_end,
                    )
            except Exception as exc:
                result.diagnostics.append(
                    {
                        "kind": "collector_error",
                        "provider": self.observability_provider,
                        "session_id": sid,
                        "runtime_name": runtime_name,
                        "error": str(exc),
                    }
                )
            evidence_id = f"{self.observability_provider}:session:{index}"
            evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    provider="aws_agentcore",
                    source="agentcore_usage",
                    query={
                        "region": self.region,
                        "runtime_name": runtime_name,
                        "target_id": session["target_id"],
                        "runtime_id": runtime_id,
                        "session_id": sid,
                        "start": start.isoformat(),
                        "end": usage_end.isoformat(),
                    },
                    raw=usage,
                )
            )
            if not usage or usage.get("missing_log_group"):
                result.diagnostics.append(
                    {
                        "kind": "agentcore_usage_unavailable",
                        "provider": self.observability_provider,
                        "runtime_name": runtime_name,
                        "runtime_id": runtime_id,
                        "session_id": sid,
                        "reason": usage.get("error") if isinstance(usage, dict) else "",
                    }
                )
            if usage:
                result.metrics.append(
                    ProviderMetric(
                        metric_id=f"agentcore_usage:{sid}",
                        provider="aws_agentcore",
                        source="agentcore_usage",
                        fields={
                            "session_id": sid,
                            "runtime_name": runtime_name,
                            "vcpu_hours": usage.get("vcpu_hours", 0.0),
                            "memory_gb_hours": usage.get("memory_gb_hours", 0.0),
                            "log_entries": usage.get("log_entries", 0),
                        },
                        evidence_refs=[evidence_id],
                    )
                )
        return evidence


class GCPCloudLoggingCollector:
    observability_provider = "gcp_cloud_logging"
    default_ingestion_delay_s = 10.0

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    @staticmethod
    def _latency_ms(latency: Any) -> float:
        text = str(latency or "").strip()
        if text.endswith("s"):
            text = text[:-1]
        return _coerce_float(text, 0.0) * 1000.0

    def _list_entries(self, context: RunContext) -> List[Dict[str, Any]]:
        try:
            import google.cloud.logging  # type: ignore

            client = google.cloud.logging.Client(project=self.project_id or None)
            start = datetime.fromtimestamp((context.start_time or time.time()) - 300)
            end = datetime.fromtimestamp((context.end_time or time.time()) + 300)
            flt = (
                'resource.type="cloud_run_revision" '
                f'timestamp>="{start.isoformat()}Z" timestamp<="{end.isoformat()}Z"'
            )
            entries = []
            for entry in client.list_entries(filter_=flt, page_size=1000):
                entries.append(entry.to_api_repr())
            return entries
        except Exception:
            return []

    def _index_entries(self, entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        indexed: Dict[str, Dict[str, Any]] = {}
        request_metas: List[Dict[str, Any]] = []
        trace_to_meta: Dict[str, Dict[str, Any]] = {}
        request_id_to_trace: Dict[str, str] = {}
        breakdowns: Dict[str, Dict[str, Any]] = {}

        for entry in entries:
            payload = entry.get("jsonPayload") or entry.get("payload") or {}
            if isinstance(payload, dict):
                rid = payload.get("request_id")
                trace = payload.get("trace") or entry.get("trace")
                if rid and trace:
                    request_id_to_trace[str(rid)] = str(trace)
                if payload.get("event") in _BREAKDOWN_EVENT_NAMES:
                    rid = str(payload.get("request_id") or payload.get("client_request_id") or payload.get("jsonrpc_id") or "")
                    if rid:
                        breakdowns[rid] = _normalise_breakdown_fields(payload)
            text = entry.get("textPayload")
            if isinstance(text, str) and text.lstrip().startswith("{"):
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = {}
                if isinstance(payload, dict) and payload.get("event") in _BREAKDOWN_EVENT_NAMES:
                    rid = str(payload.get("request_id") or payload.get("client_request_id") or payload.get("jsonrpc_id") or "")
                    if rid:
                        breakdowns[rid] = _normalise_breakdown_fields(payload)

            http_req = entry.get("httpRequest") or {}
            if isinstance(http_req, dict) and http_req.get("latency"):
                trace = str(entry.get("trace") or "")
                labels = (entry.get("resource") or {}).get("labels") or {}
                latency_ms = self._latency_ms(http_req.get("latency"))
                meta = {
                    "latency_ms": latency_ms,
                    "status": _coerce_int(http_req.get("status"), 0),
                    "service_name": labels.get("service_name") or "",
                    "trace": trace,
                }
                response_wall_ns = _datetime_text_to_ns(entry.get("timestamp"))
                _add_provider_duration_from_response(
                    meta,
                    response_wall_ns=response_wall_ns,
                    duration_ms=latency_ms,
                    confidence="provider_log",
                )
                request_metas.append(meta)
                if trace:
                    trace_to_meta[trace] = meta

        for rid, trace in request_id_to_trace.items():
            if trace in trace_to_meta:
                merged = dict(trace_to_meta[trace])
                merged.update(breakdowns.get(rid, {}))
                indexed[rid] = merged

        for rid, breakdown in breakdowns.items():
            indexed.setdefault(rid, dict(breakdown))
        return indexed

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        result = CollectionResult()
        entries = self._list_entries(context)
        indexed = self._index_entries(entries)
        evidence_id = "gcp_cloud_logging:entries"
        result.evidence.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                provider="gcp",
                source="cloud_logging",
                query={
                    "project_id": self.project_id,
                    "start_time": context.start_time,
                    "end_time": context.end_time,
                },
                raw=entries,
            )
        )
        for invocation in invocations:
            node = nodes.get(invocation.node_id)
            request_id = invocation.provider_request_id or invocation.call_id
            meta = indexed.get(request_id, {})
            fields = {
                "client_e2e_ms": invocation.client_elapsed_ms,
                "elapsed_time_ms": meta.get("latency_ms", invocation.client_elapsed_ms),
                "duration_ms": meta.get("latency_ms", invocation.client_elapsed_ms),
                "status": meta.get("status", invocation.status),
                "service_name": meta.get("service_name", ""),
                **{
                    k: v
                    for k, v in meta.items()
                    if k
                    in {
                        "app_e2e_ms",
                        "tool_exec_ms",
                        "state_sync_overhead_ms",
                        "framework_overhead_ms",
                        "pre_tool_ms",
                        "post_tool_ms",
                        "request_wall_ns",
                        "request_start_wall_ns",
                        "request_end_wall_ns",
                        "tool_start_wall_ns",
                        "tool_end_wall_ns",
                        "time_source",
                        "confidence",
                        "provider_receive_wall_ns",
                        "provider_response_wall_ns",
                        "provider_duration_ms",
                        "provider_time_source",
                        "provider_confidence",
                    }
                },
            }
            result.metrics.append(
                _metric_from_invocation(
                    "gcp",
                    "cloud_logging" if meta else "runtime",
                    invocation,
                    node,
                    fields,
                    [evidence_id],
                )
            )
            if not meta:
                result.diagnostics.append(
                    {
                        "kind": "unmatched_request_id",
                        "provider": "gcp_cloud_logging",
                        "request_id": request_id,
                        "call_id": invocation.call_id,
                    }
                )
        return result


class MCPGatewayCollector(NoopCollector):
    observability_provider = "mcp_gateway"
    default_ingestion_delay_s = 0.0

    def collect(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
    ) -> CollectionResult:
        endpoint = ""
        raw_obs = context.endpoint_map.get("observability")
        if isinstance(raw_obs, dict):
            endpoint = str(raw_obs.get("endpoint") or raw_obs.get("url") or "")
        elif isinstance(raw_obs, str):
            endpoint = raw_obs
        endpoint = endpoint.rstrip("/")
        if not endpoint:
            return super().collect(context, nodes=nodes, invocations=invocations, sessions=sessions)

        result = super().collect(context, nodes=nodes, invocations=invocations, sessions=sessions)
        try:
            import requests

            response = requests.get(
                f"{endpoint}/runs/{context.uid}/evidence",
                timeout=30,
            )
            response.raise_for_status()
            raw = response.json()
            result.evidence.append(
                EvidenceRecord(
                    evidence_id="mcp_gateway:evidence",
                    provider="mcp_gateway",
                    source="gateway_observability",
                    query={"endpoint": endpoint, "uid": context.uid},
                    raw=raw,
                )
            )
        except Exception as exc:
            result.diagnostics.append(
                {
                    "kind": "collector_error",
                    "provider": "mcp_gateway",
                    "error": str(exc),
                }
            )
        return result


def create_collector(observability_provider: str) -> ProviderCollector:
    key = str(observability_provider or "none").strip().lower()
    if key in {"ali", "ali_sls", "ali_fc", "ali_agentrun"}:
        return AliSLSCollector(
            project=os.environ.get("ATSUITE_ALI_SLS_PROJECT", "atsuite"),
            location=os.environ.get("ATSUITE_ALI_SLS_LOCATION", "us-east-1"),
        )
    if key in {"aws", "aws_lambda", "aws_lambda_cloudwatch"}:
        return AWSCloudWatchCollector(agentcore=False)
    if key in {"aws_agentcore", "aws_agentcore_cloudwatch"}:
        return AWSCloudWatchCollector(agentcore=True)
    if key in {"gcp", "gcp_faas", "gcp_mcp", "gcp_cloud_logging"}:
        return GCPCloudLoggingCollector()
    if key == "mcp_gateway":
        return MCPGatewayCollector()
    return NoopCollector()
