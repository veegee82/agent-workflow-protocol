"""Smart context sharing for AWP worker agents.

Handles two problems:
1. **Context spillover**: Large worker results are written to files instead of
   being inlined into prompts.  Small results stay inline for speed.
2. **Input registry**: Automatically discovers workspace input files and
   generates metadata (size, type, schema preview for CSV/JSON) so workers
   know what data is available without the manager having to list every file.

The inline budget is auto-detected based on the number of context entries,
but can be overridden via ``context_budget`` in the workflow YAML.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TOTAL_CONTEXT_CHARS = 64_000  # ~16K tokens — fits comfortably in any model
DEFAULT_MIN_PER_ENTRY_CHARS = 4_000   # never shrink below this per entry
DEFAULT_PREVIEW_CHARS = 2_000         # preview length for spilled results


# ---------------------------------------------------------------------------
# Context Budget — auto-detect or configured
# ---------------------------------------------------------------------------


class ContextBudgetConfig:
    """Resolved context budget settings."""

    def __init__(
        self,
        total_chars: int = DEFAULT_TOTAL_CONTEXT_CHARS,
        min_per_entry: int = DEFAULT_MIN_PER_ENTRY_CHARS,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ):
        self.total_chars = total_chars
        self.min_per_entry = min_per_entry
        self.preview_chars = preview_chars

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> ContextBudgetConfig:
        """Build from optional YAML config dict.

        Accepts::

            context_budget:
              total_chars: 64000
              min_per_entry: 4000
              preview_chars: 2000
        """
        if not raw:
            return cls()
        return cls(
            total_chars=int(raw.get("total_chars", DEFAULT_TOTAL_CONTEXT_CHARS)),
            min_per_entry=int(raw.get("min_per_entry", DEFAULT_MIN_PER_ENTRY_CHARS)),
            preview_chars=int(raw.get("preview_chars", DEFAULT_PREVIEW_CHARS)),
        )

    def per_entry_budget(self, num_entries: int) -> int:
        """Auto-detect per-entry budget based on number of context entries."""
        if num_entries <= 0:
            return self.total_chars
        calculated = self.total_chars // num_entries
        return max(calculated, self.min_per_entry)


# ---------------------------------------------------------------------------
# Context Spillover — inline small, spill large to files
# ---------------------------------------------------------------------------


def prepare_context(
    state: dict[str, Any],
    workspace_dir: Path | None,
    budget: ContextBudgetConfig | None = None,
) -> str:
    """Format worker context with smart spillover for large results.

    Small results are inlined as JSON.  Large results are written to
    ``workspace_dir/context/<key>.json`` and a truncated preview with
    the file path is shown instead.

    Args:
        state: Accumulated state dict (keys = worker IDs or agent names).
        workspace_dir: Path to workspace dir for file spillover.  If None,
            results are always inlined (no spillover possible).
        budget: Context budget config.  Auto-detected if None.

    Returns:
        Formatted markdown string with context blocks.
    """
    if budget is None:
        budget = ContextBudgetConfig()

    # Filter relevant entries
    entries: dict[str, str] = {}
    for k, v in state.items():
        if k == "task" or k.startswith("_"):
            continue
        if isinstance(v, dict):
            entries[k] = json.dumps(v, indent=2, default=str)
        elif isinstance(v, str):
            entries[k] = v

    if not entries:
        return ""

    per_entry = budget.per_entry_budget(len(entries))

    # Prepare context dir for spillover
    context_dir: Path | None = None
    if workspace_dir is not None:
        context_dir = workspace_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    for key, serialized in entries.items():
        if len(serialized) <= per_entry:
            # Inline — fits within budget
            parts.append(f"### Context: {key}\n```json\n{serialized}\n```\n")
        elif context_dir is not None:
            # Spill to file
            spill_path = context_dir / f"{key}.json"
            spill_path.write_text(serialized, encoding="utf-8")
            preview = serialized[: budget.preview_chars]
            parts.append(
                f"### Context: {key}\n"
                f"```json\n{preview}\n```\n"
                f"> Result truncated ({len(serialized):,} chars). "
                f'Full data: `_workspace_dir + "/context/{key}.json"`\n'
            )
            logger.info(
                "Context spillover: %s → %s (%s chars)",
                key,
                spill_path,
                f"{len(serialized):,}",
            )
        else:
            # No workspace dir — inline with truncation as fallback
            preview = serialized[: budget.preview_chars]
            parts.append(
                f"### Context: {key}\n```json\n{preview}\n```\n"
                f"> Result truncated ({len(serialized):,} chars). "
                f"No workspace directory available for full data.\n"
            )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Input Registry — automatic file discovery with schema preview
# ---------------------------------------------------------------------------

# File extensions we recognize and can preview
_CSV_EXTENSIONS = {".csv", ".tsv"}
_JSON_EXTENSIONS = {".json", ".jsonl", ".geojson"}
_TABULAR_EXTENSIONS = {".parquet", ".feather", ".arrow"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg"}
_DATA_EXTENSIONS = (
    _CSV_EXTENSIONS | _JSON_EXTENSIONS | _TABULAR_EXTENSIONS |
    {".xlsx", ".xls", ".h5", ".hdf5", ".pkl", ".pickle", ".npy", ".npz",
     ".txt", ".md", ".xml", ".yaml", ".yml"}
)

MAX_PREVIEW_ROWS = 3
MAX_PREVIEW_COLS = 20


def _human_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"


def _preview_csv(path: Path, max_rows: int = MAX_PREVIEW_ROWS) -> str:
    """Generate schema preview for a CSV/TSV file."""
    try:
        delimiter = "\t" if path.suffix == ".tsv" else ","
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            # Read first lines to detect structure
            sample = f.read(32_768)  # 32KB sample

        reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
        rows = []
        for i, row in enumerate(reader):
            if i > max_rows:
                break
            rows.append(row)

        if not rows:
            return "  (empty file)"

        header = rows[0]
        num_cols = len(header)
        col_display = header[:MAX_PREVIEW_COLS]
        if num_cols > MAX_PREVIEW_COLS:
            col_display.append(f"... (+{num_cols - MAX_PREVIEW_COLS} more)")

        lines = [f"  Columns ({num_cols}): {', '.join(col_display)}"]
        if len(rows) > 1:
            lines.append(f"  Preview (first {min(len(rows) - 1, max_rows)} rows):")
            for row in rows[1 : max_rows + 1]:
                display = row[:MAX_PREVIEW_COLS]
                lines.append(f"    {display}")

        # Try to count total rows (for small files)
        newline_count = sample.count("\n")
        if len(sample) < 32_768:
            lines.append(f"  Total rows: ~{newline_count}")
        else:
            lines.append(f"  Rows in sample: {newline_count}+")

        return "\n".join(lines)
    except Exception as e:
        return f"  (preview error: {e})"


def _preview_json(path: Path) -> str:
    """Generate schema preview for a JSON file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(16_384)  # 16KB sample

        data = json.loads(sample if len(sample) < 16_384 else sample + "}")
        if isinstance(data, dict):
            keys = list(data.keys())[:20]
            lines = [f"  Type: object with {len(data)} keys"]
            lines.append(f"  Keys: {', '.join(keys)}")
            # Show type of each value
            for k in keys[:10]:
                v = data[k]
                if isinstance(v, list):
                    lines.append(f"    {k}: array[{len(v)}]")
                elif isinstance(v, dict):
                    lines.append(f"    {k}: object({len(v)} keys)")
                else:
                    lines.append(f"    {k}: {type(v).__name__}")
            return "\n".join(lines)
        elif isinstance(data, list):
            lines = [f"  Type: array with {len(data)} items"]
            if data and isinstance(data[0], dict):
                keys = list(data[0].keys())[:20]
                lines.append(f"  Item keys: {', '.join(keys)}")
            return "\n".join(lines)
        else:
            return f"  Type: {type(data).__name__}"
    except Exception:
        # Could be JSONL
        try:
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line:
                obj = json.loads(first_line)
                if isinstance(obj, dict):
                    return f"  Type: JSONL, keys per line: {', '.join(list(obj.keys())[:15])}"
            return "  Type: JSONL"
        except Exception as e:
            return f"  (preview error: {e})"


def build_input_registry(workspace_dir: Path) -> str:
    """Scan workspace/inputs/ and context/ for available files.

    Returns a formatted markdown block describing all available data files
    with size, type, and schema preview where possible.

    Args:
        workspace_dir: Path to the workspace directory (not inputs/).

    Returns:
        Markdown string ready to inject into worker prompts.  Empty string
        if no files found.
    """
    sections: list[str] = []

    # Scan inputs/
    inputs_dir = workspace_dir / "inputs"
    if inputs_dir.exists():
        input_files = _scan_directory(inputs_dir, "inputs")
        if input_files:
            sections.append("### Input Files\n" + input_files)

    # Scan context/ (spillover from previous workers)
    context_dir = workspace_dir / "context"
    if context_dir.exists():
        context_files = _scan_directory(context_dir, "context")
        if context_files:
            sections.append("### Previous Worker Results (full data)\n" + context_files)

    if not sections:
        return ""

    header = (
        "## Available Data Files\n\n"
        "The following files are available in the workspace. "
        "Use `_workspace_dir + \"/path\"` in `code.execute` to access them.\n\n"
    )
    return header + "\n\n".join(sections)


def _scan_directory(directory: Path, prefix: str) -> str:
    """Scan a directory and build file listing with previews."""
    lines: list[str] = []
    try:
        files = sorted(directory.iterdir())
    except OSError:
        return ""

    for f in files:
        if not f.is_file() or f.name.startswith("."):
            continue

        size = _human_size(f.stat().st_size)
        ext = f.suffix.lower()
        path_ref = f'`_workspace_dir + "/{prefix}/{f.name}"`'

        lines.append(f"- **{f.name}** ({size}) — {path_ref}")

        # Add schema preview for known types
        if ext in _CSV_EXTENSIONS:
            preview = _preview_csv(f)
            lines.append(preview)
        elif ext in _JSON_EXTENSIONS:
            preview = _preview_json(f)
            lines.append(preview)
        elif ext in _TABULAR_EXTENSIONS:
            lines.append(f"  Type: {ext[1:].upper()} (binary tabular format)")
            lines.append(f"  Read with: `pd.read_{ext[1:]}({path_ref})`")

    return "\n".join(lines)
