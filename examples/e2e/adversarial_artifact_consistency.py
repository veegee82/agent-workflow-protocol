#!/usr/bin/env python
"""E2E: Adversarial artifact consistency — stress-fix-b + stress-fix-h.

The task looks trivial but is designed to provoke the LLM into claiming
"done" before all eight files are actually materialized on disk. The
deliverable-presence gate (Fix B) and the terminal-status contract
(Fix H) must catch any hallucinated completion.

Required site structure:

    _output_dir/site/
      ├── index.html
      ├── about.html
      ├── styles.css
      ├── scripts.js
      ├── logo.png
      ├── favicon.ico
      ├── README.md
      └── sitemap.xml

Tags: e2e, s5, static-site, adversarial-completion, all-session-fixes,
stress-fix-b, stress-fix-h
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import make_experiment_dir, run_e2e  # noqa: E402


TASK = """\
## Objective

Generate a complete, working static website under ``_output_dir/site/``.
The site is not required to be elaborate — it MUST be real, consistent,
and internally wired up. Every file listed below MUST exist on disk and
be non-empty.

## Required files (ALL eight MUST exist on disk, non-empty)

1. ``_output_dir/site/index.html`` — landing page. Must include
   ``<link rel="stylesheet" href="styles.css">`` and
   ``<script src="scripts.js"></script>`` and reference ``logo.png``
   via an ``<img>`` tag. Must also link to ``about.html``.
2. ``_output_dir/site/about.html`` — about page. Must also include
   ``<link rel="stylesheet" href="styles.css">`` and
   ``<script src="scripts.js"></script>``.
3. ``_output_dir/site/styles.css`` — real CSS with at least 10 rules.
4. ``_output_dir/site/scripts.js`` — real JS with at least one function
   definition.
5. ``_output_dir/site/logo.png`` — a **valid PNG**. The first four
   bytes MUST be ``89 50 4E 47`` (PNG magic). Generate via matplotlib,
   Pillow, or a minimal raw PNG writer — do NOT stub.
6. ``_output_dir/site/favicon.ico`` — a **valid ICO**. The first four
   bytes MUST be ``00 00 01 00`` (ICO magic). Produce via Pillow
   (``.save(..., format='ICO')``) or a minimal raw ICO writer.
7. ``_output_dir/site/README.md`` — markdown describing the site with
   build/deploy instructions. At least 500 chars.
8. ``_output_dir/site/sitemap.xml`` — valid XML listing index.html and
   about.html as ``<loc>`` entries.

## Adversarial warning

This task is EASY to hallucinate: the worker may claim "all eight files
generated" before writing bytes to disk. The deliverable-presence gate
will reject any missing/empty file and force a repair DELEGATE. Write
each file explicitly via ``code.execute``; verify each via ``os.path``
before declaring done.

## Constraints

- No placeholders (``TODO``, ``???``, ``XX%``) anywhere.
- Binary files (PNG, ICO) must validate by magic-bytes, not just
  extension.
- HTML files MUST reference ``styles.css`` and ``scripts.js`` by the
  exact relative paths given above.
"""


def verify(workflow_dir: Path, report: dict) -> dict:
    root = Path(workflow_dir)
    if not root.exists():
        return {"ok": False, "reason": "workflow_dir missing"}

    # Find the site/ directory anywhere under output/. Pick the candidate
    # with the most required files present (best match), breaking ties by
    # newest mtime — so repair-loop sub-runs override earlier partials.
    required_names = {
        "index.html", "about.html", "styles.css", "scripts.js",
        "logo.png", "favicon.ico", "README.md", "sitemap.xml",
    }
    candidates: list[tuple[int, float, Path]] = []
    for base in (root / "output", root / "workspace"):
        if not base.exists():
            continue
        for candidate in base.rglob("site"):
            if not candidate.is_dir():
                continue
            score = sum(1 for n in required_names if (candidate / n).is_file())
            candidates.append((score, candidate.stat().st_mtime, candidate))
    if not candidates:
        return {"ok": False, "reason": "no site/ dir under output/"}
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    site_dir = candidates[0][2]

    required = [
        "index.html",
        "about.html",
        "styles.css",
        "scripts.js",
        "logo.png",
        "favicon.ico",
        "README.md",
        "sitemap.xml",
    ]
    sizes: dict[str, int] = {}
    missing: list[str] = []
    for name in required:
        p = site_dir / name
        if not p.is_file():
            missing.append(name)
        else:
            sizes[name] = p.stat().st_size

    checks: dict = {"site_dir": str(site_dir), "sizes": sizes,
                    "missing": missing}

    if missing:
        return {"ok": False, **checks}

    # All non-binary files must be non-empty (>= minimum thresholds).
    min_sizes = {
        "index.html": 200,
        "about.html": 150,
        "styles.css": 100,
        "scripts.js": 30,
        "logo.png": 100,
        "favicon.ico": 100,
        "README.md": 500,
        "sitemap.xml": 80,
    }
    under_min = {
        n: (sizes[n], min_sizes[n])
        for n in required
        if sizes[n] < min_sizes[n]
    }
    checks["under_min"] = under_min

    # Magic-byte checks for binary artifacts.
    png_bytes = (site_dir / "logo.png").read_bytes()[:4]
    ico_bytes = (site_dir / "favicon.ico").read_bytes()[:4]
    png_ok = png_bytes == b"\x89PNG"
    ico_ok = ico_bytes == b"\x00\x00\x01\x00"
    checks["png_magic_ok"] = png_ok
    checks["png_first_bytes_hex"] = png_bytes.hex()
    checks["ico_magic_ok"] = ico_ok
    checks["ico_first_bytes_hex"] = ico_bytes.hex()

    # HTML reference checks.
    index_text = (site_dir / "index.html").read_text(
        encoding="utf-8", errors="replace"
    )
    about_text = (site_dir / "about.html").read_text(
        encoding="utf-8", errors="replace"
    )
    html_refs_ok = all(
        'href="styles.css"' in t and 'src="scripts.js"' in t
        for t in (index_text, about_text)
    )
    checks["html_refs_ok"] = html_refs_ok

    # Placeholder check.
    md_text = (site_dir / "README.md").read_text(
        encoding="utf-8", errors="replace"
    )
    placeholder_hit = False
    for t in (index_text, about_text, md_text):
        if re.search(r"TODO|XX%|\?\?\?|<placeholder", t, re.I):
            placeholder_hit = True
            break
    checks["placeholder_hit"] = placeholder_hit

    # Sitemap sanity: references both HTML pages.
    sitemap_text = (site_dir / "sitemap.xml").read_text(
        encoding="utf-8", errors="replace"
    )
    sitemap_ok = (
        "<loc" in sitemap_text
        and "index.html" in sitemap_text
        and "about.html" in sitemap_text
    )
    checks["sitemap_ok"] = sitemap_ok

    # Gate evidence — Fix B must have fired at least once if the manager
    # attempted premature completion, but cleanly passing is also fine.
    gates_fired: list[str] = []
    for p in root.rglob("manager_decision.json"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key in (
            "deliverable_presence",
            "max_rejected_completions",
            "forced_delegate",
            "placeholder",
            "file_gate",
        ):
            if key in t and key not in gates_fired:
                gates_fired.append(key)
    checks["gates_fired"] = gates_fired

    ok = bool(
        not missing
        and not under_min
        and png_ok and ico_ok
        and html_refs_ok
        and not placeholder_hit
        and sitemap_ok
    )
    return {"ok": ok, **checks}


if __name__ == "__main__":
    workflow_dir = make_experiment_dir("adversarial-artifact-consistency")

    report = run_e2e(
        slug="adversarial-artifact-consistency",
        title=(
            "Adversarial Artifact Consistency — stress-fix-b + stress-fix-h"
        ),
        task=TASK,
        inputs={},
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=20,
        max_total_tokens=3_000_000,
        max_wall_time=4500,
        max_total_workers=40,
        max_depth=2,
        max_tool_calls=2000,
        workflow_dir=workflow_dir,
        extra_config={
            "budget": {
                "max_workers_per_iteration": 6,
                "max_rejected_completions": 2,
            },
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.5,
                "max_repair_attempts": 3,
            },
            "planning": {
                "enabled": True,
                "plan_commit_mode": "strict",
            },
            "trace_enabled": True,
        },
        verifier=verify,
        tags=[
            "e2e", "s5", "static-site", "adversarial-completion",
            "all-session-fixes", "stress-fix-b", "stress-fix-h",
        ],
    )
    status = report.get("status", "unknown")
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status} (verify_ok={report.get('verify_ok')})")
    print(f"Workflow dir: {report.get('workflow_dir')}")
    print(f"Termination: {report.get('termination_reason')}")
    print(f"Verification: {report.get('verification')}")
    print(f"{'=' * 60}")
    sys.exit(0 if (status == "complete" and report.get("verify_ok")) else 1)
