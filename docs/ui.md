# AWP Workflow Studio

## Mental Model

Workflow Studio is the human window into a running AWP workflow. CLI runs are great for automation but terrible for *understanding* what a delegation loop is actually doing — which manager decision led to which worker, which worker created which tool, where the budget went, why a sub-tree terminated. Studio is built around a single idea: **make every step of an autonomous agent run visible, replayable, and reproducible**, without forcing the user to read JSON logs.

The UI is organised around three concepts that map directly to the runtime:

1. **Experiments** (formerly *sessions*) — the unit of work the user owns. An experiment groups related runs, settings, secrets, memory, and protocol notes under one persistent identity. You return to an experiment the way you return to a Jupyter notebook: it remembers everything.
2. **Runs** — the individual executions inside an experiment. Each run produces an event stream, a graph, artifacts, and (optionally) an evaluation score.
3. **The graph** — the live, recursive view of manager → worker → tool → submanager. For A4 workflows the graph nests sub-runs into colour-coded clusters so the human can see *which submanager spawned which children*, and how much budget each cluster reserved.

Studio is the default surface for the [runtime tool generation pipeline](runtime-tool-generation.md) (you watch tools being created, repaired, and called in real time), the [manager intelligence subsystems](manager-intelligence.md) (planning, hypotheses, decision journal all surface as inline panels), and the [evaluation layer](evaluation.md) (score appears next to each completed run).

<p align="center">
  <img src="../assets/ui.png" alt="AWP Workflow Studio" width="100%"/>
</p>

## Quick Start

```bash
pip install awp-agents
awp studio
```

That's it. The browser opens at `http://127.0.0.1:8420`.

### Development Install (from source)

```bash
pip install -e packages/awp-core/
pip install -e "packages/awp-runtime/[data]"
pip install -e "packages/awp-ui/[awp]"
cd packages/awp-ui/frontend && npm install && npm run build && cd -
awp studio --dev
```

### PyCharm Run Configuration

1. **Run > Edit Configurations > + > Python**
2. **Module name:** `awp.cli`
3. **Parameters:** `studio`
4. **Python interpreter:** Your project venv or `~/.awp/venv/bin/python`
5. **Working directory:** Project root

### Command-line options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 8420 | Server port |
| `--host` | 127.0.0.1 | Bind address |
| `--base-dir` | cwd | Base directory for workflow discovery |
| `--dev` | off | Development mode with Vite hot-reload |
| `--no-open` | off | Do not open browser automatically |

## UI Layout

The interface has five areas:

```
+------------------+-----------------------------------+------------------+
|                  |            Top Bar                 |                  |
|    Sessions      |  [State] [Final] [Output] [Graph] [History]          |
|    (left)        +-----------------------------------+   Settings       |
|                  |                                   |   (right)        |
|                  |         Main Content              |                  |
|                  |                                   |                  |
|                  +-----------------------------------+                  |
|                  |         Task Input Bar             |                  |
|                  |   [attach] [___task___] [run]      |                  |
+------------------+-----------------------------------+------------------+
|                        Status Bar                                       |
+------------------------------------------------------------------------+
```

### The Experiment Paradigm

Studio used to call these *sessions*. They are now **experiments** — and the rename is not cosmetic. A session implied a single conversation; an experiment is a long-lived workspace with metadata, scoped history, and multiple tabs of context that survive across runs. The two new tabs make this concrete:

- **Protocol tab** — a free-form, persistent notebook for the human running the experiment. Hypotheses, observations, links to runs, screenshots. The protocol survives every restart and is exported with the experiment.
- **Memory tab** — the agent-side counterpart with three sub-tabs:
  - **Artifacts** — files from the run's `workspace/memory/` directory (tools, facts, antipatterns produced by auto-curation). Shows file name, kind, size, and source; auto-refreshes during live runs.
  - **Short-term** — scoped session/daily memory entries written by workflows running inside this experiment. Each entry shows its tier (`session`, `daily`, `long_term`), originating run, and timestamp.
  - **Long-term** — persistent memory entries that survive across experiments.
  See [memory.md](memory.md) for the underlying tier model.

Each experiment carries metadata (title, description, tags, default settings, default secrets) and a **scoped history**: the History tab inside an experiment shows only that experiment's runs, while the global History view spans all experiments. Background runs in *other* experiments stay visible via the live status dots in the sidebar — switching experiments never silently kills a run.

This is the paradigm change: an experiment is the smallest unit of *reproducibility* in Studio. Open it tomorrow and you get back the same protocol notes, the same memory entries, the same settings, the same history — exactly the way a Jupyter notebook restores its kernel state on reopen.

### Experiments (left sidebar)

- Lists all experiments (formerly "sessions"), searchable, groupable by time or status
- Click an experiment to fully restore it (config, output, graph, results)
- Create new experiments, rename, or delete via the context menu
- Each item shows a live status dot derived from `last_run_status` (computed
  from the runs table on every list call) so background runs in other
  experiments stay visible
- **Per-experiment Play/Stop button** on each row — starts a new run on the
  selected experiment, or stops the running one. The button is kept in lockstep
  with the Run/Stop button in the Task Input Bar (both call the same store
  actions, so toggling one updates the other instantly)
- Stopped runs are persisted with `status="stopped"` and rendered as a muted
  dot rather than the pulsing blue "running" indicator
- Toggle sidebar visibility with the panel button

### Task Input Bar (bottom center)

- Multi-line textarea for describing the task
- **Enter** = Run, **Shift+Enter** = new line
- Attach files button (left) -- uploads files as workflow inputs
- Run/Stop button (right) — synchronized with the per-experiment Play/Stop
  buttons in the sidebar. Stopping a run hits `POST /api/runs/{run_id}/stop`,
  which both signals the worker thread and persists the terminal `stopped`
  status to SQLite.

### Settings (right sidebar)

- **Model** -- LLM model identifier (e.g. `openrouter/anthropic/claude-sonnet-4`)
- **Worker model** -- Optional separate model for workers
- **Sandbox** -- Execution environment (subprocess, docker, venv, none)
- **Budget** -- Max loops, tokens, workers, wall time
- **Toggles** -- Code mode, tool creation, verbose
- **Output directory** -- Where to write artifacts (empty = temp dir)
- **Secrets** -- API keys stored in the database (values never exposed in API responses)

All settings are persisted in SQLite and restored on startup.

#### Model fields and provider auto-detect

The **Model** and **Worker model** inputs are deliberately **free-text** — there is no dropdown, and you should never expect one. The backend (`runner_service.py`) and the frontend (`SettingsPanel.tsx::detectProvider`) both inspect the model string and route the call automatically:

| Model string pattern | Routed to | Required key |
|---|---|---|
| `provider/model-name` (e.g. `openai/gpt-5-mini`, `nvidia/nemotron-3-super-120b-a12b`) | OpenRouter | `OPENROUTER_API_KEY` |
| `gpt-*`, `o1-*`, `o3*` | OpenAI direct | `OPENAI_API_KEY` |
| `claude-*` | Anthropic direct | `ANTHROPIC_API_KEY` |
| `ollama/*` | Ollama (local) | none |

Defaults:

- **Manager model**: `nvidia/nemotron-3-super-120b-a12b` (OpenRouter)
- **Worker model**: `openai/gpt-5-mini` (OpenRouter)

When the worker model is left empty, workers inherit the manager model. Setting them separately is the standard pattern for cost control: a strong manager planning the run, cheap workers doing the legwork. The Settings panel shows a small badge under each field indicating the auto-detected provider, so you can verify routing at a glance.

#### Code mode and tool creation defaults

The **Code mode** and **Tool creation** toggles are **enabled by default** in Studio (and in Jupyter when no workflow is loaded). The [B1-B6 robustness pipeline](runtime-tool-generation.md) makes the default-on stance safe; most non-trivial tasks benefit from runtime adaptation, and disabling them only makes sense for strict-conformance regression runs.

## The Five Tabs

### State

Shows the current run status:

- **Final Result** -- The agent's answer, rendered as Markdown or syntax-highlighted JSON
- **Error** -- If the run failed, the error message
- **Budget summary** -- Iterations, tokens, workers, wall time with progress bars

Automatically opens when a run completes.

### Final

Displays all output artifacts generated by the workflow:

- **Images** -- PNG, JPG, SVG, WebP rendered in a grid
- **Visualizations** -- HTML files (e.g. execution graphs, Plotly charts) rendered as interactive iFrames
- **Tables** -- CSV/TSV files rendered as scrollable HTML tables with headers
- **Documents** -- Markdown files rendered with formatting, JSON/YAML/text with syntax highlighting
- **Code** -- Python files with Prism syntax highlighting and filename headers

Artifacts are discovered by scanning the run's workspace and output directories.

### Output

Live event stream during the run:

- **Run started** -- Model info
- **Iteration N** -- Each delegation loop iteration
- **Decision** -- Manager's reasoning, confidence, and delegations
- **Worker spawned/completed** -- Instructions, results, errors (verbose mode shows full details)
- **Tool calls** -- Which tools were called and their status
- **Final Result / Error** -- Run outcome

### Graph

Hierarchical tree view of the agent execution:

```
Task Root
  +-- Manager (claude-sonnet-4)
       +-- Iteration 001
       |    +-- Worker abc123 (data analysis)
       |    |    +-- Tool: code.execute
       |    |    +-- Tool: file.write
       |    +-- Worker def456 (visualization)
       |         +-- Tool: code.execute
       +-- Iteration 002: COMPLETE
```

Each node is expandable and shows:

- **Status** -- running (spinner), complete (green), error (red)
- **Confidence** -- Progress bar (green > 0.8, yellow > 0.5, red)
- **Decision** -- delegate / complete / fail badge
- **Reasoning** -- Full manager reasoning text
- **Instructions** -- What the worker was told to do
- **Tools** -- Which tools were available / used / created
- **Arguments** -- Tool call input parameters (syntax-highlighted JSON)
- **Output** -- Full result JSON (syntax-highlighted, scrollable)
- **Budget** -- Token/loop/worker snapshot

Stats bar shows total nodes, iterations, workers, and tool calls.

**LLM Trace panel.** When `trace_enabled` is active for a run (see [observability.md](observability.md#llm-call-tracing)), each worker and manager node in the Agent Inspector gains an **LLM Trace** tab. It shows every API call as an expandable card: model badge, token counts (prompt/completion/total), latency, finish reason, and the full message exchange with role-colored badges (system=purple, user=blue, assistant=green, tool=yellow). The summary header aggregates total calls, tokens, latency, and tool rounds for quick cost/performance diagnosis.

**A4 sub-run clusters.** When a workflow uses recursive delegation (A4),
the graph renders nested sub-runs as colored cluster containers (via React
Flow's `parentNode` mechanism). Clusters are color-coded by recursion depth
(violet → pink → cyan → amber) and display the triggering worker, recursion
depth, manager model, and the budget caps reserved for that sub-run. This
makes it easy to see which submanager spawned which children and how much
of the parent budget each cluster reserved.

```text
┌─ Root manager (depth 0) ────────────────────────────────┐
│  ┌─ Submanager A  depth 1  budget 40% ──────────────┐   │
│  │   worker  worker  worker                         │   │
│  │   ┌─ Submanager A.1  depth 2  budget 16% ───┐    │   │
│  │   │   worker  worker                        │    │   │
│  │   └──────────────────────────────────────────┘    │   │
│  └────────────────────────────────────────────────────┘   │
│  ┌─ Submanager B  depth 1  budget 35% ──────────────┐   │
│  │   worker  worker                                 │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

The cluster header is the place to look when a sub-tree behaves badly: it shows the *reserved* envelope (from the [reservation model](manager-intelligence.md#budget-reservation-model-and-termination-guarantees)), the *consumed* portion, and a status badge that turns red the instant the child is hard-terminated for budget exhaustion. Auto-promoted submanagers (created via [complexity-scored auto-promotion](manager-intelligence.md#complexity-scored-auto-promotion-a4-trigger)) are tagged with a small ⚙ icon so you can tell them apart from clusters that were declared up front in the YAML.

### History

List of all past runs across all sessions:

- Run ID, task, model, status, timestamp
- Click a run to load its graph

## Session Persistence

Every session is fully reproducible. When you click on a session in the sidebar, the UI restores:

| What | Stored in | Restored |
|------|-----------|----------|
| Task text | `runs.task` | Task input bar |
| Model + config | `sessions.settings_json` | Settings sidebar |
| All events | `events` table | Output tab (replayed) |
| Run results | `runs.result_json` | State tab |
| Graph | Workspace files on disk | Graph tab |
| Artifacts | Workspace files on disk | Final tab |

The backend provides `GET /api/sessions/{id}/full` which returns all runs, events, graphs, and config in a single request.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/runs` | Start a standalone run |
| `GET` | `/api/runs` | List all runs |
| `GET` | `/api/runs/:id` | Get run detail |
| `GET` | `/api/runs/:id/events` | Get persisted events |
| `GET` | `/api/runs/:id/graph` | Get execution graph |
| `GET` | `/api/runs/:id/artifacts` | List output artifacts |
| `POST` | `/api/runs/:id/stop` | Stop a running workflow |
| `GET` | `/api/sessions` | List sessions |
| `POST` | `/api/sessions` | Create session |
| `GET` | `/api/sessions/:id/full` | Full session restore |
| `POST` | `/api/sessions/:id/runs` | Start run in session |
| `GET/POST` | `/api/settings` | Load/save global settings |
| `GET/POST` | `/api/secrets` | Manage API keys |
| `GET` | `/api/files/serve?path=` | Serve workspace files |
| `GET` | `/api/tools/available` | List available tools |
| `WS` | `/ws/:run_id` | Real-time event stream |

## Architecture

```
Browser (React + Vite)
    |
    |-- REST API (FastAPI, port 8420)
    |     |-- routes.py        API endpoints
    |     |-- store.py         SQLite persistence (sessions, runs, events, settings, secrets)
    |     |-- runner_service.py Workflow execution in background threads
    |     |-- graph_builder.py  Builds React Flow graph from run directory
    |     |-- event_bus.py      Fan-out event bus with buffer + DB persistence
    |
    |-- WebSocket /ws/:run_id
    |     Real-time event streaming with replay buffer
    |
    +-- Static files (frontend/dist/)
          Production SPA served by FastAPI
```

### Per-run isolation

Each run gets its own isolated directory under the experiment:

```text
/tmp/awp-experiments/<experiment_id>/
  runs/<run_id>/              # Per-run workspace (delegation state, outputs)
    workspace/
      dynamic_tools/ → ../../shared/dynamic_tools/   # Symlink
      skills/        → ../../shared/skills/           # Symlink
    output/
  shared/                     # Persistent across runs within the experiment
    dynamic_tools/            # Tools persist and accumulate
    skills/                   # Skills persist and accumulate
```

Dynamic tools and skills are symlinked from the shared experiment-level directory into each run's workspace, so tools created in run N are available in run N+1 without copying. Delegation loop state (iterations, worker outputs, traces) stays fully isolated per run.

Legacy experiments with a flat `workspace/` + `output/` layout are automatically migrated on the first new run.

### Data flow during a run

1. User submits task via REST API
2. Backend creates a run record in SQLite and starts a background thread
3. Backend sets up per-run isolation (creates run dir, symlinks shared state)
4. Background thread launches `AgentWorkflow`, sets up a file watcher on the run directory
5. File watcher polls every 200ms for new JSON files written by the delegation loop runner
6. Each new file is translated into a `RunEvent` and pushed to the `EventBus`
7. EventBus fans out events to WebSocket subscribers AND persists them to SQLite
8. Frontend receives events via WebSocket and updates the store (output blocks, graph nodes, budget)
9. On `run.complete`, frontend loads the full graph from the backend and switches to the State tab

## Development Mode

```bash
awp studio --dev
```

This starts:
- **Vite dev server** on port 3000 with hot module replacement
- **FastAPI** on port 8420 with auto-reload
- Vite proxies `/api` and `/ws` to the backend

Edit React components in `packages/awp-ui/frontend/src/` and see changes instantly.
