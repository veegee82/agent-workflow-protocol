"""Build React Flow graph data from an AWP delegation loop run directory.

Walks the run directory structure and translates it into the React Flow
node/edge schema expected by the frontend.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from server.models import GraphData, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

_X_SPACING = 280
_Y_SPACING = 160

# Distinct hue per recursion depth so the eye can quickly tell levels apart
_DEPTH_PALETTE = [
    {"border": "#7C3AED", "bg": "rgba(124, 58, 237, 0.06)", "label": "#A78BFA"},  # depth 1: violet
    {"border": "#EC4899", "bg": "rgba(236, 72, 153, 0.06)", "label": "#F472B6"},  # depth 2: pink
    {"border": "#06B6D4", "bg": "rgba(6, 182, 212, 0.06)", "label": "#22D3EE"},   # depth 3: cyan
    {"border": "#F59E0B", "bg": "rgba(245, 158, 11, 0.06)", "label": "#FBBF24"},  # depth 4: amber
]


# Colors
_COLORS = {
    "green": "#00E676",
    "yellow": "#FFD600",
    "orange": "#FF9100",
    "red": "#FF1744",
    "grey": "#78909C",
    "blue": "#40C4FF",
    "purple": "#E040FB",
    "cyan": "#18FFFF",
}


def _confidence_color(confidence: float | None) -> str:
    if confidence is None:
        return _COLORS["grey"]
    if confidence >= 0.8:
        return _COLORS["green"]
    if confidence >= 0.5:
        return _COLORS["yellow"]
    if confidence >= 0.3:
        return _COLORS["orange"]
    return _COLORS["red"]


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _llm_trace_summary(worker_dir: Path) -> dict[str, Any]:
    """Read llm_trace/summary.json and return enrichment fields for a worker node."""
    summary = _read_json(worker_dir / "llm_trace" / "summary.json")
    if not summary:
        return {}
    total_tokens_obj = summary.get("total_tokens", {})
    return {
        "llmCallCount": summary.get("total_calls"),
        "llmTotalTokens": (
            total_tokens_obj.get("total")
            if isinstance(total_tokens_obj, dict)
            else None
        ),
        "llmLatencyMs": summary.get("total_latency_ms"),
        "llmModel": summary.get("model"),
    }


def _truncate(text: Any, max_len: int = 200) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

_counter_lock = threading.Lock()
_counter = 0


def _uid(prefix: str) -> str:
    global _counter
    with _counter_lock:
        _counter += 1
        return f"{prefix}_{_counter}"


def build_graph(run_dir: Path) -> GraphData:
    """Build a React Flow compatible graph from a run directory.

    Parameters
    ----------
    run_dir : Path
        The delegation loop run directory (contains ``run_manifest.json``).

    Returns
    -------
    GraphData
        Nodes and edges suitable for React Flow rendering.
    """
    global _counter
    _counter = 0

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    stats: dict[str, Any] = {
        "total_workers": 0,
        "total_tool_calls": 0,
        "total_iterations": 0,
        "tools_ok": 0,
        "tools_failed": 0,
    }

    manifest = _read_json(run_dir / "run_manifest.json") or {}
    task = manifest.get("task", "Unknown task")
    run_id = manifest.get("run_id", "?")
    budget = manifest.get("budget", {})
    models = manifest.get("models", {})

    # Root task node
    root_id = "task_root"
    nodes.append(
        GraphNode(
            id=root_id,
            type="task",
            position={"x": 0, "y": 0},
            data={
                "label": _truncate(task, 50),
                "nodeType": "task",
                "task": task,
                "run_id": run_id,
                "models": models,
                "budget": budget,
                "status": "running",
            },
        )
    )

    max_level, _ = _walk_run(
        run_dir,
        root_id,
        base_level=1,
        x_offset=0,
        nodes=nodes,
        edges=edges,
        stats=stats,
        prefix="",
    )

    # Update root and manager statuses based on completion
    completion = _read_json(run_dir / "run_completion.json")
    if completion:
        final_status = completion.get("status", "complete")
        for n in nodes:
            if n.id == root_id:
                n.data["status"] = final_status
            elif n.type in ("manager", "submanager") and n.data.get("status") == "running":
                n.data["status"] = final_status

    return GraphData(nodes=nodes, edges=edges, stats=stats)


def _walk_run(
    run_path: Path,
    parent_id: str,
    base_level: int,
    x_offset: int,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    stats: dict[str, Any],
    prefix: str,
    depth: int = 0,
) -> tuple[int, int]:
    """Recursively walk a run directory and build nodes/edges.

    Returns (max_level, max_x_used) so callers can stack sub-runs
    horizontally.
    """
    x_sp = _X_SPACING
    y_sp = _Y_SPACING

    manifest = _read_json(run_path / "run_manifest.json")
    models = manifest.get("models", {}) if manifest else {}

    # Manager node — depth 0 is the root manager, depth > 0 are sub-managers
    mgr_id = _uid(f"{prefix}mgr")
    mgr_model = models.get("manager", "?")
    mgr_depth = prefix.count("sub_")
    is_root_mgr = depth == 0
    mgr_type = "manager" if is_root_mgr else "submanager"
    mgr_label = (
        f"Manager ({mgr_model[:25]})"
        if is_root_mgr
        else f"Sub-Manager d{mgr_depth} ({mgr_model[:20]})"
    )
    nodes.append(
        GraphNode(
            id=mgr_id,
            type=mgr_type,
            position={"x": x_offset, "y": base_level * y_sp},
            data={
                "label": mgr_label,
                "model": mgr_model,
                "depth": mgr_depth,
                "nodeType": mgr_type,
                "status": "running",
            },
        )
    )
    edges.append(
        GraphEdge(
            id=f"edge_{parent_id}_{mgr_id}",
            source=parent_id,
            target=mgr_id,
            type="default",
            animated=True,
            style={"stroke": _COLORS["purple"], "strokeWidth": 2},
        )
    )

    max_level = base_level
    # max_x tracks the rightmost pixel used by this run's column.
    # Initialize to at least the full column width so sub-runs never
    # overlap with this column's workers.
    max_x = x_offset
    iterations_dir = run_path / "iterations"
    if not iterations_dir.exists():
        return max_level, max_x

    iter_dirs = sorted(
        [d for d in iterations_dir.iterdir() if d.is_dir()], key=lambda d: d.name
    )

    # Pre-scan: find the max number of workers in any iteration and the
    # max tool calls per worker so we can compute the column width.
    _max_workers_in_iter = 0
    _max_tcs_per_worker = 0
    for _id in iter_dirs:
        _dd = _id / "delegations"
        if _dd.exists():
            _worker_dirs = [_w for _w in _dd.iterdir() if _w.is_dir()]
            _max_workers_in_iter = max(_max_workers_in_iter, len(_worker_dirs))
            for _wd in _worker_dirs:
                _tc = _read_json(_wd / "tool_calls.json")
                _tcl = _tc if isinstance(_tc, list) else (_read_json(_wd / "result.json") or {}).get("_tool_calls", [])
                _max_tcs_per_worker = max(_max_tcs_per_worker, len(_tcl))
    # Column width: enough for iteration + workers + tool call spread.
    _NODE_W = 180  # worker node width
    _GAP = 120     # gap between columns (enough to prevent cross-column overlap)
    _TC_NODE_W = 140  # tool call node spacing
    _worker_spread = (_max_workers_in_iter + 1) * (_NODE_W + _GAP)
    _tc_spread = _max_tcs_per_worker * _TC_NODE_W if _max_tcs_per_worker > 1 else 0
    _col_width = max(x_sp, _worker_spread, _tc_spread + _NODE_W)
    # Reserve the full column width so sub-runs don't overlap
    max_x = x_offset + _col_width

    # Track the next available vertical row for iterations.
    # Each iteration gets its own row below the manager.
    next_iter_level = base_level + 1

    for iter_idx, iter_dir in enumerate(iter_dirs):
        iter_raw = iter_dir.name  # zero-padded directory name, e.g. "001"
        # Display number: strip leading zeros for clean labels ("001" → "1")
        iter_num = str(int(iter_raw)) if iter_raw.isdigit() else iter_raw
        stats["total_iterations"] += 1
        iter_level = next_iter_level

        decision_data = _read_json(iter_dir / "manager_decision.json")
        if not decision_data:
            continue

        decision_type = decision_data.get("decision", "unknown")
        confidence = decision_data.get("confidence")
        reasoning = decision_data.get("reasoning", "")
        budget_snap = _read_json(iter_dir / "budget_snapshot.json") or {}
        iter_critique = _read_json(iter_dir / "critique.json")

        dec_color = {
            "delegate": _COLORS["yellow"],
            "complete": _COLORS["green"],
            "fail": _COLORS["red"],
        }.get(decision_type, _COLORS["grey"])

        dec_id = _uid(f"{prefix}iter_{iter_raw}")

        # Iteration node: directly below manager, vertically stacked
        nodes.append(
            GraphNode(
                id=dec_id,
                type="iteration",
                position={
                    "x": x_offset,
                    "y": iter_level * y_sp,
                },
                data={
                    "label": f"Iter {iter_num}: {decision_type.upper()}",
                    "nodeType": "iteration",
                    "iteration": iter_num,
                    "decision": decision_type,
                    "confidence": confidence,
                    "reasoning": _truncate(reasoning, 300),
                    "budget": budget_snap,
                    "status": decision_type,
                    **({"critique_active": True,
                        "critique_repairs": sum(
                            len(c.get("prescriptions", []))
                            for c in (iter_critique or {}).get("critiques", [])
                        ),
                        "critique_patterns": len(
                            (iter_critique or {}).get("summary", {}).get("patterns", {})
                        )}
                       if iter_critique else {}),
                },
            )
        )
        edges.append(
            GraphEdge(
                id=f"edge_{mgr_id}_{dec_id}",
                source=mgr_id,
                target=dec_id,
                type="default",
                style={"stroke": dec_color, "strokeWidth": 1.5},
                data={"label": f"iter {iter_num}"},
            )
        )

        # Workers
        delegations_dir = iter_dir / "delegations"
        if not delegations_dir.exists():
            next_iter_level = iter_level + 1
            max_level = max(max_level, iter_level)
            continue

        # Collect eval scores from workers to propagate to iteration node
        _iter_eval_scores: list[float] = []
        _tc_before = stats["total_tool_calls"]
        _w_cursor = _NODE_W + _GAP  # start after the iteration node
        _pending_sub_runs: list[tuple] = []  # (sub_dir, parent_node_id, worker_id_str)

        worker_dirs = sorted(
            [d for d in delegations_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )

        for w_idx, worker_dir in enumerate(worker_dirs):
            worker_id_str = worker_dir.name
            stats["total_workers"] += 1
            worker_level = iter_level  # same row as iteration

            envelope = _read_json(worker_dir / "envelope.json") or {}
            result = _read_json(worker_dir / "result.json") or {}
            critique_data = _read_json(worker_dir / "critique.json")
            instructions = envelope.get("instructions", "")
            tools_allowed = envelope.get("tools_allowed", [])
            w_confidence = result.get("confidence")
            has_error = bool(result.get("error"))
            # A4: detect submanager workers (set by DelegationLoopRunner._spawn_submanager)
            is_submanager = bool(
                result.get("_submanager")
                or envelope.get("as_submanager")
            )
            sub_depth = result.get("_submanager_depth")
            sub_run_id = result.get("_submanager_run_id")
            if "_eval_score" in result:
                _iter_eval_scores.append(result["_eval_score"])

            # Tool calls
            tc_data = _read_json(worker_dir / "tool_calls.json")
            tc_list = tc_data if isinstance(tc_data, list) else result.get("_tool_calls", [])
            n_tc = len(tc_list)
            stats["total_tool_calls"] += n_tc

            color = _COLORS["red"] if has_error else _confidence_color(w_confidence)

            w_node_id = _uid(f"{prefix}w_{worker_id_str}")
            conf_label = f"{w_confidence}" if w_confidence is not None else "?"

            # Workers sit to the right of the iteration node on the same row.
            # Spacing accounts for tool calls that fan out below each worker.
            w_x = x_offset + _w_cursor
            _w_slot = max(_NODE_W + _GAP, n_tc * _TC_NODE_W) if n_tc > 0 else _NODE_W + _GAP
            _w_cursor += _w_slot
            max_x = max(max_x, w_x + _w_slot)
            nodes.append(
                GraphNode(
                    id=w_node_id,
                    type="submanager" if is_submanager else "worker",
                    position={
                        "x": w_x,
                        "y": worker_level * y_sp,
                    },
                    data={
                        "label": (
                            f"⤷ {worker_id_str} (submanager d{sub_depth})"
                            if is_submanager else worker_id_str
                        ),
                        "nodeType": "submanager" if is_submanager else "worker",
                        "isSubmanager": is_submanager,
                        "submanagerDepth": sub_depth,
                        "submanagerRunId": sub_run_id,
                        "worker_id": worker_id_str,
                        "iteration": iter_raw,
                        "confidence": w_confidence,
                        "confidenceLabel": conf_label,
                        "hasError": has_error,
                        "error": str(result.get("error", "")) if has_error else None,
                        "toolCallCount": n_tc,
                        "toolsAllowed": tools_allowed[:10],
                        "instructions": _truncate(instructions, 300),
                        "status": "error" if has_error else "complete",
                        **(_llm_trace_summary(worker_dir)),
                        **({"eval_score": result["_eval_score"],
                            "eval_action": result.get("_eval_action", ""),
                            "eval_metrics": result.get("_eval_metrics", [])}
                           if "_eval_score" in result else {}),
                        **({"critique_score": critique_data.get("score"),
                            "critique_summary": critique_data.get("summary", ""),
                            "critique_defects": critique_data.get("defects", []),
                            "critique_prescriptions": critique_data.get("prescriptions", []),
                            "critique_repairs": result.get("_critique_repairs", []),
                            "critique_effort": critique_data.get("effort_estimate", "")}
                           if critique_data else {}),
                    },
                )
            )
            edges.append(
                GraphEdge(
                    id=f"edge_{dec_id}_{w_node_id}",
                    source=dec_id,
                    target=w_node_id,
                    type="default",
                    style={"stroke": color, "strokeWidth": 1.5},
                )
            )

            # Tool call nodes — one row below the worker
            tc_level = iter_level + 1
            for tc_idx, tc in enumerate(tc_list):
                if not isinstance(tc, dict):
                    continue
                tool_name = tc.get("tool", "?")
                tc_result = tc.get("result", {})
                tc_ok = tc_result.get("ok", False)
                tc_color = _COLORS["green"] if tc_ok else _COLORS["red"]

                if tc_ok:
                    stats["tools_ok"] += 1
                else:
                    stats["tools_failed"] += 1

                tc_node_id = _uid(f"{prefix}tc_{tc_idx}")
                stdout = ""
                stderr = ""
                if isinstance(tc_result, dict):
                    data_inner = tc_result.get("data", {})
                    if isinstance(data_inner, dict):
                        stdout = _truncate(data_inner.get("stdout", ""), 400)
                        stderr = _truncate(data_inner.get("stderr", ""), 200)

                _TC_W = 140  # tool call node spacing
                tc_x = w_x + tc_idx * _TC_W
                max_x = max(max_x, tc_x + _TC_W)
                nodes.append(
                    GraphNode(
                        id=tc_node_id,
                        type="toolCall",
                        position={
                            "x": tc_x,
                            "y": tc_level * y_sp,
                        },
                        data={
                            "label": tool_name,
                            "nodeType": "toolCall",
                            "tool": tool_name,
                            "ok": tc_ok,
                            "stdout": stdout,
                            "stderr": stderr,
                            "error": str(tc_result.get("error", ""))
                            if tc_result.get("error")
                            else None,
                            "status": "complete" if tc_ok else "error",
                        },
                    )
                )
                edges.append(
                    GraphEdge(
                        id=f"edge_{w_node_id}_{tc_node_id}",
                        source=w_node_id,
                        target=tc_node_id,
                        type="default",
                        animated=False,
                        style={
                            "stroke": tc_color,
                            "strokeWidth": 1,
                            "strokeDasharray": "5,5",
                        },
                    )
                )

            # Collect sub-runs to process AFTER all workers in this
            # iteration are placed (so tool calls don't overlap with
            # sub-run columns).
            sub_run_dir = worker_dir / "runs"
            if sub_run_dir.exists():
                for sub_dir in sorted(sub_run_dir.iterdir()):
                    if sub_dir.is_dir() and (sub_dir / "run_manifest.json").exists():
                        _pending_sub_runs.append((sub_dir, w_node_id, worker_id_str))
            if (
                (worker_dir / "iterations").exists()
                and (worker_dir / "run_manifest.json").exists()
            ):
                _pending_sub_runs.append((worker_dir, w_node_id, worker_id_str))

        # Process sub-runs AFTER all workers are placed (prevents TC overlap)
        for _sub_dir, _sub_parent, _sub_wid in _pending_sub_runs:
            sub_x = max_x + _GAP
            inner_max, inner_max_x = _walk_run(
                _sub_dir,
                _sub_parent,
                base_level=base_level,
                x_offset=sub_x,
                nodes=nodes,
                edges=edges,
                stats=stats,
                prefix=f"{prefix}sub_{_sub_wid}_",
                depth=depth + 1,
            )
            max_level = max(max_level, inner_max)
            max_x = max(max_x, inner_max_x)

        # Advance the vertical cursor: 1 row for iteration+workers,
        # +1 row if any tool calls were rendered below.
        _any_tc = stats["total_tool_calls"] > _tc_before if worker_dirs else False
        next_iter_level = iter_level + (2 if _any_tc else 1)
        max_level = max(max_level, next_iter_level - 1)

        # Propagate avg eval score to iteration node
        if _iter_eval_scores:
            avg_eval = sum(_iter_eval_scores) / len(_iter_eval_scores)
            for n in nodes:
                if n.id == dec_id:
                    n.data["eval_score"] = round(avg_eval, 4)
                    n.data["eval_action"] = "accept" if avg_eval >= 0.75 else "warning" if avg_eval >= 0.5 else "fail"
                    break

    return max_level, max_x


def build_incremental_graph(
    run_dir: Path, known_node_ids: set[str] | None = None
) -> GraphData:
    """Build a graph and return only nodes/edges not in ``known_node_ids``.

    Useful for incremental updates to the frontend during a running workflow.
    """
    full = build_graph(run_dir)
    if not known_node_ids:
        return full

    new_nodes = [n for n in full.nodes if n.id not in known_node_ids]
    # Include edges where at least one endpoint is new
    new_node_ids = {n.id for n in new_nodes}
    new_edges = [
        e
        for e in full.edges
        if e.source in new_node_ids or e.target in new_node_ids
    ]

    return GraphData(nodes=new_nodes, edges=new_edges, stats=full.stats)


def find_run_dir(workspace_dir: Path) -> Path | None:
    """Locate the root delegation loop run directory under a workspace.

    The ``workspace/runs/`` directory may contain both root-level run
    directories and sub-manager run directories (all stored flat with
    timestamp-based names).  Sub-manager runs also appear nested inside
    the root run's ``iterations/*/delegations/*/runs/`` hierarchy, so
    any directory whose ID also appears *inside* another candidate's
    iteration tree is a sub-run — not the root.

    Strategy: collect all run IDs, then exclude those that appear as
    nested sub-runs of another candidate.  From the remaining roots,
    return the latest (by name).  Falls back to the latest overall if
    the filtering yields nothing.
    """
    runs_dir = workspace_dir / "workspace" / "runs"
    if not runs_dir.exists():
        return None
    candidates = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()], key=lambda d: d.name
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Build a set of sub-run IDs by scanning each candidate for nested
    # run directories.  A sub-run has its manifest under
    # <root>/iterations/*/delegations/*/runs/<sub_id>/run_manifest.json.
    all_names = {d.name for d in candidates}
    sub_run_names: set[str] = set()
    for cand in candidates:
        for nested_manifest in cand.rglob("runs/*/run_manifest.json"):
            nested_name = nested_manifest.parent.name
            if nested_name in all_names:
                sub_run_names.add(nested_name)

    roots = [d for d in candidates if d.name not in sub_run_names]
    return roots[-1] if roots else candidates[-1]
