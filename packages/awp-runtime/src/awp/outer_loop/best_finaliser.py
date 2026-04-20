"""BEST finaliser: auto-updates <task>/BEST/ based on lowest `compute_run_loss`."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from awp.outer_loop.loss import compute_run_loss


@dataclass
class FinaliseResult:
    """Result of a BEST finaliser operation."""

    updated: bool
    reason: str | None
    new_loss: float | None
    prior_loss: float | None
    skip_reason: str | None


def compute_and_update_best(
    task_dir: Path,
    new_run_dir: Path,
    force_override: bool = False,
) -> FinaliseResult:
    """Update <task>/BEST/ if new_run_dir has a lower loss.

    Args:
        task_dir: The task directory containing BEST/ subdirectory.
        new_run_dir: Path to the new run to potentially promote to BEST.
        force_override: If True, promote new_run_dir regardless of loss,
            and mark reason as "user_override".

    Returns:
        FinaliseResult with updated flag and metadata.
    """
    completion_path = new_run_dir / "run_completion.json"
    if not completion_path.exists():
        return FinaliseResult(
            updated=False,
            reason=None,
            new_loss=None,
            prior_loss=None,
            skip_reason="no_completion",
        )

    completion = json.loads(completion_path.read_text())
    status = completion.get("status")

    # Only allow auto-promotion of complete/partial runs, unless forced.
    if status not in ("complete", "partial") and not force_override:
        return FinaliseResult(
            updated=False,
            reason=None,
            new_loss=None,
            prior_loss=None,
            skip_reason="non_terminal",
        )

    # Compute the loss for the new run.
    new_loss_breakdown = compute_run_loss(new_run_dir)
    new_loss = new_loss_breakdown.total

    best_dir = task_dir / "BEST"
    manifest_path = best_dir / "manifest.json"

    # Check existing BEST manifest.
    prior_manifest: dict | None = None
    prior_loss: float | None = None
    if manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text())
        prior_loss = prior_manifest.get("loss")

        # Respect user_override unless forced.
        if prior_manifest.get("reason") == "user_override" and not force_override:
            return FinaliseResult(
                updated=False,
                reason=None,
                new_loss=new_loss,
                prior_loss=prior_loss,
                skip_reason="user_override",
            )

    # Auto-promotion: only update if new loss is strictly lower (unless forced).
    if (
        not force_override
        and prior_loss is not None
        and new_loss >= prior_loss
    ):
        return FinaliseResult(
            updated=False,
            reason=None,
            new_loss=new_loss,
            prior_loss=prior_loss,
            skip_reason="no_change",
        )

    # Promote new_run_dir to BEST.
    reason = "user_override" if force_override else "auto_loss"
    _rewrite_best(
        best_dir=best_dir,
        winner_run_dir=new_run_dir,
        winner_run_id=completion.get("run_id") or new_run_dir.name,
        loss=new_loss,
        loss_breakdown=new_loss_breakdown,
        reason=reason,
    )

    return FinaliseResult(
        updated=True,
        reason=reason,
        new_loss=new_loss,
        prior_loss=prior_loss,
        skip_reason=None,
    )


def _rewrite_best(
    best_dir: Path,
    winner_run_dir: Path,
    winner_run_id: str,
    loss: float,
    loss_breakdown,
    reason: str,
) -> None:
    """Rewrite the BEST directory with new winner artifacts.

    Args:
        best_dir: The BEST/ directory to rewrite.
        winner_run_dir: Source run directory containing FINAL/.
        winner_run_id: ID of the winner run.
        loss: Total loss score.
        loss_breakdown: LossBreakdown dataclass with component scores.
        reason: "auto_loss" or "user_override".
    """
    # Clean up old artifacts (but preserve manifest.json for now).
    if best_dir.exists():
        for p in best_dir.iterdir():
            if p.name == "manifest.json":
                continue
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    best_dir.mkdir(parents=True, exist_ok=True)

    # Copy artifacts from winner's FINAL/ directory.
    final_src = winner_run_dir / "FINAL"
    if final_src.exists() and final_src.is_dir():
        for src in final_src.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(final_src)
            dst = best_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

    # Write manifest with loss breakdown using human-friendly keys.
    manifest = {
        "winner_run_id": winner_run_id,
        "winner_source": str(winner_run_dir),
        "reason": reason,
        "loss": loss,
        "loss_breakdown": {
            "eval": loss_breakdown.eval_component,
            "critique": loss_breakdown.critique_component,
            "gate_reject": loss_breakdown.gate_component,
            "budget_burn": loss_breakdown.budget_component,
            "terminal": loss_breakdown.status_component,
            "total": loss_breakdown.total,
        },
        "raw_signals": loss_breakdown.raw_signals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (best_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
