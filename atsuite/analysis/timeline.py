from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from atsuite.analysis.model import (
    InvocationObservation,
    NodeObservation,
    ProviderMetric,
    RunContext,
    SessionObservation,
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sec_to_us(seconds: Any) -> int:
    value = _num(seconds)
    return int(round(value * 1_000_000)) if value > 0 else 0


def _ms_to_us(ms: Any) -> int:
    value = _num(ms)
    return int(round(value * 1_000)) if value >= 0 else 0


def _ns_to_us(ns: Any) -> int:
    value = _int(ns)
    return int(round(value / 1_000)) if value > 0 else 0


def _ms_to_ns(ms: Any) -> int:
    value = _num(ms)
    return int(round(value * 1_000_000)) if value >= 0 else 0


def _first_ns(fields: Dict[str, Any], *names: str) -> int:
    for name in names:
        value = _int(fields.get(name))
        if value > 0:
            return value
    return 0


@dataclass
class TimelineEvent:
    name: str
    cat: str
    ph: str
    ts: int
    pid: str
    tid: str
    dur: Optional[int] = None
    args: Dict[str, Any] = field(default_factory=dict)
    scope: str = "t"

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": self.name,
            "cat": self.cat,
            "ph": self.ph,
            "ts": self.ts,
            "pid": self.pid,
            "tid": self.tid,
        }
        if self.ph == "X" and self.dur is not None:
            payload["dur"] = max(0, int(self.dur))
        if self.ph == "i":
            payload["s"] = self.scope
        if self.args:
            payload["args"] = self.args
        return payload


class TimelineBuilder:
    def build(
        self,
        context: RunContext,
        *,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
        sessions: List[SessionObservation],
        metrics: List[ProviderMetric],
        diagnostics: Iterable[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        events: List[TimelineEvent] = []
        metrics_by_call: Dict[str, List[ProviderMetric]] = defaultdict(list)
        for metric in metrics:
            if metric.invocation_call_id:
                metrics_by_call[metric.invocation_call_id].append(metric)

        client_lanes = self._client_lanes(nodes, invocations)
        self._add_run(events, context)
        self._add_llm_nodes(events, context, nodes, client_lanes)
        self._add_sessions(events, context, sessions)

        for invocation in invocations:
            merged_metric = self._merge_metrics(metrics_by_call.get(invocation.call_id, []))
            self._add_invocation(
                events,
                context,
                invocation,
                merged_metric,
                client_tid=client_lanes.get(("tool_use", invocation.node_id), "tool_use/0"),
            )

        self._add_diagnostics(events, context, diagnostics)
        trace_events = self._metadata_events(events) + [event.to_dict() for event in events]
        return {
            "traceEvents": trace_events,
            "displayTimeUnit": "ms",
            "metadata": {
                "schema": "atsuite.analysis.timeline.v1",
                "uid": context.uid,
                "provider": context.provider,
                "observability_provider": context.observability_provider,
                "benchmark": context.benchmark,
                "trace": context.trace,
                "family": context.family,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
        }

    def _base_args(self, context: RunContext, **kwargs: Any) -> Dict[str, Any]:
        args = {"uid": context.uid}
        args.update({k: v for k, v in kwargs.items() if v not in (None, "")})
        return args

    def _span(
        self,
        events: List[TimelineEvent],
        *,
        name: str,
        cat: str,
        pid: str,
        tid: str,
        start_us: int,
        end_us: Optional[int] = None,
        dur_us: Optional[int] = None,
        args: Optional[Dict[str, Any]] = None,
    ) -> None:
        if start_us <= 0:
            return
        if dur_us is None:
            if end_us is None or end_us < start_us:
                return
            dur_us = end_us - start_us
        events.append(
            TimelineEvent(
                name=name,
                cat=cat,
                ph="X",
                ts=start_us,
                dur=max(0, int(dur_us)),
                pid=pid,
                tid=tid,
                args=dict(args or {}),
            )
        )

    def _instant(
        self,
        events: List[TimelineEvent],
        *,
        name: str,
        cat: str,
        pid: str,
        tid: str,
        ts_us: int,
        args: Optional[Dict[str, Any]] = None,
    ) -> None:
        if ts_us <= 0:
            return
        events.append(
            TimelineEvent(
                name=name,
                cat=cat,
                ph="i",
                ts=ts_us,
                pid=pid,
                tid=tid,
                args=dict(args or {}),
            )
        )

    def _add_run(self, events: List[TimelineEvent], context: RunContext) -> None:
        start_us = _sec_to_us(context.start_time)
        end_us = _sec_to_us(context.end_time)
        self._span(
            events,
            name="run",
            cat="client",
            pid="client",
            tid="run",
            start_us=start_us,
            end_us=end_us,
            args=self._base_args(
                context,
                provider=context.provider,
                observability_provider=context.observability_provider,
                benchmark=context.benchmark,
                trace=context.trace,
                family=context.family,
                time_source="client_wall_clock",
                confidence="client",
            ),
        )

    def _allocate_lanes(self, intervals: List[Tuple[int, int, int]]) -> Dict[int, int]:
        lane_ends: List[int] = []
        lanes: Dict[int, int] = {}
        for item_id, start_us, end_us in sorted(intervals, key=lambda item: (item[1], item[2], item[0])):
            if start_us <= 0:
                continue
            end_us = max(start_us, end_us)
            assigned = None
            for index, lane_end in enumerate(lane_ends):
                if start_us >= lane_end:
                    assigned = index
                    lane_ends[index] = end_us
                    break
            if assigned is None:
                assigned = len(lane_ends)
                lane_ends.append(end_us)
            lanes[item_id] = assigned
        return lanes

    def _client_lanes(
        self,
        nodes: Dict[int, NodeObservation],
        invocations: List[InvocationObservation],
    ) -> Dict[Tuple[str, int], str]:
        lanes: Dict[Tuple[str, int], str] = {}
        llm_intervals = [
            (node.node_id, _sec_to_us(node.start_time), _sec_to_us(node.end_time))
            for node in nodes.values()
            if node.node_type == "llm"
        ]
        for node_id, lane in self._allocate_lanes(llm_intervals).items():
            lanes[("llm", node_id)] = f"llm/{lane}"

        tool_intervals: List[Tuple[int, int, int]] = []
        for invocation in invocations:
            node = nodes.get(invocation.node_id)
            start_us = _sec_to_us(invocation.client_start_time)
            if start_us <= 0 and node is not None:
                start_us = _sec_to_us(node.start_time)
            dur_us = _ms_to_us(invocation.client_elapsed_ms)
            end_us = start_us + dur_us if start_us and dur_us else 0
            if end_us <= start_us and node is not None:
                end_us = _sec_to_us(node.end_time)
            tool_intervals.append((invocation.node_id, start_us, end_us))
        for node_id, lane in self._allocate_lanes(tool_intervals).items():
            lanes[("tool_use", node_id)] = f"tool_use/{lane}"
        return lanes

    def _add_llm_nodes(
        self,
        events: List[TimelineEvent],
        context: RunContext,
        nodes: Dict[int, NodeObservation],
        client_lanes: Dict[Tuple[str, int], str],
    ) -> None:
        for node_id, node in sorted(nodes.items()):
            if node.node_type != "llm":
                continue
            self._span(
                events,
                name=f"llm:{node_id}:{node.node_name}",
                cat="client",
                pid="client",
                tid=client_lanes.get(("llm", node_id), "llm/0"),
                start_us=_sec_to_us(node.start_time),
                end_us=_sec_to_us(node.end_time),
                args=self._base_args(
                    context,
                    node_id=node.node_id,
                    node_name=node.node_name,
                    node_type=node.node_type,
                    target_id=node.target_id,
                    time_source="client_wall_clock",
                    confidence="client",
                ),
            )

    def _add_sessions(
        self,
        events: List[TimelineEvent],
        context: RunContext,
        sessions: List[SessionObservation],
    ) -> None:
        if context.family == "faas":
            return
        for session in sessions:
            if not (
                session.provider_session_id
                or session.initialize_request_id
                or session.closed_at > session.opened_at
            ):
                continue
            pid = f"provider:{session.target_id or session.runtime_name or 'unknown'}"
            args = self._base_args(
                context,
                target_id=session.target_id,
                session_id=session.provider_session_id,
                initialize_request_id=session.initialize_request_id,
                time_source="client_wall_clock",
                confidence="client",
            )
            opened_us = _sec_to_us(session.opened_at)
            closed_us = _sec_to_us(session.closed_at)
            if closed_us > opened_us:
                self._span(
                    events,
                    name=f"session_open:{session.target_id}",
                    cat="provider",
                    pid=pid,
                    tid="session",
                    start_us=opened_us,
                    end_us=closed_us,
                    args=args,
                )
            else:
                self._instant(
                    events,
                    name=f"session_open:{session.target_id}",
                    cat="provider",
                    pid=pid,
                    tid="session",
                    ts_us=opened_us,
                    args=args,
                )

    def _merge_metrics(self, metrics: List[ProviderMetric]) -> ProviderMetric | None:
        if not metrics:
            return None
        fields: Dict[str, Any] = {}
        evidence_refs: List[str] = []
        provider_request_id = ""
        source = ""
        provider = ""
        node_id: Optional[int] = None
        call_id = ""
        for metric in metrics:
            fields.update(metric.fields)
            evidence_refs.extend(metric.evidence_refs)
            provider_request_id = metric.provider_request_id or provider_request_id
            source = metric.source or source
            provider = metric.provider or provider
            node_id = metric.node_id if metric.node_id is not None else node_id
            call_id = metric.invocation_call_id or call_id
        return ProviderMetric(
            metric_id="timeline:merged",
            provider=provider,
            source=source,
            node_id=node_id,
            invocation_call_id=call_id,
            provider_request_id=provider_request_id,
            fields=fields,
            evidence_refs=sorted(set(evidence_refs)),
        )

    def _add_invocation(
        self,
        events: List[TimelineEvent],
        context: RunContext,
        invocation: InvocationObservation,
        metric: ProviderMetric | None,
        client_tid: str,
    ) -> None:
        fields = dict(metric.fields) if metric is not None else {}
        target_id = invocation.target_id or invocation.runtime_name or "unknown"
        common_args = self._base_args(
            context,
            node_id=invocation.node_id,
            node_name=invocation.node_name,
            target_id=invocation.target_id,
            tool_name=invocation.tool_name,
            call_id=invocation.call_id,
            provider_request_id=invocation.provider_request_id
            or (metric.provider_request_id if metric else ""),
            session_id=invocation.provider_session_id
            or invocation.provider_metadata.get("session_id", ""),
        )

        client_start_us = _sec_to_us(invocation.client_start_time)
        client_dur_us = _ms_to_us(invocation.client_elapsed_ms)
        client_args = dict(common_args)
        client_args.update({"time_source": "client_wall_clock", "confidence": "client"})
        self._instant(
            events,
            name=f"client_send:{invocation.node_id}",
            cat="client",
            pid="client",
            tid=client_tid,
            ts_us=client_start_us,
            args=client_args,
        )
        self._span(
            events,
            name=f"tool_use:{invocation.node_id}:{invocation.node_name}",
            cat="client",
            pid="client",
            tid=client_tid,
            start_us=client_start_us,
            dur_us=client_dur_us,
            args=client_args,
        )
        self._instant(
            events,
            name=f"client_receive:{invocation.node_id}",
            cat="client",
            pid="client",
            tid=client_tid,
            ts_us=client_start_us + client_dur_us if client_start_us else 0,
            args=client_args,
        )

        self._add_provider_phases(events, invocation, fields, common_args, client_start_us)
        self._add_app_phases(events, invocation, fields, common_args, target_id)

    def _add_provider_phases(
        self,
        events: List[TimelineEvent],
        invocation: InvocationObservation,
        fields: Dict[str, Any],
        common_args: Dict[str, Any],
        client_start_us: int,
    ) -> None:
        target_id = invocation.target_id or "unknown"
        pid = f"provider:{target_id}"
        receive_ns = _first_ns(
            fields,
            "provider_receive_wall_ns",
            "cloud_receive_wall_ns",
            "provider_start_wall_ns",
        )
        response_ns = _first_ns(
            fields,
            "provider_response_wall_ns",
            "cloud_response_wall_ns",
            "provider_end_wall_ns",
        )
        duration_ns = _ms_to_ns(
            fields.get("provider_duration_ms")
            or fields.get("duration_ms")
            or fields.get("elapsed_time_ms")
        )
        if receive_ns and not response_ns and duration_ns:
            response_ns = receive_ns + duration_ns
        if response_ns and not receive_ns and duration_ns:
            receive_ns = max(0, response_ns - duration_ns)

        provider_args = dict(common_args)
        provider_args.update(
            {
                "time_source": fields.get("provider_time_source") or "provider_log",
                "confidence": fields.get("provider_confidence") or "provider_log",
            }
        )
        receive_us = _ns_to_us(receive_ns)
        response_us = _ns_to_us(response_ns)
        if receive_us:
            self._instant(
                events,
                name=f"cloud_receive:{invocation.node_id}",
                cat="provider",
                pid=pid,
                tid="provider",
                ts_us=receive_us,
                args=provider_args,
            )
        if receive_us and response_us >= receive_us:
            self._span(
                events,
                name=f"provider_duration:{invocation.node_id}",
                cat="provider",
                pid=pid,
                tid="provider",
                start_us=receive_us,
                end_us=response_us,
                args=provider_args,
            )
        else:
            missing_args = dict(common_args)
            missing_args.update(
                {
                    "diagnostic": "missing_cloud_receive_timestamp",
                    "time_source": "client_only",
                    "confidence": "missing_provider_evidence",
                }
            )
            self._instant(
                events,
                name=f"missing_cloud_receive_timestamp:{invocation.node_id}",
                cat="diagnostic",
                pid=pid,
                tid="diagnostic",
                ts_us=client_start_us,
                args=missing_args,
            )

        dispatch_ns = _first_ns(fields, "provider_dispatch_wall_ns", "provider_dispatched_wall_ns")
        dispatch_us = _ns_to_us(dispatch_ns)
        if dispatch_us:
            self._instant(
                events,
                name=f"provider_dispatch:{invocation.node_id}",
                cat="provider",
                pid=pid,
                tid="provider",
                ts_us=dispatch_us,
                args=provider_args,
            )
            if receive_us and dispatch_us >= receive_us:
                self._span(
                    events,
                    name=f"provider_queue:{invocation.node_id}",
                    cat="provider",
                    pid=pid,
                    tid="provider",
                    start_us=receive_us,
                    end_us=dispatch_us,
                    args=provider_args,
                )

    def _app_times(self, fields: Dict[str, Any]) -> Dict[str, int | str]:
        explicit_wall = any(
            _int(fields.get(name)) > 0
            for name in (
                "request_start_wall_ns",
                "request_end_wall_ns",
                "tool_start_wall_ns",
                "tool_end_wall_ns",
            )
        )
        request_start_ns = _first_ns(fields, "request_start_wall_ns", "request_wall_ns")
        request_end_ns = _first_ns(fields, "request_end_wall_ns")
        tool_start_ns = _first_ns(fields, "tool_start_wall_ns")
        tool_end_ns = _first_ns(fields, "tool_end_wall_ns")

        derived = False
        if request_start_ns and not request_end_ns and _num(fields.get("app_e2e_ms")) > 0:
            request_end_ns = request_start_ns + _ms_to_ns(fields.get("app_e2e_ms"))
            derived = True
        if request_start_ns and not tool_start_ns and _num(fields.get("pre_tool_ms")) >= 0:
            tool_start_ns = request_start_ns + _ms_to_ns(fields.get("pre_tool_ms"))
            derived = True
        if tool_start_ns and not tool_end_ns and _num(fields.get("tool_exec_ms")) > 0:
            tool_end_ns = tool_start_ns + _ms_to_ns(fields.get("tool_exec_ms"))
            derived = True
        if request_end_ns and not tool_end_ns and _num(fields.get("post_tool_ms")) > 0:
            tool_end_ns = max(0, request_end_ns - _ms_to_ns(fields.get("post_tool_ms")))
            derived = True
        if tool_end_ns and not tool_start_ns and _num(fields.get("tool_exec_ms")) > 0:
            tool_start_ns = max(0, tool_end_ns - _ms_to_ns(fields.get("tool_exec_ms")))
            derived = True

        source = str(fields.get("time_source") or "")
        confidence = str(fields.get("confidence") or "")
        if not source:
            source = "sdk_wall_clock" if explicit_wall else "derived_from_duration" if derived else ""
        if not confidence:
            confidence = "sdk_wall_clock" if explicit_wall else "estimated" if derived else ""
        return {
            "request_start_ns": request_start_ns,
            "request_end_ns": request_end_ns,
            "tool_start_ns": tool_start_ns,
            "tool_end_ns": tool_end_ns,
            "time_source": source,
            "confidence": confidence,
        }

    def _add_app_phases(
        self,
        events: List[TimelineEvent],
        invocation: InvocationObservation,
        fields: Dict[str, Any],
        common_args: Dict[str, Any],
        target_id: str,
    ) -> None:
        times = self._app_times(fields)
        request_start_us = _ns_to_us(times.get("request_start_ns"))
        request_end_us = _ns_to_us(times.get("request_end_ns"))
        tool_start_us = _ns_to_us(times.get("tool_start_ns"))
        tool_end_us = _ns_to_us(times.get("tool_end_ns"))
        if not request_start_us and not tool_start_us:
            return

        pid = f"app:{target_id or invocation.target_id or 'unknown'}"
        app_args = dict(common_args)
        app_args.update(
            {
                "time_source": times.get("time_source") or "derived_from_duration",
                "confidence": times.get("confidence") or "estimated",
            }
        )
        self._instant(
            events,
            name=f"enter_instance:{invocation.node_id}",
            cat="app",
            pid=pid,
            tid="app",
            ts_us=request_start_us,
            args=app_args,
        )
        self._span(
            events,
            name=f"app_request:{invocation.node_id}",
            cat="app",
            pid=pid,
            tid="app",
            start_us=request_start_us,
            end_us=request_end_us,
            args=app_args,
        )
        self._span(
            events,
            name=f"tool_exec:{invocation.node_id}:{invocation.tool_name}",
            cat="app",
            pid=pid,
            tid="tool",
            start_us=tool_start_us,
            end_us=tool_end_us,
            args=app_args,
        )
        if request_start_us and tool_start_us >= request_start_us:
            self._span(
                events,
                name=f"pre_tool:{invocation.node_id}",
                cat="app",
                pid=pid,
                tid="overhead",
                start_us=request_start_us,
                end_us=tool_start_us,
                args=app_args,
            )
        if tool_end_us and request_end_us >= tool_end_us:
            self._span(
                events,
                name=f"post_tool:{invocation.node_id}",
                cat="app",
                pid=pid,
                tid="overhead",
                start_us=tool_end_us,
                end_us=request_end_us,
                args=app_args,
            )
        state_sync_us = _ms_to_us(fields.get("state_sync_overhead_ms"))
        if state_sync_us and tool_end_us >= state_sync_us:
            self._span(
                events,
                name=f"state_sync:{invocation.node_id}",
                cat="app",
                pid=pid,
                tid="overhead",
                start_us=tool_end_us - state_sync_us,
                dur_us=state_sync_us,
                args={**app_args, "confidence": "estimated"},
            )
        framework_us = _ms_to_us(fields.get("framework_overhead_ms"))
        if framework_us and request_start_us:
            self._instant(
                events,
                name=f"framework_overhead:{invocation.node_id}",
                cat="app",
                pid=pid,
                tid="overhead",
                ts_us=request_start_us,
                args={**app_args, "duration_us": framework_us},
            )

    def _add_diagnostics(
        self,
        events: List[TimelineEvent],
        context: RunContext,
        diagnostics: Iterable[Dict[str, Any]],
    ) -> None:
        ts_us = _sec_to_us(context.end_time or context.start_time)
        for diagnostic in diagnostics:
            kind = str(diagnostic.get("kind") or "diagnostic")
            args = self._base_args(context, **diagnostic)
            self._instant(
                events,
                name=f"diagnostic:{kind}",
                cat="diagnostic",
                pid="client",
                tid="diagnostic",
                ts_us=ts_us,
                args=args,
            )

    def _metadata_events(self, events: List[TimelineEvent]) -> List[Dict[str, Any]]:
        pids = sorted({event.pid for event in events}, key=self._process_sort_key)
        tids = sorted({(event.pid, event.tid) for event in events})
        metadata: List[Dict[str, Any]] = []
        for sort_index, pid in enumerate(pids):
            metadata.append(
                {
                    "name": "process_name",
                    "ph": "M",
                    "pid": pid,
                    "tid": 0,
                    "args": {"name": pid},
                }
            )
            metadata.append(
                {
                    "name": "process_sort_index",
                    "ph": "M",
                    "pid": pid,
                    "tid": 0,
                    "args": {"sort_index": sort_index},
                }
            )
        for pid, tid in tids:
            metadata.append(
                {
                    "name": "thread_name",
                    "ph": "M",
                    "pid": pid,
                    "tid": tid,
                    "args": {"name": tid},
                }
            )
            metadata.append(
                {
                    "name": "thread_sort_index",
                    "ph": "M",
                    "pid": pid,
                    "tid": tid,
                    "args": {"sort_index": self._thread_sort_index(tid)},
                }
            )
        return metadata

    @staticmethod
    def _process_sort_key(pid: str) -> Tuple[int, str]:
        if pid == "client":
            return (0, pid)
        if pid.startswith("provider:"):
            return (1, pid)
        if pid.startswith("app:"):
            return (2, pid)
        return (9, pid)

    @staticmethod
    def _thread_sort_index(tid: str) -> int:
        if tid == "run":
            return 0
        if tid.startswith("llm/"):
            return 100 + _int(tid.split("/", 1)[1])
        if tid.startswith("tool_use/"):
            return 200 + _int(tid.split("/", 1)[1])
        if tid == "provider":
            return 0
        if tid == "session":
            return 50
        if tid == "app":
            return 0
        if tid == "tool":
            return 100
        if tid == "overhead":
            return 200
        if tid == "diagnostic":
            return 900
        return 500


class PerfettoTraceExporter:
    def __init__(self, base_dir: str | Path = "results"):
        self.base_dir = Path(base_dir)

    def export(
        self,
        trace: Dict[str, Any],
        *,
        provider: str,
        benchmark: str,
        timestamp: Optional[str] = None,
    ) -> str:
        ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.base_dir / provider / benchmark
        output_dir.mkdir(parents=True, exist_ok=True)
        trace_path = output_dir / f"{ts}.trace.json"
        trace_path.write_text(
            json.dumps(trace, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return str(trace_path)
