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
)

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
    ) -> None:
        self._seed = seed_run_dir
        self._factory = workflow_factory or default_workflow_factory
        self._iterations_root = iterations_root or (
            Path("/tmp/awp-experiments") / f"refine_{int(time.time())}"
        )
        self._model = model
        self._worker_model = worker_model

    # ------------------------------------------------------------------

    def run(self, *, iterations: int) -> RefinementResult:
        iterations = max(1, min(10, int(iterations)))
        session_id = _new_session_id()
        started_at = _utcnow()

        # R36 — gradient must be non-empty before we even enter the loop.
        gradient = extract_gradient(self._seed)
        if not gradient.is_non_empty():
            raise NothingToRefine(
                f"seed {self._seed} has no defects, rejections, or eval gaps"
            )

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

        for k in range(1, iterations + 1):
            prior_final = (
                self._seed / "FINAL" if k == 1 else outcomes[-1].run_dir / "FINAL"
            )

            workspace = self._iterations_root / f"iter_{k}"
            prepare_iteration_workspace(
                workspace_dir=workspace, prior_final_dir=prior_final
            )

            # Regenerate gradient from the prior iteration for k>1.
            current_gradient = (
                gradient if k == 1 else extract_gradient(outcomes[-1].run_dir)
            )
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
                model=self._model,
                worker_model=self._worker_model,
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
                    k=o.k, run_id=o.run_id, loss=o.loss, status=o.status
                )
                for o in outcomes
            ],
        )
        write_session_sidecar(seed_run_dir=self._seed, session=session)

        if best_iter > 0:
            winning = outcomes[best_iter - 1].run_dir
            write_best_pointer(
                seed_run_dir=self._seed,
                winning_run_dir=winning,
                session_id=session_id,
                best_loss=best_loss,
                seed_loss=seed_loss,
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
        rc = json.loads(
            (self._seed / "run_completion.json").read_text(encoding="utf-8")
        )
        budget_cfg = rc.get("budget") or {}
        observed_wall = float(
            budget_cfg.get("observed_wall_time")
            or rc.get("wall_time")
            or rc.get("wall_time_elapsed")
            or (rc.get("final_budget") or {}).get("wall_time_elapsed")
            or 0.0
        )
        seed_task = str(rc.get("task") or "")
        if not seed_task:
            raise ValueError(f"seed {self._seed} has no task recorded")

        budget = {
            "max_loops": int(
                budget_cfg.get("max_loops")
                or rc.get("max_loops")
                or (rc.get("final_budget") or {}).get("max_loops")
                or 20
            ),
            "max_total_workers": int(
                budget_cfg.get("max_total_workers")
                or (rc.get("final_budget") or {}).get("max_total_workers")
                or 20
            ),
            "max_total_tokens": int(
                budget_cfg.get("max_total_tokens")
                or (rc.get("final_budget") or {}).get("max_total_tokens")
                or 1_000_000
            ),
            "max_wall_time": int(
                budget_cfg.get("max_wall_time")
                or (rc.get("final_budget") or {}).get("max_wall_time")
                or 3600
            ),
            "max_depth": int(
                budget_cfg.get("max_depth")
                or (rc.get("final_budget") or {}).get("max_depth")
                or 4
            ),
            "max_tool_calls": int(
                budget_cfg.get("max_tool_calls")
                or (rc.get("final_budget") or {}).get("max_tool_calls")
                or 600
            ),
        }
        seed_loss = float(compute_run_loss(self._seed).total)
        return budget, observed_wall, seed_task, seed_loss


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
            return str(
                json.loads(rc.read_text(encoding="utf-8")).get("run_id")
                or run_dir.name
            )
        except json.JSONDecodeError:
            pass
    return run_dir.name


def _read_status(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if not rc.exists():
        return "unknown"
    try:
        return str(
            json.loads(rc.read_text(encoding="utf-8")).get("status", "unknown")
        )
    except json.JSONDecodeError:
        return "unknown"
