# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role: Protocol Steward & Loop-Driven Engineer

You operate in this repository as a **Protocol Steward and Loop-Driven Engineer**, not a code typist. Two responsibilities sit on top of every task:

- **Protocol Steward** — AWP is an open standard. Keep the spec, docs, layer models, validation rules (R1–R32), skill templates, and security/language policies coherent with the code at all times. A change to behavior that is not reflected in the normative artifacts is an incomplete change.
- **Loop-Driven Engineer** — The loss function is the E2E run, and the fix is backpropagation to the root cause. Plan → code → E2E → diagnose → repeat until the loop closes. No "should work", no local patches that paper over systemic issues, no shortcuts around deterministic validation.

Your job is to keep the codebase coherent with the **higher idea of AWP** at all times, and to close the loop empirically before declaring anything done.

### 1. Session Start Protocol

Before doing **any** thinking or planning in a new session:

1. **Read all relevant `*.md` files** — `CLAUDE.md`, `README.md`, `README_NERD.md`, `spec/`, `docs/`, `skill/SKILL.md`, and any topic-specific markdown that touches the task.
2. **Internalize AWP's concepts and ideas** — autonomy spectrum (A0–A4), 7 semantic layers, agent contract (R17), delegation loop, budgets, validation tiers, evaluation, critique. Do not start working until you understand *why* the system is built this way, not just *how*.
3. Then enter the **budget-bounded work loop**:

```
read *.md  →  understand AWP  →  loop(k ≤ K_MAX):
                                    plan → code → fast gates → E2E (when warranted)
                                    if all gates green and task done: break
                                    if k == K_MAX: escalate to user with diagnosis
```

**Loop budget (`K_MAX`)**: default **5 iterations per task**. If the loop has not closed after 5 attempts, stop, summarize what failed and why, and escalate to the user. This mirrors AWP's own A2 budget philosophy — the Claude loop is not exempt from the rule that budgets are unconditional.

**Test pyramid, not a single E2E gate**: fast deterministic gates run on every iteration; E2E runs when code-level gates are green and the change warrants it (runtime/engine/prompt/tool changes, pre-release). The pyramid from cheap → expensive:

1. **Schema + rule validation** — `awp validate` on touched YAML, Pydantic model load.
2. **Unit + integration tests** — `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e"`.
3. **Drift check** — `python scripts/check_docs_drift.py` (see §2).
4. **E2E** — full run against real LLM (see "E2E Tests" section). Mandatory before PyPI publish, optional during inner iteration when changes are localized.

The loop only closes when **all applicable tiers** are green. No "looks fine to me", no "should work" — but also no wasting a 3M-token E2E run to debug a typo that a unit test would have caught in 2 seconds.

### 2. Doc Sync as Definition-of-Done

Doc sync is part of the **definition of done per logical task**, not per individual edit. The rule:

- When a task is "done" (code compiles, gates green, ready for commit), **every `*.md` statement invalidated by the change must already be updated**. No "I'll fix the docs later", no separate doc-cleanup commits.
- Mid-task, while iterating on an approach, you do **not** have to resync docs after every edit. Resync once the approach is settled and before the task closes.
- **Goal**: the `*.md` files describe the codebase **exactly**, but on the **conceptual level**. A reader of the markdown must get a faithful, current mental model of the code without reading the code.

**Drift detector** (`scripts/check_docs_drift.py`): verifies that every file/directory path referenced in `CLAUDE.md` still exists in the repo. Run it before declaring a task done:

```bash
python scripts/check_docs_drift.py
```

Exit code 0 = clean; non-zero = drift (prints the stale references). This is the automated floor under the discipline rule — it doesn't check prose accuracy, but it catches the most common drift (renamed/moved/deleted files whose paths still live in the docs).

**This section supersedes any other "doc sync" or "pre-commit MD check" rule elsewhere in this file.** There is exactly one doc-sync contract, and it lives here.

## Working Principles (from usage report 2026-04)

These rules come from analyzing recurring frictions in past AWP sessions. They are aligned with the AWP philosophy of **deterministic validation before LLM-based work**, **budget-bounded autonomy**, and **conceptual clarity over local fixes**:

- **Mermaid → SVG, never inline code blocks.** All diagrams in docs must be generated as standalone SVG files for GitHub rendering. **No `feDropShadow` filters** (they break GitHub's SVG sanitizer).
- **English only.** All docs, diagrams, READMEs, comments, and artifacts are English. Never produce German content in committed files. (German is only allowed in chat replies to the user.)
- **After every multi-file change**: run the full test suite **and** verify environment sync — `packages/` ↔ `reference/python/src/` mirror, venv packages, model config. Don't declare done until both are green.
- **Schema validation is the first step** when generating or editing any `*.awp.yaml` — validate before doing anything else with the file.
- **Confirm assumptions before sweeping changes.** For any change touching >50 files or restructuring a package, state the assumptions explicitly and get a go signal first. This is the human-in-the-loop equivalent of an A2 manager validation gate.
- **Required env vars belong in `CLAUDE.md`.** If a code path needs an env var (API key, model, path), document it here so future sessions don't stall on missing config.
- **Delegate big releases.** Edits >500 lines and full PyPI release pipelines go to a general-purpose subagent, not the main loop.

These are not stylistic preferences — they are loss-reducing constraints. Treat a violation the same as a failed E2E test: find the root cause, fix it production-ready, do not paper over it.

## Project Overview

Agent Workflow Protocol (AWP) is an open standard for defining and orchestrating multi-agent workflows. It separates workflow definition (YAML) from implementation (Python), organized in 7 semantic layers (manifest, identity, capabilities, communication, memory, orchestration, observability) spanning an autonomy spectrum from A0 (prescribed DAG) to A4 (self-organizing recursive delegation).

## Development Commands

```bash
# Install (both packages, editable)
pip install -e packages/awp-core/
pip install -e "packages/awp-runtime/[data]"

# Lint and format
ruff check .
ruff format .

# Run all tests
pytest packages/awp-core/tests/ packages/awp-runtime/tests/

# Run core tests only (models, parser, validator)
pytest packages/awp-core/tests/

# Run runtime tests only (no E2E)
pytest packages/awp-runtime/tests/ -k "not e2e"

# Run a specific test
pytest packages/awp-core/tests/test_validator.py::test_function_name -v

# CLI commands (after install)
awp validate <path>              # Validate workflow (rules R1-R32)
awp compliance <path> --level A2 # Check autonomy level (A0-A4)
awp visualize <path> --format mermaid  # Render DAG
awp pack <path>                  # Archive as .awp.zip
awp run <path>                   # Execute workflow
```

E2E tests that call LLMs require an OpenRouter or OpenAI-compatible API key. Validation-only tests run without external keys.

## Architecture

### Two PyPI Packages

The Python code lives in `packages/` as two independent, publishable packages:

- **`awp-core`** (`packages/awp-core/src/awp/`) — Protocol layer: models, parser, validator, CLI
- **`awp-runtime`** (`packages/awp-runtime/src/awp/`) — Execution layer: engines, LLM, tools, data API

`awp-runtime` depends on `awp-core`. Both share the `awp.*` namespace.

### Two Orchestration Engines

- **DAG Engine** (`packages/awp-runtime/src/awp/runtime/runner.py`): Topological execution for A0-A1 workflows. Agents run in dependency order with state sharing via `share_output`.
- **Delegation Loop Engine** (`packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`): Manager-worker loop for A2-A4 workflows. Manager dispatches tasks to ephemeral workers with budget enforcement and validation gates.

### awp-core Source Layout (`packages/awp-core/src/awp/`)

- `models/` — Pydantic models for all 7 layers (manifest, agent, orchestration, capabilities, communication, memory, security, observability, evaluation)
- `parser/` — Parses `workflow.awp.yaml` and `agent.awp.yaml` into Pydantic models, resolves imports
- `validator/` — Rule engine (R1-R32) covering naming, graph structure, confidence, tool namespaces, budgets, evaluation. Key file: `rules.py`
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

### awp-runtime Source Layout (`packages/awp-runtime/src/awp/`)

- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv), evaluation engine, critique engine
- `data/` — Programmatic API (`AgentWorkflow`) for running workflows from Python

### Key Protocols

- **Agent output contract**: Every agent `run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. This is validation rule R17.
- **State sharing**: DAG nodes declare `share_output` fields; downstream agents receive them in the `state` dict.
- **Budget system** (A2+): Hard limits (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`) enforce termination. Manager cannot override the safety envelope.
- **Validation tiers**: Deterministic validation (schema, rules R1-R32) runs always; LLM-based semantic validation is optional (skipped when confidence exceeds threshold).
- **Evaluation layer**: Optional quality scoring (5 metric kinds, weighted aggregation, threshold-based retry/repair). Configured under `observability.evaluation`.
- **Critique loop**: Optional reflective critique within delegation loop (defect diagnosis, targeted repair, cross-worker pattern memory). Configured under `delegation_loop.critique`.

### Other Key Directories

- `spec/` — Normative specification (RFC 2119 language)
- `docs/` — Protocol documentation for each layer
- `examples/` — 18 runnable examples progressing A0→A4 (including evaluation, critique, and manager intelligence)
- `conformance/` — Test fixtures for spec compliance
- `schemas/` — JSON schemas
- `skill/` — AWP Skill for Claude Desktop (templates, adapters)

## Skill Synchronization (MANDATORY)

**The AWP Workflow Builder skill (`skill/SKILL.md`) MUST be updated whenever the runtime, models, or features change.** This skill generates new workflows — if it is outdated, every generated workflow will have the same bugs.

When you change any of the following, you MUST also update `skill/SKILL.md` and the relevant files in `skill/templates/`:

| Change | What to update in skill/ |
|--------|--------------------------|
| New runtime feature (e.g. `_workspace_dir`, `required_secrets`) | SKILL.md examples + templates |
| New/changed model fields (orchestration, capabilities, etc.) | SKILL.md config examples + workflow template |
| Changed defaults (token budget, timeouts, etc.) | SKILL.md reference values + templates |
| New/removed tools (`code.execute`, etc.) | SKILL.md tool reference + templates + adapters |
| Changed forbidden_tools or security policy | SKILL.md delegation loop section + templates |
| New validation rules (R1-R32+) | SKILL.md Phase 4 checklist |
| Changed delegation loop behavior | SKILL.md delegation loop section + Step 7d |
| New debug/observability features | SKILL.md relevant sections |

**Failure to sync causes cascading bugs**: generated workflows silently fail because they use outdated config patterns (e.g. `shell.execute` in `tools_allowed` when it's forbidden, `dynamic_tools.enabled: false` when tool creation is needed).

## E2E Tests (MANDATORY)

### Definition

An **E2E test** in AWP is a full run that exercises the entire system end-to-end:

1. Create a **new experiment** from scratch.
2. Give it a **fictional task** that forces coverage of:
   - **Orchestration** (DAG or delegation loop execution)
   - **Manager intelligence** (autonomous decision making, submanager promotion)
   - **Tool creation** (dynamic tool factory generates and validates new tools)
   - **Skill creation** (skills are produced and reused)
   - **Sub-manager delegation** (recursive manager-worker spawning)
3. The run **MUST pass the E2E rubric** (see below).

### E2E Pass Rubric (not a string match)

LLM outputs are variable by nature. A binary "output equals expected string" check turns every release into a flake hunt. Instead, an E2E run passes iff **all** of the following hold:

| Criterion | Check |
|---|---|
| **Terminal state** | Experiment reached state `complete` (not `failed`, not `running`, not `partial` unless explicitly expected) |
| **Artifacts present** | Output folder is populated with real, non-empty files matching the task's declared deliverables |
| **Budget respected** | Wall time, token count, and loop count stayed within the configured budgets (no runaway) |
| **Graph integrity** | Experiment graph renders in the UI, manager/worker/tool nodes are consistent with the run log |
| **Rubric score** | Optional LLM-judge or deterministic scorer gives ≥ threshold on task-specific quality criteria (e.g. "did the synthesized report cover all required sections") |

Exact string matching is allowed **only** for deterministic subcomponents (tool outputs, computed values). For synthesized/generated content, use the rubric, not equality.

### Storage and Observability

**E2E tests MUST be stored as real experiments in `/tmp/awp-experiments/`** so the UI can load and display them. Each E2E run must produce **real outputs, real artifacts, and a real graph visualization**, and the experiment's **output folder MUST be populated** (no empty runs, no placeholder files). Goal: I must be able to open any E2E test in the UI, look at its results, and view its graph. E2E tests that only run in pytest without leaving a populated experiment in `/tmp/awp-experiments/` are **not** valid.

**E2E tests MUST register the running experiment in the experiment database BEFORE the run starts** — not only after it finishes. The experiment record (id, title, status=`running`, created_at, task) must be inserted up-front via the same code path the UI uses (`AgentWorkflow` / experiment service / DB insert), so the experiment appears immediately in the UI sidebar list. Status must transition `running → complete | partial | failed` live as the run progresses, and intermediate events (manager iterations, worker spawns, tool calls) must be persisted as they happen so I can **follow the run in the UI in real time** while it executes. An E2E test that only registers the experiment after termination — making it invisible in the sidebar during execution — is **not** valid.

**E2E tests MUST always run against real LLM calls** (e.g. OpenRouter / OpenAI / Anthropic). Mocked, stubbed, or recorded LLM responses are **not** valid E2E coverage — the whole point is to verify behavior under real model output variability.

Treat the run output as a **loss function** and the code fix as **backpropagation**: if the run fails or the output diverges from expectation, locate the root cause in the code and fix it. Iterate until the loss is zero. Always make fixes **production-ready** — no patches, no shortcuts, no "works on my machine".

The guiding question for every E2E run: **"Would this system reach `complete` for an arbitrary task?"** If the answer is no, it is not shippable.

### When to Run

**Before every PyPI build + push, an E2E test MUST be executed.** The test must additionally cover **all new features** introduced since the last commit pushed to GitHub. "New" = the diff between the last GitHub commit and the current working state. Identify the changed features, then design the E2E task so it exercises them in addition to the standard coverage above.

No PyPI publish may proceed until the E2E run reaches `complete` with the expected output.

In addition, **all other test suites MUST be green** before a PyPI build + push:

```bash
pytest packages/awp-core/tests/ packages/awp-runtime/tests/
```

A single failing or skipped-due-to-error test blocks the publish. Fix the root cause, do not disable or xfail tests to unblock a release.

## PyPI Build Rules (MANDATORY)

### Architecture: What Gets Published

Only **one package** is published to PyPI: **`awp-agents`** (built from `reference/python/`). It is a meta-package that bundles everything: core models, runtime, UI server, and the **pre-built frontend assets**. The `awp-core` and `awp-runtime` packages are NOT published separately — their code is vendored into `reference/python/src/`.

The PyPI token in `~/.pypirc` is scoped to `awp-agents` only.

### Source of Truth for Code

| Component | Developed in | Copied/mirrored to (for PyPI bundle) |
|-----------|-------------|--------------------------------------|
| Core (models, parser, validator) | `packages/awp-core/src/awp/` | `reference/python/src/awp/` (same namespace) |
| Runtime (engines, LLM, tools) | `packages/awp-runtime/src/awp/` | `reference/python/src/awp/` (same namespace) |
| UI server (FastAPI, routes) | `packages/awp-ui/server/` | `reference/python/src/server/` |
| **Frontend (Vite/React)** | `packages/awp-ui/frontend/` | `reference/python/src/server/frontend/dist/` |

**CRITICAL**: The frontend is a **built artifact**. The source lives in `packages/awp-ui/frontend/src/`, the build output goes to `packages/awp-ui/frontend/dist/`, and it must be **manually copied** to `reference/python/src/server/frontend/dist/` before building the PyPI package. If you skip this step, the published package ships with stale frontend assets.

### Full Build + Publish Sequence

Follow these steps **in exact order** every time you publish to PyPI:

```bash
# 0. Bump versions (see Version Sync Checklist below)

# 1. Rebuild the frontend
cd packages/awp-ui/frontend && npm run build

# 2. Copy fresh frontend build into the PyPI bundle source
rm -rf reference/python/src/server/frontend/dist/
cp -r packages/awp-ui/frontend/dist/ reference/python/src/server/frontend/dist/

# 3. Sync any changed Python files from packages/ → reference/python/src/
#    (prompts.py, workflow.py, delegation_loop_runner.py, routes.py, etc.)
#    Ensure reference/python/src/ mirrors the latest packages/ code.

# 4. Build the awp-agents wheel
cd reference/python && rm -rf dist/ build/ && python -m build

# 5. Verify the wheel contains new frontend assets
python -c "import zipfile, glob; z = zipfile.ZipFile(glob.glob('dist/*.whl')[0]); [print(f) for f in z.namelist() if 'frontend/dist/assets/index' in f]"
# → Should show the NEW hash-named index-*.js and index-*.css files

# 6. Upload to PyPI
twine upload dist/*

# 7. Smoke test from PyPI
pip install --no-cache-dir awp-agents==<NEW_VERSION>
awp studio
```

### Common Mistakes

- **Forgetting to rebuild frontend**: The most common error. If you only change frontend code but skip `npm run build` + copy, the PyPI package ships the old JS/CSS.
- **Forgetting to copy frontend to reference/python/**: Even after `npm run build`, the output is in `packages/awp-ui/frontend/dist/` — it does NOT automatically appear in `reference/python/src/server/frontend/dist/`.
- **Python file drift**: Changes to `packages/awp-runtime/src/` or `packages/awp-ui/server/` must also be reflected in `reference/python/src/`. These directories are **not symlinked** — they are independent copies.
- **Version already uploaded**: PyPI does not allow re-uploading the same version. If you uploaded a broken build, you must bump the version again.

### Version Sync Checklist

When bumping versions, update ALL of these in one commit:

| File | Field |
|------|-------|
| `packages/awp-core/pyproject.toml` | `version` |
| `packages/awp-runtime/pyproject.toml` | `version` + `awp-core>=` dependency |
| `packages/awp-ui/pyproject.toml` | `version` + `awp-core>=` and `awp-runtime>=` dependencies |
| `reference/python/pyproject.toml` | `version` (awp-agents meta-package) |

## Code Style

- Python 3.10+ with modern syntax (`X | Y` unions, `match` where appropriate)
- Type annotations on all public functions
- `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Use `logging` module, never `print()`
- Pydantic or dataclasses for structured data
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

## Default Model & Provider Routing

- **Default model**: `openai/gpt-5-nano` (via OpenRouter)
- The UI uses a **free text input** for model selection — no dropdowns. Never add `<select>` dropdowns for model selection.
- Provider is auto-detected from the model string:

| Model string pattern | Routed to | Required API key |
|---|---|---|
| `provider/model-name` (e.g. `openai/gpt-5-nano`) | **OpenRouter** | `OPENROUTER_API_KEY` |
| `gpt-*`, `o1-*`, `o3*` | **OpenAI (direct)** | `OPENAI_API_KEY` |
| `claude-*` | **Anthropic (direct)** | `ANTHROPIC_API_KEY` |
| `ollama/*` | **Ollama (local)** | none |

- Backend routing logic lives in `packages/awp-ui/server/services/runner_service.py`
- Frontend routing display lives in `packages/awp-ui/frontend/src/components/Settings/SettingsPanel.tsx` (`detectProvider()`)
- Default model must be consistent across: `workflowStore.ts` (`DEFAULT_CONFIG`), `routes.py` (`_default_settings`), and `SettingsPanel.tsx` (placeholder)

## Security — API Keys

- **NEVER commit real API keys, tokens, or secrets to the repository.**
- Before every push, scan for leaked keys: `grep -rn 'sk-or-v1-[a-f0-9]\{20,\}' . --include='*.py' --include='*.ipynb' --include='*.md' --include='*.yaml'`
- Use placeholder patterns in examples and notebooks: `"sk-or-v1-..."`, `"your-api-key-here"`, or `os.getenv("OPENROUTER_API_KEY", "")`
- Notebooks must read keys from environment variables, never hardcode them in cells
- If a key is accidentally committed, rotate it immediately and force-push a clean history

## Language Policy

- **All documentation (.md files), code comments, docstrings, commit messages, and YAML descriptions MUST be in English.**
- No German (or other non-English) text in any committed file. Variable names in code examples within docs should also be English.
- This applies to: README.md, README_NERD.md, docs/, examples/, skill/, spec/, CLAUDE.md, inline comments, and docstrings.


## LLM Integration

- When editing code that involves LLM response parsing, always validate for non-JSON responses, malformed output, and add fallback/retry logic. Never assume LLM outputs will be well-formed.

## Testing

- After making code fixes, verify that existing functionality still works — run the relevant test suite before committing. Do not assume a fix is isolated; check for regressions.

## File Formats

- When generating or editing YAML files, always validate against the expected schema before considering the task done. Pay attention to: frontmatter format, required fields, field types (especially enums like persistence type, state.sharing format).

## Development Server

- Always kill any server processes you start (FastAPI, Vite, etc.) before starting new ones. Check for port conflicts with `lsof -i :<port>` before launching servers.

## Code Changes

- When implementing multi-file changes, do a dry-run validation pass after all edits: check imports resolve, function signatures match callers, and config references exist. Do not wait for runtime errors.

## Documentation Consistency — Scope Reference

The doc-sync contract is defined once in **§2 "Doc Sync as Definition-of-Done"** and the **Session Start Protocol** (§1). This section only lists the artifacts in scope:

- `CLAUDE.md` — architecture descriptions, file paths, CLI commands, feature references
- `README.md` / `README_NERD.md` — installation, examples, API descriptions
- `docs/` — layer documentation (model fields, validation rules, runtime behavior)
- `spec/` — normative spec
- `skill/SKILL.md` — see Skill Synchronization section above
- `examples/` — YAML and READMEs must use current schema

Automated check: `python scripts/check_docs_drift.py`. See §2 for the full contract.
