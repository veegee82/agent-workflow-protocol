"""Tests for the Deterministic Phase Runner (R33, Phase 2).

Cover the six normative invariant kinds (positive + negative where
meaningful), the timeout path, secret-scrubbing, and the R33 runtime
purity guard. The runner is always invoked through the public
``DeterministicPhaseRunner.run`` entry point — tests do not reach into
private methods.

The callable-under-test is materialised as a throwaway ``*.py`` file
under ``tmp_path`` and imported via ``sys.path`` manipulation inside a
single test-scope fixture. This mirrors the real usage pattern where a
workflow ships its own Python module alongside the YAML.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from awp.models.orchestration import DeterministicPhase, Invariant
from awp.runtime.deterministic import (
    DeterministicPhaseRunner,
    ExecutionContext,
)

# ---------------------------------------------------------------------------
# Fixture: a throwaway module with a handful of deterministic callables.
# ---------------------------------------------------------------------------


@pytest.fixture
def user_module(tmp_path, monkeypatch):
    """Write a Python module to tmp_path and make it importable.

    The module exposes:
      * ``write_file(path, body)``    -> writes body to path
      * ``sleepy(secs)``              -> sleeps to trigger timeouts
      * ``assert_no_api_key()``       -> raises if OPENROUTER_API_KEY is set
      * ``returns_exit_code(code)``   -> returns ``{"exit_code": code}``
      * ``verify_truthy(result)``     -> python_predicate positive
      * ``verify_falsy(result)``      -> python_predicate negative
    """
    mod_dir = tmp_path / "pkg"
    mod_dir.mkdir()
    (mod_dir / "__init__.py").write_text("")
    (mod_dir / "callable.py").write_text(
        textwrap.dedent(
            '''
            import os
            import time
            from pathlib import Path


            def write_file(path: str, body: str) -> dict:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(body, encoding="utf-8")
                return {"exit_code": 0, "bytes": len(body)}


            def sleepy(secs: float = 5.0) -> dict:
                time.sleep(float(secs))
                return {"exit_code": 0}


            def assert_no_api_key() -> dict:
                leaked = [
                    k for k in os.environ
                    if any(s in k for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
                ]
                if leaked:
                    raise AssertionError(
                        "secret env vars leaked to deterministic phase: "
                        + ",".join(leaked)
                    )
                return {"exit_code": 0, "scrubbed": True}


            def returns_exit_code(code: int = 0) -> dict:
                return {"exit_code": int(code)}


            def verify_truthy(result: dict) -> bool:
                return True


            def verify_falsy(result: dict) -> bool:
                return False
            '''
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    # ensure pristine import each test
    for k in list(sys.modules):
        if k.startswith("pkg"):
            sys.modules.pop(k, None)
    yield "pkg.callable"
    for k in list(sys.modules):
        if k.startswith("pkg"):
            sys.modules.pop(k, None)


def _ctx(tmp_path: Path, state: dict | None = None) -> ExecutionContext:
    ws = tmp_path / "workspace"
    out = tmp_path / "output" / "run123"
    ws.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    return ExecutionContext(
        workflow_dir=tmp_path,
        workspace_dir=ws,
        output_dir=out,
        state=dict(state or {}),
    )


def _runner(tmp_path: Path) -> DeterministicPhaseRunner:
    return DeterministicPhaseRunner(workflow_dir=tmp_path)


# ---------------------------------------------------------------------------
# 1. file_exists
# ---------------------------------------------------------------------------


def test_file_exists_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "artifact.txt"
    phase = DeterministicPhase(
        id="write",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "hello"},
        invariants=[Invariant(kind="file_exists", path="${output}/artifact.txt")],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete", r
    assert r.invariants[0].ok
    assert r.invariants[0].kind == "file_exists"


def test_file_exists_fail_missing(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "not_written.txt"
    phase = DeterministicPhase(
        id="check",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 0},
        invariants=[Invariant(kind="file_exists", path=str(out_file))],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "invariant_file_exists_violated"


# ---------------------------------------------------------------------------
# 2. file_size_range
# ---------------------------------------------------------------------------


def test_file_size_range_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "sized.txt"
    body = "x" * 1000
    phase = DeterministicPhase(
        id="size",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": body},
        invariants=[
            Invariant(
                kind="file_size_range",
                path=str(out_file),
                min_bytes=500,
                max_bytes=5000,
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete", r


def test_file_size_range_fail(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "tiny.txt"
    phase = DeterministicPhase(
        id="size",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "xx"},
        invariants=[
            Invariant(
                kind="file_size_range",
                path=str(out_file),
                min_bytes=1_000,
                max_bytes=10_000,
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "invariant_file_size_range_violated"


# ---------------------------------------------------------------------------
# 3. regex_absent
# ---------------------------------------------------------------------------


def test_regex_absent_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "clean.txt"
    phase = DeterministicPhase(
        id="clean",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "All real content, no placeholders."},
        invariants=[
            Invariant(
                kind="regex_absent",
                path=str(out_file),
                pattern=r"TODO|XXX|FIXME",
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete"


def test_regex_absent_fail(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "dirty.txt"
    phase = DeterministicPhase(
        id="dirty",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "Still has TODO markers"},
        invariants=[
            Invariant(
                kind="regex_absent",
                path=str(out_file),
                pattern=r"TODO|XXX|FIXME",
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "invariant_regex_absent_violated"


# ---------------------------------------------------------------------------
# 4. regex_present
# ---------------------------------------------------------------------------


def test_regex_present_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "signed.txt"
    phase = DeterministicPhase(
        id="signed",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "Author: Alice\n"},
        invariants=[
            Invariant(
                kind="regex_present",
                path=str(out_file),
                pattern=r"^Author: ",
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete"


def test_regex_present_fail(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    out_file = ctx.output_dir / "unsigned.txt"
    phase = DeterministicPhase(
        id="unsigned",
        callable=f"{user_module}:write_file",
        args={"path": str(out_file), "body": "No author line"},
        invariants=[
            Invariant(
                kind="regex_present",
                path=str(out_file),
                pattern=r"^Author: ",
            )
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"


# ---------------------------------------------------------------------------
# 5. exit_code
# ---------------------------------------------------------------------------


def test_exit_code_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="ec_ok",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 0},
        invariants=[Invariant(kind="exit_code", expected=0)],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete"


def test_exit_code_fail(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="ec_bad",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 7},
        invariants=[Invariant(kind="exit_code", expected=0)],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "invariant_exit_code_violated"


# ---------------------------------------------------------------------------
# 6. python_predicate
# ---------------------------------------------------------------------------


def test_python_predicate_pass(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="pred_ok",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 0},
        invariants=[
            Invariant(kind="python_predicate", module=user_module, function="verify_truthy")
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete"


def test_python_predicate_fail(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="pred_fail",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 0},
        invariants=[
            Invariant(kind="python_predicate", module=user_module, function="verify_falsy")
        ],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_returns_partial(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="slow",
        callable=f"{user_module}:sleepy",
        args={"secs": 5.0},
        timeout_s=1,
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "deterministic_timeout"


def test_max_wall_time_s_returns_phase_timeout(tmp_path, user_module):
    """Phase 3.2 — the generic ``max_wall_time_s`` field applies the
    same timeout enforcement but surfaces ``reason=phase_timeout`` so
    downstream tooling can distinguish a per-phase budget breach from
    the deterministic-only ``timeout_s`` legacy path.

    Spec: ``max_wall_time_s`` overrides ``timeout_s`` when both are
    set; a 1-second budget on a 5-second callable returns ``partial``.
    """
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="slow_generic",
        callable=f"{user_module}:sleepy",
        args={"secs": 5.0},
        # timeout_s is left at the generous default so the assertion is
        # purely about max_wall_time_s taking precedence.
        timeout_s=300,
        max_wall_time_s=1,
    )
    # Property surface is consistent.
    assert phase.effective_timeout_s == 1
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "partial"
    assert r.reason == "phase_timeout"


# ---------------------------------------------------------------------------
# Secret scrubbing
# ---------------------------------------------------------------------------


def test_secrets_are_scrubbed_from_child(tmp_path, user_module, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "leak-this-if-broken")
    monkeypatch.setenv("SOMETHING_TOKEN", "also-leak-this")
    monkeypatch.setenv("COMPLETELY_NORMAL", "preserved")
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="env",
        callable=f"{user_module}:assert_no_api_key",
        args={},
        invariants=[Invariant(kind="exit_code", expected=0)],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "complete", (r.status, r.reason, r.stderr)


# ---------------------------------------------------------------------------
# Unknown invariant kind
# ---------------------------------------------------------------------------


def test_unknown_invariant_kind_fails(tmp_path, user_module):
    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(
        id="unk",
        callable=f"{user_module}:returns_exit_code",
        args={"code": 0},
    )
    # bypass Pydantic invariant validation by mutating after construction
    # — simulates a registered-but-removed kind from a future runtime.
    object.__setattr__(
        phase,
        "invariants",
        [Invariant.model_construct(kind="totally_fake_kind")],
    )
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "failed"
    assert r.reason == "unknown_invariant_kind"


# ---------------------------------------------------------------------------
# R33 runtime purity guard (mirrors validator static check)
# ---------------------------------------------------------------------------


def test_r33_runtime_purity_rejects_openai_import(tmp_path, monkeypatch):
    """A callable whose source imports ``openai`` is rejected at runtime."""
    pkg = tmp_path / "imp_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "bad.py").write_text(
        "try:\n"
        "    import openai\n"
        "except ImportError:\n"
        "    openai = None\n"
        "\n"
        "def build():\n"
        "    return {'exit_code': 0}\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    # clean import cache
    for k in list(sys.modules):
        if k.startswith("imp_pkg"):
            sys.modules.pop(k, None)

    ctx = _ctx(tmp_path)
    phase = DeterministicPhase(id="impure", callable="imp_pkg.bad:build")
    r = _runner(tmp_path).run(phase, ctx)
    assert r.status == "failed"
    assert "R33" in r.reason or "openai" in r.reason


# ---------------------------------------------------------------------------
# DAG-runner integration: a phase-only workflow runs end-to-end and
# persists its artifacts to ``output/<run_id>/phase_<id>/``.
# ---------------------------------------------------------------------------


def test_dag_runner_dispatches_phases_post_graph(tmp_path, monkeypatch):
    """An ``engine: dag`` workflow with no graph + one deterministic phase
    completes via :class:`WorkflowRunner` and writes the expected
    artifact, result.json, and stdout.log under the run output dir.
    """
    base = tmp_path / "wf"
    base.mkdir()
    (base / "workflow.awp.yaml").write_text(
        textwrap.dedent(
            """
            awp: "1.0.0"
            workflow:
              name: wf
              version: "1.0.0"
              description: integration smoke
            orchestration:
              engine: dag
              graph: []
              phases:
                - id: write
                  type: deterministic
                  callable: mock_assembler:run
                  args:
                    body: "integration output"
                    output_path: ${output}/out.txt
                  invariants:
                    - kind: file_exists
                      path: ${output}/out.txt
                    - kind: regex_absent
                      path: ${output}/out.txt
                      pattern: TODO
            """
        ),
        encoding="utf-8",
    )
    (base / "mock_assembler.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path
            def run(body, output_path):
                p = Path(output_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                return {"exit_code": 0, "bytes": len(body)}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(base))
    for k in list(sys.modules):
        if k.startswith("mock_assembler"):
            sys.modules.pop(k, None)

    from awp.runtime import WorkflowRunner

    runner = WorkflowRunner(base)
    state = runner.run("integration test")

    phases = state.get("_phases", [])
    assert len(phases) == 1
    assert phases[0]["phase_id"] == "write"
    assert phases[0]["status"] == "complete"

    out_root = base / "output"
    run_dirs = list(out_root.iterdir())
    assert len(run_dirs) == 1
    rd = run_dirs[0]
    assert (rd / "out.txt").is_file()
    assert (rd / "out.txt").read_text(encoding="utf-8") == "integration output"
    assert (rd / "phase_write" / "result.json").is_file()
    assert (rd / "phase_write" / "stdout.log").is_file()


def test_dag_runner_phase_topological_order(tmp_path, monkeypatch):
    """Multiple phases are dispatched in topological order of depends_on."""
    base = tmp_path / "wf"
    base.mkdir()
    (base / "workflow.awp.yaml").write_text(
        textwrap.dedent(
            """
            awp: "1.0.0"
            workflow:
              name: wf
              version: "1.0.0"
              description: topological order test
            orchestration:
              engine: dag
              graph: []
              phases:
                - id: second
                  type: deterministic
                  depends_on: [first]
                  callable: mock_chain:append_b
                  args:
                    path: ${output}/chain.txt
                - id: first
                  type: deterministic
                  callable: mock_chain:write_a
                  args:
                    path: ${output}/chain.txt
            """
        ),
        encoding="utf-8",
    )
    (base / "mock_chain.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path
            def write_a(path):
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("A", encoding="utf-8")
                return {"exit_code": 0}
            def append_b(path):
                p = Path(path)
                prev = p.read_text(encoding="utf-8") if p.exists() else ""
                p.write_text(prev + "B", encoding="utf-8")
                return {"exit_code": 0}
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(base))
    for k in list(sys.modules):
        if k.startswith("mock_chain"):
            sys.modules.pop(k, None)

    from awp.runtime import WorkflowRunner

    state = WorkflowRunner(base).run("chain test")
    phase_ids = [p["phase_id"] for p in state.get("_phases", [])]
    assert phase_ids == ["first", "second"], (
        f"phases dispatched out of topological order: {phase_ids}"
    )
    out_root = base / "output"
    (rd,) = list(out_root.iterdir())
    assert (rd / "chain.txt").read_text(encoding="utf-8") == "AB"
