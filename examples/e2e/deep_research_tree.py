"""E2E Scenario 1 — Deep research tree (A3, depth >= 3).

Exercises B1 (hierarchical context digest), B2 (default submanager
inheritance) and B5 (content-aware delegation signature).

The task forces the manager to recursively decompose the problem by
asking it to plan transit for three *zones* on a fictional moon base
and then produce a *unified* inter-zone connector plan -- one natural
sub-problem per zone plus a synthesis step.

Verification:
  * AgentWorkflow returns with final_state == "complete".
  * ``wrapped["_digest_sha"]`` is populated (B1 root digest was written).
  * At least one digest JSON on disk has non-empty child_digest_hashes
    (evidence of depth >= 2, i.e. the digest is *hierarchical*).
  * Output text mentions all three zones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402


TASK = (
    "Design a transit system for a fictional moon base called 'Selene Prime' "
    "with three distinct zones: (1) RESIDENTIAL, (2) INDUSTRIAL, (3) RESEARCH. "
    "For each of the three zones, recommend a primary transit modality "
    "(e.g. maglev pod, pneumatic tube, autonomous rover) and briefly justify "
    "the choice based on zone-specific constraints (population density, cargo "
    "mass, scientific sensitivity). Then synthesize a unified inter-zone "
    "connector plan that ties all three zones together, explaining how the "
    "modalities interoperate at transfer nodes. "
    "Produce a final written plan that explicitly names all three zones "
    "(RESIDENTIAL, INDUSTRIAL, RESEARCH) and describes the connector."
)


def verify(workflow_dir: Path, result: dict) -> dict:
    # `result` is the inner loop_result (result["result"] of the wrapper).
    digest_sha = result.get("_digest_sha")

    digest_dir = workflow_dir / "workspace" / "runs"
    digests_found = list(digest_dir.rglob("digest/*.json")) if digest_dir.exists() else []
    hierarchical = False
    for p in digests_found:
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if data.get("child_digest_hashes"):
            hierarchical = True
            break

    # Look at final output text for the three zones — search both the
    # JSON blob and any artifact files we wrote.
    text_blob = json.dumps(result, default=str).lower()
    output_files = result.get("output_files") or []
    for fp in output_files:
        try:
            text_blob += "\n" + Path(fp).read_text(errors="replace").lower()
        except Exception:
            pass
    zones_ok = all(z in text_blob for z in ("residential", "industrial", "research"))

    ok = bool(digest_sha) and hierarchical and zones_ok
    return {
        "ok": ok,
        "digest_sha": digest_sha,
        "digest_files_count": len(digests_found),
        "hierarchical": hierarchical,
        "all_three_zones_mentioned": zones_ok,
    }


def main() -> int:
    report = run_e2e(
        slug="s5-deep-research-tree",
        title="S5 E2E 1 — Deep Research Tree (B1+B2+B5)",
        task=TASK,
        max_loops=30,
        max_total_tokens=3_000_000,
        max_wall_time=3600,
        max_depth=4,
        max_total_workers=60,
        verifier=verify,
    )
    return 0 if (report["status"] == "complete" and report["verify_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
