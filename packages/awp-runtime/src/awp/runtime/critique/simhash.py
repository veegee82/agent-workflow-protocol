"""Shared simhash primitives used by the L0 Output Contract (R34) and
the Repair Fixpoint guard (R35).

Extracted as a stand-alone module so the delegation-loop runner can
reuse the exact same hashing without importing the heavier
:mod:`awp.runtime.critique.l0_validator` surface (which pulls in the
full output-contract check registry).

All functions are pure Python, stdlib only — no external dependency.

Functions:

* :func:`tokenize`  — lowercased ``[A-Za-z0-9']+`` tokens.
* :func:`simhash64` — Charikar (2002) 64-bit simhash over a token bag.
* :func:`hamming64` — 64-bit Hamming distance.
* :func:`similarity` — normalized similarity ``1 - hamming / 64``.
* :func:`text_simhash` — convenience wrapper ``tokenize → simhash64``.

The parameters (64 bits, BLAKE2b per token, ``\\w+``-style tokenizer)
are pinned by the L0 NoTextLoopCheck which has been in production since
Phase 1 — do not change them without coordinating with the L0 tests.
"""

from __future__ import annotations

import hashlib
import re

__all__ = [
    "tokenize",
    "simhash64",
    "hamming64",
    "similarity",
    "text_simhash",
]


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Return a lowercased token list over ``text``.

    Matches runs of ``[A-Za-z0-9']`` — punctuation and whitespace act as
    separators. Intentionally naive so the same tokenizer serves both
    natural-language and code-shaped artifacts.
    """
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def simhash64(tokens: list[str]) -> int:
    """Charikar (2002) simhash over a bag of tokens.

    Each token is hashed to a 64-bit integer (BLAKE2b, first 8 bytes).
    For every bit position, the +1 votes from tokens with that bit set
    are weighed against the -1 votes from tokens with it clear. The
    sign of the aggregate becomes the output bit.

    Returns 0 for an empty token list — callers should treat that as
    "no signal" rather than "identical to another empty input".
    """
    vote = [0] * 64
    if not tokens:
        return 0
    for tok in tokens:
        h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        bits = int.from_bytes(h, byteorder="big", signed=False)
        for i in range(64):
            if (bits >> i) & 1:
                vote[i] += 1
            else:
                vote[i] -= 1
    out = 0
    for i in range(64):
        if vote[i] > 0:
            out |= 1 << i
    return out


def hamming64(a: int, b: int) -> int:
    """64-bit Hamming distance between two simhashes."""
    return ((a ^ b) & 0xFFFFFFFFFFFFFFFF).bit_count()


def similarity(a: int, b: int) -> float:
    """Normalized 64-bit simhash similarity in ``[0.0, 1.0]``.

    ``1.0`` is identical; ``0.5`` is random-bits-apart. Computed as
    ``1 - hamming64(a, b) / 64``.
    """
    return 1.0 - hamming64(a, b) / 64.0


def text_simhash(text: str) -> int:
    """Compute the 64-bit simhash of a whole text string.

    Convenience wrapper that tokenises and hashes in one call. For
    repair-fixpoint detection we compare full worker outputs as single
    bags, so paragraph segmentation (used by L0 NoTextLoopCheck) is
    intentionally skipped here.
    """
    return simhash64(tokenize(text))
