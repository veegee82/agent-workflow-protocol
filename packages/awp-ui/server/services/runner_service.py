"""Runner service — wraps AgentWorkflow and emits real-time events."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.event_bus import event_bus
from server.models import EventType, RunEvent

logger = logging.getLogger(__name__)

# Sequence counter per run (thread-safe)
_seq_counters: dict[str, int] = {}
_seq_lock = threading.Lock()


def _next_seq(run_id: str) -> int:
    """Return the next sequence number for a run_id (thread-safe)."""
    with _seq_lock:
        val = _seq_counters.get(run_id, 0) + 1
        _seq_counters[run_id] = val
        return val


def _make_event(
    run_id: str, event_type: EventType, data: dict[str, Any] | None = None
) -> RunEvent:
    return RunEvent(
        run_id=run_id,
        seq=_next_seq(run_id),
        type=event_type,
        data=data or {},
        timestamp=datetime.now(tz=timezone.utc),
    )


class _RunDirWatcher:
    """Watches the delegation loop run directory for new files and emits events.

    The DelegationLoopRunner writes JSON files to disk as it progresses:
      - run_manifest.json (at start)
      - iterations/001/manager_decision.json
      - iterations/001/delegations/<worker>/envelope.json
      - iterations/001/delegations/<worker>/result.json
      - iterations/001/budget_snapshot.json
      - run_completion.json (at end)

    This watcher polls for new files and translates them into RunEvent objects.
    """

    def __init__(self, run_id: str, workspace_dir: Path) -> None:
        self._run_id = run_id
        self._workspace_dir = workspace_dir
        self._seen_files: set[str] = set()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _find_run_dir(self) -> Path | None:
        """Locate the delegation loop run directory under workspace/runs/."""
        runs_dir = self._workspace_dir / "workspace" / "runs"
        if not runs_dir.exists():
            return None
        # Pick the latest run dir
        candidates = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir()], key=lambda d: d.name
        )
        return candidates[-1] if candidates else None

    def _read_json(self, path: Path) -> dict[str, Any] | list[Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _process_file(self, path: Path, rel: str) -> None:
        """Translate a newly-observed file into one or more events."""
        if rel in self._seen_files:
            return
        self._seen_files.add(rel)

        # run_manifest.json -> run.start
        if rel == "run_manifest.json":
            data = self._read_json(path)
            if data:
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(self._run_id, EventType.RUN_START, data),
                )

        # iterations/NNN/manager_decision.json -> iteration.decision
        elif "manager_decision.json" in rel:
            data = self._read_json(path)
            if data:
                parts = rel.split("/")
                iteration = parts[1] if len(parts) >= 3 else "?"
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.ITERATION_DECISION,
                        {"iteration": iteration, **data},
                    ),
                )

        # iterations/NNN/budget_snapshot.json -> budget.update
        elif "budget_snapshot.json" in rel:
            data = self._read_json(path)
            if data:
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(self._run_id, EventType.BUDGET_UPDATE, data),
                )

        # delegations/<worker>/envelope.json -> worker.spawn
        elif rel.endswith("envelope.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.WORKER_SPAWN,
                        {
                            "worker_id": worker_id,
                            "instructions": str(data.get("instructions", ""))[:500],
                            "tools_allowed": data.get("tools_allowed", []),
                        },
                    ),
                )

        # delegations/<worker>/result.json -> worker.complete
        elif rel.endswith("result.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.WORKER_COMPLETE,
                        {
                            "worker_id": worker_id,
                            "confidence": data.get("confidence"),
                            "error": data.get("error"),
                            "has_error": bool(data.get("error")),
                        },
                    ),
                )

        # delegations/<worker>/tool_calls.json -> tool.call (one per call)
        elif rel.endswith("tool_calls.json") and "delegations" in rel:
            data = self._read_json(path)
            if isinstance(data, list):
                worker_id = path.parent.name
                for tc in data:
                    if isinstance(tc, dict):
                        event_bus.emit_threadsafe(
                            self._run_id,
                            _make_event(
                                self._run_id,
                                EventType.TOOL_CALL,
                                {
                                    "worker_id": worker_id,
                                    "tool": tc.get("tool", "unknown"),
                                    "ok": tc.get("result", {}).get("ok", False),
                                },
                            ),
                        )

        # run_completion.json -> run.complete
        elif rel == "run_completion.json":
            data = self._read_json(path)
            if data:
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(self._run_id, EventType.RUN_COMPLETE, data),
                )

    def watch(self) -> None:
        """Poll the run directory until stop() is called or completion is detected."""
        while not self._stop.is_set():
            run_dir = self._find_run_dir()
            if run_dir and run_dir.exists():
                self._scan_dir(run_dir)
                # If we see completion, do one final scan and stop
                if "run_completion.json" in self._seen_files:
                    self._scan_dir(run_dir)
                    break
            self._stop.wait(timeout=0.5)

    def _scan_dir(self, run_dir: Path) -> None:
        """Walk the run directory for JSON files."""
        try:
            for path in run_dir.rglob("*.json"):
                try:
                    rel = str(path.relative_to(run_dir))
                except ValueError:
                    continue
                self._process_file(path, rel)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Active runs registry (for stop support)
# ---------------------------------------------------------------------------

_active_runs: dict[str, dict[str, Any]] = {}
_active_lock = threading.Lock()


class RunnerService:
    """Orchestrates AgentWorkflow runs with event streaming."""

    def __init__(self) -> None:
        pass

    def start_run(
        self,
        run_id: str,
        config: dict[str, Any],
    ) -> str:
        """Launch an AgentWorkflow run in a background thread.

        Parameters
        ----------
        run_id : str
            Unique run identifier (pre-generated by the caller).
        config : dict
            WorkflowConfig fields (task, model, budget params, etc.).

        Returns
        -------
        str
            The run_id.
        """
        thread = threading.Thread(
            target=self._run_workflow,
            args=(run_id, config),
            daemon=True,
            name=f"awp-run-{run_id[:8]}",
        )
        with _active_lock:
            _active_runs[run_id] = {"thread": thread, "stop": False}
        thread.start()
        return run_id

    def stop_run(self, run_id: str) -> bool:
        """Signal a run to stop. Returns True if the run was found."""
        with _active_lock:
            info = _active_runs.get(run_id)
            if info is None:
                return False
            info["stop"] = True
        return True

    def is_running(self, run_id: str) -> bool:
        with _active_lock:
            info = _active_runs.get(run_id)
            if info is None:
                return False
            return info["thread"].is_alive()

    def _run_workflow(self, run_id: str, config: dict[str, Any]) -> None:
        """Execute the workflow synchronously in a background thread."""
        from server.services.store import StoreService

        result: dict[str, Any] | None = None
        status = "failed"

        # Emit run.start
        event_bus.emit_threadsafe(
            run_id,
            _make_event(run_id, EventType.RUN_START, {"run_id": run_id, **config}),
        )

        try:
            # Lazy import to avoid circular deps and allow running without AWP installed
            from awp.data.workflow import AgentWorkflow

            # Build AgentWorkflow kwargs from config
            wf_kwargs = self._config_to_workflow_kwargs(config)

            # Create output_dir for watching
            output_dir = wf_kwargs.get("output_dir")
            if not output_dir:
                import tempfile

                tmp = tempfile.mkdtemp(prefix="awp_ui_run_")
                wf_kwargs["output_dir"] = tmp
                output_dir = tmp

            workspace_dir = Path(output_dir)

            # Start the directory watcher
            watcher = _RunDirWatcher(run_id, workspace_dir)
            watcher_thread = threading.Thread(
                target=watcher.watch,
                daemon=True,
                name=f"awp-watcher-{run_id[:8]}",
            )
            watcher_thread.start()

            # Execute the workflow (blocking)
            wf = AgentWorkflow(**wf_kwargs)
            result = wf.run()

            # Wait for the watcher to pick up remaining files
            watcher.stop()
            watcher_thread.join(timeout=3)

            status = result.get("status", "complete")

        except ImportError as exc:
            logger.error(
                "AWP runtime not installed: %s. "
                "Install with: pip install -e packages/awp-runtime/",
                exc,
            )
            status = "error"
            result = {"error": f"AWP runtime not available: {exc}"}
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id, EventType.ERROR, {"message": str(exc)}
                ),
            )

        except Exception as exc:
            logger.exception("Run %s failed with exception", run_id)
            status = "error"
            result = {"error": str(exc)}
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id, EventType.ERROR, {"message": str(exc)}
                ),
            )

        finally:
            # Emit run.complete
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id,
                    EventType.RUN_COMPLETE,
                    {"status": status, "result": result},
                ),
            )
            # Close the event bus channel for this run
            event_bus.close_run_threadsafe(run_id)

            # Persist result to DB (best-effort from background thread)
            try:
                import asyncio

                loop = event_bus._loop
                if loop and not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._persist_result(run_id, status, result),
                        loop,
                    ).result(timeout=10)
            except Exception:
                logger.warning(
                    "Failed to persist result for run %s", run_id, exc_info=True
                )

            # Cleanup active runs
            with _active_lock:
                _active_runs.pop(run_id, None)
            with _seq_lock:
                _seq_counters.pop(run_id, None)

    @staticmethod
    async def _persist_result(
        run_id: str,
        status: str,
        result: dict[str, Any] | None,
    ) -> None:
        """Persist the final result to SQLite."""
        # Import lazily to avoid circular refs at module level
        from server.app import store

        await store.update_run(
            run_id,
            status=status,
            result=result,
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    @staticmethod
    def _config_to_workflow_kwargs(config: dict[str, Any]) -> dict[str, Any]:
        """Map a WorkflowConfig dict to AgentWorkflow constructor kwargs."""
        kwargs: dict[str, Any] = {}

        # Required
        kwargs["task"] = config["task"]
        kwargs["model"] = config["model"]

        # Optional string/none fields
        for key in ("api_key", "worker_model", "output_dir"):
            if config.get(key):
                kwargs[key] = config[key]

        # Budget ints
        for key in (
            "max_loops",
            "max_total_tokens",
            "max_wall_time",
            "max_tool_calls",
            "max_total_workers",
            "max_depth",
        ):
            if key in config:
                kwargs[key] = config[key]

        # Sandbox
        if "sandbox" in config:
            kwargs["sandbox"] = config["sandbox"]
        if config.get("packages"):
            kwargs["packages"] = config["packages"]

        # Tools
        if config.get("tools") is not None:
            kwargs["tools"] = config["tools"]
        if config.get("forbidden_tools") is not None:
            kwargs["forbidden_tools"] = config["forbidden_tools"]

        # Booleans
        for key in ("code_mode", "tool_creation", "verbose"):
            if key in config:
                kwargs[key] = config[key]

        # Dict/list fields
        if config.get("secrets"):
            kwargs["secrets"] = config["secrets"]
        if config.get("skills"):
            kwargs["skills"] = config["skills"]

        # Inputs: merge dict inputs and file paths
        inputs: dict[str, Any] = dict(config.get("inputs", {}))
        for i, fpath in enumerate(config.get("input_files", [])):
            name = Path(fpath).stem or f"file_{i}"
            inputs[name] = fpath
        kwargs["inputs"] = inputs

        return kwargs


# Module-level singleton
runner_service = RunnerService()
