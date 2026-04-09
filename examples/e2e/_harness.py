"""Shared harness for S5 end-to-end experiments.

Responsibilities:
  * Load the OpenRouter key from the user's env file.
  * Register an experiment (session) + run row in the AWP UI SQLite store
    BEFORE the run starts, so the sidebar shows it live.
  * Run ``AgentWorkflow`` synchronously while a background watcher polls
    the delegation-loop run directory and persists events to the DB in
    real time — so the UI (``start.debug.py``) can display the run's
    graph, iterations, workers, tool calls, and budget updates live.
  * Update status ``running -> complete | partial | failed`` when done.
  * Link the run row to the session via ``session_runs``.
  * Support **tags** on every E2E experiment (mandatory ``e2e`` tag).

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
import threading
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


# Base dir for all E2E experiments (matches the path required by CLAUDE.md).
E2E_BASE_DIR = Path("/tmp/awp-experiments")

# Canonical DB path — must match what start_debug.py uses (local source tree).
# StoreService defaults to Path(__file__).parent.parent / "data" / awp_ui.db
# which resolves differently depending on whether server/ is imported from
# packages/awp-ui/server/ (local dev) or .venv/.../site-packages/server/
# (installed). We force the local dev path so the UI server and the E2E harness
# always share the same database.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_DB = _PROJECT_ROOT / "packages" / "awp-ui" / "server" / "data" / "awp_ui.db"


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
    tags: list[str] | None = None,
) -> None:
    from server.services.store import StoreService

    store = StoreService(db_path=_CANONICAL_DB)
    await store.init_db()
    try:
        # Ensure "e2e" tag is always present
        final_tags = list(tags or [])
        if "e2e" not in final_tags:
            final_tags.insert(0, "e2e")
        await store.create_session(
            session_id,
            title=title,
            description=f"E2E: {title}",
            hypothesis="",
            tags=final_tags,
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

    store = StoreService(db_path=_CANONICAL_DB)
    await store.init_db()
    try:
        now = datetime.now(tz=timezone.utc).isoformat()
        await store.update_run(
            run_id, status=status, result=result or {}, completed_at=now
        )
        await store.update_session(session_id, status=status)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# PID lock files — allow the UI server to distinguish live runs from orphans
# ---------------------------------------------------------------------------

_LOCK_DIR = _CANONICAL_DB.parent / "run_locks"


def _write_pid_lock(run_id: str) -> None:
    """Write a PID file so the UI server knows this run is still alive."""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    (_LOCK_DIR / f"{run_id}.pid").write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid_lock(run_id: str) -> None:
    """Remove the PID file after a run finishes."""
    try:
        (_LOCK_DIR / f"{run_id}.pid").unlink(missing_ok=True)
    except OSError:
        pass


def register_experiment(
    title: str,
    task: str,
    model: str,
    base_dir: str,
    config: dict[str, Any],
    tags: list[str] | None = None,
) -> tuple[str, str]:
    """Register an experiment in the DB. Returns (session_id, run_id).

    Parameters
    ----------
    tags : list[str], optional
        Tags for the experiment. ``"e2e"`` is always added automatically.
    """
    session_id = uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex[:12]
    asyncio.run(
        _register_async(
            session_id, run_id, title, task, model, base_dir, config, tags=tags,
        )
    )
    _write_pid_lock(run_id)
    return session_id, run_id


def finalize_experiment(
    session_id: str, run_id: str, status: str, result: dict[str, Any] | None
) -> None:
    try:
        asyncio.run(_finalize_async(session_id, run_id, status, result))
    except Exception as exc:  # pragma: no cover - finalization is best-effort
        print(f"[harness] finalize_experiment failed: {exc}", file=sys.stderr)
    finally:
        _remove_pid_lock(run_id)


# ---------------------------------------------------------------------------
# Live event watcher — persists delegation-loop progress to the DB
# ---------------------------------------------------------------------------

_event_seq_lock = threading.Lock()
_event_seq_counters: dict[str, int] = {}


def _next_event_seq(run_id: str) -> int:
    with _event_seq_lock:
        val = _event_seq_counters.get(run_id, 0) + 1
        _event_seq_counters[run_id] = val
        return val


class _E2ERunDirWatcher:
    """Polls the delegation-loop run directory and writes events to SQLite.

    This is a stripped-down version of ``runner_service._RunDirWatcher``
    that persists events directly to the DB (via ``StoreService``) instead
    of going through the in-process ``event_bus``.  This allows a separate
    UI server process (``start.debug.py``) to pick up the events via its
    ``GET /api/runs/{run_id}/events`` endpoint.
    """

    def __init__(self, run_id: str, workspace_dir: Path) -> None:
        self._run_id = run_id
        self._workspace_dir = workspace_dir
        self._seen_files: set[str] = set()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _find_run_dir(self) -> Path | None:
        runs_dir = self._workspace_dir / "workspace" / "runs"
        if not runs_dir.exists():
            return None
        candidates = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir()], key=lambda d: d.name
        )
        return candidates[-1] if candidates else None

    def _read_json(self, path: Path) -> dict[str, Any] | list[Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _persist_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Write a single event row to the DB."""
        seq = _next_event_seq(self._run_id)
        ts = datetime.now(tz=timezone.utc).isoformat()
        try:
            asyncio.run(self._persist_event_async(seq, event_type, data, ts))
        except Exception:
            pass  # best-effort

    async def _persist_event_async(
        self, seq: int, event_type: str, data: dict[str, Any], ts: str
    ) -> None:
        from server.services.store import StoreService

        store = StoreService(db_path=_CANONICAL_DB)
        await store.init_db()
        try:
            await store.save_event(self._run_id, seq, event_type, data, ts)
        finally:
            await store.close()

    @staticmethod
    def _parse_depth(parts: list[str]) -> tuple[int, str | None]:
        depth = 0
        parent_worker: str | None = None
        for i, p in enumerate(parts):
            if p == "runs" and i >= 2:
                depth += 1
                if i >= 1:
                    parent_worker = parts[i - 1]
        return depth, parent_worker

    def _process_file(self, path: Path, rel: str) -> None:
        if rel in self._seen_files:
            return
        self._seen_files.add(rel)

        parts = rel.replace("\\", "/").split("/")
        depth, parent_worker_id = self._parse_depth(parts)

        # run_manifest.json -> run.start or delegation.start
        if parts[-1] == "run_manifest.json":
            data = self._read_json(path)
            if data:
                if depth == 0:
                    self._persist_event("run.start", data)
                else:
                    models = data.get("models", {})
                    self._persist_event("delegation.start", {
                        "parent_id": parent_worker_id,
                        "depth": depth,
                        "model": models.get("manager", "?"),
                        "task": data.get("task", ""),
                    })

        # manager_decision.json -> iteration.start + iteration.decision
        elif "manager_decision.json" in rel:
            data = self._read_json(path)
            if data:
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                unique_iter = f"{iter_key}{iteration}"
                iter_start_key = f"_iter_start_{unique_iter}"
                if iter_start_key not in self._seen_files:
                    self._seen_files.add(iter_start_key)
                    self._persist_event("iteration.start", {
                        "iteration": unique_iter,
                        "depth": depth,
                        "parent_id": parent_worker_id,
                    })
                delegations = data.get("delegations", [])
                summaries = []
                for d in (delegations if isinstance(delegations, list) else []):
                    if isinstance(d, dict):
                        summaries.append({
                            "worker": d.get("worker_id", d.get("id", "?")),
                            "task": str(d.get("instructions", d.get("task", "")))[:200],
                            "tools": d.get("tools_allowed", []),
                        })
                self._persist_event("iteration.decision", {
                    "iteration": unique_iter,
                    "depth": depth,
                    "parent_id": parent_worker_id,
                    "delegations": summaries,
                    **data,
                })

        # budget_snapshot.json -> budget.update
        elif "budget_snapshot.json" in rel:
            data = self._read_json(path)
            if data:
                self._persist_event("budget.update", data)

        # envelope.json -> worker.spawn
        elif rel.endswith("envelope.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                self._persist_event("worker.spawn", {
                    "worker_id": worker_id,
                    "iteration": f"{iter_key}{iteration}",
                    "depth": depth,
                    "parent_id": parent_worker_id,
                    "instructions": str(data.get("instructions", ""))[:500],
                    "tools_allowed": data.get("tools_allowed", []),
                    "code_mode": data.get("tool_config", {}).get(
                        "code_mode", data.get("code_mode")
                    ),
                })

        # result.json -> worker.complete
        elif rel.endswith("result.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                self._persist_event("worker.complete", {
                    "worker_id": worker_id,
                    "iteration": f"{iter_key}{iteration}",
                    "depth": depth,
                    "confidence": data.get("confidence"),
                    "error": data.get("error"),
                    "has_error": bool(data.get("error")),
                })

        # tool_calls.json -> tool.call
        elif rel.endswith("tool_calls.json"):
            data = self._read_json(path)
            if isinstance(data, list):
                worker_id = path.parent.name
                if worker_id == "tools":
                    worker_id = path.stem.removesuffix("_tool_calls")
                for i, tc in enumerate(data):
                    if isinstance(tc, dict):
                        self._persist_event("tool.call", {
                            "worker_id": worker_id,
                            "depth": depth,
                            "call_index": i,
                            "tool": tc.get("tool", "unknown"),
                            "ok": tc.get("result", {}).get("ok", True)
                            if isinstance(tc.get("result"), dict) else True,
                        })

        # critique.json -> critique.result
        elif rel.endswith("critique.json"):
            data = self._read_json(path)
            if data:
                self._persist_event("critique.result", {
                    "worker_id": path.parent.name if "delegations" in rel else None,
                    "depth": depth,
                    "score": data.get("score"),
                    "summary": data.get("summary", ""),
                })

        # run_completion.json -> run.complete
        elif rel == "run_completion.json":
            data = self._read_json(path)
            if data:
                self._persist_event("run.complete", data)

    def watch(self) -> None:
        """Poll the run directory until stop() is called or completion."""
        while not self._stop.is_set():
            run_dir = self._find_run_dir()
            if run_dir and run_dir.exists():
                self._scan_dir(run_dir)
                if "run_completion.json" in self._seen_files:
                    self._scan_dir(run_dir)
                    break
            self._stop.wait(timeout=0.3)

    def _scan_dir(self, run_dir: Path) -> None:
        try:
            all_paths: list[tuple[str, Path]] = []
            for path in run_dir.rglob("*.json"):
                try:
                    rel = str(path.relative_to(run_dir))
                except ValueError:
                    continue
                all_paths.append((rel, path))
            # Sort: run_manifest first, run_completion last
            def _sort_key(item: tuple[str, Path]) -> tuple[int, str]:
                rel = item[0]
                if rel == "run_manifest.json":
                    return (0, rel)
                if rel == "run_completion.json":
                    return (99, rel)
                return (1, rel)
            all_paths.sort(key=_sort_key)
            for rel, path in all_paths:
                self._process_file(path, rel)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Run wrapper
# ---------------------------------------------------------------------------


def run_e2e(
    *,
    slug: str,
    title: str,
    task: str,
    inputs: dict[str, Any] | None = None,
    model: str = "openai/gpt-5-mini",
    max_loops: int = 30,
    max_total_tokens: int = 3_000_000,
    max_wall_time: int = 3600,
    max_total_workers: int = 60,
    max_depth: int = 4,
    max_tool_calls: int = 2000,
    workflow_dir: Path | None = None,
    verifier=None,
    extra_config: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Execute one E2E scenario end-to-end and return a structured report.

    Parameters
    ----------
    tags : list[str], optional
        Tags for the experiment. ``"e2e"`` is always added automatically.
        Example: ``["e2e", "s5", "tool-creation", "critique"]``
    """
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
        tags=tags,
    )
    print(f"[e2e] slug={slug} session={session_id} run={run_id}")
    print(f"[e2e] workflow_dir={workflow_dir}")

    # Start the live event watcher in a background thread so the UI
    # can display progress (iterations, workers, tool calls) in real time.
    watcher = _E2ERunDirWatcher(run_id, workflow_dir)
    watcher_thread = threading.Thread(
        target=watcher.watch, daemon=True, name=f"e2e-watcher-{run_id[:8]}"
    )
    watcher_thread.start()

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

    # Stop the live event watcher and let it do a final scan
    watcher.stop()
    watcher_thread.join(timeout=5)

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
