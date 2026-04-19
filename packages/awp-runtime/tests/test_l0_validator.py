"""Tests for the Layer-0 Output Contract validator (R34).

Cover the 6 default checks (positive + negative each), the validator
short-circuit behavior, and the two pathological regressions that
motivated R34:

* The "5 sentences repeated 10x" text-loop observed in run 3.
* The 341 MB runaway file-size-delta observed in the 2026-04 bilingual
  paper experiment.

Every check must be synchronous, side-effect free, and return within
~100 ms on a 10 MB input (we do not microbenchmark here — the
implementation is linear in input size and uses stdlib primitives
only).
"""

from __future__ import annotations

from awp.runtime.critique.contracts import (
    CheckResult,
    OutputContract,
    OutputContractCheck,
)
from awp.runtime.critique.l0_validator import (
    BalancedDelimitersCheck,
    DEFAULT_CHECK_NAMES,
    FileSizeDeltaCheck,
    JsonValidIfClaimedCheck,
    L0Validator,
    NoDuplicateHeadingsCheck,
    NoPlaceholderCheck,
    NoTextLoopCheck,
)


# ---------------------------------------------------------------------------
# Check 1 — no_placeholder
# ---------------------------------------------------------------------------


def test_no_placeholder_passes_clean_markdown() -> None:
    check = NoPlaceholderCheck()
    content = b"# Introduction\n\nThis paper presents a complete result.\n"
    r = check("paper.md", content)
    assert r.ok is True
    assert r.check == "no_placeholder"


def test_no_placeholder_rejects_todo() -> None:
    check = NoPlaceholderCheck()
    content = b"# Introduction\n\nSee TODO: add citation.\n"
    r = check("paper.md", content)
    assert r.ok is False
    assert r.check == "no_placeholder"
    assert "TODO" in r.reason
    assert r.violating_path == "paper.md"


def test_no_placeholder_rejects_title_goes_here() -> None:
    check = NoPlaceholderCheck()
    content = b"# TITLE GOES HERE\n\nActual content.\n"
    r = check("paper.tex", content)
    assert r.ok is False
    assert "TITLE GOES HERE" in r.detail["token"]


def test_no_placeholder_ignores_binary_files() -> None:
    check = NoPlaceholderCheck()
    # Binary bytes that would coincidentally contain "TODO" as a
    # literal substring — the check should skip because the suffix is
    # not text-like.
    content = b"\x00\x01TODO\x00"
    r = check("image.png", content, context={"content_type": None})
    assert r.ok is True


# ---------------------------------------------------------------------------
# Check 2 — no_text_loop
# ---------------------------------------------------------------------------


def test_no_text_loop_passes_varied_prose() -> None:
    check = NoTextLoopCheck()
    content = (
        "The first paragraph describes the motivation behind the paper "
        "in considerable detail with a wide distribution of vocabulary "
        "to avoid triggering any simhash near duplicate detection.\n\n"
        "Here we analyse the empirical dataset from three disparate "
        "regions: Northern Europe, Southeast Asia, and the Andean "
        "highlands, noting stark demographic divergences between them.\n\n"
        "Finally we conclude with recommendations for policy makers "
        "regarding multilateral funding structures and the long-term "
        "governance of transboundary water resources.\n"
    ).encode("utf-8")
    r = check("paper.md", content)
    assert r.ok is True, f"varied prose must pass, got: {r.reason}"


def test_no_text_loop_rejects_five_sentences_repeated_ten_times() -> None:
    """Regression: the pathological loop observed in run 3 of the
    bilingual paper generator. Five distinct sentences repeated 10
    times must trip the simhash check."""
    check = NoTextLoopCheck()
    block = (
        "The climate model predicts significant warming across the "
        "equatorial zone over the next fifty years under current "
        "emission trajectories and with mitigation uncertainty still "
        "high among the major emitting regions. The report underscores "
        "this finding across five independent working groups.\n\n"
    )
    content = (block * 10).encode("utf-8")
    r = check("paper.md", content)
    assert r.ok is False, "repeated identical paragraphs must be rejected"
    assert r.check == "no_text_loop"
    assert r.detail["hamming"] <= NoTextLoopCheck.MAX_HAMMING
    assert r.detail["similarity"] >= 0.9


def test_no_text_loop_ignores_short_paragraphs() -> None:
    """Below-threshold paragraphs are skipped — short list items,
    table rows, and one-liners should never trip the check."""
    check = NoTextLoopCheck()
    content = (
        "- item one\n- item one\n- item one\n- item one\n- item one\n"
        "- item one\n- item one\n- item one\n- item one\n- item one\n"
    ).encode("utf-8")
    r = check("paper.md", content)
    assert r.ok is True


# ---------------------------------------------------------------------------
# Check 3 — file_size_delta
# ---------------------------------------------------------------------------


def test_file_size_delta_passes_without_previous() -> None:
    check = FileSizeDeltaCheck()
    content = b"x" * 500_000  # 500 KB
    r = check("paper.md", content, context={"previous_size": None})
    assert r.ok is True


def test_file_size_delta_rejects_runaway_growth() -> None:
    """Regression: the 341 MB runaway file observed in the bilingual
    paper E2E. A previous attempt of 10 KB followed by a 500 KB
    output (50x growth) must be rejected."""
    check = FileSizeDeltaCheck()
    content = b"x" * 500_000  # 500 KB current
    r = check("paper.md", content, context={"previous_size": 10_000})
    assert r.ok is False
    assert r.detail["growth_factor"] == 50.0
    assert "2.5" in r.reason


def test_file_size_delta_passes_small_growth() -> None:
    """Growth under the 2.5x ceiling is acceptable — repair attempts
    can legitimately add content, not just replace it."""
    check = FileSizeDeltaCheck()
    content = b"x" * 15_000
    r = check("paper.md", content, context={"previous_size": 10_000})
    assert r.ok is True


# ---------------------------------------------------------------------------
# Check 4 — no_duplicate_headings
# ---------------------------------------------------------------------------


def test_no_duplicate_headings_passes_unique() -> None:
    check = NoDuplicateHeadingsCheck()
    content = b"# Introduction\n\nText.\n\n## Results\n\nMore.\n"
    r = check("paper.md", content)
    assert r.ok is True


def test_no_duplicate_headings_rejects_latex_section_repeat() -> None:
    """Regression: ``\\section{Introduction}`` emitted twice by a
    repair worker that appended a new draft without removing the
    previous one."""
    check = NoDuplicateHeadingsCheck()
    content = (
        br"\section{Introduction}" + b"\n"
        br"First version." + b"\n\n"
        br"\section{Introduction}" + b"\n"
        br"Second version."
    )
    r = check("paper.tex", content)
    assert r.ok is False
    assert "Introduction" in r.reason
    assert r.detail["heading"] == "Introduction"


def test_no_duplicate_headings_rejects_markdown_repeat_case_insensitive() -> None:
    check = NoDuplicateHeadingsCheck()
    content = b"# Results\n\nA.\n\n# results\n\nB.\n"
    r = check("paper.md", content)
    assert r.ok is False


# ---------------------------------------------------------------------------
# Check 5 — balanced_delimiters
# ---------------------------------------------------------------------------


def test_balanced_delimiters_tolerant_on_prose_apostrophe() -> None:
    """Apostrophes in English prose must not trip the check. The
    tokenizer only counts curly/square/round brackets."""
    check = BalancedDelimitersCheck()
    content = b"It's a lovely day, isn't it? (The weather's fine.)\n"
    r = check("paper.md", content)
    assert r.ok is True


def test_balanced_delimiters_rejects_unbalanced_json() -> None:
    check = BalancedDelimitersCheck()
    content = b'{"key": "value", "list": [1, 2, 3}'  # missing closing ]
    r = check("data.json", content)
    assert r.ok is False
    assert "brackets" in r.reason or "braces" in r.reason
    assert r.severity == "error"


def test_balanced_delimiters_warning_on_prose_imbalance() -> None:
    """An unbalanced paren in a .md file is a WARNING, not an error
    — natural language is tolerant."""
    check = BalancedDelimitersCheck()
    content = b"This sentence (has an unclosed paren.\n"
    r = check("paper.md", content)
    assert r.ok is False
    assert r.severity == "warning"


def test_balanced_delimiters_ignores_fenced_code() -> None:
    """Triple-backtick fences are skipped — unmatched braces inside
    example code must not trip the check."""
    check = BalancedDelimitersCheck()
    content = (
        b"Some prose.\n\n"
        b"```\n"
        b"function foo() {\n"
        b"```\n\n"
        b"More prose.\n"
    )
    r = check("paper.md", content)
    assert r.ok is True


# ---------------------------------------------------------------------------
# Check 6 — json_valid_if_claimed
# ---------------------------------------------------------------------------


def test_json_valid_if_claimed_passes_on_valid_json() -> None:
    check = JsonValidIfClaimedCheck()
    content = b'{"a": 1, "b": [2, 3]}'
    r = check("data.json", content)
    assert r.ok is True


def test_json_valid_if_claimed_rejects_malformed() -> None:
    check = JsonValidIfClaimedCheck()
    content = b'{"a": 1, "b": [2, 3'
    r = check("data.json", content)
    assert r.ok is False
    assert "json.loads" in r.reason


def test_json_valid_if_claimed_ignores_non_json_suffix() -> None:
    check = JsonValidIfClaimedCheck()
    content = b"not json at all"
    r = check("paper.md", content)
    assert r.ok is True


def test_json_valid_if_claimed_fires_on_claimed_format_context() -> None:
    """When the caller declares ``claimed_format="json"`` the check
    fires even on a non-.json filename."""
    check = JsonValidIfClaimedCheck()
    content = b"not json"
    r = check("output.txt", content, context={"claimed_format": "json"})
    assert r.ok is False


# ---------------------------------------------------------------------------
# Validator orchestrator
# ---------------------------------------------------------------------------


def test_validator_runs_all_defaults_by_name() -> None:
    v = L0Validator()
    content = b"# Clean\n\nSingle paragraph.\n"
    r = v.run("paper.md", content)
    assert isinstance(r, CheckResult)
    assert r.ok is True
    assert r.check == "l0_chain"


def test_validator_short_circuits_on_first_error() -> None:
    """The validator returns the FIRST failing error-severity check,
    not a list, when ``short_circuit=True`` (default)."""
    v = L0Validator()
    # Placeholder fires before text_loop — confirm we get the
    # placeholder rejection, not the structurally-clean rest.
    content = b"# Title\n\nThis section is TODO.\n"
    r = v.run("paper.md", content)
    assert isinstance(r, CheckResult)
    assert r.ok is False
    assert r.check == "no_placeholder"


def test_validator_non_short_circuit_returns_full_list() -> None:
    v = L0Validator()
    content = b"# Only heading\n"
    results = v.run("paper.md", content, short_circuit=False)
    assert isinstance(results, list)
    # All 6 default checks must have run
    names = {r.check for r in results}
    for default in DEFAULT_CHECK_NAMES:
        assert default in names, f"default check {default!r} must run"


def test_validator_respects_enabled_false() -> None:
    contract = OutputContract(enabled=False)
    v = L0Validator(contract)
    content = b"TODO: everything"
    r = v.run("paper.md", content)
    # With no checks registered the synthetic pass is returned.
    assert isinstance(r, CheckResult)
    assert r.ok is True
    assert r.check == "l0_chain"


def test_validator_filters_by_check_name() -> None:
    """``checks: ["no_placeholder"]`` runs only one default check —
    text-loop violations are no longer caught."""
    contract = OutputContract(checks=["no_placeholder"])
    v = L0Validator(contract)
    # Pure text-loop case that would fail ``no_text_loop`` but passes
    # ``no_placeholder``.
    block = (
        "Some deterministic paragraph with at least twenty distinct "
        "words repeated across the entire document to trigger the "
        "simhash path but we filter that check out.\n\n"
    )
    content = (block * 10).encode("utf-8")
    r = v.run("paper.md", content)
    assert r.ok is True  # text_loop not in chain


def test_validator_default_expands_to_six_checks() -> None:
    v = L0Validator()
    results = v.run("output.md", b"clean content\n", short_circuit=False)
    assert isinstance(results, list)
    assert len(results) == 6


def test_validator_non_short_circuit_reports_warnings() -> None:
    """When ``short_circuit=False`` warnings surface in the result
    list but do not halt the chain."""
    v = L0Validator()
    content = b"Some prose (with unclosed paren.\n"
    results = v.run("paper.md", content, short_circuit=False)
    # balanced_delimiters rejects at warning severity
    assert isinstance(results, list)
    delim = next(r for r in results if r.check == "balanced_delimiters")
    assert delim.ok is False
    assert delim.severity == "warning"


def test_output_contract_check_protocol_runtime_check() -> None:
    """Every bundled check satisfies the Protocol structurally."""
    for cls in (
        NoPlaceholderCheck,
        NoTextLoopCheck,
        FileSizeDeltaCheck,
        NoDuplicateHeadingsCheck,
        BalancedDelimitersCheck,
        JsonValidIfClaimedCheck,
    ):
        instance = cls()
        assert isinstance(instance, OutputContractCheck), (
            f"{cls.__name__} must satisfy the OutputContractCheck protocol"
        )
        assert hasattr(instance, "name")
        assert callable(instance)
