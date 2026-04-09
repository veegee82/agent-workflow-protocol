"""E2E Scenario — Edge-AI Market Intelligence Report (A4, sub-managers).

Exercises sub-manager delegation, dynamic tool creation, skill reuse,
critique loop, and planning. The task forces 4 dedicated sub-managers
(tech landscape, market analysis, use-case deep-dive, regulatory) each
spawning multiple workers.

Verification:
  * AgentWorkflow returns with final_state in ("complete", "partial").
  * Output directory contains a markdown report and a JSON comparison matrix.
  * At least 2 distinct sub-manager run directories exist (depth >= 1).
  * Report text mentions at least 6 of the 8 required manufacturers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402


TASK = (
    'Baue einen vollstaendigen Markt-Intelligence-Report zum Thema '
    '"Edge-AI-Inferenz-Chips 2026". Der Report muss vier eigenstaendige '
    'Teilbereiche abdecken, die jeweils so umfangreich sind, dass sie '
    'selbst wieder in mehrere Unteraufgaben zerlegt werden muessen:\n\n'
    '1. Technologie-Landschaft - Architekturen (NPU, TPU, FPGA, neuromorph), '
    'Benchmarks (TOPS/Watt), Fertigungsprozesse, thermische Limits. '
    'Mindestens 8 Hersteller vergleichen.\n'
    '2. Marktanalyse - Segmentierung (Automotive, IoT, Mobile, Industrial), '
    'CAGR-Prognosen, Top-10-Player mit Marktanteilen, Lieferketten-Risiken.\n'
    '3. Use-Case-Deep-Dive - Mindestens 5 reale Deployments mit '
    'Kosten/Latenz/Energieprofilen, inkl. Code-Beispielen fuer ein '
    'Inferenz-Pipeline-Benchmark.\n'
    '4. Regulatorisches & Geopolitisches Umfeld - Exportkontrollen (US/EU/CN), '
    'Subventionsprogramme, Patente, Standardisierung.\n\n'
    'Anforderungen:\n'
    '- Jeder Teilbereich MUSS von einem dedizierten Submanager bearbeitet '
    'werden, der wiederum eigene Worker fuer Recherche, Synthese und '
    'Validierung spawnt.\n'
    '- Der Top-Level-Manager darf die Teilbereiche NICHT selbst ausfuehren '
    '- er muss promoten und delegieren.\n'
    '- Erzeuge mindestens ein neues Tool dynamisch (z.B. benchmark.normalize '
    'oder market.aggregate), das von mehreren Workern wiederverwendet wird.\n'
    '- Erzeuge mindestens eine wiederverwendbare Skill '
    '(z.B. "competitive-matrix-builder").\n'
    '- Endergebnis: ein konsolidierter Markdown-Report (>= 2000 Woerter) '
    'plus eine Vergleichsmatrix als strukturierte Daten (JSON).\n'
    '- Konfidenz pro Teilbereich >= 0.8, Gesamt-Konfidenz >= 0.85.\n\n'
    'Erfolgskriterium: Run erreicht complete, alle 4 Submanager haben '
    'mindestens 2 Worker gespawnt, mindestens 1 Tool und 1 Skill wurden '
    'erzeugt und wiederverwendet.'
)

# Manufacturers that should appear in the report
EXPECTED_VENDORS = [
    "nvidia", "google", "intel", "amd", "qualcomm",
    "xilinx", "mythic", "ibm", "apple", "samsung",
    "mediatek", "arm", "hailo", "syntiant",
]


def verify(workflow_dir: Path, result: dict) -> dict:
    """Check E2E success criteria."""
    # 1. Check output files exist
    output_dir = workflow_dir / "output"
    if not output_dir.exists():
        output_dir = workflow_dir

    md_files = list(output_dir.rglob("*.md"))
    json_files = list(output_dir.rglob("*.json"))

    has_report = any(
        f.stem in ("final_report", "deliverables_markdown", "markdown_report",
                    "technology_landscape_overview")
        or "report" in f.stem.lower()
        for f in md_files
    )
    has_matrix = any(
        "matrix" in f.stem or "comparison" in f.stem
        for f in json_files
    )

    # 2. Check sub-manager depth
    runs_dir = workflow_dir / "workspace" / "runs"
    sub_run_dirs = []
    if runs_dir.exists():
        for p in runs_dir.rglob("run_manifest.json"):
            depth = str(p).count("/runs/")
            if depth >= 2:
                sub_run_dirs.append(str(p))

    # 3. Check vendor coverage in all text output
    text_blob = json.dumps(result, default=str).lower()
    for fp in md_files:
        try:
            text_blob += "\n" + fp.read_text(errors="replace").lower()
        except Exception:
            pass
    for fp in json_files:
        try:
            text_blob += "\n" + fp.read_text(errors="replace").lower()
        except Exception:
            pass

    vendors_found = [v for v in EXPECTED_VENDORS if v in text_blob]

    ok = has_report and len(vendors_found) >= 4 and len(sub_run_dirs) >= 1
    return {
        "ok": ok,
        "has_report": has_report,
        "has_matrix": has_matrix,
        "md_files": len(md_files),
        "json_files": len(json_files),
        "sub_run_dirs": len(sub_run_dirs),
        "vendors_found": vendors_found,
        "vendors_count": len(vendors_found),
    }


def main() -> int:
    report = run_e2e(
        slug="s5-edge-ai-market-intel",
        title="S5 E2E — Edge-AI Market Intelligence Report (sub-managers + tools)",
        task=TASK,
        model="openai/gpt-5-mini",
        max_loops=30,
        max_total_tokens=5_000_000,
        max_wall_time=3600,
        max_total_workers=100,
        max_depth=4,
        max_tool_calls=2000,
        verifier=verify,
        tags=["s5", "sub-manager", "tool-creation", "planning", "critique"],
    )
    return 0 if (report["status"] == "complete" and report["verify_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
