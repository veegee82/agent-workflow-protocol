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

    max_level = _walk_run(
        run_dir,
        root_id,
        base_level=1,
        x_offset=0,
        nodes=nodes,
        edges=edges,
        stats=stats,
        prefix="",
    )

    # Completion node
    completion = _read_json(run_dir / "run_completion.json")
    if completion:
        comp_status = completion.get("status", "?")
        total_iters = completion.get("total_iterations", "?")
        final_budget = completion.get("final_budget", {})
        color = _COLORS["green"] if comp_status == "complete" else _COLORS["red"]

        nodes.append(
            GraphNode(
                id="completion",
                type="completion",
                position={"x": 0, "y": (max_level + 1) * _Y_SPACING},
                data={
                    "label": f"Result: {comp_status}",
                    "nodeType": "completion",
                    "status": comp_status,
                    "totalIterations": total_iters,
                    "finalBudget": final_budget,
                },
            )
        )
        edges.append(
            GraphEdge(
                id=f"edge_{root_id}_completion",
                source=root_id,
                target="completion",
                type="default",
                animated=False,
                style={"stroke": color, "strokeWidth": 2},
            )
        )

    # Update root and manager statuses based on completion
    if completion:
        final_status = completion.get("status", "complete")
        for n in nodes:
            if n.id == root_id:
                n.data["status"] = final_status
            elif n.type == "manager" and n.data.get("status") == "running":
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
) -> int:
    """Recursively walk a run directory and build nodes/edges."""
    manifest = _read_json(run_path / "run_manifest.json")
    models = manifest.get("models", {}) if manifest else {}

    # Manager node
    mgr_id = _uid(f"{prefix}mgr")
    mgr_model = models.get("manager", "?")
    nodes.append(
        GraphNode(
            id=mgr_id,
            type="manager",
            position={"x": x_offset, "y": base_level * _Y_SPACING},
            data={
                "label": f"Manager ({mgr_model[:25]})",
                "model": mgr_model,
                "depth": prefix.count("sub_"),
                "nodeType": "manager",
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
    iterations_dir = run_path / "iterations"
    if not iterations_dir.exists():
        return max_level

    iter_dirs = sorted(
        [d for d in iterations_dir.iterdir() if d.is_dir()], key=lambda d: d.name
    )

    for iter_idx, iter_dir in enumerate(iter_dirs):
        iter_num = iter_dir.name
        stats["total_iterations"] += 1
        iter_level = base_level + 1

        decision_data = _read_json(iter_dir / "manager_decision.json")
        if not decision_data:
            continue

        decision_type = decision_data.get("decision", "unknown")
        confidence = decision_data.get("confidence")
        reasoning = decision_data.get("reasoning", "")
        budget_snap = _read_json(iter_dir / "budget_snapshot.json") or {}

        dec_color = {
            "delegate": _COLORS["yellow"],
            "complete": _COLORS["green"],
            "fail": _COLORS["red"],
        }.get(decision_type, _COLORS["grey"])

        dec_id = _uid(f"{prefix}iter_{iter_num}")

        nodes.append(
            GraphNode(
                id=dec_id,
                type="iteration",
                position={
                    "x": x_offset + iter_idx * _X_SPACING,
                    "y": iter_level * _Y_SPACING,
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
        max_level = max(max_level, iter_level)

        # Workers
        delegations_dir = iter_dir / "delegations"
        if not delegations_dir.exists():
            continue

        worker_dirs = sorted(
            [d for d in delegations_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
        )

        for w_idx, worker_dir in enumerate(worker_dirs):
            worker_id_str = worker_dir.name
            stats["total_workers"] += 1
            worker_level = iter_level + 1

            envelope = _read_json(worker_dir / "envelope.json") or {}
            result = _read_json(worker_dir / "result.json") or {}
            instructions = envelope.get("instructions", "")
            tools_allowed = envelope.get("tools_allowed", [])
            w_confidence = result.get("confidence")
            has_error = bool(result.get("error"))

            # Tool calls
            tc_data = _read_json(worker_dir / "tool_calls.json")
            tc_list = tc_data if isinstance(tc_data, list) else result.get("_tool_calls", [])
            n_tc = len(tc_list)
            stats["total_tool_calls"] += n_tc

            color = _COLORS["red"] if has_error else _confidence_color(w_confidence)

            w_node_id = _uid(f"{prefix}w_{worker_id_str}")
            conf_label = f"{w_confidence}" if w_confidence is not None else "?"

            nodes.append(
                GraphNode(
                    id=w_node_id,
                    type="worker",
                    position={
                        "x": x_offset + iter_idx * _X_SPACING + w_idx * (_X_SPACING // 2),
                        "y": worker_level * _Y_SPACING,
                    },
                    data={
                        "label": worker_id_str,
                        "nodeType": "worker",
                        "worker_id": worker_id_str,
                        "confidence": w_confidence,
                        "confidenceLabel": conf_label,
                        "hasError": has_error,
                        "error": str(result.get("error", "")) if has_error else None,
                        "toolCallCount": n_tc,
                        "toolsAllowed": tools_allowed[:10],
                        "instructions": _truncate(instructions, 300),
                        "status": "error" if has_error else "complete",
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
            max_level = max(max_level, worker_level)

            # Tool call nodes
            tc_level = worker_level + 1
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

                nodes.append(
                    GraphNode(
                        id=tc_node_id,
                        type="toolCall",
                        position={
                            "x": x_offset
                            + iter_idx * _X_SPACING
                            + w_idx * (_X_SPACING // 2)
                            + tc_idx * 100,
                            "y": tc_level * _Y_SPACING,
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
                max_level = max(max_level, tc_level)

            # Sub-runs (A4 recursive delegation)
            sub_run_dir = worker_dir / "runs"
            if sub_run_dir.exists():
                for sub_dir in sorted(sub_run_dir.iterdir()):
                    if sub_dir.is_dir() and (sub_dir / "run_manifest.json").exists():
                        max_level = max(
                            max_level,
                            _walk_run(
                                sub_dir,
                                w_node_id,
                                max_level + 1,
                                x_offset + iter_idx * _X_SPACING,
                                nodes,
                                edges,
                                stats,
                                f"{prefix}sub_{worker_id_str}_",
                            ),
                        )

            if (
                (worker_dir / "iterations").exists()
                and (worker_dir / "run_manifest.json").exists()
            ):
                max_level = max(
                    max_level,
                    _walk_run(
                        worker_dir,
                        w_node_id,
                        max_level + 1,
                        x_offset + iter_idx * _X_SPACING,
                        nodes,
                        edges,
                        stats,
                        f"{prefix}sub_{worker_id_str}_",
                    ),
                )

    return max_level


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
    """Locate the latest delegation loop run directory under a workspace."""
    runs_dir = workspace_dir / "workspace" / "runs"
    if not runs_dir.exists():
        return None
    candidates = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()], key=lambda d: d.name
    )
    return candidates[-1] if candidates else None
