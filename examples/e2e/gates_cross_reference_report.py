"""E2E Test 2 — Datenpipeline-Bericht mit echten Cross-Referenzen.

Exercises:
- cross_reference   (citations [N] and References section must align;
                      Fig. N references must match embedded images)
- syntax_compile    (.py, .csv, .md)
- success_criteria  (checklist literal presence)
- deliverable_presence
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402

TASK = """## Ziel
Erstelle einen reproduzierbaren Mini-Datenanalyse-Report über einen
fiktionalen Datensatz "Mars-Rover-Mission Tagebuch 2145". Der Output
enthält Daten, Code, Text mit **korrekten Zitaten und Figuren-Referenzen**.

## Liefergegenstände (relativ zu _output_dir)
- [ ] _output_dir/data.csv — 10 Zeilen synthetische Missions-Einträge mit
      den Spalten `sol,distance_m,samples,battery_pct`.
- [ ] _output_dir/analyze.py — Python-Skript das `data.csv` einliest und die
      Mittelwerte ausgibt. Muss syntaktisch valide sein.
- [ ] _output_dir/report.md — Markdown-Report mit:
      * Einleitung, Methodik, Ergebnisse, Diskussion
      * mindestens **3 nummerierte Zitate** im Text der Form `[1]`, `[2]`, `[3]`
      * Eine `## References` (oder `## Literatur`) Sektion mit Einträgen
        `[1] ...`, `[2] ...`, `[3] ...` — für **jedes** gezitierte `[N]`
        muss genau ein Eintrag existieren.
      * Mindestens **2 eingebundene PNG-Bilder** via Markdown-Image-Syntax
        `![caption](fig1.png)` und `![caption](fig2.png)`.
      * Mindestens einen Verweis `siehe Fig. 1` und `siehe Fig. 2` im
        Text. **Nicht** auf `Fig. 3` oder höher verweisen — es gibt nur 2
        Bilder.
- [ ] _output_dir/fig1.png — eine kleine Plot-PNG (≥2 KB, kein 1×1-Pixel
      Platzhalter). Darf gerne aus `analyze.py` via matplotlib
      generiert werden, muss aber am Ende als Datei vorliegen.
- [ ] _output_dir/fig2.png — zweites Plot-PNG, ebenfalls ≥2 KB.

## Erfolgskriterien
- `data.csv` hat genau 11 Zeilen (Header + 10 Daten) und 4 Spalten.
- `analyze.py` parst ohne SyntaxError.
- `report.md` zitiert [1], [2], [3] und definiert sie in `## References`.
- `report.md` verweist auf `Fig. 1` und `Fig. 2` und bindet
  `fig1.png` + `fig2.png` ein.
- Keine Platzhalter (`TODO`, `XX%`, `???`) in den Deliverables.

## Hinweise
Der fiktionale Datensatz darf erfunden sein — Konsistenz ist aber
Pflicht. Füge in mindestens einem Plan-Subtask
`required_outputs: ["data.csv", "analyze.py", "report.md", "fig1.png", "fig2.png"]`.
"""


EXTRA_CONFIG = {
    "llm_trace": {"enabled": True, "persist": True},
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
    must = ["data.csv", "analyze.py", "report.md", "fig1.png", "fig2.png"]
    resolved: dict[str, Path] = {}
    for name in must:
        hits = list(out_dir.rglob(name))
        if not hits:
            ok = False
            findings.append(f"missing: {name}")
        else:
            resolved[name] = hits[0]

    # data.csv row/col check
    if "data.csv" in resolved:
        lines = resolved["data.csv"].read_text(encoding="utf-8").strip().split("\n")
        if len(lines) != 11:
            ok = False
            findings.append(f"data.csv has {len(lines)} lines, expected 11")

    # report.md citation check
    if "report.md" in resolved:
        txt = resolved["report.md"].read_text(encoding="utf-8")
        import re
        cites = {int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", txt)}
        if not {1, 2, 3} <= cites:
            ok = False
            findings.append(f"report.md missing required cites — found {cites}")
        if "References" not in txt and "Literatur" not in txt:
            ok = False
            findings.append("report.md missing References/Literatur section")
        for fname in ("fig1.png", "fig2.png"):
            if fname not in txt:
                ok = False
                findings.append(f"report.md does not embed {fname}")

    # PNG size check
    for fname in ("fig1.png", "fig2.png"):
        if fname in resolved and resolved[fname].stat().st_size < 2048:
            ok = False
            findings.append(
                f"{fname} is only {resolved[fname].stat().st_size} bytes "
                f"(< 2KB, placeholder?)"
            )

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
        slug="gates-cross-reference",
        title="Gates E2E 2: Cross-reference report",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=12,
        max_total_tokens=2_000_000,
        max_wall_time=1800,
        max_total_workers=30,
        max_depth=0,  # no submanagers — avoid budget-recursion bug
        max_tool_calls=600,
        extra_config=EXTRA_CONFIG,
        verifier=verify,
        tags=["e2e", "gates", "cross_reference", "syntax_compile"],
    )
    print("\n[e2e] FINAL REPORT")
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0 if report.get("status") == "complete" else 1)
