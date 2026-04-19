#!/usr/bin/env python3
"""E2E full-coverage test for the AWP outer loop (Phase A1-A4 + UI).

Orchestrates a 3-task x 2-epoch suite with real OpenRouter LLM calls and
manually drives the outer-loop primitives (ArtifactRegistry, epochs /
epoch_runs rows in ``~/.awp/outer_loop.db``, TextGradOptimizer) while
running each per-task AWP run through the shared ``_harness.run_e2e``
helper so the experiment appears live in the UI sidebar.

Design note
-----------
``SuiteRunner.run_epoch`` invokes ``AgentWorkflow`` directly and does NOT
register runs in the UI SQLite DB (``~/.awp/awp_ui.db``). To get live
UI visibility we bypass ``SuiteRunner`` for the per-task execution and
call ``run_e2e`` ourselves (which registers + streams), then write the
epoch / epoch_runs rows into the outer-loop DB by hand (via raw SQL
plus ``SqliteArtifactStore`` / ``ArtifactRegistry`` for version writes).
All 6 task runs land in the same session so the UI groups them as one
experiment.

This script is **write-only**; the user launches it manually with the
UI server running.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ----- Repo path plumbing ---------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _sub in (
    "packages/awp-core/src",
    "packages/awp-runtime/src",
    "packages/awp-ui/server",
):
    sys.path.insert(0, str(_PROJECT_ROOT / _sub))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import run_e2e, load_openrouter_key  # noqa: E402


# ----- Constants ------------------------------------------------------------

SUITE_NAME = "fact_card_generator"

TAGS = [
    "e2e",
    "s5",
    "outer-loop",
    "tool-creation",
    "critique",
    "memory",
    "planning",
    "optimizer",
]

ALL_ARTIFACTS: list[str] = [
    "worker_pitfalls",
    "manager_planning_preamble",
    "experiment_context_hint_template",
    "pattern_library",
    "tool_description_templates",
    "critique_rubric",
]

# Optimizer is asked to consider this narrow subset (keeps the LLM call
# cheap — the other three artifacts are larger / more structural and
# unlikely to yield a useful single-epoch edit).
CANDIDATE_ARTIFACTS: list[str] = [
    "worker_pitfalls",
    "manager_planning_preamble",
    "critique_rubric",
]

REQUIRED_METRIC_TYPES: frozenset[str] = frozenset({
    "metric.confidence",
    "metric.critique",
    "metric.eval",
    "metric.budget",
    "metric.gate",
    "metric.tool_call",
})


TASKS: list[dict[str, str]] = [
    dict(
        name="octopi",
        prompt=(
            "Build a fact-card JSON about octopi. Use code.execute to:\n"
            "1. Compute 3 numeric 'fun facts' (hearts=3, arms=8, approximate "
            "chromatophore count per arm ~ 200000). Derive at least one "
            "combined statistic (e.g. total chromatophores = arms * per_arm).\n"
            "2. Write the final JSON to "
            "workspace/output/octopi_fact_card.json with fields:\n"
            "   - title (str)\n"
            "   - facts (list of exactly 3 strings)\n"
            "   - computed_stats (dict of 3 numbers, including the combined stat)\n"
            "   - sources (list of 2+ strings, short bibliographic or URL-style)\n"
            "   - confidence (float 0-1, must be >= 0.7)\n"
            "Your result must pass critique + evaluation before completion. "
            "Include confidence in the top-level agent output."
        ),
    ),
    dict(
        name="neutron_stars",
        prompt=(
            "Build a fact-card JSON about neutron stars. Use code.execute to:\n"
            "1. Compute 3 numeric 'fun facts' (solar mass ~ 1.4, radius km "
            "~ 10, typical rotation frequency Hz ~ 700). Derive at least "
            "one combined statistic (e.g. surface gravity proxy = "
            "mass_kg / radius_m^2 in arbitrary units).\n"
            "2. Write the final JSON to "
            "workspace/output/neutron_stars_fact_card.json with fields:\n"
            "   - title (str)\n"
            "   - facts (list of exactly 3 strings)\n"
            "   - computed_stats (dict of 3 numbers, including the combined stat)\n"
            "   - sources (list of 2+ strings)\n"
            "   - confidence (float 0-1, must be >= 0.7)\n"
            "Your result must pass critique + evaluation before completion. "
            "Include confidence in the top-level agent output."
        ),
    ),
    dict(
        name="silk_road",
        prompt=(
            "Build a fact-card JSON about the historical Silk Road. Use "
            "code.execute to:\n"
            "1. Compute 3 numeric 'fun facts' (approximate length km ~ 6400, "
            "active duration centuries ~ 15, peak annual trade volume proxy "
            "in tonnes ~ 10000). Derive at least one combined statistic "
            "(e.g. cumulative trade volume over active duration).\n"
            "2. Write the final JSON to "
            "workspace/output/silk_road_fact_card.json with fields:\n"
            "   - title (str)\n"
            "   - facts (list of exactly 3 strings)\n"
            "   - computed_stats (dict of 3 numbers, including the combined stat)\n"
            "   - sources (list of 2+ strings)\n"
            "   - confidence (float 0-1, must be >= 0.7)\n"
            "Your result must pass critique + evaluation before completion. "
            "Include confidence in the top-level agent output."
        ),
    ),
]


# ----- Outer-loop DB + registry helpers -------------------------------------


def _get_outer_loop_infra() -> tuple[Any, Any, Path]:
    """Return (store, registry, db_path). Both use ~/.awp/outer_loop.db."""
    from awp.outer_loop.artifacts import ArtifactRegistry
    from awp.outer_loop.store import SqliteArtifactStore

    db_path = Path.home() / ".awp" / "outer_loop.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Opening SqliteArtifactStore applies _SCHEMA (CREATE TABLE IF NOT EXISTS)
    # so the raw-SQL writes below can rely on the tables existing.
    store = SqliteArtifactStore(str(db_path))
    registry = ArtifactRegistry(db_path=str(db_path))
    return store, registry, db_path


def _build_llm_client():
    """Build an LLMClient pinned to the manager model via OpenRouter."""
    from awp.runtime.llm import LLMClient
    return LLMClient(model="openai/gpt-5-mini")


# ----- Run-dir discovery ----------------------------------------------------


def _find_run_dir(report: dict[str, Any]) -> Path:
    """Locate the delegation-loop run directory (holding run_completion.json
    + metrics.jsonl) for a completed ``run_e2e`` invocation.

    The harness pins per-run directories at
    ``<workflow_dir>/workspace/runs/<run-id>``. When multiple runs share
    one workflow_dir (session reuse) we match on the ``run_id`` substring
    but fall back to mtime-ordered traversal if no match is found.
    """
    workflow_dir = Path(report["workflow_dir"])
    runs_dir = workflow_dir / "workspace" / "runs"
    run_id: str = str(report.get("run_id") or "")

    if runs_dir.exists():
        # Prefer a directory whose run_manifest.json carries our run_id, or
        # whose name contains run_id. This is the common case.
        candidates: list[tuple[float, Path]] = []
        for d in runs_dir.iterdir():
            if not d.is_dir():
                continue
            # Skip sub-manager dirs (nested runs/...) — they live under
            # delegations/<worker>/runs/, not at the top level.
            rc = d / "run_completion.json"
            if not rc.exists():
                continue
            if run_id and run_id in d.name:
                return d
            try:
                candidates.append((rc.stat().st_mtime, d))
            except OSError:
                continue

        # Check run_manifest.json content match as second best
        for _mtime, d in sorted(candidates, key=lambda x: -x[0]):
            manifest = d / "run_manifest.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    if run_id and data.get("run_id") == run_id:
                        return d
                except (OSError, json.JSONDecodeError):
                    pass

        # Fallback: most recently modified
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]

    # Last-resort: search shallowly under workflow_dir
    for rc in workflow_dir.rglob("run_completion.json"):
        return rc.parent

    # Give up — return workflow_dir so the loss function still returns
    # a well-defined neutral value.
    return workflow_dir


def _compute_loss(run_dir: Path) -> float:
    from awp.outer_loop.loss import compute_run_loss
    return float(compute_run_loss(run_dir).total)


def _extract_scores(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Read eval/critique/token signals from run_completion.json."""
    scores: dict[str, Any] = {
        "status": report.get("status"),
        "wf_status": report.get("wf_status"),
        "termination_reason": report.get("termination_reason"),
        "duration_s": report.get("duration_s"),
    }
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            data = json.loads(rc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for k in (
            "status",
            "reason",
            "eval_score",
            "critique_score",
            "tokens_used",
            "workers_spawned",
            "loops_used",
            "gate_rejection_count",
        ):
            if k in data:
                scores.setdefault(k, data[k])
    return scores


def _verify_metric_types(run_dirs: list[Path]) -> dict[str, bool]:
    """Aggregate every ``metric.*`` type seen across all run dirs."""
    found: set[str] = set()
    for rd in run_dirs:
        path = rd / "metrics.jsonl"
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tp = obj.get("type") or obj.get("event") or ""
                if isinstance(tp, str):
                    found.add(tp)
        except OSError:
            continue
    return {t: (t in found) for t in REQUIRED_METRIC_TYPES}


# ----- Suite / epoch write helpers (raw SQL — the tables are created by the
# store constructor via ``_SCHEMA``) -----------------------------------------


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_suite(
    db_path: Path,
    suite_id: str,
    name: str,
    tasks: list[dict[str, str]],
    baseline: dict[str, int],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT OR REPLACE INTO task_suites "
            "(id, name, tasks_json, baseline_artifacts_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                suite_id,
                name,
                json.dumps(
                    [{"name": t["name"], "task": t["prompt"]} for t in tasks]
                ),
                json.dumps(baseline),
                _iso_now(),
            ),
        )


def _insert_epoch(
    db_path: Path,
    epoch_id: str,
    suite_id: str,
    epoch_num: int,
    parent_artifacts: dict[str, int],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO epochs "
            "(id, suite_id, epoch_num, started_at, completed_at, "
            "mean_loss, parent_artifacts_json, child_artifacts_json) "
            "VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL)",
            (
                epoch_id,
                suite_id,
                epoch_num,
                _iso_now(),
                json.dumps(parent_artifacts),
            ),
        )


def _insert_epoch_run(
    db_path: Path,
    epoch_id: str,
    run_id: str,
    task_name: str,
    loss: float,
    scores: dict[str, Any],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO epoch_runs "
            "(epoch_id, run_id, task_name, loss, scores_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                epoch_id,
                run_id,
                task_name,
                float(loss),
                json.dumps(scores, default=str),
            ),
        )


def _finalize_epoch(
    db_path: Path,
    epoch_id: str,
    mean_loss: float,
    child_artifacts_record: dict[str, Any],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "UPDATE epochs SET completed_at = ?, mean_loss = ?, "
            "child_artifacts_json = ? WHERE id = ?",
            (
                _iso_now(),
                float(mean_loss),
                json.dumps(child_artifacts_record, default=str),
                epoch_id,
            ),
        )


def _run_optimizer(
    registry: Any,
    epoch_id: str,
    epoch_num: int,
    suite_id: str,
    task_results: list[dict[str, Any]],
    learning_rate: float,
    parent_artifacts: dict[str, int],
) -> dict[str, Any] | None:
    """Build an EpochResult, ask TextGradOptimizer for one proposal, and
    persist it via the registry. Returns the update record on success.
    """
    try:
        from awp.outer_loop.loss import compute_run_loss
        from awp.outer_loop.runner import EpochResult, TaskRunResult
        from awp.outer_loop.textgrad import TextGradOptimizer
    except Exception as exc:  # pragma: no cover
        print(f"[e2e] optimizer imports failed: {exc}")
        return None

    # Build synthetic EpochResult from our task_results list.
    tr_objs: list[TaskRunResult] = []
    for tr in task_results:
        breakdown = compute_run_loss(Path(tr["run_dir"]))
        tr_objs.append(
            TaskRunResult(
                task_name=tr["name"],
                run_id=tr["run_id"],
                run_dir=str(tr["run_dir"]),
                status=str(tr.get("status") or "unknown"),
                loss=float(tr["loss"]),
                breakdown=breakdown,
            )
        )
    mean_loss = (
        sum(t.loss for t in tr_objs) / len(tr_objs) if tr_objs else None
    )
    epoch_result = EpochResult(
        epoch_id=epoch_id,
        suite_id=suite_id,
        suite_name=SUITE_NAME,
        epoch_num=epoch_num,
        parent_artifacts=dict(parent_artifacts),
        child_artifacts=dict(parent_artifacts),
        task_results=tr_objs,
        mean_loss=mean_loss,
        started_at="",
        completed_at="",
    )

    llm = _build_llm_client()
    optimizer = TextGradOptimizer(llm_client=llm, registry=registry)

    try:
        update = optimizer.propose_update(
            epoch_result,
            candidate_artifacts=CANDIDATE_ARTIFACTS,
            learning_rate=learning_rate,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] TextGradOptimizer.propose_update failed: {exc}")
        return None

    if update is None or not update.artifact_name:
        print("[e2e] optimizer declined all candidates — no update")
        return None

    try:
        parent_version = int(parent_artifacts.get(update.artifact_name, 0))
        new_version = registry.put_version(
            update.artifact_name,
            update.proposed_content,
            parent_version=parent_version,
            epoch_id=epoch_id,
        )
        registry.set_active(update.artifact_name, new_version.version)
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] registry write failed: {exc}")
        return None

    print(
        f"[e2e] optimizer updated {update.artifact_name} "
        f"v{parent_version} -> v{new_version.version} "
        f"(expected_loss_reduction={update.expected_loss_reduction:.2f}, "
        f"confidence={update.confidence:.2f})"
    )
    return {
        "type": "update",
        "artifact": update.artifact_name,
        "from_version": parent_version,
        "to_version": int(new_version.version),
        "rationale": update.rationale,
        "expected_loss_reduction": update.expected_loss_reduction,
        "confidence": update.confidence,
        "learning_rate": learning_rate,
    }


# ----- Main driver ----------------------------------------------------------


def main() -> int:
    load_openrouter_key()
    print("[e2e] Starting outer-loop full-coverage E2E")

    store, registry, db_path = _get_outer_loop_infra()
    _ = store  # kept alive to ensure schema is applied

    # Session is created by the harness on the FIRST run_e2e call
    # (session_id=None → harness creates + returns it). Subsequent calls
    # pass the returned id so all 6 runs group into one sidebar experiment.
    session_id: str | None = None
    suite_id = uuid.uuid4().hex[:12]

    _insert_suite(
        db_path,
        suite_id=suite_id,
        name=SUITE_NAME,
        tasks=TASKS,
        baseline={n: 0 for n in ALL_ARTIFACTS},
    )

    run_dirs_all: list[Path] = []
    epoch_summaries: list[dict[str, Any]] = []

    for epoch_num in (1, 2):
        epoch_id = uuid.uuid4().hex[:12]
        parent_artifacts = {
            n: registry.get_active(n).version for n in ALL_ARTIFACTS
        }
        _insert_epoch(
            db_path,
            epoch_id=epoch_id,
            suite_id=suite_id,
            epoch_num=epoch_num,
            parent_artifacts=parent_artifacts,
        )
        print(
            f"\n[e2e] === Epoch {epoch_num} (epoch_id={epoch_id}) ==="
        )
        print(f"[e2e] parent_artifacts={parent_artifacts}")

        task_results: list[dict[str, Any]] = []
        for task in TASKS:
            slug = f"outer-loop-e{epoch_num}-{task['name']}"
            title = (
                f"Outer-Loop Coverage - Epoch {epoch_num} - {task['name']}"
            )
            print(f"\n[e2e] Running {slug} ...")
            report = run_e2e(
                slug=slug,
                title=title,
                task=task["prompt"],
                model="openai/gpt-5-mini",
                max_loops=6,
                max_total_tokens=600_000,
                max_wall_time=240,
                max_total_workers=5,
                max_depth=2,
                max_tool_calls=80,
                tags=TAGS,
                session_id=session_id,
            )
            # Capture session_id from the first run so subsequent runs
            # land in the same UI session and the sidebar groups them.
            if session_id is None:
                session_id = str(report.get("session_id") or "")
            run_dir = _find_run_dir(report)
            run_dirs_all.append(run_dir)

            loss = _compute_loss(run_dir)
            scores = _extract_scores(run_dir, report)
            _insert_epoch_run(
                db_path,
                epoch_id=epoch_id,
                run_id=str(report["run_id"]),
                task_name=task["name"],
                loss=loss,
                scores=scores,
            )
            task_results.append(
                {
                    "name": task["name"],
                    "run_id": str(report["run_id"]),
                    "run_dir": str(run_dir),
                    "loss": loss,
                    "status": str(report.get("status") or "unknown"),
                }
            )
            print(
                f"[e2e] task={task['name']} status={report['status']} "
                f"loss={loss:.4f}"
            )

        losses = [t["loss"] for t in task_results if t["loss"] is not None]
        mean_loss = sum(losses) / len(losses) if losses else 0.0
        print(f"[e2e] Epoch {epoch_num} mean_loss={mean_loss:.4f}")

        child_record: dict[str, Any] = {
            "artifacts": dict(parent_artifacts),
            "events": [],
        }

        if epoch_num == 1:
            print("[e2e] Running TextGradOptimizer between epochs ...")
            update_event = _run_optimizer(
                registry=registry,
                epoch_id=epoch_id,
                epoch_num=epoch_num,
                suite_id=suite_id,
                task_results=task_results,
                learning_rate=0.5,
                parent_artifacts=parent_artifacts,
            )
            if update_event is not None:
                child_record["artifacts"][update_event["artifact"]] = (
                    update_event["to_version"]
                )
                child_record["events"].append(update_event)

        _finalize_epoch(
            db_path,
            epoch_id=epoch_id,
            mean_loss=mean_loss,
            child_artifacts_record=child_record,
        )
        epoch_summaries.append(
            {
                "epoch_id": epoch_id,
                "epoch_num": epoch_num,
                "mean_loss": mean_loss,
                "task_results": task_results,
                "child_record": child_record,
            }
        )

    # ---- Verification ------------------------------------------------------
    print("\n[e2e] === Verification ===")
    ok = True

    # 1. UI DB session_runs must have 6 rows for this session
    ui_db = Path.home() / ".awp" / "awp_ui.db"
    sr_count = 0
    if ui_db.exists():
        with sqlite3.connect(str(ui_db)) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM session_runs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            sr_count = int(row[0] if row else 0)
    status_1 = "OK" if sr_count == 6 else "FAIL"
    print(f"[verify 1/7] UI DB session_runs for session={session_id}: "
          f"{sr_count}/6 - {status_1}")
    ok &= (sr_count == 6)

    # 2. All required metric.* types present across all runs
    metric_presence = _verify_metric_types(run_dirs_all)
    missing = sorted(t for t, p in metric_presence.items() if not p)
    status_2 = "OK" if not missing else f"FAIL missing={missing}"
    print(f"[verify 2/7] metric.* types: "
          f"{sum(metric_presence.values())}/{len(REQUIRED_METRIC_TYPES)} "
          f"- {status_2}")
    ok &= (not missing)

    # 3. 2 epoch rows in outer_loop.db
    with sqlite3.connect(str(db_path)) as con:
        ec = int(
            con.execute(
                "SELECT COUNT(*) FROM epochs WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()[0]
        )
    status_3 = "OK" if ec == 2 else "FAIL"
    print(f"[verify 3/7] epochs rows: {ec}/2 - {status_3}")
    ok &= (ec == 2)

    # 4. 6 epoch_runs rows
    with sqlite3.connect(str(db_path)) as con:
        erc = int(
            con.execute(
                "SELECT COUNT(*) FROM epoch_runs WHERE epoch_id IN "
                "(SELECT id FROM epochs WHERE suite_id = ?)",
                (suite_id,),
            ).fetchone()[0]
        )
    status_4 = "OK" if erc == 6 else "FAIL"
    print(f"[verify 4/7] epoch_runs rows: {erc}/6 - {status_4}")
    ok &= (erc == 6)

    # 5. artifact_versions >= 0 (optimizer may or may not have proposed)
    with sqlite3.connect(str(db_path)) as con:
        av = int(
            con.execute(
                "SELECT COUNT(*) FROM artifact_versions"
            ).fetchone()[0]
        )
    print(f"[verify 5/7] artifact_versions rows: {av} (>=0, optional) - OK")

    # 6. Loss trajectory (bonus — we do not gate on direction)
    if len(epoch_summaries) == 2:
        l1 = epoch_summaries[0]["mean_loss"]
        l2 = epoch_summaries[1]["mean_loss"]
        delta = l2 - l1
        arrow = "down" if delta < 0 else ("up" if delta > 0 else "flat")
        print(f"[verify 6/7] loss {l1:.4f} -> {l2:.4f} "
              f"({arrow}, bonus signal)")

    # 7. run_completion.json per run
    missing_rc = [
        rd for rd in run_dirs_all if not (rd / "run_completion.json").exists()
    ]
    status_7 = "OK" if not missing_rc else f"FAIL missing={len(missing_rc)}"
    print(f"[verify 7/7] run_completion.json present: "
          f"{len(run_dirs_all) - len(missing_rc)}/{len(run_dirs_all)} "
          f"- {status_7}")
    ok &= (not missing_rc)

    # ---- Summary -----------------------------------------------------------
    print("\n[e2e] === Summary ===")
    print(f"[e2e] Session ID: {session_id}")
    print(f"[e2e] Suite ID:   {suite_id}")
    print(f"[e2e] UI DB:      {ui_db}")
    print(f"[e2e] Outer DB:   {db_path}")
    print(
        "[e2e] Open the UI sidebar, pick the session above, and switch "
        "to the Optimizer tab - pick suite 'fact_card_generator' for "
        "charts / delta timeline."
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
