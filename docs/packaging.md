# Packaging & Distribution

AWP defines a standard packaging format (`.awp.zip`) for distributing and exchanging workflows, along with ClawHub integration for publishing to the open skill registry.

## The `.awp.zip` Format

### File Extension

AWP packages must use the `.awp.zip` file extension. Recommended naming: `{workflow-name}-{version}.awp.zip`.

Example: `research-and-write-1.0.0.awp.zip`

### Archive Structure

The package must be a standard ZIP archive containing a single top-level directory matching the workflow name:

```
research-and-write-1.0.0.awp.zip
└── research-and-write/
    ├── manifest.json                  # REQUIRED -- Package manifest
    ├── workflow.awp.yaml              # REQUIRED -- Workflow manifest
    ├── agents/
    │   ├── research_analyst/
    │   │   ├── agent.awp.yaml
    │   │   ├── agent.py
    │   │   └── workflow/
    │   │       └── ...
    │   └── report_writer/
    │       └── ...
    ├── mcp/                           # OPTIONAL
    ├── skills/                        # OPTIONAL
    └── data/                          # OPTIONAL (input data only)
```

### Package Manifest (`manifest.json`)

Every AWP package must include a `manifest.json` at the root of the workflow directory within the archive.

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Workflow name. Must match `workflow.name` in `workflow.awp.yaml`. |
| `version` | string | Workflow version. Must match `workflow.version`. |
| `awp_version` | string | AWP protocol version. Must match the `awp` field. |
| `created_at` | string | ISO 8601 timestamp (UTC) when the package was created. |
| `checksum` | string | SHA-256 hash of `workflow.awp.yaml`. |
| `files` | list | List of all files with individual checksums. |

#### File Entry Format

Each entry in the `files` list must have:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Relative path within the archive. |
| `sha256` | string | SHA-256 hex digest of the file contents. |
| `size` | integer | File size in bytes. |

#### Example

```json
{
  "name": "research-and-write",
  "version": "1.0.0",
  "awp_version": "1.0.0",
  "created_at": "2026-03-23T14:30:00.000Z",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb924...",
  "files": [
    {
      "path": "workflow.awp.yaml",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb924...",
      "size": 2048
    },
    {
      "path": "agents/research_analyst/agent.awp.yaml",
      "sha256": "a1b2c3d4e5f6...",
      "size": 1024
    },
    {
      "path": "agents/research_analyst/agent.py",
      "sha256": "b2c3d4e5f6a1...",
      "size": 512
    }
  ]
}
```

## Checksums

All checksums must use SHA-256 and be lowercase hexadecimal strings (64 characters).

### Verification Process

When unpacking an AWP package, the runtime must:

1. Verify that `manifest.json` exists.
2. Verify the `checksum` field matches the SHA-256 of `workflow.awp.yaml`.
3. Verify that every file listed in `files` exists in the archive.
4. Verify that each file's SHA-256 matches its declared `sha256` value.
5. Verify that no extra files exist that are not listed in `files` (excluding `manifest.json` itself).

If any step fails, the runtime must reject the package and report which checks failed.

## Excluded Content

These files and directories must be excluded from packages by default:

| Pattern | Reason |
|---------|--------|
| `workspace/` | Runtime-generated memory data. |
| `runs/` | Runtime execution data. |
| `__pycache__/` | Python bytecode cache. |
| `.git/` | Version control metadata. |
| `*.pyc` | Compiled Python bytecode. |
| `.env` | Environment variables (may contain secrets). |
| `logs/` | Runtime log files. |
| `data/state/` | Persisted state. |
| `data/output/` | Output artifacts. |
| `.DS_Store` | macOS metadata. |
| `node_modules/` | Node.js dependencies. |

### `.awpignore`

If a `.awpignore` file exists at the workflow root, the packaging tool must apply its patterns in addition to the defaults. The format follows `.gitignore` syntax:

```
# Custom exclusions
data/raw/
*.tmp
*.log
secrets/
```

## CLI Commands

### `awp pack`

Creates an AWP package from a workflow directory.

```bash
awp pack [--output <path>] [<workflow-dir>]
```

| Flag | Description |
|------|-------------|
| `--output`, `-o` | Output path. Default: `{name}-{version}.awp.zip` in current directory. |
| `<workflow-dir>` | Path to workflow directory. Default: current directory. |

Behavior:
1. Validate the workflow (run validation rules R1-R8 at minimum).
2. Exclude files matching default patterns and `.awpignore`.
3. Compute SHA-256 checksums for all included files.
4. Generate `manifest.json`.
5. Create the ZIP archive.

### `awp unpack`

Extracts an AWP package.

```bash
awp unpack [--output <path>] [--verify] <package>
```

| Flag | Description |
|------|-------------|
| `--output`, `-o` | Output directory. Default: current directory. |
| `--verify` | Verify checksums after extraction. Default: `true`. |
| `<package>` | Path to the `.awp.zip` package. |

### `awp verify`

Verifies a package without extracting.

```bash
awp verify <package>
```

Behavior:
1. Open the ZIP archive without extracting.
2. Read `manifest.json`.
3. Verify all checksums.
4. Run validation rules on `workflow.awp.yaml` and all `agent.awp.yaml` files.
5. Report results.

## ClawHub Publishing

ClawHub is the open skill registry for agent frameworks. AWP workflows can be published as ClawHub skills.

### Adding ClawHub Metadata

Add a `SKILL.md` at the workflow root with ClawHub-compatible YAML frontmatter:

```markdown
---
name: my-research-pipeline
description: >
  Three-agent research pipeline. AWP L1 Composable compliant.
version: 1.0.0
metadata:
  openclaw:
    requires:
      env:
        - LLM_API_KEY
        - LLM_MODEL
      bins: []
    primaryEnv: LLM_API_KEY
    homepage: https://github.com/user/my-research-pipeline
    tags:
      - awp
      - awp-workflow
      - research
      - multi-agent
---

# Research Pipeline

A three-agent AWP workflow for automated research.

## Usage

\```bash
awp run . --task "Research quantum computing trends"
\```
```

Alternatively, include ClawHub metadata directly in `workflow.awp.yaml`:

```yaml
workflow:
  name: my-research-pipeline
  version: "1.0.0"
  description: "Three-agent research pipeline"
  tags: ["awp", "research"]

  clawhub:
    slug: my-research-pipeline
    primary_env: LLM_API_KEY
    requires:
      env: [LLM_API_KEY, LLM_MODEL]
```

AWP runtimes should ignore the `clawhub` section.

### Publishing Commands

```bash
# Generate SKILL.md from workflow.awp.yaml
awp clawhub init <workflow-dir>

# Pack as ClawHub-ready directory
awp clawhub pack <workflow-dir> [-o <output-dir>]

# Publish directly
awp clawhub publish <workflow-dir>

# Or use the clawhub CLI directly
clawhub publish my-workflow/
```

### Installing Workflows

```bash
clawhub install my-research-pipeline
awp run my-research-pipeline/ --task "Research AI safety"
```

### Discovery Tags

AWP skills on ClawHub use these tag conventions:

| Tag | Meaning |
|-----|---------|
| `awp` | AWP-related skill |
| `awp-workflow` | A complete AWP workflow |
| `awp-extension` | A domain extension |
| `awp-builder` | The AWP build skill itself |
| `awp-l0` through `awp-l5` | Compliance level |
| `multi-agent` | Multi-agent workflow |

```bash
clawhub search awp                    # Find AWP workflows
clawhub explore --sort trending
```

## Package Metadata

Registries and package managers may derive these fields from the manifest:

| Field | Source | Description |
|-------|--------|-------------|
| `name` | `manifest.json` | Workflow name. |
| `version` | `manifest.json` | Version for dependency resolution. |
| `awp_version` | `manifest.json` | Protocol compatibility. |
| `description` | `workflow.awp.yaml` | Human-readable description. |
| `author` | `workflow.awp.yaml` | Author or organization. |
| `license` | `workflow.awp.yaml` | SPDX license identifier. |
| `tags` | `workflow.awp.yaml` | Categorization tags. |
| `agent_count` | Derived | Number of agents. |
| `conformance` | `workflow.awp.yaml` or derived | Compliance level (L0-L5). |
