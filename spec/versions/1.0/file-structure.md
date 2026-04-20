# File Structure

**AWP Specification v1.0.0 — File Structure**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](spec.md) · **Non-normative explainer**: [docs/file-structure.md](../../../docs/file-structure.md) · **Related normative artifacts**: [packaging.md](packaging.md) (how this layout packs into `.awp.zip`), [layers/00-manifest.md](layers/00-manifest.md) (the root document at the top of this layout) · **Runtime consumers**: [docs/runtime.md](../../../docs/runtime.md), [docs/observability.md](../../../docs/observability.md)

---

## 1. Overview

This document defines the required and optional directory layout for an AWP workflow. A conformant AWP workflow MUST follow this structure to ensure portability across runtimes and tooling.

---

## 2. Directory Layout

```
{workflow-name}/
├── workflow.awp.yaml                    # REQUIRED — Workflow manifest
├── agents/                              # REQUIRED — Agent definitions
│   └── {agent_id}/                      # REQUIRED — One directory per agent
│       ├── agent.awp.yaml               # REQUIRED — Agent configuration
│       ├── agent.py                     # REQUIRED (Python ref impl) — Agent class
│       └── workflow/                    # OPTIONAL — Workflow artifacts
│           ├── instructions/            # OPTIONAL — System prompt files
│           │   └── SYSTEM_PROMPT.md     # OPTIONAL — Primary system prompt
│           ├── prompt/                  # OPTIONAL — Additional prompt fragments
│           │   └── 00_INTRO.md          # OPTIONAL — Prompt introduction
│           ├── output_schema/           # OPTIONAL — Output JSON Schemas
│           │   └── output_schema.json   # OPTIONAL — Primary output schema
│           ├── output_schema_desc/      # OPTIONAL — Schema descriptions
│           │   └── output_schema_desc.json  # OPTIONAL — Field descriptions
│           ├── preprocessor/            # OPTIONAL — Data preprocessing
│           │   └── preprocessor.py      # OPTIONAL — Preprocessor class
│           └── skills/                  # OPTIONAL — Agent-specific skills
│               └── add_skills.md        # OPTIONAL — Skill references
├── mcp/                                 # OPTIONAL — Custom MCP tools
│   └── custom_tools.py                  # OPTIONAL — Tool definitions
├── skills/                              # OPTIONAL — Project-level skills
│   └── domain_knowledge/               # OPTIONAL — Skill directories
│       └── SKILL.md                     # OPTIONAL — Skill content
├── workspace/                           # OPTIONAL — Memory (created at runtime)
│   ├── MEMORY.md                        # OPTIONAL — Long-term memory
│   └── memory/                          # OPTIONAL — Daily logs
│       └── YYYY-MM-DD.md               # OPTIONAL — Daily log files
└── data/                                # OPTIONAL — Input/output/state data
    ├── input/                           # OPTIONAL — Input data files
    ├── output/                          # OPTIONAL — Output data files
    └── state/                           # OPTIONAL — Persisted state files
```

---

## 3. Required Files and Directories

### 3.1 `workflow.awp.yaml`

- **Status:** REQUIRED
- **Location:** Root of the workflow directory.
- **Description:** The workflow manifest. See [Layer 0: Manifest](layers/00-manifest.md).
- The runtime MUST reject a workflow directory that does not contain this file.

### 3.2 `agents/` Directory

- **Status:** REQUIRED
- **Location:** Root of the workflow directory.
- **Description:** Contains one subdirectory per agent declared in the orchestration graph.

### 3.3 `agents/{agent_id}/` Directory

- **Status:** REQUIRED for each agent in the graph.
- **Naming:** The directory name MUST match the `identity.id` field in the agent's `agent.awp.yaml`.
- **Validation:** The runtime MUST verify that a directory exists for every agent referenced in `orchestration.graph`.

### 3.4 `agents/{agent_id}/agent.awp.yaml`

- **Status:** REQUIRED
- **Description:** The agent configuration file. See [Layer 1: Agent Identity](layers/01-agent-identity.md).

### 3.5 `agents/{agent_id}/agent.py`

- **Status:** REQUIRED for the Python reference implementation.
- **Description:** The Python module containing the agent class. Non-Python runtimes MAY use an alternative file.
- **Note:** The file name is a convention of the Python reference implementation. The `runtime.class_name` field in `agent.awp.yaml` specifies which class to import.

---

## 4. Optional Files and Directories

### 4.1 `agents/{agent_id}/workflow/`

- **Status:** OPTIONAL
- **Description:** Contains workflow artifacts for the agent: prompts, schemas, preprocessors, and skills.
- **Convention:** The directory name is configurable via `runtime.strategy_folder` in `agent.awp.yaml`. Default: `"workflow"`.

### 4.2 `agents/{agent_id}/workflow/instructions/`

- **Status:** OPTIONAL
- **Description:** System prompt files. The primary system prompt SHOULD be named `SYSTEM_PROMPT.md`.
- **Loading:** Files in this directory are loaded when `prompt.system` references a file path.

### 4.3 `agents/{agent_id}/workflow/prompt/`

- **Status:** OPTIONAL
- **Description:** Additional prompt fragments. Files are loaded in alphabetical order.
- **Convention:** Prefix files with numbers for explicit ordering (e.g., `00_INTRO.md`, `01_CONTEXT.md`).

### 4.4 `agents/{agent_id}/workflow/output_schema/`

- **Status:** OPTIONAL
- **Description:** JSON Schema files for output validation.
- **Files:**
  - `output_schema.json` — The primary output contract schema.
  - `tool_call.json` — Schema for tool call output format (if applicable).

### 4.5 `agents/{agent_id}/workflow/output_schema_desc/`

- **Status:** OPTIONAL
- **Description:** Human-readable descriptions for output schema fields. Used for LLM prompt construction.
- **Files:**
  - `output_schema_desc.json` — Field descriptions for the output schema.
  - `tool_call_desc.json` — Field descriptions for tool call format.

### 4.6 `agents/{agent_id}/workflow/preprocessor/`

- **Status:** OPTIONAL
- **Description:** Data preprocessing modules. Preprocessors transform raw input data before it reaches the agent.
- **Files:**
  - `preprocessor.py` — Preprocessor class implementing `BasePreprocessor`.

### 4.7 `agents/{agent_id}/workflow/skills/`

- **Status:** OPTIONAL
- **Description:** Agent-specific skill files. These are loaded only for this agent.
- **Files:**
  - `add_skills.md` — References to global skills.
  - Any `.md` or `.skill` files — Inline skill content.

### 4.8 `mcp/`

- **Status:** OPTIONAL
- **Location:** Root of the workflow directory.
- **Description:** Custom MCP tool definitions. See [Layer 2: Capabilities](layers/02-capabilities.md), Section 4.
- **Discovery:** When `capabilities.custom_tools.auto_discovery` is `true`, the runtime MUST scan this directory for `@app.tool()` decorated functions.

### 4.9 `skills/`

- **Status:** OPTIONAL
- **Location:** Root of the workflow directory.
- **Description:** Project-level skills shared across all agents in the workflow.
- **Loading:** Loaded after foundation skills and before agent-specific skills.

### 4.10 `workspace/`

- **Status:** OPTIONAL (created at runtime)
- **Location:** Root of the workflow directory.
- **Description:** Memory storage directory. Created by the runtime when memory is enabled.
- **Contents:**
  - `MEMORY.md` — Long-term memory (Tier 1).
  - `memory/` — Daily log directory (Tier 2), containing `YYYY-MM-DD.md` files.

### 4.11 `data/`

- **Status:** OPTIONAL
- **Location:** Root of the workflow directory.
- **Description:** Data directory for input files, output files, and persisted state.
- **Subdirectories:**
  - `input/` — Input data files for the workflow.
  - `output/` — Output artifacts produced by the workflow.
  - `state/` — Persisted state files (when `state.persistence.enabled` is `true`).

---

## 5. File Naming Conventions

| Convention | Applies To | Example |
|------------|-----------|---------|
| kebab-case | Workflow directory name | `research-and-write/` |
| snake_case | Agent directory name | `research_analyst/` |
| UPPER_CASE.md | Memory and prompt files | `MEMORY.md`, `SYSTEM_PROMPT.md` |
| snake_case.py | Python modules | `agent.py`, `preprocessor.py` |
| snake_case.json | Schema files | `output_schema.json` |
| snake_case.yaml | Configuration files | `workflow.awp.yaml`, `agent.awp.yaml` |
| NN_name.md | Ordered prompt fragments | `00_INTRO.md`, `01_CONTEXT.md` |
| YYYY-MM-DD.md | Daily log files | `2026-03-23.md` |

---

## 6. Path Resolution

All file paths in AWP configuration files are relative to the workflow root directory unless otherwise specified.

- `prompt.system: "workflow/instructions/SYSTEM_PROMPT.md"` resolves to `{workflow-root}/agents/{agent_id}/workflow/instructions/SYSTEM_PROMPT.md` (relative to the agent directory).
- `output.contract: "workflow/output_schema/output_schema.json"` resolves to `{workflow-root}/agents/{agent_id}/workflow/output_schema/output_schema.json` (relative to the agent directory).
- `state.persistence.path: "data/state"` resolves to `{workflow-root}/data/state` (relative to workflow root).

The runtime MUST resolve paths consistently and MUST report an error if a referenced file does not exist.

---

## 7. Excluded Files

The following files and directories SHOULD NOT be included in workflow packages or version control:

| Pattern | Reason |
|---------|--------|
| `workspace/` | Runtime-generated memory data. |
| `runs/` | Runtime execution data. |
| `__pycache__/` | Python bytecode cache. |
| `.git/` | Version control metadata. |
| `*.pyc` | Compiled Python files. |
| `.env` | Environment variables (may contain secrets). |
| `logs/` | Runtime log files. |
| `data/state/` | Persisted state (runtime-specific). |
