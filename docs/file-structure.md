# Directory Layout

This document defines the required and optional directory layout for an AWP workflow.

## Complete Directory Tree

```
{workflow-name}/
├── workflow.awp.yaml                    # REQUIRED -- Workflow manifest
├── agents/                              # REQUIRED -- Agent definitions
│   └── {agent_id}/                      # REQUIRED -- One directory per agent
│       ├── agent.awp.yaml               # REQUIRED -- Agent configuration
│       ├── agent.py                     # REQUIRED (Python ref impl) -- Agent class
│       └── workflow/                    # OPTIONAL -- Workflow artifacts
│           ├── instructions/            # OPTIONAL -- System prompt files
│           │   └── SYSTEM_PROMPT.md     # OPTIONAL -- Primary system prompt
│           ├── prompt/                  # OPTIONAL -- Additional prompt fragments
│           │   └── 00_INTRO.md          # OPTIONAL -- Prompt introduction
│           ├── output_schema/           # OPTIONAL -- Output JSON Schemas
│           │   └── output_schema.json   # OPTIONAL -- Primary output schema
│           ├── output_schema_desc/      # OPTIONAL -- Schema descriptions
│           │   └── output_schema_desc.json  # OPTIONAL -- Field descriptions
│           ├── preprocessor/            # OPTIONAL -- Data preprocessing
│           │   └── preprocessor.py      # OPTIONAL -- Preprocessor class
│           └── skills/                  # OPTIONAL -- Agent-specific skills
│               └── add_skills.md        # OPTIONAL -- Skill references
├── mcp/                                 # OPTIONAL -- Custom MCP tools
│   └── custom_tools.py                  # OPTIONAL -- Tool definitions
├── skills/                              # OPTIONAL -- Project-level skills
│   └── domain_knowledge/               # OPTIONAL -- Skill directories
│       └── SKILL.md                     # OPTIONAL -- Skill content
├── workspace/                           # OPTIONAL -- Memory (created at runtime)
│   ├── MEMORY.md                        # OPTIONAL -- Long-term memory
│   └── memory/                          # OPTIONAL -- Daily logs
│       └── YYYY-MM-DD.md               # OPTIONAL -- Daily log files
└── data/                                # OPTIONAL -- Input/output/state data
    ├── input/                           # OPTIONAL -- Input data files
    ├── output/                          # OPTIONAL -- Output data files
    └── state/                           # OPTIONAL -- Persisted state files
```

## Required Files and Directories

### `workflow.awp.yaml`

- **Required**
- **Location:** Root of the workflow directory.
- **Description:** The workflow [manifest](manifest.md). The runtime must reject a workflow directory that does not contain this file.

### `agents/` Directory

- **Required**
- **Location:** Root of the workflow directory.
- **Description:** Contains one subdirectory per agent declared in the orchestration graph.

### `agents/{agent_id}/` Directory

- **Required** for each agent in the graph.
- **Naming:** The directory name must match the `identity.id` field in the agent's `agent.awp.yaml`. See [R8](validation.md).

### `agents/{agent_id}/agent.awp.yaml`

- **Required**
- **Description:** The [agent configuration](agent.md) file.

### `agents/{agent_id}/agent.py`

- **Required** for the Python reference implementation.
- **Description:** Python module containing the agent class. Non-Python runtimes may use an alternative file.
- **Note:** The `runtime.class_name` field in `agent.awp.yaml` specifies which class to import.

## Optional Files and Directories

### `agents/{agent_id}/workflow/`

Workflow artifacts directory. Name is configurable via `runtime.strategy_folder` (default: `"workflow"`).

### `agents/{agent_id}/workflow/instructions/`

System prompt files. Primary file should be named `SYSTEM_PROMPT.md`. Loaded when `prompt.system` references a file path.

### `agents/{agent_id}/workflow/prompt/`

Additional prompt fragments. Files are loaded in alphabetical order. Convention: prefix with numbers for explicit ordering (e.g., `00_INTRO.md`, `01_CONTEXT.md`).

### `agents/{agent_id}/workflow/output_schema/`

JSON Schema files for output validation:
- `output_schema.json` -- Primary output contract schema.
- `tool_call.json` -- Schema for tool call output format (if applicable).

### `agents/{agent_id}/workflow/output_schema_desc/`

Human-readable descriptions for output schema fields. Used for LLM prompt construction:
- `output_schema_desc.json` -- Field descriptions for the output schema.
- `tool_call_desc.json` -- Field descriptions for tool call format.

### `agents/{agent_id}/workflow/preprocessor/`

Data preprocessing modules:
- `preprocessor.py` -- Preprocessor class.

### `agents/{agent_id}/workflow/skills/`

Agent-specific skill files loaded only for this agent:
- `add_skills.md` -- References to global skills.
- Any `.md` or `.skill` files -- Inline skill content.

### `mcp/`

Custom MCP tool definitions. See [Tools Reference](tools.md). When `capabilities.custom_tools.auto_discovery` is `true`, the runtime scans this directory for `@app.tool()` decorated functions.

### `skills/`

Project-level skills shared across all agents in the workflow. Loaded after foundation skills and before agent-specific skills. See [Tools Reference](tools.md).

### `workspace/`

Memory storage directory. Created by the runtime when memory is enabled. See [Memory Reference](memory.md).

- `MEMORY.md` -- Long-term memory (Tier 1).
- `memory/` -- Daily log directory (Tier 2), containing `YYYY-MM-DD.md` files.

### `data/`

Data directory for input files, output files, and persisted state:
- `input/` -- Input data files for the workflow.
- `output/` -- Output artifacts produced by the workflow.
- `state/` -- Persisted state files (when `state.persistence.enabled` is `true`).

## File Naming Conventions

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

## Path Resolution

All file paths in AWP configuration files are relative to the appropriate base directory:

- `prompt.system: "workflow/instructions/SYSTEM_PROMPT.md"` resolves relative to the agent directory.
- `output.contract: "workflow/output_schema/output_schema.json"` resolves relative to the agent directory.
- `state.persistence.path: "data/state"` resolves relative to the workflow root.

The runtime must resolve paths consistently and report an error if a referenced file does not exist.

## Excluded Files

These files and directories should not be included in workflow packages or version control:

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
| `data/output/` | Output artifacts (generated at runtime). |
| `.DS_Store` | macOS filesystem metadata. |
| `node_modules/` | Node.js dependencies. |

See [Packaging Reference](packaging.md) for details on packaging exclusions.
