"""E2E tests — runs each autonomy-level notebook (A0-A4) against real LLMs.

Each notebook under ``examples/jupyter/autonomy-levels/A{N}.ipynb`` is
executed via ``jupyter nbconvert --execute``. The run PASSES when every
cell executes without raising (the notebook's own assertion cell is the
rubric). A failing cell propagates as a ``CellExecutionError`` from
nbclient and this test reports which cell failed.

Preconditions:
  * ``OPENROUTER_API_KEY`` is in the environment or in
    ``/home/shumway/projects/meta-agents/.env`` (the notebooks load it
    themselves).
  * ``jupyter`` + ``nbconvert`` + ``ipykernel`` installed.

These tests are tagged ``e2e`` (see CLAUDE.md E2E rules) and are
deselected by ``-k "not e2e"``. Per-level timeouts mirror the expected
runtime documented in the notebooks' README.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK_DIR = REPO_ROOT / "examples" / "jupyter" / "autonomy-levels"
OUTPUT_DIR = Path("/tmp/awp-autonomy-notebook-runs")


LEVELS = [
    ("A0", 180),   # ~30s expected; 3 min buffer
    ("A1", 360),   # ~60s expected; 6 min buffer
    ("A2", 720),   # ~2 min expected; 12 min buffer
    ("A3", 1200),  # ~5 min expected; 20 min buffer
    ("A4", 1800),  # ~10 min expected; 30 min buffer
]


def _require_api_key() -> None:
    if os.environ.get("OPENROUTER_API_KEY"):
        return
    env_path = Path("/home/shumway/projects/meta-agents/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return
    pytest.skip("OPENROUTER_API_KEY not available")


def _require_jupyter() -> None:
    if shutil.which("jupyter") is None:
        pytest.skip("jupyter not installed in this environment")


@pytest.mark.e2e
@pytest.mark.parametrize("level,timeout", LEVELS)
def test_autonomy_notebook_runs(level: str, timeout: int) -> None:
    """Execute A{level}.ipynb end-to-end and assert no cell raised."""
    _require_api_key()
    _require_jupyter()

    notebook = NOTEBOOK_DIR / f"{level}.ipynb"
    assert notebook.exists(), f"notebook missing: {notebook}"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_name = f"{level}_out.ipynb"

    cmd = [
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        "--output",
        out_name,
        "--output-dir",
        str(OUTPUT_DIR),
        str(notebook),
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(REPO_ROOT),
    )
    out_path = OUTPUT_DIR / out_name

    if proc.returncode != 0:
        # nbconvert writes CellExecutionError to stderr — surface it
        msg = (
            f"{level} notebook failed (rc={proc.returncode}).\n"
            f"stderr:\n{proc.stderr[-4000:]}\n"
            f"stdout:\n{proc.stdout[-1000:]}"
        )
        pytest.fail(msg)

    assert out_path.exists(), f"no output notebook at {out_path}"
