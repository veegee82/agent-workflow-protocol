"""E2E Test 3 — Full-Stack mit Smoke-Test, Sub-Manager und Tool-Creation.

Exercises:
- smoke_test        (RUN.sh runs and exits 0)
- syntax_compile    (.py)
- cross_reference   (README cites numbered test ids)
- success_criteria
- tool_creation     (manager creates a dynamic helper tool)
- delegation        (sub-manager for test execution)
- LLM trace persistence
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402

TASK = """## Ziel
Baue ein **kleines Python-Rechner-Paket** mit ausführbarer Smoke-Test-Suite.
Der Run darf erst `complete` melden, wenn das Smoke-Skript `RUN.sh` grün
durchläuft (Exit 0).

## Liefergegenstände (relativ zu _output_dir)
- [ ] _output_dir/calculator.py — Modul mit vier reinen Funktionen:
      `add(a, b) -> float`, `sub(a, b) -> float`, `mul(a, b) -> float`,
      `div(a, b) -> float`. `div` wirft `ValueError` bei Division durch
      Null. Keine externen Abhängigkeiten, nur `math` erlaubt.
- [ ] _output_dir/test_calculator.py — unittest-basierte Tests mit
      mindestens einem Test pro Funktion (IDs T1 add, T2 sub, T3 mul,
      T4 div-ok, T5 div-by-zero). Insgesamt ≥5 Tests.
- [ ] _output_dir/RUN.sh — Bash-Script das mit
      `python test_calculator.py` die Tests ausführt. Muss ohne Argumente
      aufrufbar sein und bei allen grünen Tests Exit 0 geben.
- [ ] _output_dir/README.md — beschreibt das Paket, listet die Tests als
      nummerierte Liste `1. T1 ...`, `2. T2 ...` und referenziert sie als
      `[1]`, `[2]`, ..., `[5]` im Fließtext; unter `## References` werden
      `[1]`..`[5]` wieder aufgeführt (als Kurzbeschreibung).

## Erfolgskriterien
- `calculator.py` importiert ohne Fehler.
- `test_calculator.py` hat ≥5 Testmethoden.
- `RUN.sh` gibt Exit 0 und ein Zeile enthält `OK` (unittest Standard).
- `README.md` zitiert [1]..[5] und definiert sie alle in `## References`.
- Kein Platzhalter.

## Plan-Hinweise
Dein Task-Plan sollte:
- Subtask mit `required_outputs: ["calculator.py", "test_calculator.py", "RUN.sh", "README.md"]`
- Subtask mit `executable: ["RUN.sh"]` damit das smoke_test-Gate prüft.

Optional (wird getestet): Wenn du einen kleinen dynamic Tool brauchst
(z.B. zum Schreiben + Validieren der Dateien in einem Schritt), darfst
du `tools.factory` nutzen. Nicht Pflicht.
"""


EXTRA_CONFIG = {
    "llm_trace": {"enabled": True, "persist": True},
    # Erlaubt Code-Execution, damit der Manager/Worker Tests selbst aus-
    # führen kann und nicht nur auf smoke_test_gate angewiesen ist.
    "code_mode": {"enabled": True},
    "tool_creation": {"enabled": True},
    "critique": {"enabled": False},
    "evaluation": {"enabled": False},
}


def verify(workflow_dir: Path, result: dict) -> dict:
    findings: list[str] = []
    ok = True
    canonical = workflow_dir / "canonical_run"
    run_dir = canonical.resolve() if canonical.exists() else None
    if run_dir is None:
        runs = list((workflow_dir / "workspace" / "runs").iterdir())
        if runs:
            run_dir = sorted(runs)[-1]
    if run_dir is None:
        return {"ok": False, "details": ["no run_dir"]}

    out_dir = run_dir / "output" / run_dir.name
    must = ["calculator.py", "test_calculator.py", "RUN.sh", "README.md"]
    resolved: dict[str, Path] = {}
    for name in must:
        hits = list(out_dir.rglob(name))
        if not hits:
            ok = False
            findings.append(f"missing: {name}")
        else:
            resolved[name] = hits[0]

    if "calculator.py" in resolved:
        import ast
        try:
            ast.parse(resolved["calculator.py"].read_text(encoding="utf-8"))
        except SyntaxError as exc:
            ok = False
            findings.append(f"calculator.py SyntaxError: {exc}")

    if "test_calculator.py" in resolved:
        txt = resolved["test_calculator.py"].read_text(encoding="utf-8")
        import re
        n = len(re.findall(r"def test_", txt))
        if n < 5:
            ok = False
            findings.append(f"test_calculator.py only has {n} tests, need ≥5")

    if "RUN.sh" in resolved:
        import subprocess
        try:
            proc = subprocess.run(
                ["bash", str(resolved["RUN.sh"])],
                capture_output=True, timeout=30,
                cwd=str(resolved["RUN.sh"].parent),
            )
            if proc.returncode != 0:
                ok = False
                findings.append(
                    f"RUN.sh exit={proc.returncode} stderr_tail="
                    f"{(proc.stderr or b'')[-200:].decode(errors='replace')}"
                )
        except Exception as exc:
            ok = False
            findings.append(f"RUN.sh could not execute: {exc}")

    if "README.md" in resolved:
        txt = resolved["README.md"].read_text(encoding="utf-8")
        import re
        cites = {int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", txt)}
        if not {1, 2, 3, 4, 5} <= cites:
            ok = False
            findings.append(f"README missing required cites, found {cites}")

    # Check tool-creation & submanager evidence
    tool_defs = list((workflow_dir / "shared" / "dynamic_tools").glob("*.json"))
    findings.append(f"dynamic_tools produced: {len(tool_defs)}")
    submanagers = list(run_dir.rglob("result.json"))
    findings.append(f"result.json files (workers+submgrs): {len(submanagers)}")

    sc = run_dir / "deliverable_scorecard.json"
    if sc.exists():
        try:
            d = json.loads(sc.read_text(encoding="utf-8"))
            findings.append(
                f"scorecard: verified={d.get('verified')} "
                f"({d.get('deliverables_verified')}/{d.get('deliverables_total')})"
            )
        except Exception:
            pass

    return {"ok": ok, "details": findings}


if __name__ == "__main__":
    report = run_e2e(
        slug="gates-smoke-delegation",
        title="Gates E2E 3: Smoke + delegation + tool-creation",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=15,
        max_total_tokens=2_500_000,
        max_wall_time=2400,
        max_total_workers=40,
        max_depth=0,  # keep flat — smoke_test + tool_creation still runnable
        max_tool_calls=800,
        extra_config=EXTRA_CONFIG,
        verifier=verify,
        tags=["e2e", "gates", "smoke_test", "tool-creation", "sub-manager"],
    )
    print("\n[e2e] FINAL REPORT")
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report.get("status") == "complete" else 1)
