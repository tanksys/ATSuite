from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = 2


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@dataclass
class RunContext:
    uid: str
    provider: str
    observability_provider: str
    benchmark: str
    trace: str
    family: str
    config_path: str
    start_time: float = 0.0
    end_time: float = 0.0
    targets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    endpoint_map: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RunContext":
        return cls(
            uid=str(payload.get("uid", "")),
            provider=str(payload.get("provider", "")),
            observability_provider=str(payload.get("observability_provider", "")),
            benchmark=str(payload.get("benchmark", "")),
            trace=str(payload.get("trace", "")),
            family=str(payload.get("family", "")),
            config_path=str(payload.get("config_path", "")),
            start_time=float(payload.get("start_time", 0.0) or 0.0),
            end_time=float(payload.get("end_time", 0.0) or 0.0),
            targets=dict(payload.get("targets") or {}),
            endpoint_map=dict(payload.get("endpoint_map") or {}),
        )


@dataclass
class NodeObservation:
    node_id: int
    node_name: str
    node_type: str
    runtime_name: str = ""
    target_id: str = ""
    family: str = ""
    runtime_config: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    elapsed_ms: float = 0.0
    diagnostics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "NodeObservation":
        return cls(
            node_id=int(payload.get("node_id", 0)),
            node_name=str(payload.get("node_name", "")),
            node_type=str(payload.get("node_type", "")),
            runtime_name=str(payload.get("runtime_name", "")),
            target_id=str(payload.get("target_id", "")),
            family=str(payload.get("family", "")),
            runtime_config=dict(payload.get("runtime_config") or {}),
            start_time=float(payload.get("start_time", 0.0) or 0.0),
            end_time=float(payload.get("end_time", 0.0) or 0.0),
            elapsed_ms=float(payload.get("elapsed_ms", 0.0) or 0.0),
            diagnostics=[str(v) for v in payload.get("diagnostics") or []],
        )


@dataclass
class InvocationObservation:
    node_id: int
    node_name: str
    target_id: str
    runtime_name: str
    family: str
    tool_name: str
    call_id: str
    uid: str
    status: str = "ok"
    error: str = ""
    provider_request_id: str = ""
    provider_session_id: str = ""
    client_start_time: float = 0.0
    client_elapsed_ms: float = 0.0
    provider_metadata: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "InvocationObservation":
        return cls(
            node_id=int(payload.get("node_id", 0)),
            node_name=str(payload.get("node_name", "")),
            target_id=str(payload.get("target_id", "")),
            runtime_name=str(payload.get("runtime_name", "")),
            family=str(payload.get("family", "")),
            tool_name=str(payload.get("tool_name", "")),
            call_id=str(payload.get("call_id", "")),
            uid=str(payload.get("uid", "")),
            status=str(payload.get("status", "ok")),
            error=str(payload.get("error", "")),
            provider_request_id=str(payload.get("provider_request_id", "")),
            provider_session_id=str(payload.get("provider_session_id", "")),
            client_start_time=float(payload.get("client_start_time", 0.0) or 0.0),
            client_elapsed_ms=float(payload.get("client_elapsed_ms", 0.0) or 0.0),
            provider_metadata=dict(payload.get("provider_metadata") or {}),
            evidence_refs=[str(v) for v in payload.get("evidence_refs") or []],
        )


@dataclass
class SessionObservation:
    uid: str
    target_id: str
    runtime_name: str
    provider_session_id: str = ""
    initialize_request_id: str = ""
    opened_at: float = 0.0
    closed_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SessionObservation":
        return cls(
            uid=str(payload.get("uid", "")),
            target_id=str(payload.get("target_id", "")),
            runtime_name=str(payload.get("runtime_name", "")),
            provider_session_id=str(payload.get("provider_session_id", "")),
            initialize_request_id=str(payload.get("initialize_request_id", "")),
            opened_at=float(payload.get("opened_at", 0.0) or 0.0),
            closed_at=float(payload.get("closed_at", 0.0) or 0.0),
            metadata=dict(payload.get("metadata") or {}),
            evidence_refs=[str(v) for v in payload.get("evidence_refs") or []],
        )


@dataclass
class StateObservation:
    uid: str
    provider: str
    operation: str
    services: List[str] = field(default_factory=list)
    size_gb: float = 0.0
    operation_count: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "StateObservation":
        return cls(
            uid=str(payload.get("uid", "")),
            provider=str(payload.get("provider", "")),
            operation=str(payload.get("operation", "")),
            services=[str(v) for v in payload.get("services") or []],
            size_gb=float(payload.get("size_gb", 0.0) or 0.0),
            operation_count=int(payload.get("operation_count", 0) or 0),
            started_at=float(payload.get("started_at", 0.0) or 0.0),
            ended_at=float(payload.get("ended_at", 0.0) or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class ProviderMetric:
    metric_id: str
    provider: str
    source: str
    node_id: Optional[int] = None
    invocation_call_id: str = ""
    provider_request_id: str = ""
    fields: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProviderMetric":
        node_id = payload.get("node_id")
        return cls(
            metric_id=str(payload.get("metric_id", "")),
            provider=str(payload.get("provider", "")),
            source=str(payload.get("source", "")),
            node_id=int(node_id) if node_id is not None else None,
            invocation_call_id=str(payload.get("invocation_call_id", "")),
            provider_request_id=str(payload.get("provider_request_id", "")),
            fields=dict(payload.get("fields") or {}),
            evidence_refs=[str(v) for v in payload.get("evidence_refs") or []],
        )


@dataclass
class CostLineItem:
    category: str
    provider: str
    amount: float
    currency: str
    resource_id: str = ""
    node_id: Optional[int] = None
    invocation_call_id: str = ""
    formula: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)


@dataclass
class EvidenceRecord:
    evidence_id: str
    provider: str
    source: str
    query: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EvidenceRecord":
        return cls(
            evidence_id=str(payload.get("evidence_id", "")),
            provider=str(payload.get("provider", "")),
            source=str(payload.get("source", "")),
            query=dict(payload.get("query") or {}),
            raw=payload.get("raw"),
        )


@dataclass
class CollectionResult:
    metrics: List[ProviderMetric] = field(default_factory=list)
    evidence: List[EvidenceRecord] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalysisReport:
    schema_version: int
    run: Dict[str, Any]
    summary: Dict[str, Any]
    nodes: Dict[str, Dict[str, Any]]
    invocations: List[Dict[str, Any]]
    costs: List[Dict[str, Any]]
    diagnostics: List[Dict[str, Any]]
    evidence_path: str = ""
    report_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self)
