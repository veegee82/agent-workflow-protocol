"""Skill loader — loads external skills from files, directories, and ZIP archives.

Supports three input formats:
- Single Markdown file (.md)
- Directory with SKILL.md + optional references/ and examples/ subdirs
- ZIP archive (.zip or .skill) containing the same directory structure

All formats are normalized to SkillBundle dataclasses.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillBundle:
    """A loaded skill with its content and optional references."""

    name: str
    content: str
    references: dict[str, str] = field(default_factory=dict)


def load_skill(path: str | Path) -> SkillBundle:
    """Load a single skill from a file path, directory, or archive.

    Args:
        path: Path to a .md file, directory (with SKILL.md), or .zip/.skill archive.

    Returns:
        SkillBundle with name, content, and references.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If the format is not recognized or SKILL.md is missing.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Skill path does not exist: {p}")

    if p.is_file() and p.suffix in (".zip", ".skill"):
        return _load_from_archive(p)
    elif p.is_file() and p.suffix == ".md":
        return _load_from_file(p)
    elif p.is_dir():
        return _load_from_directory(p)
    else:
        raise ValueError(
            f"Unsupported skill format: {p}. "
            "Expected .md file, directory with SKILL.md, or .zip/.skill archive."
        )


def load_external_skills(paths: list[str | Path]) -> list[SkillBundle]:
    """Load multiple skills from a list of paths.

    Args:
        paths: List of paths to skill files, directories, or archives.

    Returns:
        List of SkillBundle objects.
    """
    bundles: list[SkillBundle] = []
    for path in paths:
        try:
            bundle = load_skill(path)
            bundles.append(bundle)
            logger.info("Loaded skill: %s (%d chars)", bundle.name, len(bundle.content))
        except Exception as exc:
            logger.error("Failed to load skill from %s: %s", path, exc)
            raise
    return bundles


def _load_from_file(p: Path) -> SkillBundle:
    """Load a skill from a single Markdown file."""
    content = p.read_text(encoding="utf-8")
    name = p.stem
    return SkillBundle(name=name, content=content)


def _load_from_directory(d: Path) -> SkillBundle:
    """Load a skill from a directory containing SKILL.md."""
    skill_md = d / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"Directory {d} does not contain SKILL.md")

    content = skill_md.read_text(encoding="utf-8")
    name = d.name
    references = _collect_references(d)

    # Append references to content
    full_content = content
    if references:
        full_content += "\n\n---\n\n## References\n\n"
        for ref_name, ref_content in sorted(references.items()):
            full_content += f"### {ref_name}\n\n{ref_content}\n\n"

    return SkillBundle(name=name, content=full_content, references=references)


def _load_from_archive(p: Path) -> SkillBundle:
    """Load a skill from a ZIP archive (.zip or .skill)."""
    if not zipfile.is_zipfile(p):
        raise ValueError(f"Not a valid ZIP archive: {p}")

    with tempfile.TemporaryDirectory(prefix="awp_skill_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(p, "r") as zf:
            zf.extractall(tmp_path)

        # Check if contents are nested in a single subdirectory
        entries = list(tmp_path.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            extract_dir = entries[0]
        else:
            extract_dir = tmp_path

        if not (extract_dir / "SKILL.md").exists():
            raise ValueError(f"Archive {p} does not contain SKILL.md")

        bundle = _load_from_directory(extract_dir)
        bundle.name = p.stem
        return bundle


def _collect_references(d: Path) -> dict[str, str]:
    """Collect reference and example files from subdirectories."""
    refs: dict[str, str] = {}

    for subdir_name in ("references", "examples"):
        subdir = d / subdir_name
        if not subdir.is_dir():
            continue
        for f in sorted(subdir.rglob("*")):
            if f.is_file():
                try:
                    content = f.read_text(encoding="utf-8")
                    rel = f.relative_to(d)
                    refs[str(rel)] = content
                except UnicodeDecodeError:
                    logger.debug("Skipping binary file: %s", f)

    return refs
