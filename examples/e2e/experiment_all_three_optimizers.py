#!/usr/bin/env python3
"""E2E: experiment hierarchy exercised by all three optimizers + UI.

Runs:
    Phase 1 — create experiment + seed task via CLI
    Phase 2 — `awp run --target`         (real LLM seed run)
    Phase 3 — `awp refine --target`      (real LLM, 2 iterations)
    Phase 4 — `awp optimize --target`    (real LLM, 1 epoch over 1-task suite)
    Phase 5 — assertions + final state report

Watch in the UI:
    The UI must be running on :8420. Before firing this script, start:
        awp studio &
    Then open http://127.0.0.1:8420 and switch the sidebar to "Experiments".

Visibility timing (known today):
    * Experiment + task appear in the sidebar IMMEDIATELY after phases 1.
    * The seed run lands in the sidebar AFTER phase 2 completes
      (no mid-run event streaming for CLI-target runs; runs are DB-registered
      in the post-run finaliser).
    * Refinement iterations appear in a single batch AFTER phase 3 completes.
    * Optimize epoch-runs appear in a single batch AFTER phase 4 completes.
    * BEST updates live in the Task detail view after each phase completes.

Budget expectation:
    * Seed:     ~50-150k tokens
    * Refine:   ~100-300k tokens (2 iterations, budgets halved each iter)
    * Optimize: ~100-250k tokens (1 epoch, 1 trivial task, TextGrad disabled)
    * Total:    ~250-700k tokens. Roughly $0.50-$1.50 on OpenRouter
                depending on model routing.

Prerequisites:
    * OPENROUTER_API_KEY set (or sourced from /home/shumway/projects/meta-agents/.env)
    * `pip install -e packages/awp-core packages/awp-runtime packages/awp-ui`

Run manually (blocks 15-30 min):
    python examples/e2e/experiment_all_three_optimizers.py
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def _load_api_key() -> None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    candidate = Path("/home/shumway/projects/meta-agents/.env")
    if not candidate.exists():
        print(
            "OPENROUTER_API_KEY not set and no .env found at "
            f"{candidate}. Set the key manually and retry.",
            file=sys.stderr,
        )
        sys.exit(2)
    for line in candidate.read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENROUTER_API_KEY="):
            os.environ["OPENROUTER_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return
    print("OPENROUTER_API_KEY line missing in .env", file=sys.stderr)
    sys.exit(2)


def _run(cmd: list[str], env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        if check:
            sys.exit(result.returncode)
    return result


def _build_minimal_workflow(workflow_dir: Path) -> None:
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "workflow.awp.yaml").write_text(
        """\
name: hierarchy-e2e
description: Minimal delegation-loop workflow for the all-three-optimizers E2E.
version: 1
engine: delegation_loop
autonomy: A2
orchestration:
  delegation_loop:
    max_loops: 8
    max_total_workers: 6
    max_total_tokens: 150000
    max_wall_time: 300
""",
        encoding="utf-8",
    )


def _build_minimal_suite(suite_path: Path) -> None:
    suite_path.write_text(
        """\
name: hierarchy_e2e_suite
description: Single-task suite for the optimize phase of the all-three E2E.
baseline_artifacts: {}
tasks:
  - name: tiny
    task: "Write a one-sentence tagline for an experiment-hierarchy feature."
    model: openai/gpt-5-mini
    worker_model: deepseek/deepseek-chat-v3.1
    budget:
      max_loops: 3
      max_total_workers: 2
      max_total_tokens: 20000
      max_wall_time: 120
""",
        encoding="utf-8",
    )


def main() -> int:
    _load_api_key()

    # Use the production paths so the UI picks the experiment up.
    env = os.environ.copy()

    scratch = Path("/tmp") / f"hierarchy_e2e_{int(time.time())}"
    scratch.mkdir(parents=True, exist_ok=True)
    workflow_dir = scratch / "workflow"
    _build_minimal_workflow(workflow_dir)
    suite_path = scratch / "suite.yaml"
    _build_minimal_suite(suite_path)

    print("=" * 60)
    print("Phase 1: experiment + seed task")
    print("=" * 60)
    r = _run(
        [sys.executable, "-m", "awp", "experiment", "create", "AllThree E2E",
         "--goal", "Exercise seed + refine + optimize via the hierarchy"],
        env=env,
    )
    exp_id = json.loads(r.stdout)["experiment_id"]
    print(f"✓ experiment_id = {exp_id}")

    r = _run(
        [sys.executable, "-m", "awp", "task", "create",
         exp_id, "Write a one-sentence summary of AWP's autonomy spectrum"],
        env=env,
    )
    task_id = json.loads(r.stdout)["task_id"]
    target = f"{exp_id}:{task_id}"
    print(f"✓ task_id = {task_id}  (target: {target})")

    print(
        "\nNow open http://127.0.0.1:8420 (or start with `awp studio &` first),"
        f"\nswitch the sidebar to 'Experiments', and expand '{exp_id[:16]}...'."
        "\nThe tree should show the seed task you just created."
        "\n\n[RETURN] to continue → fire the seed run (real LLM)."
    )
    try:
        input()
    except EOFError:
        pass

    print("=" * 60)
    print("Phase 2: seed run (real LLM)")
    print("=" * 60)
    _run(
        [sys.executable, "-m", "awp", "run", str(workflow_dir),
         "--task", "Write a one-sentence summary of AWP's autonomy spectrum",
         "--target", target],
        env=env,
    )
    print(f"✓ seed run complete — open Task {task_id} in the UI to see the loss + BEST.")

    print(
        "\n[RETURN] to continue → fire the refine loop (2 iterations, real LLM)."
    )
    try:
        input()
    except EOFError:
        pass

    print("=" * 60)
    print("Phase 3: refinement (2 iterations)")
    print("=" * 60)
    _run(
        [sys.executable, "-m", "awp", "refine", "--target", target, "--iterations", "2"],
        env=env,
    )
    print(f"✓ refinement complete — expect 2 new refine_iter runs in the Task detail view.")

    print(
        "\n[RETURN] to continue → fire outer-loop optimization (1 epoch, real LLM)."
    )
    try:
        input()
    except EOFError:
        pass

    print("=" * 60)
    print("Phase 4: optimize (1 epoch)")
    print("=" * 60)
    _run(
        [sys.executable, "-m", "awp", "optimize", str(suite_path),
         "--target", target, "--epochs", "1"],
        env=env,
    )
    print(f"✓ optimize complete — expect optimize_epoch_run entries in the Task detail view.")

    print("=" * 60)
    print("Phase 5: assertions")
    print("=" * 60)

    db_path = Path(env.get("AWP_UI_DB_PATH") or (Path.home() / ".awp" / "awp_ui.db"))
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, run_role, loss, status FROM runs WHERE task_id = ? ORDER BY created_at",
        (f"{exp_id}:{task_id}",),
    ).fetchall()
    task = con.execute(
        "SELECT best_run_id, best_reason FROM tasks WHERE id = ?",
        (f"{exp_id}:{task_id}",),
    ).fetchone()
    con.close()

    print(f"\nRuns for task {task_id}:")
    for r in rows:
        loss_str = f"{r['loss']:.3f}" if r["loss"] is not None else "—"
        print(f"  {r['id'][:12]}  role={r['run_role']:<20} status={r['status']:<10} loss={loss_str}")

    roles = {r["run_role"] for r in rows}
    print(f"\nDistinct roles observed: {sorted(roles)}")
    print(f"Task BEST: {task['best_run_id']} (reason: {task['best_reason']})")

    assert "seed" in roles, "seed run missing"
    assert "refine_iter" in roles, "refine iterations missing"
    assert "optimize_epoch_run" in roles, "optimize epoch runs missing"
    assert task["best_run_id"] is not None, "BEST not set"

    print("\n" + "=" * 60)
    print("✓ All three optimizers fired, all three roles present in DB, BEST set.")
    print("  Experiment dir:", Path("/tmp/awp-experiments") / exp_id)
    print("  UI:              http://127.0.0.1:8420")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
