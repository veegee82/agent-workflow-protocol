"""Tests for the ``repo.fact(query, max_snippets)`` built-in tool
(Phase 3.4).

Covers:

(a) index-build correctness over a 3-file fixture;
(b) query returns ranked snippets by TF-IDF (most relevant first);
(c) cache hit — a second call does NOT rebuild the index.

The tool is exercised directly (low-level ``repo_fact`` function) AND
through the public :class:`ToolRegistry` surface so both integration
seams are covered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.runtime.builtin_tools.repo_fact import (
    RepoFactIndex,
    clear_index_cache,
    repo_fact,
)
from awp.runtime.tools import ToolRegistry


@pytest.fixture(autouse=True)
def _isolated_process_cache():
    """Clear the module-level index cache before and after every test
    so a leaked index from one test can never poison another.
    """
    clear_index_cache()
    yield
    clear_index_cache()


def _build_fixture_inputs(base: Path) -> None:
    """Populate a workspace with three text files covering distinct
    topics so TF-IDF has a meaningful IDF signal."""
    inputs = base / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)

    (inputs / "llm_basics.md").write_text(
        "# Large Language Models\n\n"
        "Large language models are trained on massive corpora of text data. "
        "Transformers use self-attention to relate every token to every other token.\n\n"
        "Self-attention is the core computational primitive of the transformer architecture. "
        "It lets the network route information between arbitrary positions in the sequence.\n\n"
        "Pretraining creates a generalist model; finetuning specialises it for a downstream task.\n",
        encoding="utf-8",
    )
    (inputs / "sorting.md").write_text(
        "# Sorting algorithms\n\n"
        "Quicksort is a divide-and-conquer sorting algorithm with average time complexity n log n.\n\n"
        "Mergesort also runs in n log n but uses extra memory proportional to the input size.\n\n"
        "Heapsort is another comparison-based sort with guaranteed n log n performance.\n",
        encoding="utf-8",
    )
    (inputs / "cooking.txt").write_text(
        "Sourdough bread requires a starter culture of wild yeast and lactobacilli.\n\n"
        "A well-fermented dough develops gluten structure and a characteristic tang.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# (a) Index build correctness
# ---------------------------------------------------------------------------


def test_index_build_covers_all_three_files(tmp_path):
    workspace = tmp_path / "workspace"
    _build_fixture_inputs(workspace)

    idx = RepoFactIndex(
        inputs_root=workspace / "inputs",
        cache_path=workspace / RepoFactIndex.CACHE_FILENAME,
    )
    idx.ensure_loaded()

    # All three files must contribute at least one paragraph.
    covered_paths = {d.path for d in idx._documents}
    assert covered_paths == {"llm_basics.md", "sorting.md", "cooking.txt"}, covered_paths

    # The IDF dictionary must include topic-distinguishing terms.
    assert "quicksort" in idx._idf
    assert "transformer" in idx._idf or "transformers" in idx._idf
    assert "sourdough" in idx._idf

    # Cache file written to disk and contains the fingerprint.
    cache = workspace / RepoFactIndex.CACHE_FILENAME
    assert cache.is_file()
    payload = cache.read_text(encoding="utf-8")
    assert "fingerprint" in payload
    assert "documents" in payload


# ---------------------------------------------------------------------------
# (b) TF-IDF ranking: topically-relevant paragraphs come first
# ---------------------------------------------------------------------------


def test_query_returns_tf_idf_ranked_snippets(tmp_path):
    workspace = tmp_path / "workspace"
    _build_fixture_inputs(workspace)

    results = repo_fact(
        query="How does self-attention work in transformer models?",
        max_snippets=3,
        workspace_dir=workspace,
    )

    # At least one hit, all from the LLM file — the sorting and cooking
    # files have zero token overlap with the query.
    assert len(results) >= 1
    # Top hit MUST come from the LLM file.
    assert results[0]["path"] == "llm_basics.md"
    # Score strictly positive.
    assert results[0]["score"] > 0.0
    # Snippet contains at least one of the query's distinguishing tokens.
    snippet = results[0]["snippet"].lower()
    assert any(tok in snippet for tok in ("self-attention", "transformer", "attention"))

    # Results are sorted by score descending.
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)

    # A completely unrelated query returns nothing.
    empty = repo_fact(
        query="xyzzy plover grue nothing in corpus",
        max_snippets=3,
        workspace_dir=workspace,
    )
    assert empty == []


# ---------------------------------------------------------------------------
# (c) Cache hit — second call does NOT rebuild
# ---------------------------------------------------------------------------


def test_second_call_hits_cache_without_rebuild(tmp_path):
    workspace = tmp_path / "workspace"
    _build_fixture_inputs(workspace)

    cache_path = workspace / RepoFactIndex.CACHE_FILENAME

    # Call 1 — cold. Build is forced because there is no cache on disk.
    idx = RepoFactIndex(inputs_root=workspace / "inputs", cache_path=cache_path)
    idx.ensure_loaded()
    assert idx.rebuild_count == 1
    assert cache_path.is_file()

    # Call 2 on a FRESH instance (mimics a second worker call within the
    # same run, after the in-memory cache was dropped). The fingerprint
    # matches the on-disk cache, so the index loads from JSON and
    # rebuild_count stays at 0.
    idx2 = RepoFactIndex(inputs_root=workspace / "inputs", cache_path=cache_path)
    idx2.ensure_loaded()
    assert idx2.rebuild_count == 0, (
        "cache hit expected on 2nd call but the index rebuilt"
    )
    # Functional equivalence — same query, same ranking.
    r1 = idx.query("quicksort divide and conquer", max_snippets=1)
    r2 = idx2.query("quicksort divide and conquer", max_snippets=1)
    assert r1 == r2

    # Mutating an input file invalidates the cache on the NEXT load.
    (workspace / "inputs" / "sorting.md").write_text(
        "Brand new content about bubble sort — O(n^2) complexity.\n",
        encoding="utf-8",
    )
    idx3 = RepoFactIndex(inputs_root=workspace / "inputs", cache_path=cache_path)
    idx3.ensure_loaded()
    assert idx3.rebuild_count == 1, (
        "cache must invalidate when an input file changes"
    )


# ---------------------------------------------------------------------------
# ToolRegistry integration
# ---------------------------------------------------------------------------


def test_tool_registry_exposes_repo_fact(tmp_path):
    workspace = tmp_path / "workspace"
    _build_fixture_inputs(workspace)

    reg = ToolRegistry(workflow_dir=tmp_path)
    # Registered under the canonical fully-qualified name.
    assert "repo.fact" in reg._tools
    # Definition is a valid OpenAI-style function spec.
    definition = reg._definitions["repo.fact"]["function"]
    assert definition["name"] == "repo.fact"
    assert "query" in definition["parameters"]["properties"]
    assert definition["parameters"]["required"] == ["query"]

    # Standard AWP envelope on success.
    result = reg.call(
        "repo.fact",
        {"query": "how do transformers use attention?", "max_snippets": 2},
    )
    assert result["ok"] is True
    assert result["status"] == 200
    data = result["data"]
    assert "snippets" in data
    assert data["count"] == len(data["snippets"])
    assert data["query"].startswith("how do transformers")
    assert all("path" in s and "snippet" in s for s in data["snippets"])

    # Invalid query returns an error envelope (not an exception).
    err = reg.call("repo.fact", {"query": "   "})
    assert err["ok"] is False
    assert err["status"] == 400
