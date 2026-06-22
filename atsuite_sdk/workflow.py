from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class Edge:
    target_id: int
    params: Dict[str, Any] = field(default_factory=dict)
    interval_ms: float = 0.0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Edge":
        return cls(
            target_id=int(payload.get("id", 0)),
            params=payload.get("params") or {},
            interval_ms=float(payload.get("interval", 0.0)),
        )


@dataclass(frozen=True)
class Node:
    node_id: int
    name: str
    node_type: str
    edge_to: List[Edge] = field(default_factory=list)
    time_ms: float = 0.0
    output: Any = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Node":
        edges = [Edge.from_dict(edge) for edge in payload.get("edge_to", [])]
        return cls(
            node_id=int(payload.get("id", 0)),
            name=str(payload.get("name", "")),
            node_type=str(payload.get("type", "")),
            edge_to=edges,
            time_ms=float(payload.get("time", 0.0)),
            output=payload.get("output"),
        )


@dataclass(frozen=True)
class Trace:
    name: str
    description: str
    deploy_config: str
    nodes: List[Node]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Trace":
        return cls(
            name=str(payload.get("name", "")),
            description=str(payload.get("discription", "")),
            deploy_config=str(payload.get("deploy_config", "")),
            nodes=[Node.from_dict(node) for node in payload.get("nodes", [])],
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "Trace":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def node_type_stats(self) -> Dict[str, Dict[str, float | int]]:
        totals: Dict[str, Dict[str, float | int]] = {}
        for node in self.nodes:
            entry = totals.setdefault(node.node_type, {"count": 0, "time_ms": 0.0})
            entry["count"] += 1
            entry["time_ms"] += float(node.time_ms)
        return totals


def load_trace_from_file(path: str | Path) -> Trace:
    return Trace.from_file(path)
