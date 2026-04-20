"""Tests for continuation prefix rendering."""

from __future__ import annotations

import pytest

from awp.continuation import (
    BundleEntry,
    ContinuationBudgetError,
    ContinuationBundle,
    ReferencePointer,
    render_continuation_prefix,
)


def _bundle(primaries, references=None, feedback="test"):
    return ContinuationBundle(
        primary_materials=list(primaries),
        reference_paths=list(references or []),
        user_feedback=feedback,
    )


def test_prefix_contains_sections() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-seed", "paper.md", "This is the paper body.")],
        feedback="make section 3 deeper",
    )
    prefix = render_continuation_prefix(b)
    assert "## Continuation Context" in prefix
    assert "### Prior deliverable (primary)" in prefix
    assert "paper.md" in prefix
    assert "This is the paper body." in prefix
    assert "## User Feedback" in prefix
    assert "make section 3 deeper" in prefix
    assert "## Your Task" in prefix


def test_reference_section_present_when_given() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[ReferencePointer("001-s", "BEST/b.json", 1234, '{"x": 1}')],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "### Reference material" in prefix
    assert "BEST/b.json" in prefix
    assert "1234" in prefix
    assert '{"x": 1}' in prefix


def test_reference_section_omitted_when_empty() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "### Reference material" not in prefix


def test_determinism() -> None:
    b = _bundle(
        primaries=[
            BundleEntry("001-s", "a.md", "A"),
            BundleEntry("001-s", "b.md", "B"),
        ],
        feedback="fb",
    )
    assert render_continuation_prefix(b) == render_continuation_prefix(b)


def test_reference_stub_degradation() -> None:
    # Build a tiny primary + a huge reference-head
    big_head = "x" * 400_000
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[ReferencePointer("001-s", "big.json", 1_000_000, big_head)],
        feedback="fb",
    )
    # With a tight budget the first-200-chars must drop
    prefix = render_continuation_prefix(b, max_chars=5_000)
    assert big_head[:100] not in prefix  # head was stripped
    assert "big.json" in prefix          # path still listed
    assert "1000000" in prefix           # size still listed


def test_reference_drop_when_still_over() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "tiny")],
        references=[
            ReferencePointer("001-s", f"f{i}.md", 100, "head" * 50)
            for i in range(200)
        ],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b, max_chars=1_000)
    assert "### Reference material" not in prefix
    assert "tiny" in prefix  # primary preserved


def test_primary_overflow_raises() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "big.md", "y" * 100_000)],
        feedback="fb",
    )
    with pytest.raises(ContinuationBudgetError, match="primary"):
        render_continuation_prefix(b, max_chars=1_000)


def test_max_chars_default_honors_80pct_of_150k_tokens() -> None:
    # Default budget ≈ 480_000 chars (0.8 × 150_000 tokens × 4 chars/token).
    # A 300_000-char primary should fit without error.
    b = _bundle(
        primaries=[BundleEntry("001-s", "big.md", "y" * 300_000)],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "y" * 100 in prefix
