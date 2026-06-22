from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from atsuite.analysis.model import (
    SCHEMA_VERSION,
    InvocationObservation,
    NodeObservation,
    RunContext,
    SessionObservation,
    StateObservation,
)


class RunRecorder:
    """Thread-safe provider-neutral observation store for one replay run."""

    def __init__(
        self,
        *,
        provider: str,
        observability_provider: str,
        benchmark: str,
        trace: str,
        family: str,
        config_path: str,
        targets: Optional[Dict[str, Dict[str, Any]]] = None,
        endpoint_map: Optional[Dict[str, Any]] = None,
    ):
        self._lock = threading.RLock()
        self.context = RunContext(
            uid="",
            provider=provider,
            observability_provider=observability_provider,
            benchmark=benchmark,
            trace=trace,
            family=family,
            config_path=config_path,
            targets=dict(targets or {}),
            endpoint_map=dict(endpoint_map or {}),
        )
        self.nodes: Dict[int, NodeObservation] = {}
        self.invocations: List[InvocationObservation] = []
        self.sessions: List[SessionObservation] = []
        self.state: List[StateObservation] = []

    def start_run(self, uid: str, start_time: Optional[float] = None) -> None:
        with self._lock:
            self.context.uid = uid
            self.context.start_time = float(start_time if start_time is not None else time.time())
            self.context.end_time = 0.0
            self.nodes = {}
            self.invocations = []
            self.sessions = []
            self.state = []

    def finish_run(self, end_time: Optional[float] = None) -> None:
        with self._lock:
            self.context.end_time = float(end_time if end_time is not None else time.time())

    def start_node(
        self,
        *,
        node_id: int,
        node_name: str,
        node_type: str,
        runtime_name: str = "",
        target_id: str = "",
        family: str = "",
        runtime_config: Optional[Dict[str, Any]] = None,
        start_time: Optional[float] = None,
    ) -> None:
        with self._lock:
            existing = self.nodes.get(node_id)
            obs = existing or NodeObservation(
                node_id=node_id,
                node_name=node_name,
                node_type=node_type,
            )
            obs.node_name = node_name
            obs.node_type = node_type
            obs.runtime_name = runtime_name
            obs.target_id = target_id
            obs.family = family
            obs.runtime_config = dict(runtime_config or {})
            obs.start_time = float(start_time if start_time is not None else time.time())
            obs.end_time = 0.0
            obs.elapsed_ms = 0.0
            self.nodes[node_id] = obs

    def finish_node(self, node_id: int, end_time: Optional[float] = None) -> None:
        with self._lock:
            obs = self.nodes.get(node_id)
            if obs is None:
                return
            obs.end_time = float(end_time if end_time is not None else time.time())
            obs.elapsed_ms = max(0.0, (obs.end_time - obs.start_time) * 1000.0)

    def record_session_open(
        self,
        *,
        target_id: str,
        runtime_name: str,
        provider_session_id: str = "",
        initialize_request_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        opened_at: Optional[float] = None,
    ) -> None:
        with self._lock:
            self.sessions.append(
                SessionObservation(
                    uid=self.context.uid,
                    target_id=target_id,
                    runtime_name=runtime_name,
                    provider_session_id=provider_session_id,
                    initialize_request_id=initialize_request_id,
                    metadata=dict(metadata or {}),
                    opened_at=float(opened_at if opened_at is not None else time.time()),
                )
            )

    def record_invocation(
        self,
        *,
        node_id: int,
        node_name: str,
        target_id: str,
        runtime_name: str,
        family: str,
        tool_name: str,
        call_id: str,
        status: str,
        provider_request_id: str = "",
        provider_session_id: str = "",
        client_start_time: float = 0.0,
        client_elapsed_ms: float = 0.0,
        error: str = "",
        provider_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self.invocations.append(
                InvocationObservation(
                    node_id=node_id,
                    node_name=node_name,
                    target_id=target_id,
                    runtime_name=runtime_name,
                    family=family,
                    tool_name=tool_name,
                    call_id=call_id,
                    uid=self.context.uid,
                    status=status,
                    error=error,
                    provider_request_id=provider_request_id,
                    provider_session_id=provider_session_id,
                    client_start_time=float(client_start_time or 0.0),
                    client_elapsed_ms=float(client_elapsed_ms or 0.0),
                    provider_metadata=dict(provider_metadata or {}),
                )
            )

    def record_state(
        self,
        *,
        provider: str,
        operation: str,
        services: Iterable[str] = (),
        size_gb: float = 0.0,
        operation_count: int = 0,
        started_at: float = 0.0,
        ended_at: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self.state.append(
                StateObservation(
                    uid=self.context.uid,
                    provider=provider,
                    operation=operation,
                    services=sorted(str(s) for s in services if str(s)),
                    size_gb=float(size_gb or 0.0),
                    operation_count=int(operation_count or 0),
                    started_at=float(started_at or 0.0),
                    ended_at=float(ended_at if ended_at is not None else time.time()),
                    metadata=dict(metadata or {}),
                )
            )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "context": self.context.to_dict(),
                "nodes": [node.to_dict() for node in sorted(self.nodes.values(), key=lambda n: n.node_id)],
                "invocations": [inv.to_dict() for inv in self.invocations],
                "sessions": [session.to_dict() for session in self.sessions],
                "state": [state.to_dict() for state in self.state],
            }

    def save_events(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.snapshot(), indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return str(path)

    @classmethod
    def from_events(cls, path: str | Path) -> "RunRecorder":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        context = RunContext.from_dict(dict(payload.get("context") or {}))
        recorder = cls(
            provider=context.provider,
            observability_provider=context.observability_provider,
            benchmark=context.benchmark,
            trace=context.trace,
            family=context.family,
            config_path=context.config_path,
            targets=context.targets,
            endpoint_map=context.endpoint_map,
        )
        recorder.context = context
        recorder.nodes = {
            node.node_id: node
            for node in (NodeObservation.from_dict(dict(raw)) for raw in payload.get("nodes") or [])
        }
        recorder.invocations = [
            InvocationObservation.from_dict(dict(raw)) for raw in payload.get("invocations") or []
        ]
        recorder.sessions = [
            SessionObservation.from_dict(dict(raw)) for raw in payload.get("sessions") or []
        ]
        recorder.state = [
            StateObservation.from_dict(dict(raw)) for raw in payload.get("state") or []
        ]
        return recorder


RunObserver = RunRecorder
