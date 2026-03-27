# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agent Workflow Protocol (AWP) is an open standard for defining and orchestrating multi-agent workflows. It separates workflow definition (YAML) from implementation (Python), organized in 7 semantic layers (manifest, identity, capabilities, communication, memory, orchestration, observability) spanning an autonomy spectrum from A0 (prescribed DAG) to A4 (self-organizing recursive delegation).

## Development Commands

All commands run from `reference/python/`.

```bash
# Install
pip install -e reference/python/

# Lint and format
ruff check .
ruff format .

# Run all tests
pytest reference/python/tests/

# Run a single test file
pytest reference/python/tests/test_validator.py

# Run a specific test
pytest reference/python/tests/test_validator.py::test_function_name -v

# CLI commands (after install)
awp validate <path>              # Validate workflow (rules R1-R26)
awp compliance <path> --level A2 # Check autonomy level (A0-A4)
awp visualize <path> --format mermaid  # Render DAG
awp pack <path>                  # Archive as .awp.zip
awp run <path>                   # Execute workflow
```

E2E tests that call LLMs require an OpenRouter or OpenAI-compatible API key. Validation-only tests run without external keys.

## Architecture

### Two Orchestration Engines

- **DAG Engine** (`reference/python/src/awp/runtime/runner.py`): Topological execution for A0-A1 workflows. Agents run in dependency order with state sharing via `share_output`.
- **Delegation Loop Engine** (`reference/python/src/awp/runtime/delegation_loop_runner.py`): Manager-worker loop for A2-A4 workflows. Manager dispatches tasks to ephemeral workers with budget enforcement and validation gates.

### Core Source Layout (`reference/python/src/awp/`)

- `models/` — Pydantic models for all 7 layers (manifest, agent, orchestration, capabilities, communication, memory, security, observability)
- `parser/` — Parses `workflow.awp.yaml` and `agent.awp.yaml` into Pydantic models, resolves imports
- `validator/` — Rule engine (R1-R26) covering naming, graph structure, confidence, tool namespaces, budgets. Key file: `rules.py`
- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv)
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

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

## Code Style

- Python 3.10+ with modern syntax (`X | Y` unions, `match` where appropriate)
- Type annotations on all public functions
- `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Use `logging` module, never `print()`
- Pydantic or dataclasses for structured data
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
