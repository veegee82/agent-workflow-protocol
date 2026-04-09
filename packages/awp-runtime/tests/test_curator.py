"""Unit tests for Baustein 4 — auto-curation of run knowledge."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from awp.runtime.curator import Curator, CurationReport, read_prior_memory
from awp.runtime.digest import Digest, DigestStore


class _StubRegistry:
    def __init__(self, dynamic: dict, definitions: dict) -> None:
        self._dynamic_tools = dynamic
        self._definitions = definitions


def _make_digest_store(tmp_path: Path) -> DigestStore:
    return DigestStore(workspace=tmp_path / "workspace" / "runs" / "run1")


def _mk_digest(key_facts, iteration=1, goal="g"):
    return Digest(goal=goal, key_facts=list(key_facts), iteration=iteration, run_id="run1")


@pytest.fixture
def workflow_dir(tmp_path: Path) -> Path:
    d = tmp_path / "wf"
    d.mkdir()
    return d


def test_curate_tools_basic(workflow_dir):
    reg = _StubRegistry(
        dynamic={
            "dynamic.alpha": {"creator": "worker_a", "created_at": "2026-04-09T00:00:00Z"},
        },
        definitions={
            "dynamic.alpha": {
                "type": "function",
                "function": {
                    "name": "dynamic.alpha",
                    "description": "Alpha does alpha things.",
                    "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
                },
            }
        },
    )
    c = Curator(
        workflow_dir=workflow_dir,
        run_id="run1",
        digest_store=None,
        final_result={},
        dynamic_tools_registry=reg,
        root_digest_sha=None,
        failed_signatures=[],
    )
    report = c.curate()
    assert report.tools_added == 1
    recipe = workflow_dir / "memory" / "tools" / "dynamic.alpha.md"
    assert recipe.exists()
    body = recipe.read_text()
    assert "Alpha does alpha things" in body
    assert "## v1" in body
    assert "content_hash:" in body


def test_curate_tools_idempotent(workflow_dir):
    reg = _StubRegistry(
        dynamic={"dynamic.a": {"creator": "w"}},
        definitions={"dynamic.a": {"function": {"description": "d", "parameters": {}}}},
    )
    kwargs = dict(
        workflow_dir=workflow_dir,
        run_id="run1",
        digest_store=None,
        final_result={},
        dynamic_tools_registry=reg,
        root_digest_sha=None,
        failed_signatures=[],
    )
    r1 = Curator(**kwargs).curate()
    r2 = Curator(**kwargs).curate()
    assert r1.tools_added == 1
    assert r2.tools_added == 0
    assert r2.tools_versioned == 0
    # File should only contain one v1 section.
    body = (workflow_dir / "memory" / "tools" / "dynamic.a.md").read_text()
    assert body.count("## v1") == 1


def test_curate_tools_versioning(workflow_dir):
    reg1 = _StubRegistry(
        dynamic={"dynamic.a": {"creator": "w"}},
        definitions={"dynamic.a": {"function": {"description": "first", "parameters": {"type": "object"}}}},
    )
    Curator(
        workflow_dir=workflow_dir, run_id="r1", digest_store=None,
        final_result={}, dynamic_tools_registry=reg1,
        root_digest_sha=None, failed_signatures=[],
    ).curate()
    reg2 = _StubRegistry(
        dynamic={"dynamic.a": {"creator": "w"}},
        definitions={"dynamic.a": {"function": {"description": "SECOND", "parameters": {"type": "object", "properties": {"y": {}}}}}},
    )
    r = Curator(
        workflow_dir=workflow_dir, run_id="r2", digest_store=None,
        final_result={}, dynamic_tools_registry=reg2,
        root_digest_sha=None, failed_signatures=[],
    ).curate()
    assert r.tools_versioned == 1
    body = (workflow_dir / "memory" / "tools" / "dynamic.a.md").read_text()
    assert "## v1" in body and "## v2" in body
    assert "SECOND" in body


def test_curate_facts_cross_confirm(workflow_dir):
    store = _make_digest_store(workflow_dir)
    # root digest references two children, only "common fact" appears in both
    c1 = _mk_digest(["common fact", "only c1"])
    c2 = _mk_digest(["common fact", "only c2"])
    sha1 = store.put(c1)
    sha2 = store.put(c2)
    root = Digest(
        goal="g", key_facts=["root only fact"], child_digest_hashes=[sha1, sha2],
        iteration=2, run_id="run1",
    )
    root_sha = store.put(root)

    r = Curator(
        workflow_dir=workflow_dir, run_id="run1", digest_store=store,
        final_result={}, dynamic_tools_registry=None,
        root_digest_sha=root_sha, failed_signatures=[],
    ).curate()
    assert r.facts_added == 1
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    facts = (workflow_dir / "memory" / "facts" / f"{day}.md").read_text()
    assert "common fact" in facts
    assert "only c1" not in facts
    assert "root only fact" not in facts


def test_curate_antipatterns(workflow_dir):
    failed = [
        {"signature": "sigA", "reason": "redundant", "iteration": 3, "instructions": "do X"},
        {"signature": "sigB", "reason": "low_confidence", "iteration": 4, "instructions": "do Y"},
    ]
    c = Curator(
        workflow_dir=workflow_dir, run_id="run1", digest_store=None,
        final_result={}, dynamic_tools_registry=None,
        root_digest_sha=None, failed_signatures=failed,
    )
    r = c.curate()
    assert r.antipatterns_added == 2
    files = list((workflow_dir / "memory" / "antipatterns").glob("*.md"))
    assert len(files) == 2
    # Re-running is idempotent.
    r2 = Curator(
        workflow_dir=workflow_dir, run_id="run1", digest_store=None,
        final_result={}, dynamic_tools_registry=None,
        root_digest_sha=None, failed_signatures=failed,
    ).curate()
    assert r2.antipatterns_added == 0


def test_read_prior_memory_structure_and_cap(workflow_dir):
    # Seed memory dir with the three kinds.
    (workflow_dir / "memory" / "tools").mkdir(parents=True)
    (workflow_dir / "memory" / "facts").mkdir(parents=True)
    (workflow_dir / "memory" / "antipatterns").mkdir(parents=True)
    (workflow_dir / "memory" / "tools" / "alpha.md").write_text(
        "# Tool Recipe: alpha\n## v1\n- content_hash: x\n\n### Purpose\nDoes alpha.\n"
    )
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (workflow_dir / "memory" / "facts" / f"{day}.md").write_text(
        "# Facts\n- [r1] this is a confirmed fact\n"
    )
    (workflow_dir / "memory" / "antipatterns" / "deadbeef.md").write_text(
        "# Antipattern deadbeef\n- reason: redundant\n\nInstructions went here\n"
    )
    md = read_prior_memory(workflow_dir)
    assert "## PRIOR RUN MEMORY" in md
    assert "### Known Tools" in md
    assert "alpha: Does alpha." in md
    assert "### Confirmed Facts" in md
    assert "confirmed fact" in md
    assert "### Antipatterns to Avoid" in md
    assert "redundant" in md
    assert len(md) <= 3000


def test_read_prior_memory_cap_enforced(workflow_dir):
    tools = workflow_dir / "memory" / "tools"
    tools.mkdir(parents=True)
    for i in range(60):
        (tools / f"tool_{i:03d}.md").write_text(
            f"# Tool Recipe: tool_{i}\n## v1\n\n### Purpose\n"
            f"{'x' * 200}\n"
        )
    md = read_prior_memory(workflow_dir)
    assert len(md) <= 3000


def test_empty_memory_returns_empty(workflow_dir):
    assert read_prior_memory(workflow_dir) == ""


def test_curate_report_is_dict():
    rep = CurationReport(tools_added=1)
    assert rep.to_dict()["tools_added"] == 1
