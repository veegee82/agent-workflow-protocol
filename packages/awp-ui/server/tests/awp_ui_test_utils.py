"""Shared helpers for Plan 7 UI tests (no LLM, no side-effects)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def _seed_experiment_task(tmp_path: Path) -> tuple[str, str, Path]:
    """Construct fake experiment + task directory structure. Returns (exp_id, task_key, seed_output_dir)."""
    exp_id = str(uuid.uuid4())[:8]
    tid = str(uuid.uuid4())[:8]
    seed_output = tmp_path / exp_id / "tasks" / tid / "seed"
    seed_output.mkdir(parents=True, exist_ok=True)
    return exp_id, f"{exp_id}:{tid}", seed_output


def _mk_fake_run(base: Path, run_id: str, score: float) -> None:
    run_dir = base / "output" / "workspace" / "runs" / run_id
    # Also create at the simpler output/<run_id> path for older callers
    simple = base / "output" / run_id
    for rd in (run_dir, simple):
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "run_completion.json").write_text(json.dumps({
            "run_id": run_id, "status": "complete", "task": "t",
            "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
            "eval": {"score": score}, "critique": {"defects": []}, "gate_rejections": 0,
        }))
        (rd / "events.jsonl").write_text("")
        (rd / "metrics.jsonl").write_text("")
        (rd / "FINAL").mkdir(exist_ok=True)
        (rd / "FINAL" / "paper.md").write_text(f"run={run_id}")
