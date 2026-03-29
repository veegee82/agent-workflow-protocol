"""Resolver for filesystem glob sources."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)


class GlobResolver:
    """Resolve ``kind='glob'`` sources using ``pathlib.Path.glob()``."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "glob"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        pattern = source.uri
        merge = source.params.get("merge", "directory")

        # Determine root and relative pattern
        has_glob_chars = any(c in pattern for c in ("*", "?", "["))
        abs_path = Path(pattern)

        if abs_path.is_absolute():
            if has_glob_chars:
                # Split absolute glob into root (non-glob prefix) + relative pattern
                parts = list(PurePosixPath(pattern).parts)
                root_parts: list[str] = []
                for part in parts:
                    if any(c in part for c in ("*", "?", "[")):
                        break
                    root_parts.append(part)
                root = Path(*root_parts) if root_parts else Path("/")
                rel_pattern = str(PurePosixPath(pattern).relative_to(root))
            else:
                # Exact absolute file path — use parent as root, name as pattern
                root = abs_path.parent
                rel_pattern = abs_path.name
        else:
            root = Path(source.params.get("root", ".")).resolve()
            rel_pattern = pattern

        logger.info("Globbing '%s' from root %s", rel_pattern, root)
        matches = sorted(root.glob(rel_pattern))
        paths = [str(p) for p in matches]

        if not paths:
            logger.warning("Glob pattern '%s' matched no files in %s", rel_pattern, root)
            return ResolverResult(
                data=[],
                metadata={
                    "source_kind": "glob", "root": str(root),
                    "pattern": pattern, "match_count": 0,
                },
            )

        # If merge="concat" and format="csv", concatenate all matched CSVs
        if merge == "concat" and source.format == "csv":
            data = self._concat_csv(matches)
            return ResolverResult(
                data=data,
                metadata={
                    "source_kind": "glob",
                    "root": str(root),
                    "pattern": pattern,
                    "match_count": len(paths),
                    "merge": merge,
                    "format": "csv",
                },
            )

        # Single file: return path string
        if len(paths) == 1:
            return ResolverResult(
                data=paths[0],
                metadata={
                    "source_kind": "glob",
                    "root": str(root),
                    "pattern": pattern,
                    "match_count": 1,
                },
            )

        # Multiple files: return list of path strings
        return ResolverResult(
            data=paths,
            metadata={
                "source_kind": "glob",
                "root": str(root),
                "pattern": pattern,
                "match_count": len(paths),
            },
        )

    @staticmethod
    def _concat_csv(paths: list[Path]) -> Any:
        """Concatenate CSV files into a single DataFrame."""
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas is required for merge='concat' with CSV files. "
                "Install with: pip install pandas"
            )

        frames: list[Any] = []
        for p in paths:
            if p.is_file() and p.suffix.lower() in (".csv", ".tsv"):
                sep = "\t" if p.suffix.lower() == ".tsv" else ","
                frames.append(pd.read_csv(p, sep=sep))
                logger.debug("Read %s for concat", p)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
