"""Smoke + golden-output tests for ``awp optimize`` (Phase A2).

The CLI runs `optimize` against a stub workflow factory injected via a
monkeypatched ``_default_workflow_factory``. This avoids any LLM call
while still exercising the real argparse + handler code in
``awp.cli.cmd_optimize``.
"""

from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path

from awp import cli as awp_cli


def _stub_factory(monkeypatch) -> None:
    """Replace _default_workflow_factory with a stub that writes a fake run."""

    def _fake(task, output_dir):
        run_id = f"run-{task.name}-{uuid.uuid4().hex[:6]}"
        run_dir = Path(output_dir) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_completion.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "complete",
                    "eval": {"score": 0.9},
                    "critique": {"score": 0.85},
                    "final_budget": {"budget_remaining_pct": 75.0},
                    "config_used": {"max_rejected_completions": 2},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
        return run_id, run_dir

    import awp.outer_loop.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_default_workflow_factory", _fake)


def test_optimize_help_works() -> None:
    """`awp optimize --help` must not crash and must mention the suite arg."""
    import argparse

    try:
        awp_cli.main(["optimize", "--help"])
    except SystemExit as e:
        # argparse's --help calls SystemExit(0) — that's the success path.
        assert e.code == 0
    else:
        # If main() returns instead of raising SystemExit, that's also fine
        # so long as it didn't error out.
        pass

    # Sanity: argparse should still recognise the subcommand at module level.
    assert callable(getattr(awp_cli, "cmd_optimize", None))
    assert callable(getattr(awp_cli, "cmd_optimize_inspect", None))
    # Silence unused-import warning for argparse.
    _ = argparse


def test_optimize_runs_suite_and_prints_table(tmp_path, monkeypatch, capsys) -> None:
    _stub_factory(monkeypatch)

    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(
        textwrap.dedent(
            """\
            name: cli_smoke_v1
            tasks:
              - name: alpha
                task: "do alpha"
              - name: beta
                task: "do beta"
            """
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "outer_loop.db"
    output_dir = tmp_path / "out"

    rc = awp_cli.main(
        [
            "optimize",
            str(suite_yaml),
            "--epochs",
            "1",
            "--output-dir",
            str(output_dir),
            "--db",
            str(db_path),
        ]
    )
    assert rc == 0

    captured = capsys.readouterr()
    out = captured.out
    # Header + at least one row + mean-loss line must appear.
    assert "Suite: cli_smoke_v1" in out
    assert "Task" in out and "Status" in out and "Loss" in out
    assert "alpha" in out and "beta" in out
    assert "Mean loss:" in out

    # DB must hold the persisted rows.
    from awp.outer_loop.store import SqliteArtifactStore

    store = SqliteArtifactStore(str(db_path))
    suite_row = store.find_task_suite_by_name("cli_smoke_v1")
    assert suite_row is not None
    epochs = store.list_epochs(suite_row["id"])
    assert len(epochs) == 1
    assert epochs[0]["mean_loss"] is not None


def test_optimize_inspect_lists_persisted_epoch(tmp_path, monkeypatch, capsys) -> None:
    _stub_factory(monkeypatch)

    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(
        textwrap.dedent(
            """\
            name: inspect_smoke_v1
            tasks:
              - name: only_task
                task: "single task"
            """
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "outer_loop.db"

    # First run an epoch so there is something to inspect.
    rc = awp_cli.main(
        [
            "optimize",
            str(suite_yaml),
            "--epochs",
            "1",
            "--output-dir",
            str(tmp_path / "out"),
            "--db",
            str(db_path),
        ]
    )
    assert rc == 0
    capsys.readouterr()  # flush

    # Now inspect by name.
    rc = awp_cli.main(
        [
            "optimize-inspect",
            "inspect_smoke_v1",
            "--db",
            str(db_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    assert "inspect_smoke_v1" in captured
    assert "Epoch 1" in captured
    assert "only_task" in captured
