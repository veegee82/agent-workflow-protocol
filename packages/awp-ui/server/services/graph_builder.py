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

# Sub-run cluster geometry
_CLUSTER_PAD_X = 60
_CLUSTER_PAD_Y = 30
_CLUSTER_HEADER_H = 70

# Distinct hue per recursion depth so the eye can quickly tell levels apart
_DEPTH_PALETTE = [
    {"border": "#7C3AED", "bg": "rgba(124, 58, 237, 0.06)", "label": "#A78BFA"},  # depth 1: violet
    {"border": "#EC4899", "bg": "rgba(236, 72, 153, 0.06)", "label": "#F472B6"},  # depth 2: pink
    {"border": "#06B6D4", "bg": "rgba(6, 182, 212, 0.06)", "label": "#22D3EE"},   # depth 3: cyan
    {"border": "#F59E0B", "bg": "rgba(245, 158, 11, 0.06)", "label": "#FBBF24"},  # depth 4: amber
]


def _palette_for_depth(depth: int) -> dict[str, str]:
    """Return a colour theme for a recursion depth (cycles for very deep trees)."""
    if depth <= 0:
        depth = 1
    return _DEPTH_PALETTE[(depth - 1) % len(_DEPTH_PALETTE)]

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


def _walk_subrun_clustered(
    sub_dir: Path,
    triggering_worker_node_id: str,
    triggering_worker_data: dict[str, Any],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    stats: dict[str, Any],
    prefix: str,
    depth: int,
) -> int:
    """Walk a sub-run and wrap all of its nodes inside a ``subRunCluster``.

    The cluster acts as a visual container (rendered as a coloured outlined
    box in the frontend). Children inside the cluster are repositioned to
    be parent-relative as required by React Flow's subflow API.

    Returns the depth level (in the parent's coordinate space) reached by
    the sub-run, which is one — the cluster collapses the entire sub-run
    into a single visual unit so the parent layout doesn't have to grow.
    """
    # 1. Snapshot list lengths so we can identify which nodes/edges this
    #    walk is responsible for
    nodes_before = len(nodes)
    edges_before = len(edges)

    # 2. Create the cluster placeholder. We will set its position + style
    #    after the inner walk has finished and we know its bounding box.
    cluster_id = _uid(f"{prefix}cluster")
    sub_manifest = _read_json(sub_dir / "run_manifest.json") or {}
    sub_run_id = sub_manifest.get("run_id", sub_dir.name)
    sub_models = sub_manifest.get("models", {})
    sub_budget = sub_manifest.get("budget", {})
    palette = _palette_for_depth(depth)

    cluster_node = GraphNode(
        id=cluster_id,
        type="subRunCluster",
        position={"x": 0, "y": 0},  # placeholder, set below
        data={
            "label": (
                f"⤷ Submanager: {triggering_worker_data.get('worker_id', '?')}"
                f"  ·  depth {depth}"
            ),
            "nodeType": "subRunCluster",
            "depth": depth,
            "sub_run_id": sub_run_id,
            "triggering_worker": triggering_worker_data.get("worker_id"),
            "triggering_node_id": triggering_worker_node_id,
            "manager_model": sub_models.get("manager"),
            "worker_model": sub_models.get("worker"),
            "budget": sub_budget,
            "palette": palette,
        },
        style={
            "background": palette["bg"],
            "border": f"2px dashed {palette['border']}",
            "borderRadius": "12px",
            "padding": "0px",
        },
        zIndex=-(10 + depth),  # negative so children render above the box
    )
    nodes.append(cluster_node)

    # 3. Walk the sub-run normally. The triggering worker is the visual
    #    parent so the connecting edge points into the cluster, but the
    #    walk uses an internal coordinate system starting at (0, 0).
    inner_max_level = _walk_run(
        sub_dir,
        triggering_worker_node_id,
        base_level=0,
        x_offset=0,
        nodes=nodes,
        edges=edges,
        stats=stats,
        prefix=f"{prefix}sub_{triggering_worker_data.get('worker_id', '?')}_",
        depth=depth,
    )

    # 4. Identify the nodes added by THIS walk (excluding the cluster itself)
    new_nodes = nodes[nodes_before + 1 :]
    if not new_nodes:
        # Empty sub-run — drop the cluster entirely so the layout stays clean
        nodes.pop(nodes_before)
        return 0

    # 5. Find the direct children (nodes that were not assigned to a deeper
    #    cluster by a recursive call). These are what we re-parent.
    direct_children = [n for n in new_nodes if n.parentNode is None]
    nested_clusters = [
        n for n in new_nodes
        if n.parentNode is None and n.type == "subRunCluster"
    ]

    # Statistics so the frontend can show meaningful collapse summaries and a
    # navigator tree without re-walking the graph.
    descendant_count = len(new_nodes)
    worker_count = sum(
        1 for n in new_nodes if n.type in ("worker", "submanager")
    )
    iteration_count = sum(1 for n in new_nodes if n.type == "iteration")
    nested_cluster_count = len(nested_clusters)
    cluster_node.data["descendant_count"] = descendant_count
    cluster_node.data["worker_count"] = worker_count
    cluster_node.data["iteration_count"] = iteration_count
    cluster_node.data["nested_cluster_count"] = nested_cluster_count
    # Deep clusters start collapsed so the initial view stays compact;
    # the user can expand them on demand from the header or the navigator.
    cluster_node.data["auto_collapse"] = depth >= 2

    # 6. Compute bounding box of direct children in their absolute coords
    if direct_children:
        # Each direct child has an (x, y); we also need to know how big
        # they are so the cluster doesn't clip them. Use generous defaults.
        NODE_W = 220
        NODE_H = 130
        min_x = min(n.position["x"] for n in direct_children)
        min_y = min(n.position["y"] for n in direct_children)
        max_x = max(n.position["x"] for n in direct_children) + NODE_W
        max_y = max(n.position["y"] for n in direct_children) + NODE_H

        cluster_w = (max_x - min_x) + 2 * _CLUSTER_PAD_X
        cluster_h = (max_y - min_y) + _CLUSTER_HEADER_H + 2 * _CLUSTER_PAD_Y
    else:
        min_x = min_y = 0
        cluster_w, cluster_h = 400, 200

    # 7. Re-parent direct children to the cluster and re-position relative
    #    to its origin (cluster's top-left corner sits at (0, 0) in its own
    #    coordinate system; children get _CLUSTER_PAD_X and _CLUSTER_HEADER_H
    #    offsets so they don't overlap the header).
    for child in direct_children:
        child.parentNode = cluster_id
        child.extent = "parent"
        child.position = {
            "x": child.position["x"] - min_x + _CLUSTER_PAD_X,
            "y": child.position["y"] - min_y + _CLUSTER_HEADER_H,
        }

    # 8. Set cluster geometry
    cluster_node.style.update(
        {
            "width": cluster_w,
            "height": cluster_h,
        }
    )

    # 9. Position the cluster itself relative to the triggering worker
    #    (the parent's coordinate frame). Stack vertically below the worker.
    triggering_node = next(
        (n for n in nodes if n.id == triggering_worker_node_id), None
    )
    if triggering_node is not None:
        cluster_node.position = {
            "x": triggering_node.position["x"] - cluster_w / 2 + 50,
            "y": triggering_node.position["y"] + 180,
        }

    # 10. Mark every edge created INSIDE this cluster with a hint so the
    #     frontend can render them in the depth-palette colour
    for e in edges[edges_before:]:
        e.data = e.data or {}
        e.data["clusterDepth"] = depth
        e.data["clusterColor"] = palette["border"]

    # 11. Add a fat connection edge from the triggering worker into the
    #     cluster to make the parent→cluster relationship visually obvious
    edges.append(
        GraphEdge(
            id=f"edge_{triggering_worker_node_id}_to_{cluster_id}",
            source=triggering_worker_node_id,
            target=cluster_id,
            type="default",
            animated=True,
            style={
                "stroke": palette["border"],
                "strokeWidth": 3,
                "strokeDasharray": "8,4",
            },
            data={"clusterEdge": True, "depth": depth},
        )
    )

    return 1


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
        iter_critique = _read_json(iter_dir / "critique.json")

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
        max_level = max(max_level, iter_level)

        # Workers
        delegations_dir = iter_dir / "delegations"
        if not delegations_dir.exists():
            continue

        # Collect eval scores from workers to propagate to iteration node
        _iter_eval_scores: list[float] = []

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

            nodes.append(
                GraphNode(
                    id=w_node_id,
                    type="submanager" if is_submanager else "worker",
                    position={
                        "x": x_offset + iter_idx * _X_SPACING + w_idx * (_X_SPACING // 2),
                        "y": worker_level * _Y_SPACING,
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
                        "confidence": w_confidence,
                        "confidenceLabel": conf_label,
                        "hasError": has_error,
                        "error": str(result.get("error", "")) if has_error else None,
                        "toolCallCount": n_tc,
                        "toolsAllowed": tools_allowed[:10],
                        "instructions": _truncate(instructions, 300),
                        "status": "error" if has_error else "complete",
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

            # Sub-runs (A4 recursive delegation) — wrap each in a cluster
            triggering_data = {"worker_id": worker_id_str}
            sub_run_dir = worker_dir / "runs"
            if sub_run_dir.exists():
                for sub_dir in sorted(sub_run_dir.iterdir()):
                    if sub_dir.is_dir() and (sub_dir / "run_manifest.json").exists():
                        _walk_subrun_clustered(
                            sub_dir,
                            w_node_id,
                            triggering_data,
                            nodes,
                            edges,
                            stats,
                            prefix,
                            depth + 1,
                        )

            if (
                (worker_dir / "iterations").exists()
                and (worker_dir / "run_manifest.json").exists()
            ):
                _walk_subrun_clustered(
                    worker_dir,
                    w_node_id,
                    triggering_data,
                    nodes,
                    edges,
                    stats,
                    prefix,
                    depth + 1,
                )

        # Propagate avg eval score to iteration node
        if _iter_eval_scores:
            avg_eval = sum(_iter_eval_scores) / len(_iter_eval_scores)
            for n in nodes:
                if n.id == dec_id:
                    n.data["eval_score"] = round(avg_eval, 4)
                    n.data["eval_action"] = "accept" if avg_eval >= 0.75 else "warning" if avg_eval >= 0.5 else "fail"
                    break

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
