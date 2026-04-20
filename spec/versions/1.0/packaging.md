# Packaging

**AWP Specification v1.0.0 — Packaging**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](spec.md) · **Non-normative explainer**: [docs/packaging.md](../../../docs/packaging.md) · **Related normative artifacts**: [file-structure.md](file-structure.md) (layout that gets packaged), [layers/00-manifest.md](layers/00-manifest.md) (root document inside the package), [validation-rules.md](validation-rules.md) · **Distribution**: [docs/skill-system.md](../../../docs/skill-system.md) (ClawHub registry)

---

## 1. Overview

AWP defines a standard packaging format (`.awp.zip`) for distributing and exchanging workflows. The package is a ZIP archive containing the complete workflow directory with a `manifest.json` integrity file at the root.

---

## 2. Package Format

### 2.1 File Extension

AWP packages MUST use the `.awp.zip` file extension.

**Example:** `research-and-write-1.0.0.awp.zip`

The recommended naming convention is `{workflow-name}-{version}.awp.zip`.

### 2.2 Archive Format

- The package MUST be a standard ZIP archive (ZIP64 is permitted for large workflows).
- The archive MUST contain a single top-level directory matching the workflow name.
- All files within the archive MUST be relative to this top-level directory.

### 2.3 Archive Structure

```
research-and-write-1.0.0.awp.zip
└── research-and-write/
    ├── manifest.json                  # REQUIRED — Package manifest
    ├── workflow.awp.yaml              # REQUIRED — Workflow manifest
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

---

## 3. Package Manifest (`manifest.json`)

Every AWP package MUST include a `manifest.json` file at the root of the workflow directory within the archive.

### 3.1 Required Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `name` | string | REQUIRED | Workflow name. MUST match `workflow.name` in `workflow.awp.yaml`. |
| `version` | string | REQUIRED | Workflow version. MUST match `workflow.version` in `workflow.awp.yaml`. |
| `awp_version` | string | REQUIRED | AWP protocol version. MUST match the `awp` field in `workflow.awp.yaml`. |
| `created_at` | string | REQUIRED | ISO 8601 timestamp (UTC) when the package was created. |
| `checksum` | string | REQUIRED | SHA-256 hash of `workflow.awp.yaml`. |
| `files` | list | REQUIRED | List of all files in the package with individual checksums. |

### 3.2 File Entry Format

Each entry in the `files` list MUST have:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Relative path within the archive (from the workflow root). |
| `sha256` | string | SHA-256 hex digest of the file contents. |
| `size` | integer | File size in bytes. |

### 3.3 Example `manifest.json`

```json
{
  "name": "research-and-write",
  "version": "1.0.0",
  "awp_version": "1.0.0",
  "created_at": "2026-03-23T14:30:00.000Z",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "files": [
    {
      "path": "workflow.awp.yaml",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "size": 2048
    },
    {
      "path": "agents/research_analyst/agent.awp.yaml",
      "sha256": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "size": 1024
    },
    {
      "path": "agents/research_analyst/agent.py",
      "sha256": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
      "size": 512
    }
  ]
}
```

---

## 4. Checksums

### 4.1 Algorithm

All checksums MUST use SHA-256. The checksum value MUST be a lowercase hexadecimal string (64 characters).

### 4.2 Verification

When unpacking an AWP package, the runtime MUST:

1. Verify that `manifest.json` exists.
2. Verify the `checksum` field matches the SHA-256 of `workflow.awp.yaml`.
3. Verify that every file listed in `files` exists in the archive.
4. Verify that each file's SHA-256 matches its declared `sha256` value.
5. Verify that no extra files exist in the archive that are not listed in `files` (excluding `manifest.json` itself).

If any verification step fails, the runtime MUST reject the package and report which checks failed.

---

## 5. Excluded Content

The following files and directories MUST be excluded from AWP packages by default:

| Pattern | Reason |
|---------|--------|
| `workspace/` | Runtime-generated memory data. Workflow-specific and potentially large. |
| `runs/` | Runtime execution data. Not part of the workflow definition. |
| `__pycache__/` | Python bytecode cache. Platform-specific. |
| `.git/` | Version control metadata. Not part of the workflow definition. |
| `*.pyc` | Compiled Python bytecode. Platform-specific. |
| `.env` | Environment variables. MAY contain secrets. |
| `logs/` | Runtime log files. Not part of the workflow definition. |
| `data/state/` | Persisted state. Runtime-specific. |
| `data/output/` | Output artifacts. Generated at runtime. |
| `.DS_Store` | macOS filesystem metadata. |
| `node_modules/` | Node.js dependencies. |

Packaging tools SHOULD support a `.awpignore` file (similar to `.gitignore` syntax) for additional exclusion patterns.

### 5.1 `.awpignore`

If a `.awpignore` file exists in the workflow root, the packaging tool MUST apply its patterns in addition to the default exclusions. The format follows `.gitignore` syntax:

```
# Custom exclusions
data/raw/
*.tmp
*.log
secrets/
```

---

## 6. CLI Commands

AWP-conformant tooling SHOULD provide the following CLI commands for packaging:

### 6.1 `awp pack`

Creates an AWP package from a workflow directory.

```
awp pack [--output <path>] [<workflow-dir>]
```

| Flag | Description |
|------|-------------|
| `--output`, `-o` | Output path for the package. Default: `{name}-{version}.awp.zip` in the current directory. |
| `<workflow-dir>` | Path to the workflow directory. Default: current directory. |

**Behavior:**

1. Validate the workflow directory (run validation rules R1–R8 at minimum).
2. Exclude files matching default exclusion patterns and `.awpignore`.
3. Compute SHA-256 checksums for all included files.
4. Generate `manifest.json`.
5. Create the ZIP archive with the workflow directory as the single top-level entry.

### 6.2 `awp unpack`

Extracts an AWP package to a directory.

```
awp unpack [--output <path>] [--verify] <package>
```

| Flag | Description |
|------|-------------|
| `--output`, `-o` | Output directory. Default: current directory. |
| `--verify` | Verify checksums after extraction. Default: `true`. |
| `<package>` | Path to the `.awp.zip` package. |

**Behavior:**

1. Extract the ZIP archive.
2. If `--verify` is enabled (default), verify all checksums per Section 4.2.
3. Report verification results.

### 6.3 `awp verify`

Verifies an AWP package without extracting.

```
awp verify <package>
```

**Behavior:**

1. Open the ZIP archive without extracting.
2. Read `manifest.json`.
3. Verify all checksums per Section 4.2.
4. Run validation rules on `workflow.awp.yaml` and all `agent.awp.yaml` files.
5. Report results.

---

## 7. Package Metadata

Registries and package managers MAY use the following metadata derived from the manifest:

| Field | Source | Description |
|-------|--------|-------------|
| `name` | `manifest.json` | Workflow name for registry lookup. |
| `version` | `manifest.json` | Version for dependency resolution. |
| `awp_version` | `manifest.json` | Protocol compatibility. |
| `description` | `workflow.awp.yaml` | Human-readable description. |
| `author` | `workflow.awp.yaml` | Author or organization. |
| `license` | `workflow.awp.yaml` | SPDX license identifier. |
| `tags` | `workflow.awp.yaml` | Categorization tags. |
| `agent_count` | Derived | Number of agents in the workflow. |
| `conformance` | `workflow.awp.yaml` or derived | AWP conformance level (L0–L5). |

---

## 8. Processing Rules

1. An AWP package MUST contain exactly one top-level directory.
2. The top-level directory name SHOULD match the `workflow.name`.
3. `manifest.json` MUST be present directly inside the top-level directory.
4. `workflow.awp.yaml` MUST be present directly inside the top-level directory.
5. The `manifest.json` fields `name`, `version`, and `awp_version` MUST match the corresponding fields in `workflow.awp.yaml`.
6. All checksums MUST use SHA-256 and MUST be lowercase hexadecimal strings.
7. The runtime MUST reject packages that fail checksum verification.
8. The runtime MUST reject packages that contain files not listed in `manifest.json` (excluding `manifest.json` itself).
9. Packaging tools MUST apply default exclusions and `.awpignore` patterns.
10. Packaging tools MUST NOT include files matching default exclusion patterns even if not listed in `.awpignore`.
