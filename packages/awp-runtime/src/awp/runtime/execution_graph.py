"""Post-run execution graph visualization.

Generates a self-contained interactive HTML graph using vis.js (no Python
dependencies beyond stdlib). Shows the full call hierarchy including managers,
workers, tool calls, sub-delegations (A4 recursive), confidence, and timing.

Works for both DAG (A0-A1) and Delegation Loop (A2+) engines.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colors & helpers
# ---------------------------------------------------------------------------

_COLORS = {
    "green": "#00E676",
    "yellow": "#FFD600",
    "orange": "#FF9100",
    "red": "#FF1744",
    "grey": "#78909C",
    "blue": "#40C4FF",
    "purple": "#E040FB",
    "cyan": "#18FFFF",
    "white": "#ECEFF1",
    "bg": "#0d1117",
    "panel": "#161b22",
    "border": "#30363d",
    "text": "#c9d1d9",
    "muted": "#8b949e",
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


def _truncate(text: str | list | Any, max_len: int = 200) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\n", " ").replace('"', '\\"').strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _read_json(path: Path) -> dict[str, Any] | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


def _js_str(s: str | Any) -> str:
    """Escape a string for safe embedding in JS."""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Data collection — build a flat list of nodes & edges
# ---------------------------------------------------------------------------


def _collect_delegation_data(run_dir: Path) -> dict[str, Any]:
    """Walk a delegation loop run directory and collect all graph data."""
    nodes: list[dict] = []
    edges: list[dict] = []
    stats = {
        "total_workers": 0,
        "total_tool_calls": 0,
        "total_iterations": 0,
        "tools_ok": 0,
        "tools_failed": 0,
    }
    _counter = [0]

    def _uid(prefix: str) -> str:
        _counter[0] += 1
        return f"{prefix}_{_counter[0]}"

    def _walk_run(run_path: Path, parent_id: str, base_level: int, prefix: str = "") -> int:
        manifest = _read_json(run_path / "run_manifest.json")
        models = manifest.get("models", {}) if manifest else {}

        mgr_id = _uid(f"{prefix}mgr")
        mgr_model = models.get("manager", "?")
        nodes.append({
            "id": mgr_id, "label": f"Manager\\n{mgr_model[:25]}",
            "shape": "star", "color": _COLORS["purple"], "size": 35,
            "level": base_level, "group": "manager",
            "title": f"<b>Manager</b><br>Model: {_js_str(mgr_model)}<br>Depth: {prefix.count('sub_')}",
        })
        edges.append({"from": parent_id, "to": mgr_id, "color": _COLORS["purple"], "width": 2})

        max_level = base_level
        iterations_dir = run_path / "iterations"
        if not iterations_dir.exists():
            return max_level

        iter_dirs = sorted([d for d in iterations_dir.iterdir() if d.is_dir()], key=lambda d: d.name)

        for iter_dir in iter_dirs:
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

            dec_color = {"delegate": _COLORS["yellow"], "complete": _COLORS["green"],
                         "fail": _COLORS["red"]}.get(decision_type, _COLORS["grey"])
            dec_id = _uid(f"{prefix}iter_{iter_num}")

            budget_pct = budget_snap.get("budget_remaining_pct", "?")
            nodes.append({
                "id": dec_id,
                "label": f"Iter {iter_num}\\n{decision_type.upper()}\\nconf: {confidence}",
                "shape": "box", "color": dec_color, "size": 24,
                "level": iter_level, "group": "decision",
                "title": (
                    f"<b>Iteration {iter_num}</b><br>"
                    f"Decision: {decision_type}<br>"
                    f"Confidence: {confidence}<br>"
                    f"Budget remaining: {budget_pct}%<br>"
                    f"Reasoning: {_js_str(_truncate(reasoning, 300))}"
                ),
            })
            edges.append({"from": mgr_id, "to": dec_id, "label": f"iter {iter_num}",
                          "color": "#555", "width": 1.5})
            max_level = max(max_level, iter_level)

            delegations_dir = iter_dir / "delegations"
            if not delegations_dir.exists():
                continue

            worker_dirs = sorted([d for d in delegations_dir.iterdir() if d.is_dir()], key=lambda d: d.name)

            for worker_dir in worker_dirs:
                worker_id = worker_dir.name
                stats["total_workers"] += 1
                worker_level = iter_level + 1

                envelope = _read_json(worker_dir / "envelope.json") or {}
                result = _read_json(worker_dir / "result.json") or {}
                instructions = envelope.get("instructions", "")
                tools_allowed = envelope.get("tools_allowed", [])
                w_confidence = result.get("confidence")
                has_error = bool(result.get("error"))
                conf_source = result.get("_confidence_source", "")

                # Tool calls
                tc_data = _read_json(worker_dir / "tool_calls.json")
                tc_list = tc_data if isinstance(tc_data, list) else result.get("_tool_calls", [])
                n_tc = len(tc_list)
                stats["total_tool_calls"] += n_tc

                # Generated artifacts
                n_gen_tools = len(list((worker_dir / "generated_tools").glob("*.py"))) if (worker_dir / "generated_tools").exists() else 0
                n_gen_skills = len(list((worker_dir / "generated_skills").glob("*.md"))) if (worker_dir / "generated_skills").exists() else 0

                color = _COLORS["red"] if has_error else _confidence_color(w_confidence)
                w_node_id = _uid(f"{prefix}w_{worker_id}")

                conf_label = f"{w_confidence}" if w_confidence is not None else "?"
                conf_note = f" ({conf_source})" if conf_source else ""

                output_keys = [k for k in result if k not in (
                    "_tool_calls", "tools_created", "tools_registered",
                    "skills_created", "confidence", "error", "_confidence_source",
                )]

                nodes.append({
                    "id": w_node_id,
                    "label": f"{worker_id}\\nconf: {conf_label}\\n{n_tc} calls",
                    "shape": "dot", "color": color, "size": max(18, 12 + n_tc * 2),
                    "level": worker_level, "group": "worker",
                    "title": (
                        f"<b>{worker_id}</b><br>"
                        f"Status: {'ERROR' if has_error else 'OK'}<br>"
                        f"Confidence: {conf_label}{conf_note}<br>"
                        f"Tools allowed: {', '.join(tools_allowed[:5]) or 'none'}<br>"
                        f"Tool calls: {n_tc}<br>"
                        f"Generated tools: {n_gen_tools}<br>"
                        f"Generated skills: {n_gen_skills}<br>"
                        f"Output fields: {', '.join(output_keys[:5])}<br>"
                        f"Instructions: {_js_str(_truncate(instructions, 300))}"
                        + (f"<br><span style='color:#FF1744'>Error: {_js_str(_truncate(str(result.get('error', '')), 200))}</span>" if has_error else "")
                    ),
                })
                edges.append({"from": dec_id, "to": w_node_id, "color": color, "width": 1.5})
                max_level = max(max_level, worker_level)

                # Tool call nodes
                tc_level = worker_level + 1
                for tc_idx, tc in enumerate(tc_list):
                    tool_name = tc.get("tool", "?")
                    tc_result = tc.get("result", {})
                    tc_ok = tc_result.get("ok", False)
                    tc_color = _COLORS["green"] if tc_ok else _COLORS["red"]
                    tc_node_id = _uid(f"{prefix}tc_{tc_idx}")

                    if tc_ok:
                        stats["tools_ok"] += 1
                    else:
                        stats["tools_failed"] += 1

                    stdout = tc_result.get("data", {}).get("stdout", "")
                    stderr = tc_result.get("data", {}).get("stderr", "")

                    nodes.append({
                        "id": tc_node_id,
                        "label": tool_name.split(".")[-1],
                        "shape": "triangle", "color": tc_color, "size": 10,
                        "level": tc_level, "group": "tool_call",
                        "title": (
                            f"<b>{tool_name}</b> {'OK' if tc_ok else 'FAILED'}<br>"
                            + (f"stdout: <pre>{_js_str(_truncate(stdout, 400))}</pre>" if stdout else "")
                            + (f"stderr: <pre>{_js_str(_truncate(stderr, 200))}</pre>" if stderr else "")
                            + (f"error: {_js_str(str(tc_result.get('error', '')))}" if tc_result.get("error") else "")
                        ),
                    })
                    edges.append({"from": w_node_id, "to": tc_node_id, "color": tc_color,
                                  "width": 1, "dashes": True})
                    max_level = max(max_level, tc_level)

                # Sub-runs (A4 recursive delegation)
                sub_run_dir = worker_dir / "runs"
                if sub_run_dir.exists():
                    for sub_dir in sorted(sub_run_dir.iterdir()):
                        if sub_dir.is_dir() and (sub_dir / "run_manifest.json").exists():
                            max_level = max(max_level,
                                _walk_run(sub_dir, w_node_id, max_level + 1, f"{prefix}sub_{worker_id}_"))

                if (worker_dir / "iterations").exists() and (worker_dir / "run_manifest.json").exists():
                    max_level = max(max_level,
                        _walk_run(worker_dir, w_node_id, max_level + 1, f"{prefix}sub_{worker_id}_"))

        return max_level

    # Root
    manifest = _read_json(run_dir / "run_manifest.json") or {}
    task = manifest.get("task", "Unknown task")
    run_id = manifest.get("run_id", "?")
    budget = manifest.get("budget", {})
    models = manifest.get("models", {})

    root_id = "task_root"
    nodes.append({
        "id": root_id, "label": f"Task\\n{_truncate(task, 35)}",
        "shape": "diamond", "color": _COLORS["blue"], "size": 45,
        "level": 0, "group": "task",
        "title": (
            f"<b>Task</b><br>{_js_str(_truncate(task, 500))}<br><br>"
            f"Run ID: {run_id}<br>"
            f"Manager: {models.get('manager', '?')}<br>"
            f"Worker: {models.get('worker', '?')}<br>"
            f"Max loops: {budget.get('max_loops', '?')}<br>"
            f"Max workers: {budget.get('max_total_workers', '?')}<br>"
            f"Max tokens: {budget.get('max_total_tokens', '?')}"
        ),
    })

    max_level = _walk_run(run_dir, root_id, base_level=1)

    # Completion
    completion = _read_json(run_dir / "run_completion.json")
    if completion:
        comp_status = completion.get("status", "?")
        total_iters = completion.get("total_iterations", "?")
        final_budget = completion.get("final_budget", {})
        comp_color = _COLORS["green"] if comp_status == "complete" else _COLORS["red"]

        nodes.append({
            "id": "completion",
            "label": f"Result\\n{comp_status}\\niters: {total_iters}",
            "shape": "box", "color": comp_color, "size": 30,
            "level": max_level + 1, "group": "completion",
            "title": (
                f"<b>Completion</b><br>"
                f"Status: {comp_status}<br>"
                f"Iterations: {total_iters}<br>"
                f"Budget remaining: {final_budget.get('budget_remaining_pct', '?')}%<br>"
                f"Workers spawned: {final_budget.get('workers', {}).get('spawned', '?')}<br>"
                f"Wall time: {final_budget.get('wall_time', {}).get('elapsed_s', '?')}s"
            ),
        })
        edges.append({"from": root_id, "to": "completion", "color": comp_color,
                      "width": 2, "dashes": True})

    return {"nodes": nodes, "edges": edges, "stats": stats, "task": task, "run_id": run_id}


# ---------------------------------------------------------------------------
# HTML renderer — uses string.Template ($var) to avoid JS brace conflicts
# ---------------------------------------------------------------------------

def _render_html(data: dict[str, Any]) -> str:
    """Render the execution graph data into a self-contained HTML string."""
    from string import Template

    c = _COLORS
    nodes_json = json.dumps(data["nodes"], ensure_ascii=False)
    edges_json = json.dumps(data["edges"], ensure_ascii=False)
    stats = data["stats"]
    task_display = _truncate(data.get("task", ""), 120)

    return Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AWP Execution Graph</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: $bg; color: $text; font-family: -apple-system, 'Segoe UI', Roboto, monospace; }

  #container { display: flex; height: 100vh; }
  #sidebar { width: 320px; background: $panel; border-right: 1px solid $border;
             overflow-y: auto; padding: 16px; flex-shrink: 0; }
  #graph { flex: 1; }

  h1 { font-size: 16px; color: $blue; margin-bottom: 12px; }
  h2 { font-size: 13px; color: $muted; text-transform: uppercase; letter-spacing: 1px;
       margin: 16px 0 8px; border-bottom: 1px solid $border; padding-bottom: 4px; }

  .stat { display: flex; justify-content: space-between; padding: 4px 0;
          font-size: 13px; border-bottom: 1px solid $border; }
  .stat-label { color: $muted; }
  .stat-value { font-weight: bold; }
  .stat-value.green { color: $green; }
  .stat-value.red { color: $red; }
  .stat-value.yellow { color: $yellow; }
  .stat-value.blue { color: $blue; }

  .legend { margin-top: 12px; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 12px; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-shape { width: 12px; height: 12px; flex-shrink: 0; }
  .legend-star { color: $purple; font-size: 16px; line-height: 12px; }
  .legend-triangle { width: 0; height: 0; border-left: 6px solid transparent;
                     border-right: 6px solid transparent; border-bottom: 10px solid $cyan; }

  #detail { margin-top: 16px; font-size: 12px; line-height: 1.5; }
  #detail h3 { font-size: 14px; color: $white; margin-bottom: 6px; }
  #detail-content { background: $bg; border: 1px solid $border; border-radius: 6px;
                    padding: 10px; max-height: 300px; overflow-y: auto; word-break: break-word; }
  #detail-content b { color: $blue; }
  #detail-content pre { background: #1c2128; padding: 6px; border-radius: 4px;
                        font-size: 11px; overflow-x: auto; margin: 4px 0; white-space: pre-wrap; }

  .controls { margin: 12px 0; display: flex; gap: 6px; flex-wrap: wrap; }
  .btn { background: $border; color: $text; border: none; padding: 5px 10px;
         border-radius: 4px; cursor: pointer; font-size: 11px; }
  .btn:hover { background: $muted; color: $bg; }
  .btn.active { background: $blue; color: $bg; }

  .task-text { font-size: 12px; color: $text; padding: 8px; background: $bg;
               border: 1px solid $border; border-radius: 6px; line-height: 1.4; }
</style>
</head>
<body>
<div id="container">
  <div id="sidebar">
    <h1>AWP Execution Graph</h1>
    <div class="task-text">$task_display</div>

    <h2>Stats</h2>
    <div class="stat"><span class="stat-label">Iterations</span><span class="stat-value blue">$stat_iterations</span></div>
    <div class="stat"><span class="stat-label">Workers</span><span class="stat-value blue">$stat_workers</span></div>
    <div class="stat"><span class="stat-label">Tool Calls</span><span class="stat-value blue">$stat_tool_calls</span></div>
    <div class="stat"><span class="stat-label">Tools OK</span><span class="stat-value green">$stat_tools_ok</span></div>
    <div class="stat"><span class="stat-label">Tools Failed</span><span class="stat-value red">$stat_tools_failed</span></div>
    <div class="stat"><span class="stat-label">Nodes</span><span class="stat-value">$stat_nodes</span></div>

    <h2>Controls</h2>
    <div class="controls">
      <button class="btn" onclick="fitGraph()">Fit All</button>
      <button class="btn" onclick="toggleTools()" id="btnTools">Show Tools</button>
      <button class="btn" onclick="togglePhysics()" id="btnPhysics">Physics</button>
      <button class="btn" onclick="expandAll()">Expand All</button>
      <button class="btn" onclick="collapseToWorkers()">Collapse</button>
    </div>

    <h2>Legend</h2>
    <div class="legend">
      <div class="legend-item"><div class="legend-shape" style="background:$blue;clip-path:polygon(50% 0%,100% 100%,0% 100%);width:14px;height:14px;"></div> Task</div>
      <div class="legend-item"><span class="legend-star">&#9733;</span> Manager</div>
      <div class="legend-item"><div class="legend-shape" style="background:$yellow;border-radius:2px;"></div> Iteration (delegate)</div>
      <div class="legend-item"><div class="legend-dot" style="background:$green;"></div> Worker (conf &ge; 0.8)</div>
      <div class="legend-item"><div class="legend-dot" style="background:$yellow;"></div> Worker (conf 0.5-0.8)</div>
      <div class="legend-item"><div class="legend-dot" style="background:$orange;"></div> Worker (conf 0.3-0.5)</div>
      <div class="legend-item"><div class="legend-dot" style="background:$red;"></div> Worker (conf &lt; 0.3 / error)</div>
      <div class="legend-item"><div class="legend-triangle"></div> Tool call</div>
    </div>

    <div id="detail">
      <h3>Details</h3>
      <div id="detail-content"><i style="color:$muted">Click a node to inspect.</i></div>
    </div>
  </div>
  <div id="graph"></div>
</div>

<script>
var nodesData = $nodes_json;
var edgesData = $edges_json;

var nodes = new vis.DataSet(nodesData);
var edges = new vis.DataSet(edgesData);
var toolNodes = nodesData.filter(function(n) { return n.group === 'tool_call'; }).map(function(n) { return n.id; });
var toolsVisible = false;

var container = document.getElementById('graph');
var network = new vis.Network(container, { nodes: nodes, edges: edges }, {
  layout: {
    hierarchical: {
      enabled: true, direction: 'UD', sortMethod: 'directed',
      levelSeparation: 120, nodeSpacing: 160, treeSpacing: 200,
      blockShifting: true, edgeMinimization: true,
    }
  },
  physics: { enabled: false },
  edges: {
    arrows: { to: { enabled: true, scaleFactor: 0.6 } },
    smooth: { type: 'cubicBezier', forceDirection: 'vertical' },
    font: { size: 10, color: '$muted', face: 'monospace' },
  },
  nodes: {
    font: { size: 12, face: 'monospace', color: '$text' },
    borderWidth: 2, borderWidthSelected: 3,
    shadow: { enabled: true, color: 'rgba(0,0,0,0.3)', size: 8, x: 2, y: 2 },
  },
  interaction: {
    hover: true, tooltipDelay: 80, zoomView: true, dragView: true,
    navigationButtons: true, keyboard: { enabled: true },
  },
});

network.on('click', function(params) {
  var detail = document.getElementById('detail-content');
  if (params.nodes.length > 0) {
    var node = nodes.get(params.nodes[0]);
    detail.innerHTML = node.title || '<i>No details.</i>';
  } else {
    detail.innerHTML = '<i style="color:$muted">Click a node to inspect.</i>';
  }
});

function fitGraph() { network.fit({ animation: { duration: 400, easingFunction: 'easeInOutQuad' } }); }
function toggleTools() {
  var btn = document.getElementById('btnTools');
  if (toolsVisible) {
    toolNodes.forEach(function(id) { nodes.update({ id: id, hidden: true }); });
    btn.textContent = 'Show Tools'; btn.classList.add('active');
  } else {
    toolNodes.forEach(function(id) { nodes.update({ id: id, hidden: false }); });
    btn.textContent = 'Hide Tools'; btn.classList.remove('active');
  }
  toolsVisible = !toolsVisible;
}
function togglePhysics() {
  var btn = document.getElementById('btnPhysics');
  var on = btn.classList.toggle('active');
  network.setOptions({ physics: { enabled: on, solver: 'hierarchicalRepulsion' } });
}
function expandAll() {
  nodesData.forEach(function(n) { nodes.update({ id: n.id, hidden: false }); });
  toolsVisible = true;
  document.getElementById('btnTools').textContent = 'Hide Tools';
  document.getElementById('btnTools').classList.remove('active');
}
function collapseToWorkers() {
  toolNodes.forEach(function(id) { nodes.update({ id: id, hidden: true }); });
  toolsVisible = false;
  document.getElementById('btnTools').textContent = 'Show Tools';
  document.getElementById('btnTools').classList.add('active');
}

// Start collapsed and fit
collapseToWorkers();
setTimeout(fitGraph, 200);
</script>
</body>
</html>""").safe_substitute(
        nodes_json=nodes_json,
        edges_json=edges_json,
        task_display=task_display,
        stat_iterations=stats["total_iterations"],
        stat_workers=stats["total_workers"],
        stat_tool_calls=stats["total_tool_calls"],
        stat_tools_ok=stats["tools_ok"],
        stat_tools_failed=stats["tools_failed"],
        stat_nodes=len(data["nodes"]),
        **c,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_execution_graph(
    run_dir: Path,
    output_path: Path | None = None,
    workflow_dir: Path | None = None,
) -> Path | None:
    """Generate an interactive HTML execution graph for a completed run.

    No external Python dependencies required — generates self-contained HTML
    with vis.js loaded from CDN.

    Args:
        run_dir: Path to the run directory (delegation loop) or workflow dir (DAG).
        output_path: Where to write the HTML file.
        workflow_dir: For DAG runs, the workflow root directory.

    Returns:
        Path to the generated HTML file, or None if generation failed.
    """
    if output_path is None:
        output_path = run_dir / "execution_graph.html"

    try:
        is_delegation = (run_dir / "run_manifest.json").exists() or (
            run_dir / "iterations"
        ).exists()

        if is_delegation:
            data = _collect_delegation_data(run_dir)
            html = _render_html(data)
        else:
            # DAG mode — use legacy builder if pyvis available, otherwise skip
            try:
                from pyvis.network import Network  # noqa: F401
                net = _build_dag_graph_legacy(
                    workflow_dir or run_dir,
                    (workflow_dir or run_dir) / "data" / "state",
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                net.save_graph(str(output_path))
                logger.info("Execution graph saved to %s", output_path)
                return output_path
            except ImportError:
                logger.warning("DAG graph requires pyvis. Install with: pip install pyvis")
                return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        logger.info("Execution graph saved to %s", output_path)
        return output_path

    except Exception as exc:
        logger.warning("Failed to generate execution graph: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Legacy DAG builder (requires pyvis)
# ---------------------------------------------------------------------------

def _build_dag_graph_legacy(
    workflow_dir: Path,
    state_dir: Path,
) -> Any:
    """Build a Pyvis Network from DAG workflow run data (legacy, requires pyvis)."""
    from pyvis.network import Network

    net = Network(
        height="900px", width="100%", directed=True,
        bgcolor="#0d1117", font_color="#c9d1d9",
    )
    net.set_options(json.dumps({
        "layout": {"hierarchical": {"enabled": True, "direction": "UD",
                   "sortMethod": "directed", "levelSeparation": 150, "nodeSpacing": 180}},
        "physics": {"enabled": False},
        "edges": {"arrows": {"to": {"enabled": True}}, "smooth": {"type": "cubicBezier"}},
        "nodes": {"font": {"size": 14, "face": "monospace"}, "borderWidth": 2},
        "interaction": {"hover": True, "tooltipDelay": 100},
    }))

    state_files: dict[str, dict] = {}
    if state_dir.exists():
        for sf in state_dir.glob("*.json"):
            data = _read_json(sf)
            if data:
                state_files[sf.stem] = data

    for name, state in state_files.items():
        if name == "final":
            continue
        result = state.get(name, state) if name in state else state
        conf = result.get("confidence")
        color = _confidence_color(conf)
        net.add_node(name, label=f"{name}\\nconf: {conf}", shape="square", color=color, size=25)

    if "final" in state_files:
        net.add_node("final", label="Final State", shape="diamond", color=_COLORS["blue"], size=30)

    return net
