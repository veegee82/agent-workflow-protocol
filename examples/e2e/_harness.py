"""Shared harness for S5 end-to-end experiments.

Responsibilities:
  * Load the OpenRouter key from the user's env file.
  * Register an experiment (session) + run row in the AWP UI SQLite store
    BEFORE the run starts, so the sidebar shows it live.
  * Run ``AgentWorkflow`` synchronously.
  * Update status ``running -> complete | partial | failed`` when done.
  * Link the run row to the session via ``session_runs``.

These helpers intentionally mirror the code path the FastAPI server uses
(`StoreService`) so the UI loads our E2E runs identically to UI-launched
ones. The only deviation is that we skip the HTTP layer and talk to the
store directly from a script.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_openrouter_key() -> str:
    """Load OPENROUTER_API_KEY from the known user env file or os.environ."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = Path("/home/shumway/projects/meta-agents/.env")
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "OPENROUTER_API_KEY":
                v = v.strip().strip('"').strip("'")
                os.environ["OPENROUTER_API_KEY"] = v
                return v
    raise RuntimeError("OPENROUTER_API_KEY not found in env or meta-agents/.env")


# Base dir for all S5 E2E experiments (matches the path required by CLAUDE.md).
E2E_BASE_DIR = Path("/tmp/awp-experiments")


def make_experiment_dir(slug: str) -> Path:
    E2E_BASE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = E2E_BASE_DIR / f"{slug}-{ts}-{uuid.uuid4().hex[:6]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Experiment DB registration (async StoreService wrapped in asyncio.run)
# ---------------------------------------------------------------------------


async def _register_async(
    session_id: str,
    run_id: str,
    title: str,
    task: str,
    model: str,
    base_dir: str,
    config: dict[str, Any],
) -> None:
    from server.services.store import StoreService

    store = StoreService()
    await store.init_db()
    try:
        await store.create_session(
            session_id,
            title=title,
            description=f"S5 E2E: {title}",
            hypothesis="",
            tags=["e2e", "s5"],
            base_dir=base_dir,
        )
        await store.save_run(
            run_id=run_id,
            task=task,
            model=model,
            config=config,
            status="running",
        )
        await store.add_run_to_session(session_id, run_id)
        # Flip session status to 'running' so the sidebar shows the live dot.
        await store.update_session(session_id, status="running")
    finally:
        await store.close()


async def _finalize_async(
    session_id: str,
    run_id: str,
    status: str,
    result: dict[str, Any] | None,
) -> None:
    from server.services.store import StoreService

    store = StoreService()
    await store.init_db()
    try:
        now = datetime.now(tz=timezone.utc).isoformat()
        await store.update_run(
            run_id, status=status, result=result or {}, completed_at=now
        )
        await store.update_session(session_id, status=status)
    finally:
        await store.close()


def register_experiment(
    title: str, task: str, model: str, base_dir: str, config: dict[str, Any]
) -> tuple[str, str]:
    session_id = uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex[:12]
    asyncio.run(
        _register_async(session_id, run_id, title, task, model, base_dir, config)
    )
    return session_id, run_id


def finalize_experiment(
    session_id: str, run_id: str, status: str, result: dict[str, Any] | None
) -> None:
    try:
        asyncio.run(_finalize_async(session_id, run_id, status, result))
    except Exception as exc:  # pragma: no cover - finalization is best-effort
        print(f"[harness] finalize_experiment failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Run wrapper
# ---------------------------------------------------------------------------


def run_e2e(
    *,
    slug: str,
    title: str,
    task: str,
    inputs: dict[str, Any] | None = None,
    model: str = "openai/gpt-5-nano",
    max_loops: int = 30,
    max_total_tokens: int = 3_000_000,
    max_wall_time: int = 3600,
    max_total_workers: int = 60,
    max_depth: int = 4,
    max_tool_calls: int = 2000,
    workflow_dir: Path | None = None,
    verifier=None,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one E2E scenario end-to-end and return a structured report."""
    load_openrouter_key()
    from awp.data import AgentWorkflow

    if workflow_dir is None:
        workflow_dir = make_experiment_dir(slug)
    workflow_dir = Path(workflow_dir).resolve()

    config = {
        "slug": slug,
        "title": title,
        "model": model,
        "max_loops": max_loops,
        "max_total_tokens": max_total_tokens,
        "max_wall_time": max_wall_time,
        "max_total_workers": max_total_workers,
        "max_depth": max_depth,
        "max_tool_calls": max_tool_calls,
        "workflow_dir": str(workflow_dir),
    }
    if extra_config:
        config.update(extra_config)

    session_id, run_id = register_experiment(
        title=title,
        task=task,
        model=model,
        base_dir=str(workflow_dir),
        config=config,
    )
    print(f"[e2e] slug={slug} session={session_id} run={run_id}")
    print(f"[e2e] workflow_dir={workflow_dir}")
    t0 = time.time()
    status = "failed"
    result: dict[str, Any] = {}
    err: str | None = None
    try:
        wf = AgentWorkflow(
            inputs=inputs or {},
            task=task,
            model=model,
            max_loops=max_loops,
            max_total_tokens=max_total_tokens,
            max_wall_time=max_wall_time,
            max_total_workers=max_total_workers,
            max_depth=max_depth,
            max_tool_calls=max_tool_calls,
            output_dir=str(workflow_dir),
            verbose=True,
        )
        result = wf.run()
        # AgentWorkflow returns a wrapper with `status` ("complete",
        # "partial", "budget_exceeded", "stall_detected", "failed",
        # "error"). For our purposes a "partial" caused by
        # `forced_convergence` is also acceptable as long as the
        # scenario verifier (which checks output content + B-block
        # evidence) confirms the run delivered the expected result.
        wf_status = str(result.get("status") or "unknown")
        loop_result = result.get("result") or {}
        term_reason = ""
        if isinstance(loop_result, dict):
            term_reason = str(loop_result.get("termination_reason") or "")
        # The wrapper status alone is not the final verdict -- the
        # verifier decides based on evidence on disk. Here we just
        # track the raw state; `status` is refined after verification.
        if wf_status == "complete":
            status = "complete"
        elif wf_status in ("partial", "budget_exceeded", "stall_detected"):
            status = "partial"
        else:
            status = "failed"
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()}"
        print(f"[e2e] EXCEPTION: {err}", file=sys.stderr)
        status = "failed"

    duration = time.time() - t0
    finalize_experiment(session_id, run_id, status, result)

    verification: dict[str, Any] = {}
    verify_ok = False
    if verifier is not None and status != "failed":
        try:
            verifier_payload = result.get("result") if isinstance(result, dict) else {}
            if not isinstance(verifier_payload, dict):
                verifier_payload = {}
            # Propagate top-level artifact paths into the inner dict
            # without creating a self-referencing cycle.
            if isinstance(result, dict):
                for k in ("output_files", "artifacts", "output_dir"):
                    if k in result and k not in verifier_payload:
                        verifier_payload[k] = result[k]
            verification = verifier(workflow_dir, verifier_payload) or {}
            verify_ok = bool(verification.get("ok"))
            # Promote partial -> complete if content verification passes:
            # we consider the E2E successful even when the delegation
            # loop terminated on a budget or convergence condition as
            # long as the artifacts on disk show the feature was used.
            if verify_ok and status == "partial":
                status = "complete"
        except Exception as exc:
            verification = {"ok": False, "error": str(exc)}

    report = {
        "slug": slug,
        "session_id": session_id,
        "run_id": run_id,
        "workflow_dir": str(workflow_dir),
        "status": status,
        "duration_s": round(duration, 1),
        "wf_status": wf_status,
        "termination_reason": term_reason,
        "verification": verification,
        "verify_ok": verify_ok,
        "error": err,
    }

    # Write report next to the experiment so subsequent runs can read it.
    try:
        (workflow_dir / "e2e_report.json").write_text(json.dumps(report, indent=2))
    except Exception:
        pass

    line = "PASS" if (status == "complete" and verify_ok) else "FAIL"
    print(f"[e2e] {line} slug={slug} status={status} verify={verify_ok}")
    print(f"[e2e] report: {json.dumps(report, indent=2)}")
    return report
