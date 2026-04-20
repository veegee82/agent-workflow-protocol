"""Continuation bundle loader."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class ContinuationInputError(Exception):
    """Raised when a continuation input cannot be resolved on disk."""


@dataclass
class BundleEntry:
    """One primary file loaded into memory."""
    source_task: str
    relative_path: str           # relative to the source task dir
    content_text: str            # UTF-8 decoded content


@dataclass
class ReferencePointer:
    """One reference path — Manager may fetch via fs.read if needed."""
    source_task: str
    relative_path: str
    size_bytes: int
    summary_head: str            # first 200 chars


@dataclass
class ContinuationBundle:
    primary_materials: list[BundleEntry] = field(default_factory=list)
    reference_paths: list[ReferencePointer] = field(default_factory=list)
    user_feedback: str = ""


def load_continuation_bundle(
    task_dir: Path, experiment_dir: Path
) -> ContinuationBundle:
    """Read `task.json`, resolve inputs, build a ContinuationBundle.

    Raises ContinuationInputError on: wrong mode, missing from_task,
    from_task without BEST, explicit path outside source task dir.
    """
    task_json = task_dir / "task.json"
    if not task_json.exists():
        raise ContinuationInputError(f"task.json not found at {task_json}")
    task = json.loads(task_json.read_text(encoding="utf-8"))
    if task.get("mode") != "continuation":
        raise ContinuationInputError(
            f"task {task.get('task_id')} is not a continuation"
        )
    bundle = ContinuationBundle(user_feedback=task.get("user_feedback", ""))

    for entry in task.get("inputs", []):
        src_task_id = entry["from_task"]
        role = entry["role"]
        src_dir = experiment_dir / "tasks" / src_task_id
        if not src_dir.exists():
            raise ContinuationInputError(
                f"from_task not found: {src_task_id}"
            )
        src_best = src_dir / "BEST"
        if not src_best.exists():
            raise ContinuationInputError(
                f"from_task {src_task_id} has no BEST/ — run it to completion first"
            )

        # Resolve paths: either whole BEST/ (bundle shorthand) or explicit paths
        if entry.get("bundle"):
            # Enumerate files under BEST/, excluding manifest.json
            file_list = [
                p for p in src_best.rglob("*")
                if p.is_file() and p.name != "manifest.json"
            ]
            rel_paths = [str(p.relative_to(src_dir)) for p in file_list]
        else:
            rel_paths = list(entry.get("paths", []))

        for rel in rel_paths:
            # Safety: reject traversal
            if ".." in rel.split("/") or rel.startswith("/"):
                raise ContinuationInputError(
                    f"path escapes source task: {rel!r}"
                )
            abs_path = src_dir / rel
            if not abs_path.exists() or not abs_path.is_file():
                raise ContinuationInputError(
                    f"referenced file not found: {src_task_id}/{rel}"
                )
            if role == "primary":
                bundle.primary_materials.append(
                    BundleEntry(
                        source_task=src_task_id,
                        relative_path=rel[len("BEST/"):] if rel.startswith("BEST/") else rel,
                        content_text=abs_path.read_text(encoding="utf-8"),
                    )
                )
            elif role == "reference":
                head = ""
                try:
                    head = abs_path.read_text(encoding="utf-8")[:200]
                except UnicodeDecodeError:
                    head = "<binary>"
                bundle.reference_paths.append(
                    ReferencePointer(
                        source_task=src_task_id,
                        relative_path=rel,
                        size_bytes=abs_path.stat().st_size,
                        summary_head=head,
                    )
                )
            else:
                raise ContinuationInputError(
                    f"unknown role {role!r} for input from {src_task_id}"
                )

    return bundle
