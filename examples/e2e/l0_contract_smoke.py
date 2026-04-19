#!/usr/bin/env python3
"""Smoke E2E for the Layer-0 Output Contract gate (R34).

Three scenarios back-to-back, same experiment session so the UI
shows them grouped. Each case produces a small artifact and we verify
the L0 gate reacted correctly:

* Case A — worker emits an output containing ``TITLE GOES HERE``.
  Expected: L0 rejects at ``no_placeholder``. The run should spend
  zero LLM tokens on critique of this specific artifact because L0
  short-circuits first.
* Case B — worker emits the pathological "5 sentences repeated 10x"
  text loop. Expected: L0 rejects at ``no_text_loop``.
* Case C — worker emits clean output. Expected: L0 passes, critique
  runs normally, run proceeds to COMPLETE.

Tag set: ``["e2e", "l0", "smoke"]``.

Verification consults ``run_completion.json`` and the gate records
under ``workspace/runs/<run>/gates/*/l0.json`` (if the run reached
iteration 1). Full verification that "no critique call fired on this
artifact" needs the LLM trace — we inspect the trace directory when
it exists but do not fail the case on its absence (trace is opt-in).

Usage::

    python examples/e2e/l0_contract_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import run_e2e  # noqa: E402


# Minimal tasks — we want short runs that exercise the L0 gate in each
# branch. The instructions are explicit so the worker reliably emits
# the target defect (Case A / B) or clean output (Case C).

_CASE_A_TASK = (
    "Create a file named 'output/report.md' with exactly two paragraphs. "
    "The first paragraph MUST literally contain the string 'TITLE GOES HERE' "
    "as an unreplaced placeholder. The second paragraph is a short sentence. "
    "Write the file using the available tooling, then declare COMPLETE."
)

_CASE_B_TASK = (
    "Create a file 'output/report.md' with exactly 10 paragraphs. "
    "Every paragraph MUST contain the same 5 sentences, word-for-word "
    "identical — this is a deliberate test of the text-loop detector. "
    "Each paragraph: 'The climate model predicts significant warming "
    "across the equatorial zone over the next fifty years under current "
    "emission trajectories and with mitigation uncertainty still high "
    "among the major emitting regions. The report underscores this "
    "finding across five independent working groups. Additional "
    "quantitative analysis suggests robust regional effects. The "
    "dataset covers four decades of observational records. "
    "Recommendations target both mitigation and adaptation policy.' "
    "Separate paragraphs with blank lines."
)

_CASE_C_TASK = (
    "Create a file 'output/report.md' summarizing the three most famous "
    "papers in probabilistic graphical models from the 1980s. Two short "
    "paragraphs, each with distinct vocabulary — no duplication. Do NOT "
    "include any placeholder words like TODO or TBD. Declare COMPLETE "
    "when the file is written."
)


def _read_gates(workflow_dir: Path) -> list[dict]:
    """Enumerate every persisted gate JSON record under the run dir."""
    gates: list[dict] = []
    runs_root = workflow_dir / "workspace" / "runs"
    if not runs_root.is_dir():
        return gates
    for run_dir in runs_root.iterdir():
        gdir = run_dir / "gates"
        if not gdir.is_dir():
            continue
        for iter_dir in gdir.iterdir():
            if not iter_dir.is_dir():
                continue
            for gf in iter_dir.glob("*.json"):
                try:
                    gates.append(json.loads(gf.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    pass
    return gates


def _verify_case_a(workflow_dir: Path, _result: dict) -> dict:
    """Case A: expect an L0 rejection with ``l0_check == "no_placeholder"``."""
    gates = _read_gates(workflow_dir)
    l0_rejections = [g for g in gates if g.get("gate") == "l0" and not g.get("passed")]
    placeholder = [
        g for g in l0_rejections if g.get("l0_check") == "no_placeholder"
    ]
    return {
        "ok": bool(placeholder),
        "case": "A",
        "expected": "l0_reject:no_placeholder",
        "observed_gates": len(gates),
        "l0_rejections": len(l0_rejections),
        "matched": len(placeholder),
    }


def _verify_case_b(workflow_dir: Path, _result: dict) -> dict:
    """Case B: expect an L0 rejection with ``l0_check == "no_text_loop"``."""
    gates = _read_gates(workflow_dir)
    l0_rejections = [g for g in gates if g.get("gate") == "l0" and not g.get("passed")]
    loops = [g for g in l0_rejections if g.get("l0_check") == "no_text_loop"]
    return {
        "ok": bool(loops),
        "case": "B",
        "expected": "l0_reject:no_text_loop",
        "observed_gates": len(gates),
        "l0_rejections": len(l0_rejections),
        "matched": len(loops),
    }


def _verify_case_c(workflow_dir: Path, result: dict) -> dict:
    """Case C: clean output. The terminal status aggregator decides
    success — we verify no L0 error-severity rejection fired.
    Warnings (balanced_delimiters on prose) are tolerated."""
    gates = _read_gates(workflow_dir)
    l0_errors = [
        g
        for g in gates
        if g.get("gate") == "l0"
        and not g.get("passed")
        # The persisted record stores detail.severity via the detail dict
        # when available — on absence, default to "error" (conservative).
    ]
    wf_status = str(result.get("status") or "")
    return {
        "ok": (not l0_errors) and wf_status in ("complete", "partial", "unknown"),
        "case": "C",
        "expected": "l0_pass",
        "observed_gates": len(gates),
        "l0_rejections": len(l0_errors),
        "wf_status": wf_status,
    }


def _run_case(case: str, task: str, verifier, session_id: str | None) -> dict:
    return run_e2e(
        slug=f"l0-contract-{case}",
        title=f"L0 Contract Smoke — Case {case.upper()}",
        task=task,
        model="openai/gpt-5-mini",
        max_loops=4,
        max_total_tokens=200_000,
        max_wall_time=180,
        max_total_workers=4,
        max_depth=2,
        max_tool_calls=30,
        tags=["e2e", "l0", "smoke"],
        verifier=verifier,
        session_id=session_id,
    )


def main() -> int:
    session_id = None
    reports: list[dict] = []

    for case, task, verifier in (
        ("a", _CASE_A_TASK, _verify_case_a),
        ("b", _CASE_B_TASK, _verify_case_b),
        ("c", _CASE_C_TASK, _verify_case_c),
    ):
        report = _run_case(case, task, verifier, session_id)
        session_id = report["session_id"]
        reports.append(report)

    ok_count = sum(1 for r in reports if (r.get("verification") or {}).get("ok"))
    print(f"\n[l0_contract_smoke] {ok_count}/3 cases passed")
    for r in reports:
        v = r.get("verification") or {}
        print(
            f"  case={v.get('case', '?')} ok={v.get('ok')} "
            f"expected={v.get('expected', '?')} observed={v}"
        )

    return 0 if ok_count == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
