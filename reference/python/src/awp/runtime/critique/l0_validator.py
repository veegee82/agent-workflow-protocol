"""Layer 0 Output Contract — validator + 6 default checks.

See ``docs/critique.md`` § "Layer 0 Output Contract (R34)" for the
normative semantics. This module implements the bundled default checks
and the :class:`L0Validator` orchestrator that runs them in canonical
order.

Design rules (enforced by the :class:`OutputContractCheck` protocol in
``contracts.py``):

* Synchronous, side-effect free, no LLM.
* ``< 100 ms`` on a 10 MB input.
* Checks operate on ``(path, content, context)`` — no subprocess spawn,
  no socket, no file read beyond the provided ``content``.
* All state (previous attempt size, attempt number, claimed format)
  flows through the ``context`` dict.

Default checks (canonical order):

1. :class:`NoPlaceholderCheck` — rejects ``TODO``/``XXX``/``???``/
   ``Lorem ipsum``/``TBD``/``FIXME``/``TITLE GOES HERE``/``Author Name``/
   ``to be filled`` on any text artifact.
2. :class:`NoTextLoopCheck` — per-paragraph simhash (Charikar 2002);
   rejects if any pair of ≥20-word paragraphs has Hamming distance ≤ 6.
3. :class:`FileSizeDeltaCheck` — rejects when
   ``current / previous > 2.5``. Passes when ``previous_size`` is None.
4. :class:`NoDuplicateHeadingsCheck` — Markdown + LaTeX duplicate headers.
5. :class:`BalancedDelimitersCheck` — ``{}``/``[]``/``()`` balance
   (tokenizer ignores LaTeX verbatim, Markdown triple-backtick fences,
   JSON string literals). Warning-level on non-code artifacts.
6. :class:`JsonValidIfClaimedCheck` — ``.json`` suffix or
   ``claimed_format == "json"`` → ``json.loads`` must succeed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import CheckResult, OutputContract, OutputContractCheck
from .simhash import (
    hamming64 as _hamming64,
    simhash64 as _simhash64,
    tokenize as _tokenize,
)

__all__ = [
    "L0Validator",
    "NoPlaceholderCheck",
    "NoTextLoopCheck",
    "FileSizeDeltaCheck",
    "NoDuplicateHeadingsCheck",
    "BalancedDelimitersCheck",
    "JsonValidIfClaimedCheck",
    "DEFAULT_CHECK_NAMES",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TEXT_SUFFIXES = {
    ".md",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".rst",
    ".html",
    ".htm",
    ".xml",
    ".csv",
    ".log",
    "",  # no suffix
}


def _is_text_artifact(path: str, content_type: str | None) -> bool:
    """Best-effort text/binary decision.

    Rules:
    * Known text suffixes (``.md``, ``.tex``, ``.txt``, …) — text.
    * Missing suffix — text (worker outputs often have bare names).
    * ``content_type`` starting with ``text/`` or ``application/json`` —
      text.
    * Everything else — not text.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return True
    if content_type:
        ct = content_type.lower()
        if ct.startswith("text/") or ct in ("application/json", "application/xml"):
            return True
    return False


def _decode_best_effort(content: bytes) -> str | None:
    """Decode bytes as UTF-8; return None for pure binary."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Check 1 — NoPlaceholder
# ---------------------------------------------------------------------------


class NoPlaceholderCheck:
    """Reject outputs that still contain drafting placeholders.

    Matches (word-boundary where applicable, case-sensitive for the
    literal markers that indicate unfinished text):

    * ``TODO``, ``XXX``, ``FIXME``, ``TBD``
    * ``???`` (three consecutive question marks)
    * ``Lorem ipsum``
    * ``TITLE GOES HERE``, ``Author Name``, ``to be filled``
    """

    name = "no_placeholder"

    _PATTERN = re.compile(
        r"\bTODO\b|\bXXX\b|\?\?\?|Lorem ipsum|\bTBD\b|\bFIXME\b|"
        r"TITLE GOES HERE|Author Name|to be filled",
    )

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        content_type = ctx.get("content_type")
        if not _is_text_artifact(path, content_type):
            return CheckResult(ok=True, check=self.name, violating_path=path)

        text = _decode_best_effort(content)
        if text is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        m = self._PATTERN.search(text)
        if m is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        # Report the matched token + 40-char window around it for context.
        start = max(0, m.start() - 20)
        end = min(len(text), m.end() + 20)
        window = text[start:end].replace("\n", " ")
        return CheckResult(
            ok=False,
            check=self.name,
            reason=f"found placeholder token {m.group(0)!r}",
            violating_path=path,
            detail={
                "token": m.group(0),
                "offset": m.start(),
                "window": window,
            },
        )


# ---------------------------------------------------------------------------
# Check 2 — NoTextLoop (simhash over paragraphs, Charikar 2002)
# ---------------------------------------------------------------------------


# NOTE: the ``_tokenize`` / ``_simhash64`` / ``_hamming64`` symbols now live
# in :mod:`awp.runtime.critique.simhash` and are re-exported under their
# original private names here so existing imports keep working byte-for-byte.
# The Phase-3 Repair Fixpoint guard (R35) imports from the shared module
# directly instead of reaching into this file.

_PARAGRAPH_SEP = re.compile(r"\n\s*\n")


class NoTextLoopCheck:
    """Reject outputs whose paragraphs are near-duplicates of each other.

    Splits the artifact on blank lines, keeps paragraphs with ≥ 20
    tokens (via :func:`_tokenize`), computes a 64-bit simhash for each,
    and rejects when any pair has Hamming distance ≤ 6 bits (~
    similarity ≥ 0.91). This catches the "produce more output by
    repeating the same 5 sentences 10×" pathology without a
    dependency on an external simhash library.
    """

    name = "no_text_loop"

    # 6 bits of 64 ≈ similarity 0.906 — tuned so the pathological
    # "5 sentences repeated 10 times" case trips reliably.
    MAX_HAMMING = 6
    MIN_WORDS = 20

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        content_type = ctx.get("content_type")
        if not _is_text_artifact(path, content_type):
            return CheckResult(ok=True, check=self.name, violating_path=path)

        text = _decode_best_effort(content)
        if text is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        paragraphs = [p.strip() for p in _PARAGRAPH_SEP.split(text) if p.strip()]
        # Compute simhash only for paragraphs with enough words to be
        # meaningful; short list-items / table rows are skipped.
        hashes: list[tuple[int, int, str]] = []  # (index, simhash, preview)
        for idx, p in enumerate(paragraphs):
            toks = _tokenize(p)
            if len(toks) < self.MIN_WORDS:
                continue
            h = _simhash64(toks)
            hashes.append((idx, h, p[:80]))

        if len(hashes) < 2:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        for i in range(len(hashes)):
            for j in range(i + 1, len(hashes)):
                dist = _hamming64(hashes[i][1], hashes[j][1])
                if dist <= self.MAX_HAMMING:
                    sim = 1.0 - dist / 64.0
                    return CheckResult(
                        ok=False,
                        check=self.name,
                        reason=(
                            f"paragraphs {hashes[i][0]} and {hashes[j][0]} "
                            f"are near-duplicates (hamming={dist}, "
                            f"similarity={sim:.3f})"
                        ),
                        violating_path=path,
                        detail={
                            "paragraph_a": hashes[i][0],
                            "paragraph_b": hashes[j][0],
                            "hamming": dist,
                            "similarity": round(sim, 4),
                            "preview_a": hashes[i][2],
                            "preview_b": hashes[j][2],
                        },
                    )
        return CheckResult(ok=True, check=self.name, violating_path=path)


# ---------------------------------------------------------------------------
# Check 3 — FileSizeDelta
# ---------------------------------------------------------------------------


class FileSizeDeltaCheck:
    """Reject repair outputs whose size explodes relative to the previous
    attempt.

    The runtime injects ``previous_size`` (in bytes) through the
    ``context`` dict. If absent or ``None`` (first attempt, no prior
    comparison), the check passes. If
    ``current / previous > MAX_GROWTH`` (default ``2.5``), it rejects —
    this catches the "append-leak" class of failures where a worker
    repeatedly concatenates its own output onto the previous version.
    """

    name = "file_size_delta"

    MAX_GROWTH = 2.5

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        previous = ctx.get("previous_size")
        current = len(content)
        if previous is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)
        if not isinstance(previous, int) or previous <= 0:
            # Defensive: treat any non-positive previous as "no baseline".
            return CheckResult(ok=True, check=self.name, violating_path=path)
        ratio = current / previous
        if ratio > self.MAX_GROWTH:
            return CheckResult(
                ok=False,
                check=self.name,
                reason=(
                    f"output size grew from {previous} B to {current} B "
                    f"(factor {ratio:.2f} > {self.MAX_GROWTH})"
                ),
                violating_path=path,
                detail={
                    "previous_bytes": previous,
                    "current_bytes": current,
                    "growth_factor": round(ratio, 4),
                },
            )
        return CheckResult(ok=True, check=self.name, violating_path=path)


# ---------------------------------------------------------------------------
# Check 4 — NoDuplicateHeadings
# ---------------------------------------------------------------------------


class NoDuplicateHeadingsCheck:
    """Reject artifacts with duplicate Markdown or LaTeX section headers.

    Matches (multiline):

    * Markdown ``^#{1,6}\\s+(.+)$`` (excluding trailing pound signs, if
      present — common in CommonMark).
    * LaTeX ``\\section*?\\{…\\}`` and ``\\subsection*?\\{…\\}``.

    Duplicates are detected case-insensitively after trimming whitespace
    and punctuation.
    """

    name = "no_duplicate_headings"

    _MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
    _LATEX_SECTION = re.compile(r"\\(?:section|subsection)\*?\{([^}]+)\}")

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        content_type = ctx.get("content_type")
        if not _is_text_artifact(path, content_type):
            return CheckResult(ok=True, check=self.name, violating_path=path)

        text = _decode_best_effort(content)
        if text is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        seen: dict[str, int] = {}
        dup: tuple[str, int] | None = None
        for m in self._MD_HEADING.finditer(text):
            norm = m.group(1).strip().lower()
            if not norm:
                continue
            if norm in seen:
                dup = (m.group(1).strip(), seen[norm])
                break
            seen[norm] = m.start()
        if dup is None:
            for m in self._LATEX_SECTION.finditer(text):
                norm = m.group(1).strip().lower()
                if not norm:
                    continue
                if norm in seen:
                    dup = (m.group(1).strip(), seen[norm])
                    break
                seen[norm] = m.start()
        if dup is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        return CheckResult(
            ok=False,
            check=self.name,
            reason=f"duplicate heading: {dup[0]!r}",
            violating_path=path,
            detail={
                "heading": dup[0],
                "first_offset": dup[1],
            },
        )


# ---------------------------------------------------------------------------
# Check 5 — BalancedDelimiters
# ---------------------------------------------------------------------------


@dataclass
class _DelimCounts:
    braces: int = 0
    brackets: int = 0
    parens: int = 0


def _count_delimiters(text: str) -> _DelimCounts:
    """Count ``{}``/``[]``/``()`` pairs with skip regions.

    Skipped:
    * LaTeX verbatim blocks (``\\begin{verbatim}`` … ``\\end{verbatim}``).
    * Markdown triple-backtick fenced code blocks.
    * JSON string literals (``"…"``, with ``\\"`` and ``\\\\`` escapes).

    Note: this tokenizer is intentionally naïve — a real AST is out of
    scope for L0. On well-formed artifacts the counts balance; on the
    pathological "unclosed brace" failure class it reliably detects the
    imbalance.
    """
    counts = _DelimCounts()
    i = 0
    n = len(text)
    in_fence = False
    while i < n:
        # Markdown triple-backtick fence toggles (only at line start
        # after optional whitespace).
        if text[i:i + 3] == "```":
            in_fence = not in_fence
            i += 3
            continue
        if in_fence:
            i += 1
            continue
        # LaTeX verbatim skip
        if text.startswith(r"\begin{verbatim}", i):
            close = text.find(r"\end{verbatim}", i)
            if close == -1:
                # Unclosed verbatim — consume to EOF to avoid spurious
                # errors from content that would otherwise have
                # balanced delimiters.
                return counts
            i = close + len(r"\end{verbatim}")
            continue
        ch = text[i]
        # JSON string skip
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            i = j
            continue
        if ch == "{":
            counts.braces += 1
        elif ch == "}":
            counts.braces -= 1
        elif ch == "[":
            counts.brackets += 1
        elif ch == "]":
            counts.brackets -= 1
        elif ch == "(":
            counts.parens += 1
        elif ch == ")":
            counts.parens -= 1
        i += 1
    return counts


_CODE_SUFFIXES = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go",
                  ".rs", ".json", ".yaml", ".yml", ".tex"}


class BalancedDelimitersCheck:
    """Count ``{}``/``[]``/``()`` pairs; reject imbalance.

    Prose is tolerant by design: on non-code artifacts (``.md``,
    ``.txt``, unknown suffix) the check downgrades its severity to
    ``warning`` so a stray unmatched parenthesis in a sentence does
    not block completion. On code-like artifacts (``.py``, ``.json``,
    ``.tex``, …) the check rejects at ``error`` severity.
    """

    name = "balanced_delimiters"

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        content_type = ctx.get("content_type")
        if not _is_text_artifact(path, content_type):
            return CheckResult(ok=True, check=self.name, violating_path=path)

        text = _decode_best_effort(content)
        if text is None:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        counts = _count_delimiters(text)
        if counts.braces == 0 and counts.brackets == 0 and counts.parens == 0:
            return CheckResult(ok=True, check=self.name, violating_path=path)

        suffix = Path(path).suffix.lower()
        is_code = suffix in _CODE_SUFFIXES
        severity = "error" if is_code else "warning"

        parts = []
        if counts.braces:
            parts.append(f"braces off by {counts.braces}")
        if counts.brackets:
            parts.append(f"brackets off by {counts.brackets}")
        if counts.parens:
            parts.append(f"parens off by {counts.parens}")
        reason = "; ".join(parts)

        return CheckResult(
            ok=False,
            check=self.name,
            reason=reason,
            severity=severity,
            violating_path=path,
            detail={
                "braces_delta": counts.braces,
                "brackets_delta": counts.brackets,
                "parens_delta": counts.parens,
                "is_code_artifact": is_code,
            },
        )


# ---------------------------------------------------------------------------
# Check 6 — JsonValidIfClaimed
# ---------------------------------------------------------------------------


class JsonValidIfClaimedCheck:
    """If the artifact claims JSON, ``json.loads`` must succeed.

    Claim sources (any of):

    * ``Path(path).suffix.lower() == ".json"``.
    * ``context.get("claimed_format") == "json"``.

    For non-claimed artifacts, the check passes unconditionally.
    """

    name = "json_valid_if_claimed"

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ctx = context or {}
        suffix = Path(path).suffix.lower()
        claimed = ctx.get("claimed_format")
        if suffix != ".json" and claimed != "json":
            return CheckResult(ok=True, check=self.name, violating_path=path)

        text = _decode_best_effort(content)
        if text is None:
            return CheckResult(
                ok=False,
                check=self.name,
                reason="artifact claimed JSON but bytes are not UTF-8 decodable",
                violating_path=path,
            )
        try:
            json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            return CheckResult(
                ok=False,
                check=self.name,
                reason=f"json.loads failed: {exc}",
                violating_path=path,
                detail={"error": str(exc)},
            )
        return CheckResult(ok=True, check=self.name, violating_path=path)


# ---------------------------------------------------------------------------
# Validator orchestrator
# ---------------------------------------------------------------------------


DEFAULT_CHECK_NAMES: list[str] = [
    "no_placeholder",
    "no_text_loop",
    "file_size_delta",
    "no_duplicate_headings",
    "balanced_delimiters",
    "json_valid_if_claimed",
]


def _build_default_checks() -> list[OutputContractCheck]:
    return [
        NoPlaceholderCheck(),
        NoTextLoopCheck(),
        FileSizeDeltaCheck(),
        NoDuplicateHeadingsCheck(),
        BalancedDelimitersCheck(),
        JsonValidIfClaimedCheck(),
    ]


class L0Validator:
    """Orchestrates the L0 contract chain over one worker artifact.

    Construction reads the :class:`OutputContract` config (dataclass or
    dict) and resolves ``checks`` → concrete callables. The special
    name ``"default"`` expands to the 6 bundled defaults. Extra checks
    supplied via ``contract.extra`` are loaded via :func:`_load_extra`
    — this intentionally stays minimal (no plug-in ecosystem): workflow
    authors import their own module on the Python path.

    Usage
    -----

    >>> v = L0Validator()
    >>> result = v.run("paper.md", data_bytes, context={"attempt": 2,
    ...                                                  "previous_size": 4096})
    >>> if not result.ok:
    ...     reject_with(result.check, result.reason, result.violating_path)
    """

    def __init__(self, contract: OutputContract | dict | None = None) -> None:
        if contract is None:
            contract = OutputContract()
        elif isinstance(contract, dict):
            contract = OutputContract(
                checks=list(contract.get("checks") or ["default"]),
                extra=list(contract.get("extra") or []),
                enabled=bool(contract.get("enabled", True)),
            )
        self.contract = contract
        self._checks: list[OutputContractCheck] = self._resolve_checks(contract)

    def _resolve_checks(self, contract: OutputContract) -> list[OutputContractCheck]:
        resolved: list[OutputContractCheck] = []
        if not contract.enabled:
            return resolved

        # Build a name → instance map of the defaults so users can
        # filter down by naming individual checks.
        defaults_by_name = {c.name: c for c in _build_default_checks()}

        for entry in contract.checks:
            if entry == "default":
                resolved.extend(_build_default_checks())
            elif entry in defaults_by_name:
                resolved.append(defaults_by_name[entry])
            else:
                # Unknown names are silently ignored — workflow authors
                # can add non-default names alongside extras without
                # crashing the runtime. The missing check shows up in
                # events as "not run" rather than "failed to import".
                continue

        for extra in contract.extra or []:
            impl = self._load_extra(extra)
            if impl is not None:
                resolved.append(impl)

        return resolved

    @staticmethod
    def _load_extra(spec: dict[str, Any]) -> OutputContractCheck | None:
        """Load an ``{"name": ..., "implementation": "mod.path:Cls"}``
        entry. Returns ``None`` if import fails; the orchestrator treats
        that as "extra check not available" and proceeds. A failing
        extra MUST NOT crash the L0 chain.
        """
        impl_ref = spec.get("implementation")
        if not isinstance(impl_ref, str) or ":" not in impl_ref:
            return None
        mod_path, attr = impl_ref.split(":", 1)
        try:
            import importlib

            mod = importlib.import_module(mod_path)
            cls_or_fn = getattr(mod, attr)
            instance = cls_or_fn() if isinstance(cls_or_fn, type) else cls_or_fn
        except Exception:
            return None
        if not isinstance(instance, OutputContractCheck):
            # Soft-type-check via Protocol — we accept anything callable
            # with a .name attribute.
            if not (callable(instance) and hasattr(instance, "name")):
                return None
        return instance

    def run(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
        *,
        short_circuit: bool = True,
    ) -> CheckResult | list[CheckResult]:
        """Run the contract chain on a single artifact.

        Parameters
        ----------
        path : str
            Absolute or workflow-relative path of the artifact (used for
            the ``violating_path`` field and the suffix-based heuristics
            in :class:`JsonValidIfClaimedCheck` + friends).
        content : bytes
            Raw artifact bytes. L0 checks own the decoding decision
            (some want bytes, most want UTF-8 text).
        context : dict, optional
            Extra state for stateful checks — ``previous_size``,
            ``attempt``, ``claimed_format``, ``content_type``. Individual
            checks tolerate missing keys.
        short_circuit : bool, keyword-only, default ``True``
            ``True`` (default) returns the first failing :class:`CheckResult`
            (or a synthetic pass if all checks pass). ``False`` returns
            the full list — every check runs, warnings do not stop the
            chain. Use ``False`` when you want a scorecard.

        Returns
        -------
        CheckResult | list[CheckResult]
            A single result in short-circuit mode, a list otherwise.
        """
        results: list[CheckResult] = []
        for check in self._checks:
            try:
                r = check(path, content, context)
            except Exception as exc:  # pragma: no cover - defensive
                r = CheckResult(
                    ok=True,  # A raising check must not block production.
                    check=getattr(check, "name", "unknown"),
                    reason=f"check raised: {exc}",
                    severity="warning",
                    violating_path=path,
                    detail={"error": str(exc)},
                )
            results.append(r)
            if short_circuit and not r.ok and r.severity == "error":
                return r
        if short_circuit:
            # All error-severity checks passed; return a synthetic pass
            # (the first warning-only failure, if any, is NOT returned
            # to preserve the "first error-severity failure wins" contract).
            return CheckResult(
                ok=True,
                check="l0_chain",
                reason="all error-severity checks passed",
                violating_path=path,
            )
        return results
