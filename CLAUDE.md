# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
awp validate <path>              # Validate workflow (rules R1-R26)
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

- `models/` — Pydantic models for all 7 layers (manifest, agent, orchestration, capabilities, communication, memory, security, observability)
- `parser/` — Parses `workflow.awp.yaml` and `agent.awp.yaml` into Pydantic models, resolves imports
- `validator/` — Rule engine (R1-R26) covering naming, graph structure, confidence, tool namespaces, budgets. Key file: `rules.py`
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

### awp-runtime Source Layout (`packages/awp-runtime/src/awp/`)

- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv)
- `data/` — Programmatic API (`AgentWorkflow`) for running workflows from Python

### Key Protocols

- **Agent output contract**: Every agent `run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. This is validation rule R17.
- **State sharing**: DAG nodes declare `share_output` fields; downstream agents receive them in the `state` dict.
- **Budget system** (A2+): Hard limits (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`) enforce termination. Manager cannot override the safety envelope.
- **Validation tiers**: Deterministic validation (schema, rules) runs always; LLM-based semantic validation is optional (skipped when confidence exceeds threshold).

### Other Key Directories

- `spec/` — Normative specification (RFC 2119 language)
- `docs/` — Protocol documentation for each layer
- `examples/` — 12 runnable examples progressing A0→A4
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
| New validation rules (R1-R26+) | SKILL.md Phase 4 checklist |
| Changed delegation loop behavior | SKILL.md delegation loop section + Step 7d |
| New debug/observability features | SKILL.md relevant sections |

**Failure to sync causes cascading bugs**: generated workflows silently fail because they use outdated config patterns (e.g. `shell.execute` in `tools_allowed` when it's forbidden, `dynamic_tools.enabled: false` when tool creation is needed).

## PyPI Build Rules (MANDATORY)

### All-Package Build Policy

**Every PyPI build MUST build ALL three packages together, in order:**

1. `awp-core` (`packages/awp-core/`)
2. `awp-runtime` (`packages/awp-runtime/`)
3. `awp-agents` (`reference/python/`) — the meta-package that bundles everything for end users

**Never build only one package.** Even if only one package changed, build all three. Version numbers must stay in sync across all three `pyproject.toml` files. When bumping versions, bump all three at once.

### Build + Smoke Test Sequence

After building, the following command sequence **MUST succeed before considering the build done**:

```bash
# 1. Build all three packages
cd packages/awp-core && rm -rf dist/ build/ && python -m build
cd packages/awp-runtime && rm -rf dist/ build/ && python -m build
cd reference/python && rm -rf dist/ build/ && python -m build

# 2. Install the meta-package (pulls in core + runtime + UI)
pip install awp-agents

# 3. Smoke test — this MUST launch without errors
awp studio
```

`pip install awp-agents && awp studio` is the **golden path**. If this command fails at any point (import errors, missing dependencies, missing frontend assets, version mismatches), the build is broken. Do not push or publish until it works.

### Version Sync Checklist

When bumping versions, update ALL of these in one commit:

| File | Field |
|------|-------|
| `packages/awp-core/pyproject.toml` | `version` |
| `packages/awp-runtime/pyproject.toml` | `version` + `awp-core>=` dependency |
| `packages/awp-ui/pyproject.toml` | `version` + `awp-core>=` and `awp-runtime>=` in `[project.optional-dependencies]` |
| `reference/python/pyproject.toml` | `version` (awp-agents meta-package) |

## Code Style

- Python 3.10+ with modern syntax (`X | Y` unions, `match` where appropriate)
- Type annotations on all public functions
- `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Use `logging` module, never `print()`
- Pydantic or dataclasses for structured data
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

## Default Model & Provider Routing

- **Default model**: `nvidia/nemotron-3-super-120b-a12b:free` (free via OpenRouter)
- The UI uses a **free text input** for model selection — no dropdowns. Never add `<select>` dropdowns for model selection.
- Provider is auto-detected from the model string:

| Model string pattern | Routed to | Required API key |
|---|---|---|
| `provider/model-name` (e.g. `nvidia/nemotron-3-super-120b-a12b:free`) | **OpenRouter** | `OPENROUTER_API_KEY` |
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
