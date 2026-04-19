#!/usr/bin/env python3
"""Smoke E2E for the Deterministic Phase Runner (R33, Phase 2).

Exercises the full R33 pipeline end-to-end in the DAG engine:

1. One LLM agent (``drafter``) produces a short JSON artifact with a
   structured ``body`` field via the AWP runtime.
2. A deterministic phase (``assemble``) reads the draft JSON from the
   DAG state, wraps the body in a fixed Markdown template, and writes
   ``final.txt`` under ``${output}``.
3. The phase's invariants check that the output exists, is within the
   expected size range, and contains no residual ``TODO`` placeholders.

Tag set: ``["e2e", "deterministic-phase", "smoke"]``.

This E2E is **domain-agnostic**: no PDFs, no LaTeX, no Docker, no
external services. It only demonstrates the protocol — LLM draft ->
deterministic assembly -> invariant check — for an arbitrary
text-manipulation task.

Usage::

    python examples/e2e/deterministic_phase_smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (  # noqa: E402
    E2E_BASE_DIR,
    finalize_experiment,
    load_openrouter_key,
    register_experiment,
)

# ---------------------------------------------------------------------------
# Workflow scaffolding — written fresh into a tmp experiment dir so the
# run is fully reproducible. We deliberately avoid touching
# examples/workflows/ to keep the repo clean.
# ---------------------------------------------------------------------------


_WORKFLOW_YAML = """\
awp: "1.0.0"

workflow:
  name: deterministic-phase-smoke
  version: "1.0.0"
  description: "Smoke E2E for the R33 deterministic phase runner"
  author: "AWP E2E"
  tags: ["e2e", "deterministic-phase", "smoke"]

orchestration:
  engine: dag
  execution:
    mode: sequential
    timeout:
      per_agent: 120
      total: 300
  graph:
    - id: drafter
      agent: drafter
      depends_on: []
      share_output:
        - body
        - confidence
  phases:
    - id: assemble
      type: deterministic
      depends_on: [drafter]
      callable: deterministic_smoke_assembler:build_final
      args:
        body: "${state.drafter.body}"
        output_path: "${output}/final.txt"
        title: "AWP R33 Smoke"
      timeout_s: 60
      invariants:
        - kind: file_exists
          path: "${output}/final.txt"
        - kind: file_size_range
          path: "${output}/final.txt"
          min_bytes: 20
          max_bytes: 5000
        - kind: regex_absent
          path: "${output}/final.txt"
          pattern: "TODO|XXX|FIXME"

state:
  model: shared_dict
  sharing:
    strategy: full
"""


_AGENT_YAML = """\
awp_agent: "1.0.0"

identity:
  id: drafter
  role: draft_writer
  description: "Writes a short JSON draft with a 'body' field"

model:
  name: ""
  parameters:
    temperature: 0.3
    max_tokens: 256

prompt:
  system: "workflow/instructions/SYSTEM_PROMPT.md"
  user_template: "workflow/prompt/00_INTRO.md"

output:
  format: json
  schema: "workflow/output_schema/output_schema.json"
  contract:
    body:
      type: string
      description: "A single-paragraph body text"
      required: true
    confidence:
      type: number
      minimum: 0.0
      maximum: 1.0
      required: true
  validation:
    mode: strict
    on_invalid: retry
    max_retries: 2
"""


_SYSTEM_PROMPT = """\
You write a single short paragraph (2-4 sentences) describing the AWP
Compiler Layer — the idea that deterministic phases should assemble
artifacts from LLM drafts rather than burning tokens on mechanical
string manipulation. Keep it general, do not include the literal words
TODO, XXX, FIXME, or placeholder. Return JSON with 'body' (the
paragraph) and 'confidence' (0.0-1.0) only.
"""


_USER_TEMPLATE = """\
Task: {{task}}
Return the JSON described in the system prompt. No prose outside JSON.
"""


_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "body": {"type": "string", "description": "Short paragraph"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["body", "confidence"],
}


_OUTPUT_SCHEMA_DESC = {
    "body": "Short paragraph describing the AWP Compiler Layer.",
    "confidence": "Model confidence in [0.0, 1.0].",
}


_ASSEMBLER_PY = '''\
"""Deterministic assembler for the R33 smoke E2E.

This module is deliberately pure: no LLM imports, no network, no
domain-specific code. It demonstrates the R33 contract — take an LLM
draft's structured field, wrap it in a fixed template, and write a
file. The DAG runner dispatches it after the LLM agent completes.
"""

from __future__ import annotations

from pathlib import Path


def build_final(body: str, output_path: str, title: str = "") -> dict:
    """Wrap ``body`` in a Markdown template and write to ``output_path``.

    Returns an exit-code-bearing dict for the exit_code invariant.
    """
    body = (body or "").strip() or "(empty draft)"
    title = title or "Untitled"
    content = (
        f"# {title}\\n\\n"
        f"{body}\\n\\n"
        f"---\\nGenerated by AWP deterministic phase.\\n"
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return {
        "exit_code": 0,
        "output_path": str(out),
        "bytes_written": len(content.encode("utf-8")),
    }
'''


def _scaffold_workflow(base_dir: Path) -> None:
    """Write the minimal workflow directory tree under ``base_dir``."""
    (base_dir / "workflow.awp.yaml").write_text(_WORKFLOW_YAML, encoding="utf-8")

    agent_dir = base_dir / "agents" / "drafter"
    wf = agent_dir / "workflow"
    for sub in ("instructions", "prompt", "output_schema", "output_schema_desc"):
        (wf / sub).mkdir(parents=True, exist_ok=True)

    (agent_dir / "agent.awp.yaml").write_text(_AGENT_YAML, encoding="utf-8")
    (wf / "instructions" / "SYSTEM_PROMPT.md").write_text(
        _SYSTEM_PROMPT, encoding="utf-8"
    )
    (wf / "prompt" / "00_INTRO.md").write_text(_USER_TEMPLATE, encoding="utf-8")
    (wf / "output_schema" / "output_schema.json").write_text(
        json.dumps(_OUTPUT_SCHEMA, indent=2), encoding="utf-8"
    )
    (wf / "output_schema_desc" / "output_schema_desc.json").write_text(
        json.dumps(_OUTPUT_SCHEMA_DESC, indent=2), encoding="utf-8"
    )

    # The deterministic callable lives as a sibling module importable
    # from the experiment dir (we'll prepend the dir to sys.path before
    # invoking the runner).
    (base_dir / "deterministic_smoke_assembler.py").write_text(
        _ASSEMBLER_PY, encoding="utf-8"
    )


def _verify(workflow_dir: Path, run_state: dict) -> dict:
    """Verification: run.complete, phase.complete, final.txt sane."""
    # Find the output directory — run_id is keyed into path.
    out_root = workflow_dir / "output"
    run_dirs = [p for p in out_root.iterdir() if p.is_dir()] if out_root.exists() else []
    if not run_dirs:
        return {"ok": False, "reason": "no output dir"}
    # The single run will own the first (and only) output dir.
    run_dir = run_dirs[0]
    final = run_dir / "final.txt"
    phase_dir = run_dir / "phase_assemble"
    phase_result_path = phase_dir / "result.json"

    checks = {
        "final_exists": final.is_file(),
        "final_nonempty": final.is_file() and final.stat().st_size > 0,
        "phase_result_exists": phase_result_path.is_file(),
    }
    phase_status = None
    invariants_ok = None
    if phase_result_path.is_file():
        try:
            phase = json.loads(phase_result_path.read_text(encoding="utf-8"))
            phase_status = phase.get("status")
            invariants_ok = all(
                (i.get("ok") is True) for i in phase.get("invariants", [])
            )
        except json.JSONDecodeError:
            phase_status = "unparseable"
    checks["phase_status_complete"] = phase_status == "complete"
    checks["all_invariants_ok"] = bool(invariants_ok)

    # No TODOs — the regex_absent invariant already guarantees this but
    # we double-check from the E2E side to catch any silent skip.
    content = final.read_text(encoding="utf-8") if final.is_file() else ""
    checks["no_todo"] = "TODO" not in content and "FIXME" not in content

    ok = all(checks.values())
    return {
        "ok": ok,
        "checks": checks,
        "phase_status": phase_status,
        "final_path": str(final),
    }


def main() -> int:
    load_openrouter_key()

    # Prepare experiment directory.
    import uuid
    from datetime import datetime

    E2E_BASE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    workflow_dir = E2E_BASE_DIR / f"deterministic-phase-smoke-{ts}-{uuid.uuid4().hex[:6]}"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    _scaffold_workflow(workflow_dir)

    # Make the assembler module importable for both the DAG runner and
    # the validator's R33 static check.
    sys.path.insert(0, str(workflow_dir))
    # Clear any cached module name from a previous run in the same session.
    sys.modules.pop("deterministic_smoke_assembler", None)

    title = "Deterministic Phase Smoke (R33)"
    task = (
        "Draft a single paragraph explaining why deterministic phases belong "
        "between the LLM inner loop and the outer optimiser."
    )
    model = os.environ.get("AWP_E2E_MODEL", "openai/gpt-5-mini")
    config = {
        "slug": "deterministic-phase-smoke",
        "title": title,
        "model": model,
        "engine": "dag",
        "workflow_dir": str(workflow_dir),
    }
    session_id, run_id = register_experiment(
        title=title,
        task=task,
        model=model,
        base_dir=str(workflow_dir),
        config=config,
        tags=["e2e", "deterministic-phase", "smoke"],
    )
    print(f"[e2e] slug=deterministic-phase-smoke session={session_id} run={run_id}")
    print(f"[e2e] workflow_dir={workflow_dir}")

    from awp.runtime import WorkflowRunner

    runner = WorkflowRunner(workflow_dir, worker_model=model)
    # The drafter has an empty model.name — inject a default.
    if runner._llm is None:
        from awp.runtime.llm import LLMClient

        runner._llm = LLMClient(model=model)

    status = "failed"
    result: dict = {}
    try:
        result = runner.run(task)
        phases = result.get("_phases") or []
        phase_status = result.get("_phase_status")
        print(f"[e2e] run complete. phases={len(phases)}  phase_status={phase_status}")
        if phase_status == "failed":
            status = "failed"
        elif phase_status == "partial":
            status = "partial"
        else:
            status = "complete"
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(f"[e2e] exception: {exc}\n{traceback.format_exc()}", file=sys.stderr)
        status = "failed"

    verification = _verify(workflow_dir, result)
    finalize_experiment(session_id, run_id, status, result)
    verify_ok = bool(verification.get("ok"))
    if verify_ok and status == "partial":
        status = "complete"
        finalize_experiment(session_id, run_id, status, result)

    line = "PASS" if (status == "complete" and verify_ok) else "FAIL"
    print(f"[e2e] {line} status={status} verify={verify_ok}")
    print(f"[e2e] verification: {json.dumps(verification, indent=2)}")

    # Persist the report.
    try:
        (workflow_dir / "e2e_report.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "verify_ok": verify_ok,
                    "verification": verification,
                    "session_id": session_id,
                    "run_id": run_id,
                    "workflow_dir": str(workflow_dir),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    # Best-effort cleanup of sys.path pollution from this run.
    try:
        sys.path.remove(str(workflow_dir))
    except ValueError:
        pass
    # Don't auto-delete the experiment dir — the UI reads it from here.
    _ = shutil  # kept for future cleanup hooks

    return 0 if (status == "complete" and verify_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
