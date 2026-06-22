from __future__ import annotations

import json
from collections import Counter, deque
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Dict, Iterable


TOOL_NODE_TYPES = {"tool", "tool_use"}
LLM_DISPLAY_SCALE_DIVISOR = 5.0


def _is_tool_node(node: Dict[str, Any]) -> bool:
    return str(node.get("type", "")).strip().lower() in TOOL_NODE_TYPES


def _display_duration_ms(node: Dict[str, Any]) -> float:
    duration = float(node.get("time", 0.0) or 0.0)
    if str(node.get("type", "")).strip().lower() == "llm":
        return duration / LLM_DISPLAY_SCALE_DIVISOR
    return duration


def _safe_resolve(base_path: Path, relative_path: str, repo_root: Path) -> Path | None:
    candidate = (base_path / relative_path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return candidate


def _tool_names_in_trace(trace_payload: Dict[str, Any]) -> set[str]:
    return {
        str(node.get("name", "")).strip()
        for node in trace_payload.get("nodes", [])
        if _is_tool_node(node) and str(node.get("name", "")).strip()
    }


def _build_node_by_id(trace_payload: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {
        int(node["id"]): node
        for node in trace_payload.get("nodes", [])
    }


def _build_incoming_by_id(trace_payload: Dict[str, Any]) -> Dict[int, list[dict[str, Any]]]:
    incoming_by_id: Dict[int, list[dict[str, Any]]] = {}
    for node in trace_payload.get("nodes", []):
        incoming_by_id.setdefault(int(node["id"]), [])
    for node in trace_payload.get("nodes", []):
        source_id = int(node["id"])
        for edge in node.get("edge_to", []):
            target_id = int(edge.get("id", -1))
            incoming_by_id.setdefault(target_id, []).append(
                {
                    "from": source_id,
                    "edge": edge,
                }
            )
    return incoming_by_id


def _sort_node_ids_by_schedule(
    node_ids: Iterable[int],
    start_time_by_id: Dict[str, float],
) -> list[int]:
    return sorted(
        node_ids,
        key=lambda node_id: (float(start_time_by_id.get(str(node_id), 0.0)), int(node_id)),
    )


def _choose_display_anchor_id(
    incoming_edges: list[dict[str, Any]],
    node_by_id: Dict[int, Dict[str, Any]],
    start_time_by_id: Dict[str, float],
) -> int | None:
    non_tool_incoming = [
        item
        for item in incoming_edges
        if not _is_tool_node(node_by_id.get(int(item["from"]), {}))
    ]
    if not non_tool_incoming:
        return None

    non_tool_incoming.sort(
        key=lambda item: (
            -float(start_time_by_id.get(str(int(item["from"])), 0.0)),
            -int(item["from"]),
        )
    )
    return int(non_tool_incoming[0]["from"])


def _collect_config_trace_metadata(
    config_payload: Dict[str, Any],
) -> tuple[set[str], int, int]:
    trace_names: set[str] = set()
    explicit_stateful_entries = 0
    explicit_stateful_true = 0

    for node in config_payload.get("nodes", []):
        if not isinstance(node, dict):
            continue
        raw_trace_names = node.get("trace_names", [])
        if not isinstance(raw_trace_names, list):
            continue
        for item in raw_trace_names:
            if isinstance(item, str):
                trace_name = item.strip()
                if trace_name:
                    trace_names.add(trace_name)
                continue
            if not isinstance(item, dict):
                continue
            trace_name = str(item.get("name", "")).strip()
            if not trace_name:
                continue
            trace_names.add(trace_name)
            if "stateful" in item:
                explicit_stateful_entries += 1
                if bool(item.get("stateful", False)):
                    explicit_stateful_true += 1

    return trace_names, explicit_stateful_entries, explicit_stateful_true


def _config_matches_trace_file(
    *,
    config_path: Path,
    config_payload: Dict[str, Any],
    trace_path: Path,
    repo_root: Path,
) -> int:
    trace_file = str(config_payload.get("trace_file", "") or "").strip()
    if not trace_file:
        return 0

    resolved_trace_file = _safe_resolve(config_path.parent, trace_file, repo_root)
    if resolved_trace_file is None or not resolved_trace_file.exists():
        return 0
    if resolved_trace_file == trace_path.resolve():
        return 2

    try:
        resolved_payload = json.loads(resolved_trace_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    source_trace_path = str(resolved_payload.get("source_trace_path", "") or "").strip()
    if source_trace_path and Path(source_trace_path).resolve() == trace_path.resolve():
        return 1

    return 0


def _infer_config_path_from_trace_location(
    trace_payload: Dict[str, Any],
    trace_path: Path,
    *,
    repo_root: Path,
) -> Path | None:
    if trace_path.parent.name != "trace":
        return None

    benchmark_root = trace_path.parent.parent
    config_dir = benchmark_root / "config"
    if not config_dir.exists():
        return None

    trace_tool_names = _tool_names_in_trace(trace_payload)
    if not trace_tool_names:
        return None

    candidates: list[tuple[tuple[int, int, int, int, int], str, Path]] = []

    for config_path in sorted(config_dir.glob("*.json")):
        try:
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        config_trace_names, explicit_stateful_entries, explicit_stateful_true = (
            _collect_config_trace_metadata(config_payload)
        )
        matched = len(trace_tool_names & config_trace_names)
        if matched == 0:
            continue

        unmatched = len(trace_tool_names - config_trace_names)
        trace_file_match = _config_matches_trace_file(
            config_path=config_path,
            config_payload=config_payload,
            trace_path=trace_path,
            repo_root=repo_root,
        )

        score = (
            trace_file_match,
            matched,
            -unmatched,
            explicit_stateful_entries,
            explicit_stateful_true,
        )
        candidates.append((score, str(config_path), config_path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], -item[0][3], -item[0][4], item[1]))
    return candidates[0][2]


def resolve_stateful_tool_names(
    trace_payload: Dict[str, Any],
    trace_path: Path,
    *,
    repo_root: Path,
) -> set[str]:
    deploy_config = str(trace_payload.get("deploy_config", "") or "").strip()
    config_path = None
    if deploy_config:
        config_path = _safe_resolve(trace_path.parent, deploy_config, repo_root)
    if config_path is None:
        config_path = _infer_config_path_from_trace_location(
            trace_payload,
            trace_path,
            repo_root=repo_root,
        )
    if config_path is None or not config_path.exists():
        return set()

    try:
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()

    stateful_names: set[str] = set()
    for node in config_payload.get("nodes", []):
        if not isinstance(node, dict):
            continue
        trace_names = node.get("trace_names", [])
        if not isinstance(trace_names, list):
            continue
        for item in trace_names:
            if not isinstance(item, dict):
                continue
            if not item.get("stateful", False):
                continue
            trace_name = str(item.get("name", "")).strip()
            if trace_name:
                stateful_names.add(trace_name)

    return stateful_names


def _build_display_edges(
    trace_payload: Dict[str, Any],
    tool_mode_by_id: Dict[str, str],
    start_time_by_id: Dict[str, float],
) -> list[tuple[int, int]]:
    node_by_id = _build_node_by_id(trace_payload)
    incoming_by_id = _build_incoming_by_id(trace_payload)
    root_tool_ids: list[int] = []

    for node_id, node in node_by_id.items():
        if not _is_tool_node(node):
            continue
        incoming_edges = incoming_by_id.get(node_id, [])
        has_tool_predecessor = any(
            _is_tool_node(node_by_id.get(int(item["from"]), {})) for item in incoming_edges
        )
        if not has_tool_predecessor:
            root_tool_ids.append(node_id)

    grouped_roots: Dict[str, Dict[str, Any]] = {}
    for node_id in root_tool_ids:
        incoming_edges = incoming_by_id.get(node_id, [])
        anchor_id = _choose_display_anchor_id(incoming_edges, node_by_id, start_time_by_id)
        group_key = f"none:{node_id}" if anchor_id is None else str(anchor_id)
        group = grouped_roots.setdefault(
            group_key,
            {
                "anchor_id": anchor_id,
                "stateful": [],
                "stateless": [],
                "root_tool_ids": set(),
                "downstream_non_tool_target_ids": set(),
            },
        )
        group["root_tool_ids"].add(node_id)
        node = node_by_id.get(node_id, {})
        for edge in node.get("edge_to", []):
            target_id = int(edge.get("id", -1))
            target_node = node_by_id.get(target_id)
            if target_node is not None and not _is_tool_node(target_node):
                group["downstream_non_tool_target_ids"].add(target_id)
        mode = tool_mode_by_id.get(str(node_id), "stateless")
        if mode == "stateful":
            group["stateful"].append(node_id)
        else:
            group["stateless"].append(node_id)

    root_tool_id_set = set(root_tool_ids)
    suppressed_raw_edges: set[tuple[int, int]] = set()
    display_edges: list[tuple[int, int]] = []
    for group in grouped_roots.values():
        for root_tool_id in group["root_tool_ids"]:
            for target_id in group["downstream_non_tool_target_ids"]:
                suppressed_raw_edges.add((int(root_tool_id), int(target_id)))
    for node in trace_payload.get("nodes", []):
        source_id = int(node["id"])
        for edge in node.get("edge_to", []):
            target_id = int(edge.get("id", -1))
            if (source_id, target_id) in suppressed_raw_edges:
                continue
            target_node = node_by_id.get(target_id)
            if target_node is not None and _is_tool_node(target_node) and target_id in root_tool_id_set:
                continue
            display_edges.append((source_id, target_id))

    for group in grouped_roots.values():
        stateful_ids = _sort_node_ids_by_schedule(group["stateful"], start_time_by_id)
        stateless_ids = _sort_node_ids_by_schedule(group["stateless"], start_time_by_id)
        anchor_id = group["anchor_id"]
        downstream_non_tool_target_ids = sorted(group["downstream_non_tool_target_ids"])
        terminal_tool_ids = (
            stateless_ids
            if stateless_ids
            else ([stateful_ids[-1]] if stateful_ids else [])
        )
        if stateful_ids:
            if anchor_id is not None:
                display_edges.append((anchor_id, stateful_ids[0]))
            for prev_id, next_id in zip(stateful_ids, stateful_ids[1:]):
                display_edges.append((prev_id, next_id))
            fanout_source = stateful_ids[-1]
            for node_id in stateless_ids:
                display_edges.append((fanout_source, node_id))
        elif anchor_id is not None:
            for node_id in stateless_ids:
                display_edges.append((anchor_id, node_id))

        for tool_id in terminal_tool_ids:
            for target_id in downstream_non_tool_target_ids:
                display_edges.append((tool_id, target_id))

    return display_edges


def compute_tool_graph_metrics(
    trace_payload: Dict[str, Any],
    tool_mode_by_id: Dict[str, str],
    start_time_by_id: Dict[str, float],
) -> Dict[str, Any]:
    nodes = trace_payload.get("nodes", [])
    node_types = {int(node["id"]): node.get("type", "") for node in nodes}
    node_ids = {int(node["id"]) for node in nodes}
    adjacency = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}

    for source_id, target_id in _build_display_edges(trace_payload, tool_mode_by_id, start_time_by_id):
        if source_id not in adjacency or target_id not in indegree:
            continue
        adjacency[source_id].append(target_id)
        indegree[target_id] += 1

    roots = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    queue: deque[int] = deque(roots)
    tool_levels: Dict[int, int] = {}

    for root in roots:
        tool_levels[root] = 1 if str(node_types[root]).strip().lower() in TOOL_NODE_TYPES else 0

    while queue:
        node_id = queue.popleft()
        current_tool_level = tool_levels.get(node_id, 0)
        for neighbor in adjacency.get(node_id, []):
            next_tool_level = current_tool_level + (
                1 if str(node_types.get(neighbor, "")).strip().lower() in TOOL_NODE_TYPES else 0
            )
            tool_levels[neighbor] = max(tool_levels.get(neighbor, 0), next_tool_level)
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    level_by_id = {
        str(node_id): level
        for node_id, level in tool_levels.items()
        if str(node_types.get(node_id, "")).strip().lower() in TOOL_NODE_TYPES
    }
    level_counts = Counter(level_by_id.values())

    return {
        "depth": max(level_counts, default=0),
        "width": max(level_counts.values(), default=0),
        "level_by_id": level_by_id,
    }


def _build_node_maps(
    trace_payload: Dict[str, Any],
) -> tuple[Dict[int, Dict[str, Any]], Dict[int, int], set[int]]:
    nodes = trace_payload.get("nodes", [])
    node_by_id = {int(node["id"]): node for node in nodes}
    in_degree = {node_id: 0 for node_id in node_by_id}

    for node in nodes:
        for edge in node.get("edge_to", []):
            target_id = int(edge.get("id", -1))
            if target_id in in_degree:
                in_degree[target_id] += 1

    reachable_nodes = set(node_by_id)
    return node_by_id, in_degree, reachable_nodes


def compute_scheduled_start_times(
    trace_payload: Dict[str, Any],
    stateful_tool_names: Iterable[str],
) -> Dict[str, float]:
    stateful_tool_names = set(stateful_tool_names)
    node_by_id, in_degree, reachable_nodes = _build_node_maps(trace_payload)
    ready_nodes: set[int] = {
        node_id for node_id, degree in in_degree.items() if degree == 0
    }
    start_time_by_id: Dict[int, float] = {}
    pending: list[tuple[float, int, int]] = []
    submitted: set[int] = set()
    current_time = 0.0
    active_stateful_node: int | None = None
    submission_order = 0

    def is_stateful_tool_node(node_id: int) -> bool:
        node = node_by_id[node_id]
        return _is_tool_node(node) and str(node.get("name", "")) in stateful_tool_names

    def submit_node(node_id: int) -> None:
        nonlocal submission_order
        if node_id in submitted or node_id not in reachable_nodes:
            return
        submitted.add(node_id)
        start_time_by_id[node_id] = current_time
        end_time = current_time + _display_duration_ms(node_by_id[node_id])
        heappush(pending, (end_time, submission_order, node_id))
        submission_order += 1

    def schedule_ready_nodes() -> None:
        nonlocal active_stateful_node

        non_tool_ready = sorted(
            node_id for node_id in ready_nodes if not _is_tool_node(node_by_id[node_id])
        )
        for node_id in non_tool_ready:
            ready_nodes.remove(node_id)
            submit_node(node_id)

        if active_stateful_node is None:
            stateful_ready = sorted(
                node_id for node_id in ready_nodes if is_stateful_tool_node(node_id)
            )
            if stateful_ready:
                chosen = stateful_ready[0]
                ready_nodes.remove(chosen)
                active_stateful_node = chosen
                submit_node(chosen)
                return

        if active_stateful_node is None:
            for node_id in sorted(ready_nodes):
                ready_nodes.remove(node_id)
                submit_node(node_id)

    schedule_ready_nodes()

    while pending or ready_nodes:
        if not pending:
            schedule_ready_nodes()
            if not pending:
                break

        next_end_time, _, node_id = heappop(pending)
        current_time = next_end_time
        completed = [node_id]
        while pending and pending[0][0] == current_time:
            completed.append(heappop(pending)[2])

        for completed_node_id in completed:
            if completed_node_id == active_stateful_node:
                active_stateful_node = None
            current_node = node_by_id[completed_node_id]
            for edge in current_node.get("edge_to", []):
                target_id = int(edge.get("id", -1))
                if target_id not in reachable_nodes:
                    continue
                in_degree[target_id] -= 1
                if in_degree[target_id] == 0:
                    ready_nodes.add(target_id)

        schedule_ready_nodes()

    return {str(node_id): start for node_id, start in start_time_by_id.items()}


def build_enriched_trace_payload(
    trace_path: Path,
    *,
    repo_root: Path,
) -> Dict[str, Any]:
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    stateful_tool_names = resolve_stateful_tool_names(
        payload,
        trace_path,
        repo_root=repo_root,
    )
    tool_mode_by_id = {
        str(node["id"]): ("stateful" if node.get("name") in stateful_tool_names else "stateless")
        for node in payload.get("nodes", [])
        if _is_tool_node(node)
    }
    start_time_by_id = compute_scheduled_start_times(payload, stateful_tool_names)
    payload["viewer_metadata"] = {
        "stateful_tool_names": sorted(stateful_tool_names),
        "tool_mode_by_id": tool_mode_by_id,
        "start_time_ms_by_id": start_time_by_id,
        "tool_graph": compute_tool_graph_metrics(payload, tool_mode_by_id, start_time_by_id),
    }
    return payload
