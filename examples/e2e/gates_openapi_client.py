"""E2E Test 1 — Schema-bound OpenAPI + Python client.

Exercises the new completion gates:
- syntax_compile  (validates .py / .json / .md)
- schema          (validates openapi.json against a declared JSON-Schema)
- success_criteria (checkbox items in the task are advisory-checked)
- deliverable_presence (required_outputs must all exist, non-empty)

Low-complexity scenario: single manager, no submanager needed, but the
manager MUST produce three interdependent files that all pass gates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402

TASK = """## Ziel
Entwirf eine minimale **Aufgabenverwaltungs-API** als OpenAPI-3-Spec und
erzeuge einen passenden Python-Client als Stub. Alle Artefakte sollen
**deterministisch prüfbar** sein.

## Liefergegenstände (Pfade relativ zu _output_dir)
- [ ] _output_dir/openapi.json — OpenAPI-3.0.3 Spec mit mindestens den Endpoints
      `GET /tasks`, `POST /tasks`, `GET /tasks/{id}`, `DELETE /tasks/{id}`,
      vollständigem `components.schemas.Task`.
- [ ] _output_dir/client.py — Python-Modul mit einer Klasse `TaskClient` und den
      vier Methoden `list_tasks`, `create_task`, `get_task`, `delete_task`.
      Nur Standard-Library und `requests`. Keine externe Ausführung.
- [ ] _output_dir/README.md — enthält ein `## Usage`-Abschnitt mit
      einem Python-Code-Block, der `TaskClient` importiert und aufruft.

## Erfolgskriterien
- `_output_dir/openapi.json` ist valides JSON.
- `openapi.json` enthält die Literale `"openapi"`, `"paths"`, `"components"`.
- `_output_dir/client.py` hat keinen SyntaxError.
- `_output_dir/README.md` enthält die Zeichenkette `TaskClient` und einen geschlossenen Code-Fence.

## Hinweise
Schreibe die Dateien in `_output_dir`. Verwende keine Platzhalter wie
`TODO`, `XX%`, `???`. Wenn dein Plan Subtasks deklariert, trage
`required_outputs: ["openapi.json", "client.py", "README.md"]` in
**mindestens einem Subtask** ein, damit die Deliverable-Gates die Pfade
finden.
"""


# JSON-Schema for openapi.json — drives the new schema_gate.
OPENAPI_JSON_SCHEMA = {
    "type": "object",
    "required": ["openapi", "info", "paths", "components"],
    "properties": {
        "openapi": {"type": "string", "pattern": r"^3\."},
        "info": {
            "type": "object",
            "required": ["title", "version"],
        },
        "paths": {
            "type": "object",
            "minProperties": 4,
        },
        "components": {
            "type": "object",
            "required": ["schemas"],
            "properties": {
                "schemas": {
                    "type": "object",
                    "required": ["Task"],
                },
            },
        },
    },
}


EXTRA_CONFIG = {
    # Sichtbare Plan-Hints: schema_gate findet diese über _task_plan
    "initial_plan_hints": {
        "required_outputs": ["openapi.json", "client.py", "README.md"],
        "schemas": {"openapi.json": OPENAPI_JSON_SCHEMA},
    },
    # Phase B: strict success_criteria
    "strict_criteria": False,
    # Alle LLM traces an
    "llm_trace": {"enabled": True, "persist": True},
    # Deaktiviere die teuren LLM-basierten Quality-Gates fürs E2E —
    # die neuen Phase-A-Gates (syntax_compile, schema, cross_reference,
    # success_criteria, smoke_test) sollen isoliert getestet werden.
    "critique": {"enabled": False},
    "evaluation": {"enabled": False},
}


def verify(workflow_dir: Path, result: dict) -> dict:
    findings: list[str] = []
    ok = True
    # Find run_dir via canonical_run
    run_dir = None
    canonical = workflow_dir / "canonical_run"
    if canonical.exists():
        run_dir = canonical.resolve()
    if run_dir is None:
        runs = list((workflow_dir / "workspace" / "runs").iterdir())
        if runs:
            run_dir = sorted(runs)[-1]
    if run_dir is None:
        return {"ok": False, "details": ["no run_dir found"]}

    out_dir = run_dir / "output" / run_dir.name
    expected = ["openapi.json", "client.py", "README.md"]
    for name in expected:
        # Search anywhere under out_dir (it may be nested under a timestamp)
        matches = list(out_dir.rglob(name))
        if not matches:
            ok = False
            findings.append(f"missing deliverable: {name}")
            continue
        p = matches[0]
        if p.stat().st_size == 0:
            ok = False
            findings.append(f"empty deliverable: {name}")

    # Quick content checks
    jm = list(out_dir.rglob("openapi.json"))
    if jm:
        try:
            data = json.loads(jm[0].read_text(encoding="utf-8"))
            if "openapi" not in data or "paths" not in data or "components" not in data:
                ok = False
                findings.append("openapi.json missing top-level keys")
            elif len(data.get("paths", {})) < 4:
                ok = False
                findings.append(
                    f"openapi.json has only {len(data.get('paths', {}))} paths"
                )
        except Exception as exc:
            ok = False
            findings.append(f"openapi.json invalid: {exc}")

    cp = list(out_dir.rglob("client.py"))
    if cp:
        src = cp[0].read_text(encoding="utf-8")
        if "TaskClient" not in src:
            ok = False
            findings.append("client.py missing TaskClient class")
        try:
            import ast
            ast.parse(src)
        except SyntaxError as exc:
            ok = False
            findings.append(f"client.py SyntaxError: {exc}")

    # Scorecard check — Phase D
    sc = run_dir / "deliverable_scorecard.json"
    if sc.exists():
        try:
            scd = json.loads(sc.read_text(encoding="utf-8"))
            findings.append(
                f"scorecard: {scd.get('deliverables_verified')}/"
                f"{scd.get('deliverables_total')} verified, "
                f"verified={scd.get('verified')}"
            )
        except Exception:
            pass

    return {"ok": ok, "details": findings}


if __name__ == "__main__":
    report = run_e2e(
        slug="gates-openapi-client",
        title="Gates E2E 1: OpenAPI + Python client",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=10,
        max_total_tokens=1_500_000,
        max_wall_time=1500,
        max_total_workers=30,
        max_depth=0,  # disable all submanager spawning
        max_tool_calls=500,
        extra_config=EXTRA_CONFIG,
        verifier=verify,
        tags=["e2e", "gates", "schema", "syntax_compile", "quick"],
    )
    print("\n[e2e] FINAL REPORT")
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report.get("status") == "complete" else 1)
