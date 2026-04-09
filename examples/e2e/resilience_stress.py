#!/usr/bin/env python3
"""E2E Scenario — Resilience stress test.

Exercises the robustness fixes introduced in v1.0.43:
  * A1: LLM retry with exponential backoff (transient error recovery)
  * A2: Critique gate max-rejection bypass (3 rejections → auto-bypass)
  * C2: Budget-exhaustion graceful promotion (partial_complete when conf ≥ 0.5)
  * C3: Circuit breaker for repeated manager failures

This test runs a moderate-complexity task with tight budgets to force
budget-exhaustion scenarios and validates that the run terminates
gracefully (partial_complete or complete) rather than failing hard.

Tags: e2e, s5, resilience, critique, quick
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


TASK = (
    "Analyze the top 5 programming languages by popularity in 2025. "
    "For each language, provide: (1) name, (2) a one-sentence description "
    "of its primary use case, (3) estimated market share percentage "
    "(must be a real number, NOT a placeholder like 'XX%'). "
    "Use code execution to compute the total market share and verify "
    "it sums to a plausible number (50-100%). Return a JSON object with "
    "key 'languages' (list of dicts) and 'total_share' (number)."
)


def verify(workflow_dir: Path, result: dict) -> dict:
    """Verify the run produced substantive output."""
    text = json.dumps(result, default=str).lower()

    # Check for at least 3 language names
    known_langs = [
        "python", "javascript", "typescript", "java", "c++",
        "c#", "go", "rust", "kotlin", "swift", "php", "ruby",
    ]
    langs_found = sum(1 for lang in known_langs if lang in text)

    # Check no placeholders remain
    has_placeholders = any(
        p in text for p in ("xx%", "todo", "???", "tbd", "placeholder")
    )

    # Check for any output files or substantial result
    has_content = len(text) > 200

    # Scan the run directory for gate traces (critique_bypass, circuit_breaker)
    gate_traces: list[str] = []
    for p in workflow_dir.rglob("*.json"):
        try:
            content = p.read_text(errors="replace")
            if "critique_bypass" in content or "circuit_breaker" in content:
                gate_traces.append(p.name)
        except Exception:
            pass

    ok = langs_found >= 3 and not has_placeholders and has_content
    return {
        "ok": ok,
        "languages_found": langs_found,
        "has_placeholders": has_placeholders,
        "has_content": has_content,
        "gate_traces": gate_traces[:5],
    }


def main() -> int:
    report = run_e2e(
        slug="resilience-stress",
        title="Resilience Stress Test — Budget + Critique Gates",
        task=TASK,
        model="openai/gpt-4.1-nano",
        max_loops=15,
        max_total_tokens=1_500_000,
        max_wall_time=600,
        max_total_workers=20,
        max_depth=2,
        max_tool_calls=100,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.7,
                "max_repair_attempts": 1,
            },
        },
        verifier=verify,
        tags=["e2e", "s5", "resilience", "critique", "quick"],
    )

    ok = report["status"] in ("complete", "partial") and report.get("verify_ok")
    print(f"\n[resilience_stress] {'PASS' if ok else 'FAIL'} — status={report['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
