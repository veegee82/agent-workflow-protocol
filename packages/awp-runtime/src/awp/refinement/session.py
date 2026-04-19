"""RefinementSession model + sidecar + BEST pointer writers.

Each refinement session produces exactly one sidecar file under
``<seed>/refinement_sessions/<session_id>.json`` and at most one update
to ``<seed>/BEST/`` — the latter only if the session's best loss is
strictly lower than the incumbent ``BEST/manifest.json.best_loss`` (or
if ``BEST/`` does not yet exist).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RefinementIteration:
    k: int
    run_id: str
    loss: float
    status: str


@dataclass
class RefinementSession:
    session_id: str
    seed_run_id: str
    started_at: str
    completed_at: str
    stop_reason: str
    best_iter: int
    iterations: list[RefinementIteration] = field(default_factory=list)


def write_session_sidecar(*, seed_run_dir: Path, session: RefinementSession) -> Path:
    sessions_dir = seed_run_dir / "refinement_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session.session_id}.json"
    payload = asdict(session)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_best_pointer(
    *,
    seed_run_dir: Path,
    winning_run_dir: Path,
    session_id: str,
    best_loss: float,
    seed_loss: float,
) -> Path | None:
    """Update ``<seed>/BEST/`` if and only if ``best_loss`` is strictly
    lower than the incumbent.

    Returns the ``BEST/`` path if it was written, otherwise ``None``.
    """
    best_dir = seed_run_dir / "BEST"
    manifest_path = best_dir / "manifest.json"
    if manifest_path.exists():
        try:
            incumbent = json.loads(manifest_path.read_text(encoding="utf-8"))
            if float(incumbent.get("best_loss", float("inf"))) <= best_loss:
                logger.info(
                    "refinement.best.no_overwrite current=%.4f proposed=%.4f",
                    incumbent["best_loss"],
                    best_loss,
                )
                return None
        except (json.JSONDecodeError, OSError):
            logger.warning("refinement.best.manifest_unreadable — overwriting")

    winning_final = winning_run_dir / "FINAL"
    if not winning_final.exists():
        raise FileNotFoundError(f"winning run has no FINAL/: {winning_run_dir}")

    if best_dir.exists():
        shutil.rmtree(best_dir)
    best_dir.mkdir(parents=True)

    link_mode = True
    for src in winning_final.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(winning_final)
        dst = best_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if link_mode:
            try:
                os.link(src, dst)
                continue
            except OSError:
                link_mode = False
        shutil.copy2(src, dst)

    manifest = {
        "best_run_id": _read_run_id(winning_run_dir),
        "best_loss": best_loss,
        "seed_loss": seed_loss,
        "session_id": session_id,
        "winning_run_dir": str(winning_run_dir),
    }
    (best_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return best_dir


def _read_run_id(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            data = json.loads(rc.read_text(encoding="utf-8"))
            return str(data.get("run_id") or run_dir.name)
        except json.JSONDecodeError:
            pass
    return run_dir.name
