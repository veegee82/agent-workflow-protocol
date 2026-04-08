# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role: Code-Architect

You operate in this repository as a **Code-Architect**, not a code typist. Your job is to keep the codebase coherent with the **higher idea of AWP** at all times.

### 1. Session Start Protocol

Before doing **any** thinking or planning in a new session:

1. **Read all relevant `*.md` files** — `CLAUDE.md`, `README.md`, `README_NERD.md`, `spec/`, `docs/`, `skill/SKILL.md`, and any topic-specific markdown that touches the task.
2. **Internalize AWP's concepts and ideas** — autonomy spectrum (A0–A4), 7 semantic layers, agent contract (R17), delegation loop, budgets, validation tiers, evaluation, critique. Do not start working until you understand *why* the system is built this way, not just *how*.
3. Then enter the work loop:

```
read *.md  →  understand AWP  →  loop(n):
                                    plan → code → E2E test
                                    if E2E test passes: break
```

The loop only exits when the E2E test passes. No "looks fine to me", no "should work" — the loss function is the E2E result.

### 2. Pre-Commit Doc Sync Protocol

**Before every `git commit`**: update **ALL** relevant `*.md` files to reflect the changes in this commit. Code and docs must ship together.

**Goal**: the `*.md` files describe the codebase **exactly**, but on the **conceptual level**. A reader of the markdown must get a faithful, current mental model of the code without reading the code. If a code change invalidates a single sentence in any `*.md`, that sentence is updated in the same commit.

No drift. No "I'll fix the docs later". Code ↔ docs sync is part of the definition of done.

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
awp validate <path>              # Validate workflow (rules R1-R30)
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
- `validator/` — Rule engine (R1-R30) covering naming, graph structure, confidence, tool namespaces, budgets, evaluation. Key file: `rules.py`
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

### awp-runtime Source Layout (`packages/awp-runtime/src/awp/`)

- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv), evaluation engine, critique engine
- `data/` — Programmatic API (`AgentWorkflow`) for running workflows from Python

### Key Protocols

- **Agent output contract**: Every agent `run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. This is validation rule R17.
- **State sharing**: DAG nodes declare `share_output` fields; downstream agents receive them in the `state` dict.
- **Budget system** (A2+): Hard limits (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`) enforce termination. Manager cannot override the safety envelope.
- **Validation tiers**: Deterministic validation (schema, rules R1-R30) runs always; LLM-based semantic validation is optional (skipped when confidence exceeds threshold).
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
| New validation rules (R1-R30+) | SKILL.md Phase 4 checklist |
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
3. The run **MUST reach state `complete`** and the output **MUST match the expected result**.

**E2E tests MUST be stored as real experiments in `/tmp/awp-experiments/`** so the UI can load and display them. Each E2E run must produce **real outputs, real artifacts, and a real graph visualization**, and the experiment's **output folder MUST be populated** (no empty runs, no placeholder files). Goal: I must be able to open any E2E test in the UI, look at its results, and view its graph. E2E tests that only run in pytest without leaving a populated experiment in `/tmp/awp-experiments/` are **not** valid.

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

## Documentation Consistency (MANDATORY)

### Pre-Commit MD Sync Check

**Before every commit, all `.md` files MUST be checked for consistency with the current code.** This includes:

- `CLAUDE.md` — architecture descriptions, file paths, CLI commands, and feature references must match actual code
- `README.md` / `README_NERD.md` — installation instructions, examples, and API descriptions must reflect current behavior
- `docs/` — layer documentation must match model fields, validation rules, and runtime behavior
- `spec/` — normative spec must align with implemented features
- `skill/SKILL.md` — see Skill Synchronization section above
- `examples/` — YAML and README files must use current schema and valid field values

If a code change invalidates any statement in an MD file, update the MD file in the same commit. Do not leave stale documentation behind.

### Session Bootstrap — Read All MD Files

**At the start of every new session, Claude MUST read the key documentation files** to build a mental model of the project's higher-level vision and current state before making any changes. At minimum, read:

1. `CLAUDE.md` (this file)
2. `README.md`
3. `spec/` — at least the overview/index file
4. `docs/` — scan the layer docs for current structure
5. `skill/SKILL.md`

This ensures that all changes are informed by the project's overarching design intent, not just local code context.
