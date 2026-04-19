"""Workspace preparation for a refinement iteration.

Each iteration starts from a workspace seeded with the prior iteration's
``FINAL/`` tree — hard-linked where possible, falls back to copy on
cross-device or link-refusing filesystems. The seeded tree lives under
``<workspace>/input/`` so the manager's REFINEMENT CONTEXT prefix
(rendered in ``gradient.py``) can point at a stable path.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_iteration_workspace(
    *,
    workspace_dir: Path,
    prior_final_dir: Path,
) -> Path:
    """Create ``<workspace_dir>/input/`` containing the contents of
    ``prior_final_dir``. Returns the input directory path.

    Raises
    ------
    FileNotFoundError
        If ``prior_final_dir`` does not exist.
    FileExistsError
        If ``<workspace_dir>/input/`` already exists and is non-empty —
        the caller is responsible for cleanup to avoid accidental mixing.
    """
    if not prior_final_dir.exists():
        raise FileNotFoundError(f"prior_final_dir does not exist: {prior_final_dir}")

    input_dir = workspace_dir / "input"
    if input_dir.exists() and any(input_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty {input_dir}")

    workspace_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    link_mode = True
    for src in prior_final_dir.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(prior_final_dir)
        dst = input_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if link_mode:
            try:
                os.link(src, dst)
                continue
            except OSError as exc:
                logger.info(
                    "refinement.seed.hardlink_fallback reason=%s falling back to copy",
                    exc,
                )
                link_mode = False
        shutil.copy2(src, dst)

    return input_dir
