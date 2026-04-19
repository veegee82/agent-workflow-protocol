"""Suite runner for the outer loop (Phase A2).

The runner wires three things together:

* a :class:`~awp.outer_loop.suite.TaskSuiteSpec` (set of tasks),
* the :class:`~awp.outer_loop.ArtifactRegistry` (artifact versions), and
* the :class:`~awp.outer_loop.store.SqliteArtifactStore` (epochs + epoch_runs).

Each ``run_epoch`` call:

1. inserts an ``epochs`` row in the store,
2. iterates over the suite's tasks, executing each one through the
   workflow factory (default: :class:`awp.data.AgentWorkflow`) and
   computing the per-run loss with :func:`awp.outer_loop.loss.compute_run_loss`,
3. writes one ``epoch_runs`` row per task,
4. finalises the epoch with the mean loss.

Phase A2 invariant: ``child_artifacts == parent_artifacts``. The runner
performs no artifact updates — that responsibility belongs to Phase A3's
optimiser. The plumbing is in place so wiring the optimiser is purely
additive.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .artifacts import ArtifactRegistry
from .loss import LossBreakdown, LossWeights, compute_run_loss
from .store import SqliteArtifactStore
from .suite import SuiteTask, TaskSuiteSpec

logger = logging.getLogger(__name__)


# The 6 prompt artifacts the outer loop currently knows how to optimise.
# Kept as a module-level constant so CLI, runner, and tests all agree on
# the set. Mirrors :data:`awp.outer_loop.defaults.DEFAULTS` but is
# repeated here so ``runner`` does not need to import from ``defaults``
# at module load time.
ALL_OPTIMIZABLE_ARTIFACTS: tuple[str, ...] = (
    "worker_pitfalls",
    "manager_planning_preamble",
    "experiment_context_hint_template",
    "pattern_library",
    "tool_description_templates",
    "critique_rubric",
)


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaskRunResult:
    """Per-task outcome inside one epoch."""

    task_name: str
    run_id: str
    run_dir: str
    status: str
    loss: float
    breakdown: LossBreakdown
    error: str | None = None


@dataclass
class EpochResult:
    """Aggregate outcome of one suite epoch."""

    epoch_id: str
    suite_id: str
    suite_name: str
    epoch_num: int
    parent_artifacts: dict[str, int]
    child_artifacts: dict[str, int]
    task_results: list[TaskRunResult] = field(default_factory=list)
    mean_loss: float | None = None
    started_at: str = ""
    completed_at: str = ""

    def as_table_rows(self) -> list[dict[str, Any]]:
        """Compact per-task rows for terminal printing."""
        rows: list[dict[str, Any]] = []
        for tr in self.task_results:
            raw = tr.breakdown.raw_signals
            rows.append(
                {
                    "task": tr.task_name,
                    "status": tr.status,
                    "loss": round(tr.loss, 4),
                    "eval": round(float(raw.get("eval_score", 0.0)), 3),
                    "critique": round(float(raw.get("critique_score", 0.0)), 3),
                    "rejections": int(raw.get("gate_rejection_count", 0)),
                    "error": tr.error or "",
                }
            )
        return rows


# ---------------------------------------------------------------------------
# Workflow factory protocol
# ---------------------------------------------------------------------------
#
# A *workflow factory* is any callable that takes a :class:`SuiteTask` and
# an output directory and returns a ``(run_id, run_dir)`` pair. The default
# factory invokes :class:`awp.data.AgentWorkflow`. Tests inject stubs.


WorkflowFactory = Callable[[SuiteTask, Path], tuple[str, Path]]


def _default_workflow_factory(task: SuiteTask, output_dir: Path) -> tuple[str, Path]:
    """Run a task through ``AgentWorkflow`` and return ``(run_id, run_dir)``.

    ``run_dir`` is the directory containing ``run_completion.json`` /
    ``metrics.jsonl`` for this run — i.e. the artifact root the loss
    function reads from. We extract it from the ``AgentWorkflow`` response
    metadata; if the run dir cannot be located we fall back to
    ``output_dir`` so the loss function still finds *something* (and
    falls back to neutral signals).
    """
    # Lazy import — avoids dragging the runtime stack into ``awp.outer_loop``
    # at import time, and mirrors the ``cli.py`` lazy-import pattern.
    from awp.data.workflow import AgentWorkflow

    model = task.model or os.environ.get("LLM_MODEL") or "openai/gpt-5-mini"
    worker_model = task.worker_model or os.environ.get(
        "LLM_WORKER_MODEL", "deepseek/deepseek-chat-v3.1"
    )

    budget_kwargs: dict[str, Any] = {}
    if task.budget is not None:
        for f in (
            "max_loops",
            "max_total_workers",
            "max_total_tokens",
            "max_wall_time",
            "max_tool_calls",
            "max_depth",
        ):
            v = getattr(task.budget, f)
            if v is not None:
                budget_kwargs[f] = v

    wf = AgentWorkflow(
        inputs={},
        task=task.task,
        model=model,
        worker_model=worker_model,
        output_dir=str(output_dir),
        **budget_kwargs,
    )
    response = wf.run()

    metadata = response.get("metadata", {}) if isinstance(response, dict) else {}
    run_id = str(metadata.get("run_id") or uuid.uuid4())
    # AgentWorkflow stores per-run dirs at workspace/output/<run_id>; the
    # runner's debug tree (which holds metrics.jsonl + run_completion.json)
    # lives under workspace/runs/<run_id> or similar. We probe for both.
    workspace = Path(metadata.get("workspace") or output_dir)
    run_dir = _locate_run_dir(workspace, run_id, fallback=output_dir)
    return run_id, run_dir


def _locate_run_dir(workspace: Path, run_id: str, fallback: Path) -> Path:
    """Find the directory containing ``run_completion.json`` for ``run_id``."""
    candidates = [
        workspace / "runs" / run_id,
        workspace / "logs" / run_id,
        workspace / run_id,
        workspace,
    ]
    for c in candidates:
        if (c / "run_completion.json").exists():
            return c
    # Last resort: search shallowly under the workspace. Prefer a path
    # that contains the run_id; otherwise return the first match.
    if workspace.exists():
        first_match: Path | None = None
        for child in workspace.rglob("run_completion.json"):
            if run_id in str(child):
                return child.parent
            if first_match is None:
                first_match = child.parent
        if first_match is not None:
            return first_match
    return fallback


# ---------------------------------------------------------------------------
# SuiteRunner
# ---------------------------------------------------------------------------


class SuiteRunner:
    """Runs a :class:`TaskSuiteSpec` once per :meth:`run_epoch` call.

    Phase A2 scope:

    * Persists the suite definition (idempotent, name-keyed).
    * Inserts an ``epochs`` row at start, finalises it at end.
    * Computes per-task loss and the epoch mean.
    * Does *not* touch artifact versions (``child_artifacts == parent_artifacts``).
    """

    def __init__(
        self,
        registry: ArtifactRegistry,
        store: SqliteArtifactStore,
        *,
        workflow_factory: WorkflowFactory | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._workflow_factory = workflow_factory or _default_workflow_factory

    # ------------------------------------------------------------------
    # Suite registration
    # ------------------------------------------------------------------

    def register_suite(self, suite: TaskSuiteSpec) -> str:
        """Persist the suite (or reuse the existing row) and return its id."""
        existing = self._store.find_task_suite_by_name(suite.name)
        if existing:
            return str(existing["id"])
        suite_id = str(uuid.uuid4())
        self._store.upsert_task_suite(
            suite_id=suite_id,
            name=suite.name,
            tasks_json=json.dumps([t.model_dump(mode="json") for t in suite.tasks]),
            baseline_artifacts_json=json.dumps(suite.baseline_artifacts),
            created_at=_utcnow_iso(),
        )
        return suite_id

    # ------------------------------------------------------------------
    # Epoch execution
    # ------------------------------------------------------------------

    def run_epoch(
        self,
        suite: TaskSuiteSpec,
        epoch_num: int,
        parent_artifacts: dict[str, int],
        *,
        output_dir: Path | None = None,
    ) -> EpochResult:
        """Run all tasks in ``suite`` once and aggregate the losses.

        Parameters
        ----------
        suite
            Validated suite spec.
        epoch_num
            1-based epoch counter (purely informational; the runner does
            not enforce monotonicity).
        parent_artifacts
            Mapping of artifact name → version pinned for this epoch. In
            Phase A2 the registry is not switched between tasks; this map
            is recorded for traceability and copied unchanged into
            ``child_artifacts``.
        output_dir
            Where to place per-task workspaces. Defaults to
            ``~/.awp/outer_loop_runs/<suite>/epoch_<n>/``.
        """
        suite_id = self.register_suite(suite)
        epoch_id = str(uuid.uuid4())
        started_at = _utcnow_iso()

        out_root = output_dir or (
            Path.home() / ".awp" / "outer_loop_runs" / suite.name / f"epoch_{epoch_num}"
        )
        out_root.mkdir(parents=True, exist_ok=True)

        self._store.insert_epoch(
            epoch_id=epoch_id,
            suite_id=suite_id,
            epoch_num=epoch_num,
            started_at=started_at,
            parent_artifacts_json=json.dumps(parent_artifacts),
        )
        logger.info(
            "outer_loop.epoch.start suite=%s epoch=%d id=%s",
            suite.name,
            epoch_num,
            epoch_id,
        )

        results: list[TaskRunResult] = []
        for task in suite.tasks:
            result = self._run_one_task(task, out_root)
            self._store.insert_epoch_run(
                epoch_id=epoch_id,
                run_id=result.run_id,
                task_name=task.name,
                loss=result.loss,
                scores_json=json.dumps(result.breakdown.raw_signals),
            )
            results.append(result)
            logger.info(
                "outer_loop.task.complete task=%s loss=%.4f status=%s",
                task.name,
                result.loss,
                result.status,
            )

        losses = [r.loss for r in results if r.loss is not None]
        mean_loss = sum(losses) / len(losses) if losses else None
        completed_at = _utcnow_iso()
        # A2 invariant: no optimisation step ⇒ child == parent.
        child_artifacts = dict(parent_artifacts)
        self._store.finalize_epoch(
            epoch_id=epoch_id,
            completed_at=completed_at,
            mean_loss=mean_loss,
            child_artifacts_json=json.dumps(child_artifacts),
        )
        logger.info(
            "outer_loop.epoch.complete suite=%s epoch=%d mean_loss=%s",
            suite.name,
            epoch_num,
            f"{mean_loss:.4f}" if mean_loss is not None else "n/a",
        )

        return EpochResult(
            epoch_id=epoch_id,
            suite_id=suite_id,
            suite_name=suite.name,
            epoch_num=epoch_num,
            parent_artifacts=dict(parent_artifacts),
            child_artifacts=child_artifacts,
            task_results=results,
            mean_loss=mean_loss,
            started_at=started_at,
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_one_task(self, task: SuiteTask, out_root: Path) -> TaskRunResult:
        task_dir = out_root / task.name
        task_dir.mkdir(parents=True, exist_ok=True)
        weights = task.weights.to_loss_weights() if task.weights is not None else LossWeights()
        try:
            run_id, run_dir = self._workflow_factory(task, task_dir)
        except Exception as exc:  # noqa: BLE001
            logger.exception("outer_loop.task.factory_failed task=%s", task.name)
            # Build a synthetic "failed" loss so the epoch still aggregates.
            breakdown = compute_run_loss(task_dir, weights=weights)
            # Force status component to the failed penalty regardless of
            # what the artifacts say (there are likely none).
            forced = compute_run_loss(task_dir, weights=weights)
            return TaskRunResult(
                task_name=task.name,
                run_id="<no-run>",
                run_dir=str(task_dir),
                status="failed",
                loss=max(breakdown.total, forced.total, weights.status * 1.0),
                breakdown=breakdown,
                error=str(exc)[:500],
            )

        breakdown = compute_run_loss(run_dir, weights=weights)
        # Read status from run_completion.json directly so the table
        # column matches the artifact, not the inferred one.
        status = self._read_status(run_dir)
        return TaskRunResult(
            task_name=task.name,
            run_id=str(run_id),
            run_dir=str(run_dir),
            status=status,
            loss=breakdown.total,
            breakdown=breakdown,
        )

    # ------------------------------------------------------------------
    # Phase A3 — multi-epoch optimisation with TextGrad + rollback
    # ------------------------------------------------------------------

    def optimize(
        self,
        suite: TaskSuiteSpec,
        *,
        n_epochs: int,
        learning_rate: float = 0.5,
        optimizer: "TextGradOptimizer | None" = None,
        output_dir: Path | None = None,
        rollback_on_regression: bool = True,
    ) -> list[EpochResult]:
        """Run ``n_epochs`` of the suite, applying TextGrad between epochs.

        After each epoch:

        * If ``epoch_num > 1`` and ``rollback_on_regression`` is set and
          ``mean_loss`` increased vs. the previous epoch, the artifact
          bumped at the end of the *previous* epoch is rolled back, the
          learning rate is halved, and no new proposal is solicited.
        * Otherwise, if an ``optimizer`` is provided and more epochs are
          still to come, the optimiser proposes one update (or ``None``).
          A non-``None`` proposal is persisted via ``put_version`` +
          ``set_active`` and recorded in the epoch's
          ``child_artifacts_json``.

        The method returns the list of :class:`EpochResult`s in order. The
        current ``child_artifacts_json`` payload is structured (not just
        a ``name -> version`` map) — it also carries the update metadata
        or a rollback marker. The ``child_artifacts`` attribute on each
        returned :class:`EpochResult` still exposes the plain
        ``name -> version`` view for callers that only want the pin.
        """
        if n_epochs < 1:
            raise ValueError("n_epochs must be >= 1")

        # Pin starting point — every known artifact resolves to its
        # currently-active version (may be v0). Copied every epoch so a
        # rollback cleanly reverts in-memory state too.
        current_artifacts: dict[str, int] = {}
        for name in ALL_OPTIMIZABLE_ARTIFACTS:
            if name in suite.baseline_artifacts:
                current_artifacts[name] = int(suite.baseline_artifacts[name])
            else:
                current_artifacts[name] = self._registry.get_active(name).version

        results: list[EpochResult] = []
        mean_loss_prev: float | None = None
        last_update_info: dict[str, Any] | None = None
        lr = float(learning_rate)

        for epoch_num in range(1, n_epochs + 1):
            epoch_out = output_dir / f"epoch_{epoch_num}" if output_dir is not None else None

            epoch_result = self.run_epoch(
                suite,
                epoch_num=epoch_num,
                parent_artifacts=current_artifacts,
                output_dir=epoch_out,
            )
            results.append(epoch_result)

            # --- Regression check ------------------------------------------
            mean_loss_e = epoch_result.mean_loss
            is_first = epoch_num == 1
            regression = (
                not is_first
                and rollback_on_regression
                and mean_loss_prev is not None
                and mean_loss_e is not None
                and mean_loss_e > mean_loss_prev
                and last_update_info is not None
            )

            update_record: dict[str, Any] = {
                "artifacts": dict(current_artifacts),
                "events": [],
            }

            if regression:
                # Last update made things worse → roll it back, halve lr,
                # do NOT propose a new update this epoch.
                rolled = self._rollback_last_update(last_update_info)
                lr = lr / 2.0
                if rolled is not None:
                    # Revert in-memory pin too so the next epoch starts
                    # with the parent version.
                    current_artifacts[rolled["artifact"]] = int(rolled["parent_version"])
                    update_record["artifacts"] = dict(current_artifacts)
                    update_record["events"].append(
                        {
                            "type": "rollback",
                            "artifact": rolled["artifact"],
                            "from_version": rolled["new_version"],
                            "to_version": rolled["parent_version"],
                            "reason": "mean_loss_regression",
                            "mean_loss_prev": mean_loss_prev,
                            "mean_loss_current": mean_loss_e,
                            "new_learning_rate": lr,
                        }
                    )
                    logger.info(
                        "outer_loop.optimize.rollback artifact=%s from=v%d to=v%d new_lr=%.3f",
                        rolled["artifact"],
                        rolled["new_version"],
                        rolled["parent_version"],
                        lr,
                    )
                # A regression epoch consumes the previous update record.
                last_update_info = None
            else:
                # --- Propose a new update (if this is not the last epoch) --
                propose_next = optimizer is not None and epoch_num < n_epochs
                if propose_next:
                    try:
                        update = optimizer.propose_update(
                            epoch_result,
                            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
                            learning_rate=lr,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "outer_loop.optimize.propose_failed epoch=%d error=%s",
                            epoch_num,
                            str(exc)[:200],
                        )
                        update = None
                    if update is not None:
                        applied = self._apply_update(
                            update=update,
                            epoch_id=epoch_result.epoch_id,
                            parent_version=current_artifacts[update.artifact_name],
                        )
                        if applied is not None:
                            current_artifacts[update.artifact_name] = applied["new_version"]
                            update_record["artifacts"] = dict(current_artifacts)
                            update_record["events"].append(
                                {
                                    "type": "update",
                                    "artifact": update.artifact_name,
                                    "from_version": applied["parent_version"],
                                    "to_version": applied["new_version"],
                                    "rationale": update.rationale,
                                    "expected_loss_reduction": update.expected_loss_reduction,
                                    "confidence": update.confidence,
                                    "learning_rate": lr,
                                }
                            )
                            last_update_info = {
                                "artifact": update.artifact_name,
                                "from_version": applied["parent_version"],
                                "new_version": applied["new_version"],
                                "parent_version": applied["parent_version"],
                            }
                            logger.info(
                                "outer_loop.optimize.applied artifact=%s v%d->v%d lr=%.3f",
                                update.artifact_name,
                                applied["parent_version"],
                                applied["new_version"],
                                lr,
                            )
                        else:
                            # Persistence refused the update (unchanged or
                            # clamp failure); keep last_update_info as-is.
                            pass
                    else:
                        last_update_info = None
                else:
                    # No optimizer, or last epoch — no proposal window.
                    last_update_info = None

            # Persist the richer child_artifacts payload so inspect can
            # recover the full trajectory (update + rollback metadata).
            self._store.finalize_epoch(
                epoch_id=epoch_result.epoch_id,
                completed_at=epoch_result.completed_at,
                mean_loss=epoch_result.mean_loss,
                child_artifacts_json=json.dumps(update_record),
            )
            # Mirror the final name->version pin back into the dataclass
            # so the caller sees the post-update state.
            epoch_result.child_artifacts = dict(current_artifacts)

            mean_loss_prev = mean_loss_e

        return results

    # ------------------------------------------------------------------
    # Artifact persistence helpers (Phase A3)
    # ------------------------------------------------------------------

    def _apply_update(
        self,
        *,
        update: Any,
        epoch_id: str,
        parent_version: int,
    ) -> dict[str, Any] | None:
        """Persist ``update`` via :class:`ArtifactRegistry`.

        Returns ``None`` if persistence fails for any reason — in that
        case the caller continues without bumping the version pin.
        """
        try:
            new_version = self._registry.put_version(
                update.artifact_name,
                update.proposed_content,
                parent_version=parent_version,
                epoch_id=epoch_id,
            )
            self._registry.set_active(update.artifact_name, new_version.version)
        except RuntimeError as exc:
            # Surface read-only DB immediately — the caller should not be
            # running optimize() against a registry that can't write.
            raise RuntimeError(
                f"ArtifactRegistry rejected write for {update.artifact_name!r}: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "outer_loop.optimize.persist_failed artifact=%s error=%s",
                update.artifact_name,
                str(exc)[:200],
            )
            return None
        return {
            "parent_version": int(parent_version),
            "new_version": int(new_version.version),
        }

    def _rollback_last_update(self, last_update_info: dict[str, Any]) -> dict[str, Any] | None:
        """Roll back the last applied update's active pointer.

        Returns the same dict on success (for logging) or ``None`` if
        the registry refused.
        """
        try:
            self._registry.rollback_to(
                last_update_info["artifact"],
                int(last_update_info["parent_version"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "outer_loop.optimize.rollback_failed artifact=%s error=%s",
                last_update_info.get("artifact"),
                str(exc)[:200],
            )
            return None
        return last_update_info

    @staticmethod
    def _read_status(run_dir: Path) -> str:
        rc = run_dir / "run_completion.json"
        if not rc.exists():
            return "unknown"
        try:
            data = json.loads(rc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "unknown"
        return str(data.get("status", "unknown"))


__all__ = [
    "EpochResult",
    "SuiteRunner",
    "TaskRunResult",
    "WorkflowFactory",
]
