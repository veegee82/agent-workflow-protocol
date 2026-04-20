"""RefinementLoop — orchestrator for iterative deliverable refinement.

The loop is a thin driver around ``AgentWorkflow``:

1. Read prior run → build ``RefinementGradient``.
2. Enforce R36 — non-empty gradient required.
3. Prepare workspace (hard-link prior ``FINAL/`` as ``input/``).
4. Persist ``gradient_input.json`` (R36 audit trail).
5. Invoke the workflow factory (default: wraps AgentWorkflow).
6. Compute loss via ``compute_run_loss``.
7. Apply stop-condition state machine.
8. Write session sidecar + BEST/ pointer.

The workflow factory is injected for testability — production uses
``default_workflow_factory`` which wraps AgentWorkflow.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from awp.outer_loop.loss import compute_run_loss
from awp.refinement.budget import budget_for_iteration
from awp.refinement.gradient import (
    extract_gradient,
    render_refinement_prefix,
)
from awp.refinement.seed import prepare_iteration_workspace
from awp.refinement.session import (
    RefinementIteration,
    RefinementSession,
    write_best_pointer,
    write_session_sidecar,
    write_session_sidecar_at,
)
from awp.refinement.tiers import TierLabel, TierPlan

logger = logging.getLogger(__name__)

# (run_id, run_dir)
WorkflowFactory = Callable[..., tuple[str, Path]]


class NothingToRefine(RuntimeError):
    """R36: empty gradient — refinement aborted before iteration 1."""


@dataclass
class IterationOutcome:
    k: int
    run_id: str
    run_dir: Path
    loss: float
    status: str
    parent_run_id: str
    # Tier metadata (spec 2026-04-20 §8, §11). All optional for
    # backward-compat with readers that pre-date the tiering feature.
    # ``tier`` stays ``None`` on the legacy (single-model) path; the
    # model fields carry the values that were actually passed to the
    # workflow factory for this iteration regardless of path.
    tier: TierLabel | None = None
    model_manager: str | None = None
    model_worker: str | None = None


@dataclass
class RefinementResult:
    session_id: str
    seed_run_id: str
    seed_loss: float
    best_iter: int  # 0 = seed wins
    best_loss: float
    stop_reason: str
    iterations: list[IterationOutcome] = field(default_factory=list)


_PLATEAU_EPS = 0.01
_PLATEAU_REQUIRED = 2
_REGRESSION_REQUIRED = 2
_WALL_TIME_FACTOR = 2.0


class RefinementLoop:
    """Stateful driver for a refinement session against a single seed run."""

    def __init__(
        self,
        *,
        seed_run_dir: Path,
        workflow_factory: WorkflowFactory | None = None,
        iterations_root: Path | None = None,
        model: str | None = None,
        worker_model: str | None = None,
        tier_plan: TierPlan | None = None,
        session_sidecar_dir: Path | None = None,
    ) -> None:
        self._seed = seed_run_dir
        self._factory = workflow_factory or default_workflow_factory
        self._iterations_root = iterations_root or (
            Path("/tmp/awp-experiments") / f"refine_{int(time.time())}"
        )
        self._model = model
        self._worker_model = worker_model
        self._tier_plan = tier_plan
        self._session_sidecar_dir = session_sidecar_dir

    # ------------------------------------------------------------------

    def run(self, *, iterations: int) -> RefinementResult:
        iterations = max(1, min(10, int(iterations)))
        session_id = _new_session_id()
        started_at = _utcnow()

        # R36 — gradient must be non-empty before we even enter the loop.
        gradient = extract_gradient(self._seed)
        if not gradient.is_non_empty():
            raise NothingToRefine(f"seed {self._seed} has no defects, rejections, or eval gaps")

        seed_budget, seed_wall_time, seed_task, seed_loss = self._read_seed_context()
        self._iterations_root.mkdir(parents=True, exist_ok=True)

        outcomes: list[IterationOutcome] = []
        last_loss: float | None = None
        regression_streak = 0
        plateau_streak = 0
        best_iter = 0
        best_loss = seed_loss
        cumulative_wall = 0.0
        wall_cap = seed_wall_time * _WALL_TIME_FACTOR if seed_wall_time else float("inf")
        parent_run_id = _safe_run_id(self._seed)
        stop_reason = "max_iterations"
        loop_error: str | None = None
        # Last known-good starting deliverable. Advances only when an
        # iteration produces a non-empty FINAL/. A ``partial`` iteration
        # that writes no deliverables (e.g. hit budget cap before the
        # file-writing step) MUST NOT break the chain — the next iteration
        # re-seeds from the last good baseline and tries again. This is
        # structurally correct for tiered refinement: tier=mid should get
        # a shot against the same seed even if tier=low produced nothing.
        # Regression / plateau / wall-time guards still bound wasted compute.
        last_good_final = self._seed / "FINAL"
        if not last_good_final.exists():
            # AgentWorkflow writes FINAL at workspace-level, not run-level.
            workspace_candidate = self._seed.parent.parent.parent / "output" / "FINAL"
            if workspace_candidate.exists():
                last_good_final = workspace_candidate

        # try/finally guarantees the session sidecar is written on every
        # exit path (normal completion, mid-iter exception, budget abort).
        # An iteration that crashes during workspace prep or mid-workflow
        # would otherwise leave the session invisible to downstream
        # consumers (UI, CLI, E2E assertions).
        try:
            for k in range(1, iterations + 1):
                if k == 1:
                    prior_run_dir = self._seed
                    prior_final = last_good_final
                else:
                    prior_run_dir = outcomes[-1].run_dir
                    # Ensure the prior iteration has a FINAL/ to seed from.
                    # The runtime's _write_canonical_final_output only fires
                    # when declared deliverables exist; refinement needs a
                    # starting deliverable unconditionally, so promote
                    # output/<run_id>/ into FINAL/ as a fallback.
                    _ensure_final_dir(prior_run_dir)
                    maybe_final = prior_run_dir / "FINAL"
                    if maybe_final.exists() and any(maybe_final.iterdir()):
                        # Prior iteration advanced the deliverable — adopt it.
                        last_good_final = maybe_final
                        prior_final = maybe_final
                    else:
                        # Prior iteration failed to produce fresh output
                        # (typical for partial status with budget cap hit
                        # before the file-writing gate). Re-seed from the
                        # last known-good final so this iteration still
                        # has a legitimate baseline.
                        logger.info(
                            "refinement.reseed_from_last_good k=%d "
                            "prior_run_dir=%s fallback=%s",
                            k, prior_run_dir, last_good_final,
                        )
                        prior_final = last_good_final

                if not prior_final.exists() or not any(prior_final.iterdir()):
                    # Cannot seed this iteration — stop gracefully instead
                    # of raising. The sidecar still records what we got.
                    stop_reason = "no_prior_deliverable"
                    break

                workspace = self._iterations_root / f"iter_{k}"
                prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)

                # Regenerate gradient from the prior iteration for k>1.
                current_gradient = gradient if k == 1 else extract_gradient(prior_run_dir)
                # R36 re-check on each iteration — if an iteration somehow
                # produced a "perfect" run, stop here rather than burn budget.
                if not current_gradient.is_non_empty() and k > 1:
                    stop_reason = "empty_gradient_midloop"
                    break

                (workspace / "gradient_input.json").write_text(
                    json.dumps(current_gradient.model_dump(), indent=2),
                    encoding="utf-8",
                )

                prefix = render_refinement_prefix(current_gradient)

                iter_budget = budget_for_iteration(
                    seed_budget=seed_budget, observed_wall_time=seed_wall_time
                )

                tags = ["refinement", f"refine-iter-{k}"]

                # Branch on tier_plan presence. The ``tier_plan is None``
                # path MUST be byte-identical to pre-tiering behavior
                # (spec §8 stability contract): same factory args, same
                # model pair, no extra keys.
                if self._tier_plan is not None:
                    resolved = self._tier_plan.for_iteration(k, iterations)
                    iter_manager = resolved.manager_model
                    iter_worker = resolved.worker_model
                    iter_tier: TierLabel | None = resolved.tier
                else:
                    iter_manager = self._model
                    iter_worker = self._worker_model
                    iter_tier = None

                t0 = time.time()
                run_id, run_dir = self._factory(
                    task=seed_task,
                    inputs={"prior_deliverable_path": "input/"},
                    initial_state={
                        "refinement_gradient": current_gradient.model_dump(),
                        "refinement_iteration": k,
                        "seed_run_id": _safe_run_id(self._seed),
                    },
                    output_dir=workspace,
                    parent_run_id=parent_run_id,
                    tags=tags,
                    manager_prompt_prefix=prefix,
                    budget=iter_budget,
                    model=iter_manager,
                    worker_model=iter_worker,
                )
                cumulative_wall += time.time() - t0

                loss = float(compute_run_loss(run_dir).total)
                status = _read_status(run_dir)

                outcomes.append(
                    IterationOutcome(
                        k=k,
                        run_id=run_id,
                        run_dir=run_dir,
                        loss=loss,
                        status=status,
                        parent_run_id=parent_run_id,
                        tier=iter_tier,
                        model_manager=iter_manager,
                        model_worker=iter_worker,
                    )
                )

                if loss < best_loss:
                    best_loss = loss
                    best_iter = k

                if last_loss is None:
                    regression_streak = 0
                    plateau_streak = 0
                else:
                    if loss >= last_loss:
                        regression_streak += 1
                    else:
                        regression_streak = 0
                    if abs(loss - last_loss) < _PLATEAU_EPS:
                        plateau_streak += 1
                    else:
                        plateau_streak = 0

                last_loss = loss
                parent_run_id = run_id

                if regression_streak >= _REGRESSION_REQUIRED:
                    stop_reason = "regression"
                    break
                if plateau_streak >= _PLATEAU_REQUIRED:
                    stop_reason = "plateau"
                    break
                if cumulative_wall >= wall_cap and k < iterations:
                    stop_reason = "wall_time_exhausted"
                    break
        except Exception as exc:  # noqa: BLE001
            # Capture the error on the session so the sidecar records
            # why the loop terminated abnormally. The exception is
            # re-raised AFTER the finalize block below.
            loop_error = f"{type(exc).__name__}: {exc}"
            stop_reason = f"error:{type(exc).__name__}"
            logger.exception("refinement loop aborted by exception")
            raise
        finally:
            completed_at = _utcnow()
            session = RefinementSession(
                session_id=session_id,
                seed_run_id=_safe_run_id(self._seed),
                started_at=started_at,
                completed_at=completed_at,
                stop_reason=stop_reason,
                best_iter=best_iter,
                iterations=[
                    RefinementIteration(
                        k=o.k,
                        run_id=o.run_id,
                        loss=o.loss,
                        status=o.status,
                        tier=o.tier,
                        model_manager=o.model_manager,
                        model_worker=o.model_worker,
                    )
                    for o in outcomes
                ],
                tier_plan_used=(self._tier_plan is not None) or None,
            )
            try:
                if self._session_sidecar_dir is not None:
                    write_session_sidecar_at(target_dir=self._session_sidecar_dir, session=session)
                else:
                    write_session_sidecar(seed_run_dir=self._seed, session=session)
            except Exception as sidecar_exc:  # noqa: BLE001
                logger.warning(
                    "refinement.sidecar.write_failed seed=%s error=%s",
                    self._seed,
                    sidecar_exc,
                )

            if best_iter > 0:
                try:
                    write_best_pointer(
                        seed_run_dir=self._seed,
                        winning_run_dir=outcomes[best_iter - 1].run_dir,
                        session_id=session_id,
                        best_loss=best_loss,
                        seed_loss=seed_loss,
                    )
                except Exception as best_exc:  # noqa: BLE001
                    logger.warning(
                        "refinement.best.write_failed seed=%s error=%s",
                        self._seed,
                        best_exc,
                    )

        return RefinementResult(
            session_id=session_id,
            seed_run_id=_safe_run_id(self._seed),
            seed_loss=seed_loss,
            best_iter=best_iter,
            best_loss=best_loss,
            stop_reason=stop_reason,
            iterations=outcomes,
        )

    # ------------------------------------------------------------------

    def _read_seed_context(self) -> tuple[dict[str, Any], float, str, float]:
        """Extract seed budget + wall-time + task + loss from run_completion.json.

        Supports two shapes of ``run_completion.json``:

        * Real runtime — ``final_budget`` with nested dicts::

              {
                "loops":      {"used": N,      "max": M},
                "workers":    {"spawned": N,   "max": M},
                "tokens":     {"consumed": N,  "max": M},
                "tool_calls": {"used": N,      "max": M},
                "wall_time":  {"elapsed_s": N, "max_s": M}
              }

        * Synthetic (unit-test fixtures) — flat keys on ``rc`` or on
          ``rc.budget``: ``max_loops``, ``max_total_workers`` etc.
        """
        rc = json.loads((self._seed / "run_completion.json").read_text(encoding="utf-8"))
        budget_cfg = rc.get("budget") or {}
        final = rc.get("final_budget") or {}
        # ``final`` may be nested (real runtime) or flat (synthetic).
        final_loops = final.get("loops") if isinstance(final.get("loops"), dict) else {}
        final_workers = final.get("workers") if isinstance(final.get("workers"), dict) else {}
        final_tokens = final.get("tokens") if isinstance(final.get("tokens"), dict) else {}
        final_tool = final.get("tool_calls") if isinstance(final.get("tool_calls"), dict) else {}
        final_wall = final.get("wall_time") if isinstance(final.get("wall_time"), dict) else {}

        observed_wall = float(
            budget_cfg.get("observed_wall_time")
            or rc.get("wall_time")
            or rc.get("wall_time_elapsed")
            or final_wall.get("elapsed_s")
            or final.get("wall_time_elapsed")
            or 0.0
        )
        seed_task = str(rc.get("task") or "")
        if not seed_task:
            raise ValueError(f"seed {self._seed} has no task recorded")

        budget = {
            "max_loops": int(
                budget_cfg.get("max_loops")
                or rc.get("max_loops")
                or final_loops.get("max")
                or final.get("max_loops")
                or 20
            ),
            "max_total_workers": int(
                budget_cfg.get("max_total_workers")
                or final_workers.get("max")
                or final.get("max_total_workers")
                or 20
            ),
            "max_total_tokens": int(
                budget_cfg.get("max_total_tokens")
                or final_tokens.get("max")
                or final.get("max_total_tokens")
                or 1_000_000
            ),
            "max_wall_time": int(
                budget_cfg.get("max_wall_time")
                or final_wall.get("max_s")
                or final.get("max_wall_time")
                or 3600
            ),
            "max_depth": int(
                budget_cfg.get("max_depth")
                or final.get("max_depth")
                or 4
            ),
            "max_tool_calls": int(
                budget_cfg.get("max_tool_calls")
                or final_tool.get("max")
                or final.get("max_tool_calls")
                or 600
            ),
        }
        seed_loss = float(compute_run_loss(self._seed).total)
        return budget, observed_wall, seed_task, seed_loss


def _ensure_final_dir(run_dir: Path) -> None:
    """Guarantee ``<run_dir>/FINAL/`` exists and is non-empty.

    The runtime's ``_write_canonical_final_output`` only populates FINAL
    when declared deliverables exist. For a refinement iteration that
    produced *some* output (even imperfectly), we still need a starting
    deliverable for the next iteration to seed from. This helper walks
    up to the workflow workspace, finds ``output/<run_id>/``, and hard-
    links (copy fallback) its contents into ``<run_dir>/FINAL/``.

    No-op if FINAL already exists and is non-empty, or if no output is
    found. Never raises — errors are logged and swallowed so the caller
    can fall back to the explicit "no_prior_deliverable" stop reason.
    """
    final_dir = run_dir / "FINAL"
    if final_dir.exists() and any(final_dir.iterdir()):
        return

    # Walk up the parent chain looking for ``<workspace>/output/``.
    workspace = run_dir.parent
    for _ in range(6):  # generous upward probe; the path is at most 4-5 deep
        if (workspace / "output").exists():
            break
        if workspace == workspace.parent:
            return
        workspace = workspace.parent
    output_root = workspace / "output"
    if not output_root.exists():
        return

    candidates = [p for p in output_root.iterdir() if p.is_dir()]
    if not candidates:
        return
    # Prefer a subdir matching the run_dir name (run_id); else first.
    source = next((c for c in candidates if c.name == run_dir.name), candidates[0])

    import os

    try:
        final_dir.mkdir(parents=True, exist_ok=True)
        for item in source.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(source)
            dst = final_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(item, dst)
            except OSError:
                shutil.copy2(item, dst)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "refinement.ensure_final.failed run_dir=%s error=%s", run_dir, exc
        )


def default_workflow_factory(
    *,
    task: str,
    inputs: dict[str, Any],
    initial_state: dict[str, Any],
    output_dir: Path,
    parent_run_id: str,
    tags: list[str],
    manager_prompt_prefix: str,
    budget: dict[str, Any],
    model: str | None,
    worker_model: str | None,
) -> tuple[str, Path]:
    """Production factory — wraps AgentWorkflow."""
    # Lazy import to avoid dragging the runtime into import-time cycles.
    from awp.data.workflow import AgentWorkflow

    wf = AgentWorkflow(
        inputs=inputs or {},
        task=task,
        model=model or "openai/gpt-5-mini",
        worker_model=worker_model,
        output_dir=str(output_dir),
        parent_run_id=parent_run_id,
        tags=tags,
        manager_prompt_prefix=manager_prompt_prefix,
        max_loops=budget["max_loops"],
        max_total_workers=budget["max_total_workers"],
        max_total_tokens=budget["max_total_tokens"],
        max_wall_time=budget["max_wall_time"],
        max_tool_calls=budget["max_tool_calls"],
        max_depth=budget["max_depth"],
    )
    response = wf.run()
    meta = response.get("metadata", {}) if isinstance(response, dict) else {}
    run_id = str(meta.get("run_id") or uuid.uuid4())
    workspace = Path(meta.get("workspace") or output_dir)
    # Find run_completion.json somewhere under workspace.
    if (workspace / "run_completion.json").exists():
        return run_id, workspace
    for rc in workspace.rglob("run_completion.json"):
        return run_id, rc.parent
    return run_id, workspace


def _new_session_id() -> str:
    return "refine_" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_run_id(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            return str(json.loads(rc.read_text(encoding="utf-8")).get("run_id") or run_dir.name)
        except json.JSONDecodeError:
            pass
    return run_dir.name


def _read_status(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if not rc.exists():
        return "unknown"
    try:
        return str(json.loads(rc.read_text(encoding="utf-8")).get("status", "unknown"))
    except json.JSONDecodeError:
        return "unknown"
