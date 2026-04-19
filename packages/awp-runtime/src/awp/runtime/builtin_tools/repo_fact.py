"""``repo.fact(query, max_snippets)`` — TF-IDF lookup over workspace inputs.

Phase 3.4 / robustness. The tool lets any LLM worker pull ranked text
snippets from the run's ``_workspace_dir/inputs/`` tree without needing
an embedding model or network call. Pure Python TF-IDF so the runtime
dependency surface does not grow.

Design rules:

* **Scope**: reads only under ``<workspace>/inputs/``. The rest of the
  workspace (``outputs``, ``runs``, dynamic tools) is off-limits.
* **Formats**: ``.md``, ``.markdown``, ``.txt``, ``.rst``, ``.py``
  (docstrings + comments included as plain text), ``.json``, ``.yaml``,
  ``.yml``. Binary and unknown extensions are silently skipped.
* **Cache**: per-run JSON at ``<workspace>/.fact_index.json``. The cache
  fingerprint is a ``(path, size, mtime_ns)`` tuple over every input
  file; if the fingerprint changes the index is rebuilt lazily on the
  next call. ``.fact_index.json`` itself is excluded from indexing.
* **Ranking**: bag-of-words TF-IDF with sub-linear term-frequency
  scaling (``1 + log(tf)``) and log-scaled IDF (``log((N+1)/(df+1)) +
  1``). Snippets are 400-char windows centred on the highest-scoring
  paragraph.

The tool is **not** auto-registered in default workflows. Workflow
authors opt in per subtask via ``tools_allowed: ["repo.fact"]``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# File extensions treated as text for indexing. Binary blobs (pdf,
# images, parquet) are excluded — they need a dedicated extractor.
_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".py",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".ini",
        ".cfg",
    }
)

# Minimum number of snippet characters — below this we just return the
# whole paragraph.
_SNIPPET_CHAR_BUDGET = 400


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+", re.UNICODE)
_PARAGRAPH_SEP = re.compile(r"\n\s*\n")


# Common English stopwords (small hand-curated list — no nltk
# dependency). Improves ranking on short queries like "what is X".
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "to", "of", "in", "on", "at", "by", "for", "with", "about", "as",
        "from", "up", "down", "out", "over", "under", "this", "that",
        "these", "those", "it", "its", "they", "them", "their", "there",
        "which", "who", "whom", "what", "when", "where", "why", "how",
        "if", "then", "than", "so", "too", "very", "can", "just", "not",
        "no", "nor", "only", "own", "same", "some", "any", "all", "each",
    }
)


def _tokenize(text: str) -> list[str]:
    """Lowercased token list with stopwords removed."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS]


@dataclass
class _Document:
    """One indexed paragraph."""

    path: str  # relative to the index's root
    offset: int  # character offset in the source file (paragraph start)
    text: str  # paragraph text (truncated to snippet budget when rendered)
    tokens: list[str] = field(default_factory=list)
    tf: dict[str, int] = field(default_factory=dict)
    token_count: int = 0


class RepoFactIndex:
    """Per-run TF-IDF index over ``<inputs_root>`` and its subtree.

    Persisted as JSON so a second call in the same run avoids rebuilding.
    The cache file stores ``(fingerprint, documents, idf)`` — on load the
    fingerprint is re-checked and a mismatch triggers a full rebuild.
    """

    CACHE_FILENAME = ".fact_index.json"

    def __init__(self, inputs_root: Path, cache_path: Path) -> None:
        self._inputs_root = Path(inputs_root)
        self._cache_path = Path(cache_path)
        self._documents: list[_Document] = []
        self._idf: dict[str, float] = {}
        self._fingerprint: str = ""
        # Phase 3.4 test hook — counts full rebuilds so the cache test
        # can assert "2nd call did NOT rebuild". Always monotonic
        # non-negative.
        self.rebuild_count: int = 0

    # -- Public API --------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Load the cache or rebuild the index if the fingerprint drifted."""
        fp = self._compute_fingerprint()
        if self._cache_path.is_file():
            try:
                payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict) and payload.get("fingerprint") == fp:
                self._load_from_payload(payload)
                self._fingerprint = fp
                return
        # Rebuild.
        self._build()
        self._fingerprint = fp
        self._persist()

    def query(self, query_text: str, max_snippets: int = 3) -> list[dict[str, Any]]:
        """Return up to ``max_snippets`` ranked snippets for ``query_text``."""
        self.ensure_loaded()
        if not self._documents:
            return []
        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []
        # Score every document. Sub-linear TF + IDF.
        scores: list[tuple[float, _Document]] = []
        for doc in self._documents:
            score = 0.0
            for qt in query_tokens:
                tf_raw = doc.tf.get(qt, 0)
                if tf_raw == 0:
                    continue
                tf = 1.0 + math.log(tf_raw)
                idf = self._idf.get(qt, 0.0)
                score += tf * idf
            if score > 0.0:
                scores.append((score, doc))
        if not scores:
            return []
        scores.sort(key=lambda t: t[0], reverse=True)
        take = max(1, int(max_snippets) if max_snippets else 3)
        out: list[dict[str, Any]] = []
        for score, doc in scores[:take]:
            out.append(
                {
                    "path": doc.path,
                    "offset": doc.offset,
                    "snippet": self._format_snippet(doc.text),
                    "score": round(score, 6),
                }
            )
        return out

    # -- Internal ----------------------------------------------------------

    def _format_snippet(self, text: str) -> str:
        if len(text) <= _SNIPPET_CHAR_BUDGET:
            return text
        return text[:_SNIPPET_CHAR_BUDGET].rstrip() + "…"

    def _iter_input_files(self) -> list[Path]:
        if not self._inputs_root.is_dir():
            return []
        out: list[Path] = []
        cache_abs = self._cache_path.resolve()
        for p in sorted(self._inputs_root.rglob("*")):
            if not p.is_file():
                continue
            if p.resolve() == cache_abs:
                continue
            if p.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            # Skip files larger than 2 MB — the tool is for text
            # snippets, not log dumps. Prevents pathological memory
            # blowup on an accidental ``.csv`` dump.
            try:
                if p.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            out.append(p)
        return out

    def _compute_fingerprint(self) -> str:
        """Cheap content-independent fingerprint over the input tree."""
        parts: list[str] = []
        for p in self._iter_input_files():
            try:
                st = p.stat()
            except OSError:
                continue
            rel = str(p.relative_to(self._inputs_root))
            parts.append(f"{rel}|{st.st_size}|{st.st_mtime_ns}")
        return "\n".join(parts)

    def _build(self) -> None:
        self.rebuild_count += 1
        docs: list[_Document] = []
        df: dict[str, int] = {}
        for p in self._iter_input_files():
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(self._inputs_root))
            offset = 0
            for para in _PARAGRAPH_SEP.split(raw):
                paragraph_offset = offset
                offset += len(para) + 2  # +2 for the paragraph separator approximation
                para_stripped = para.strip()
                if not para_stripped:
                    continue
                tokens = _tokenize(para_stripped)
                if not tokens:
                    continue
                tf: dict[str, int] = {}
                for t in tokens:
                    tf[t] = tf.get(t, 0) + 1
                doc = _Document(
                    path=rel,
                    offset=paragraph_offset,
                    text=para_stripped,
                    tokens=tokens,
                    tf=tf,
                    token_count=len(tokens),
                )
                docs.append(doc)
                for term in tf:
                    df[term] = df.get(term, 0) + 1
        self._documents = docs
        n_docs = len(docs) or 1
        # Smoothed IDF so unseen terms score zero without raising.
        self._idf = {
            term: math.log((n_docs + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

    def _load_from_payload(self, payload: dict[str, Any]) -> None:
        docs_raw = payload.get("documents") or []
        self._documents = []
        for d in docs_raw:
            if not isinstance(d, dict):
                continue
            self._documents.append(
                _Document(
                    path=str(d.get("path", "")),
                    offset=int(d.get("offset", 0) or 0),
                    text=str(d.get("text", "")),
                    tokens=list(d.get("tokens") or []),
                    tf=dict(d.get("tf") or {}),
                    token_count=int(d.get("token_count", 0) or 0),
                )
            )
        idf = payload.get("idf") or {}
        self._idf = {str(k): float(v) for k, v in idf.items()}

    def _persist(self) -> None:
        payload = {
            "fingerprint": self._fingerprint,
            "idf": self._idf,
            "documents": [
                {
                    "path": d.path,
                    "offset": d.offset,
                    "text": d.text,
                    "tokens": d.tokens,
                    "tf": d.tf,
                    "token_count": d.token_count,
                }
                for d in self._documents
            ],
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("repo.fact: failed to persist index: %s", exc)


# Process-local cache keyed by the absolute inputs_root so multiple
# worker calls within the same run share the loaded index in memory,
# avoiding even the cache-hit JSON parse. The key is the resolved
# string of the inputs root.
_INDEX_CACHE: dict[str, RepoFactIndex] = {}


def _get_index_for(workspace_dir: Path) -> RepoFactIndex:
    inputs_root = workspace_dir / "inputs"
    cache_path = workspace_dir / RepoFactIndex.CACHE_FILENAME
    key = str(inputs_root.resolve())
    idx = _INDEX_CACHE.get(key)
    if idx is not None:
        idx.ensure_loaded()
        return idx
    idx = RepoFactIndex(inputs_root=inputs_root, cache_path=cache_path)
    idx.ensure_loaded()
    _INDEX_CACHE[key] = idx
    return idx


def clear_index_cache() -> None:
    """Drop the process-local index cache.

    Used by tests that swap the workspace directory between calls.
    Production code should never need this — the cache is keyed by the
    resolved absolute path of ``inputs/`` so different runs never alias.
    """
    _INDEX_CACHE.clear()


def repo_fact(
    query: str,
    max_snippets: int = 3,
    *,
    workspace_dir: Path,
) -> list[dict[str, Any]]:
    """Return the top ``max_snippets`` TF-IDF snippets from the run's inputs.

    This is the low-level entry point. The :class:`ToolRegistry` wraps
    it so the LLM sees the standard ``{"ok", "status", "data", ...}``
    envelope while keeping this function easy to unit-test.
    """
    if not isinstance(query, str) or not query.strip():
        return []
    ws = Path(workspace_dir)
    idx = _get_index_for(ws)
    return idx.query(query, max_snippets=max_snippets)
