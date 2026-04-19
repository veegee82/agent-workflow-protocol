"""Completion gates — deterministic checks that must pass before a
delegation-loop run can be marked ``complete``.

Each gate is a pure function that takes the run's deliverable paths and a
small context dict, and returns a rejection record (``dict``) or ``None``
when the gate passes. Rejections carry enough per-deliverable diagnostic
for the manager's repair loop to target the exact file + reason.

This module only hosts the NEW gates introduced in the deliverable-
correctness initiative (Phase A of the plan). The legacy gates
(``critique``, ``placeholder``, ``file``, ``deliverable``,
``structural_integrity``, ``eval``) still live inside
``delegation_loop_runner.py`` for historical reasons — they are invoked
alongside the ones here by ``_run_completion_gates``.

Design contract for every gate:

- Input: ``paths: list[Path]`` of derived required deliverables + a
  ``ctx: dict`` with optional hints (``task_text``, ``plan``,
  ``workflow_dir`` etc.).
- Output: ``None`` if the gate passes, or a rejection dict with fields:

    {
      "gate":     "<gate_name>",
      "reason":   "<short human summary>",
      "findings": [
         {"file": "<relpath>", "detail": "...", "line": <int|None>,
          "rule": "<machine_tag>"},
         ...
      ],
    }

A gate MUST NOT raise on malformed input — return a rejection or None.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _read_text_safe(p: Path, limit: int = 1_000_000) -> str | None:
    """Read *p* as UTF-8 text, returning None on any IO error."""
    try:
        data = p.read_bytes()
    except OSError:
        return None
    try:
        return data[:limit].decode("utf-8", errors="replace")
    except Exception:
        return None


def _rel(path: Path, base: Path | None) -> str:
    if base is None:
        return str(path)
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


# ---------------------------------------------------------------------------
# A1 — syntax_compile gate
# ---------------------------------------------------------------------------


def _check_python(p: Path, text: str) -> tuple[bool, str]:
    try:
        ast.parse(text, filename=str(p))
        return True, ""
    except SyntaxError as exc:
        line = exc.lineno or 0
        return False, f"SyntaxError line {line}: {exc.msg}"


def _check_json(_p: Path, text: str) -> tuple[bool, str]:
    try:
        json.loads(text)
        return True, ""
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON at line {exc.lineno}: {exc.msg}"


def _check_yaml(_p: Path, text: str) -> tuple[bool, str]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return True, ""  # yaml not available — skip (non-blocking)
    try:
        yaml.safe_load(text)
        return True, ""
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        return False, f"Invalid YAML: {exc}"


def _check_markdown(_p: Path, text: str) -> tuple[bool, str]:
    # Markdown has no strict parse contract — only the most egregious
    # defects are caught here: truncated code fence, empty file.
    if not text.strip():
        return False, "Empty markdown file"
    # Count triple-backtick fences; odd count == unterminated fence
    fences = text.count("\n```")
    if fences > 0 and fences % 2 != 0:
        return False, "Unterminated code fence (odd number of ``` markers)"
    return True, ""


def _check_csv(_p: Path, text: str) -> tuple[bool, str]:
    import csv
    from io import StringIO
    try:
        reader = csv.reader(StringIO(text))
        rows = list(reader)
    except csv.Error as exc:
        return False, f"Malformed CSV: {exc}"
    if len(rows) < 1:
        return False, "Empty CSV"
    header_len = len(rows[0])
    for i, row in enumerate(rows[1:], start=2):
        if len(row) != header_len and len(row) > 0:
            return False, (
                f"CSV row {i} has {len(row)} columns, header has {header_len}"
            )
    return True, ""


_SYNTAX_HANDLERS: dict[str, Callable[[Path, str], tuple[bool, str]]] = {
    ".py": _check_python,
    ".json": _check_json,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
    ".md": _check_markdown,
    ".markdown": _check_markdown,
    ".csv": _check_csv,
}


def syntax_compile_gate(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Reject completion when any deliverable has a syntax / parse error.

    Dispatches per extension. Unknown extensions are skipped silently.
    """
    base = ctx.get("workflow_dir")
    findings: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue  # presence gate handles missing files
        handler = _SYNTAX_HANDLERS.get(p.suffix.lower())
        if handler is None:
            continue
        text = _read_text_safe(p)
        if text is None:
            continue
        ok, detail = handler(p, text)
        if not ok:
            findings.append({
                "file": _rel(p, base),
                "detail": detail,
                "rule": f"syntax_{p.suffix.lstrip('.')}",
            })
    if not findings:
        return None
    return {
        "gate": "syntax_compile",
        "reason": f"{len(findings)} deliverable(s) failed syntax/parse check",
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# A2 — schema gate
# ---------------------------------------------------------------------------


def _load_schema_declarations(ctx: dict[str, Any]) -> dict[str, Any]:
    """Extract schema declarations from the task plan.

    Convention: a subtask may declare ``{"required_outputs": ["foo.json"],
    "schemas": {"foo.json": {"type": "object", "required": ["name"]}}}``.
    """
    schemas: dict[str, Any] = {}
    plan = ctx.get("plan")
    if plan is None:
        return schemas
    subtasks = getattr(plan, "_subtasks", None) or []
    for st in subtasks:
        sch = st.get("schemas") if isinstance(st, dict) else None
        if isinstance(sch, dict):
            for rel, schema_def in sch.items():
                schemas[rel] = schema_def
    return schemas


def schema_gate(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Reject completion when a JSON/YAML deliverable fails its declared
    JSON Schema. Requires ``jsonschema`` package; silently skips if not
    installed. The schema is looked up from the plan's ``schemas`` dict.
    """
    schemas = _load_schema_declarations(ctx)
    if not schemas:
        return None
    try:
        import jsonschema  # type: ignore
    except ImportError:
        logger.debug("schema_gate: jsonschema not installed — skipping")
        return None

    base = ctx.get("workflow_dir")
    findings: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        # Match by basename or relative path suffix
        rel_name = p.name
        schema = schemas.get(rel_name)
        if schema is None:
            # Try relative to workflow_dir
            rel_str = _rel(p, base)
            schema = schemas.get(rel_str)
        if schema is None:
            continue
        text = _read_text_safe(p)
        if text is None:
            continue
        try:
            if p.suffix.lower() in (".yaml", ".yml"):
                import yaml  # type: ignore
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)
        except Exception as exc:
            findings.append({
                "file": _rel(p, base),
                "detail": f"Cannot parse for schema check: {exc}",
                "rule": "schema_parse",
            })
            continue
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
            path_str = ".".join(str(part) for part in exc.absolute_path)
            findings.append({
                "file": _rel(p, base),
                "detail": f"at {path_str or '<root>'}: {exc.message}",
                "rule": "schema_violation",
            })
    if not findings:
        return None
    return {
        "gate": "schema",
        "reason": f"{len(findings)} deliverable(s) violated declared schema",
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# A3 — success_criteria gate
# ---------------------------------------------------------------------------


_CHECKBOX_RE = re.compile(
    r"^\s*[-*]\s*\[\s*[ xX]\s*\]\s*(.+?)\s*$", re.MULTILINE
)
# Lines starting with "- " under a heading like "Erfolgskriterien" / "Success criteria"
_CRITERIA_HEADING_RE = re.compile(
    r"^##+\s*(Erfolgskriterien|Success\s+criteria|Acceptance\s+criteria)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_success_criteria(task_text: str) -> list[str]:
    """Return user-declared success-criteria items from a task description.

    Priority 1: markdown checkboxes (``- [ ]`` or ``- [x]``) anywhere.
    Priority 2: plain ``-`` bullets under a heading named
    ``Erfolgskriterien`` / ``Success criteria`` / ``Acceptance criteria``.
    """
    items = [
        m.group(1).strip()
        for m in _CHECKBOX_RE.finditer(task_text)
        if m.group(1).strip()
    ]
    if items:
        return items
    # Fallback: find heading, collect bullets until next heading
    headings = list(_CRITERIA_HEADING_RE.finditer(task_text))
    if not headings:
        return []
    start = headings[0].end()
    tail = task_text[start:]
    # Stop at next heading
    nxt = re.search(r"\n##+\s", tail)
    block = tail[: nxt.start()] if nxt else tail
    bullets = re.findall(r"^\s*[-*]\s+(.+)$", block, re.MULTILINE)
    return [b.strip() for b in bullets if b.strip()]


def success_criteria_gate(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """For each user-declared success criterion, verify it either:

    1. references a deliverable file that exists (path-token present); OR
    2. is answered by a deterministic regex (file content contains the
       keyword / number / pattern asserted in the criterion); OR
    3. must be verified by an LLM judge if available
       (``ctx['judge_fn']`` callable, optional).

    This gate is designed to be **lenient by default**: it only hard-rejects
    criteria that reference a concrete file path that doesn't exist or is
    empty. Everything else is surfaced as an ADVISORY finding which gets
    routed to the manager as context but does not block completion unless
    a stricter mode is requested via ``ctx['strict_criteria'] = True``.
    """
    task_text = ctx.get("task_text", "") or ""
    if not task_text:
        return None
    criteria = _extract_success_criteria(task_text)
    if not criteria:
        return None

    base = ctx.get("workflow_dir")
    strict = bool(ctx.get("strict_criteria", False))
    # Pre-build a cheap lookup of deliverable names for path-token matching
    deliverable_names = {p.name for p in paths if p.exists()}
    deliverable_texts: dict[str, str] = {}
    for p in paths:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            txt = _read_text_safe(p, limit=200_000)
            if txt:
                deliverable_texts[p.name] = txt

    findings: list[dict[str, Any]] = []
    for crit in criteria:
        # Rule 1: if criterion names a specific file, it must exist & be non-empty
        path_matches = re.findall(
            r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6}", crit
        )
        missing = [
            m for m in path_matches
            if m.split("/")[-1] not in deliverable_names
            and Path(m).name not in deliverable_names
        ]
        if missing and len(missing) == len(path_matches) and path_matches:
            findings.append({
                "file": ", ".join(missing[:3]),
                "detail": (
                    f"criterion references file(s) not present: "
                    f"{missing[:3]}. Criterion: \"{crit[:120]}\""
                ),
                "rule": "criterion_missing_file",
            })
            continue

        # Rule 2: look for any quoted string inside criterion — it must appear
        # in at least one deliverable. e.g. criterion says the PDF must
        # mention "arxiv_two_column" — check deliverables.
        quoted = re.findall(r"[\"'`]([^\"'`\n]{3,80})[\"'`]", crit)
        for q in quoted:
            if not any(q in txt for txt in deliverable_texts.values()):
                findings.append({
                    "file": "(any deliverable)",
                    "detail": (
                        f"criterion requires literal \"{q[:60]}\" in "
                        f"deliverables but none contain it"
                    ),
                    "rule": "criterion_missing_literal",
                })
                break  # one finding per criterion

    if not findings:
        return None
    if not strict:
        # Downgrade to advisory: log and don't block
        logger.info(
            "success_criteria_gate: %d advisory finding(s) — non-blocking "
            "(set strict_criteria=True to enforce)", len(findings),
        )
        return None
    return {
        "gate": "success_criteria",
        "reason": f"{len(findings)} success-criterion check(s) failed",
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# A4 — cross_reference gate
# ---------------------------------------------------------------------------


_NUMERIC_CITE_RE = re.compile(r"\[(\d+)\]")
_REF_LIST_HEADING_RE = re.compile(
    r"^##+\s*(References|Referenzen|Literatur|Bibliography)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REF_ITEM_RE = re.compile(r"^\s*\[(\d+)\]", re.MULTILINE)
_FIG_REF_RE = re.compile(r"\b[Ff]ig(?:ure|\.)\s*(\d+)")
_FIG_CAPTION_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")  # markdown image


def cross_reference_gate(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Per markdown/tex deliverable: check citation numbers reference
    existing entries in a References/Literatur section, and figure
    references point to images that exist.

    This extends the legacy structural_integrity gate by actually
    matching citation numbers to their targets instead of only adjacency
    heuristics.
    """
    base = ctx.get("workflow_dir")
    findings: list[dict[str, Any]] = []

    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".markdown", ".tex", ".txt"):
            continue
        text = _read_text_safe(p, limit=500_000)
        if not text:
            continue

        # 1. Citation numbers
        cites = {int(m.group(1)) for m in _NUMERIC_CITE_RE.finditer(text)}
        if cites:
            # Find References section
            heading = _REF_LIST_HEADING_RE.search(text)
            if heading:
                ref_block = text[heading.end():]
                # stop at next "## " heading
                nxt = re.search(r"\n##+\s", ref_block)
                if nxt:
                    ref_block = ref_block[:nxt.start()]
                defined = {
                    int(m.group(1))
                    for m in _REF_ITEM_RE.finditer(ref_block)
                }
            else:
                defined = set()
            missing = cites - defined
            if missing:
                findings.append({
                    "file": _rel(p, base),
                    "detail": (
                        f"cites [{', '.join(str(n) for n in sorted(missing))}] "
                        f"but References section does not define them"
                    ),
                    "rule": "citation_undefined",
                })

        # 2. Figure references vs image embeds
        fig_refs = {int(m.group(1)) for m in _FIG_REF_RE.finditer(text)}
        if fig_refs:
            image_count = len(_FIG_CAPTION_RE.findall(text))
            max_fig = max(fig_refs) if fig_refs else 0
            if max_fig > image_count:
                findings.append({
                    "file": _rel(p, base),
                    "detail": (
                        f"references Fig. up to {max_fig} but file embeds "
                        f"only {image_count} image(s)"
                    ),
                    "rule": "figure_missing",
                })

    if not findings:
        return None
    return {
        "gate": "cross_reference",
        "reason": f"{len(findings)} cross-reference defect(s)",
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# A5 — smoke_test gate
# ---------------------------------------------------------------------------


def smoke_test_gate(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Runs any ``.py`` / ``.sh`` deliverable marked as executable by the
    plan, for a short time, and reports non-zero exit codes as rejections.

    A subtask can mark a deliverable as executable via
    ``{"smoke_test": ["script.py"]}`` or ``{"executable": ["script.py"]}``.
    Without explicit marking, this gate is a no-op — we do NOT auto-run
    arbitrary scripts for security reasons.

    The subprocess runs with ``timeout=10`` and no network access is
    enforced beyond the normal process inheritance; the gate assumes the
    generated code is already subject to the code-executor sandbox when
    relevant.
    """
    plan = ctx.get("plan")
    if plan is None:
        return None
    subtasks = getattr(plan, "_subtasks", None) or []

    to_run: list[Path] = []
    names_wanted: set[str] = set()
    for st in subtasks:
        for key in ("smoke_test", "executable"):
            lst = st.get(key) if isinstance(st, dict) else None
            if isinstance(lst, list):
                names_wanted.update(str(x) for x in lst)
    if not names_wanted:
        return None

    by_name = {p.name: p for p in paths if p.exists() and p.is_file()}
    for wanted in names_wanted:
        p = by_name.get(wanted) or by_name.get(Path(wanted).name)
        if p:
            to_run.append(p)
    if not to_run:
        return None

    base = ctx.get("workflow_dir")
    findings: list[dict[str, Any]] = []
    for p in to_run:
        cmd: list[str]
        if p.suffix == ".py":
            import sys
            cmd = [sys.executable, str(p)]
        elif p.suffix == ".sh":
            cmd = ["bash", str(p)]
        else:
            continue
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
                cwd=str(p.parent),
            )
        except subprocess.TimeoutExpired:
            findings.append({
                "file": _rel(p, base),
                "detail": "smoke test timed out after 10s",
                "rule": "smoke_timeout",
            })
            continue
        except Exception as exc:
            findings.append({
                "file": _rel(p, base),
                "detail": f"smoke test could not launch: {exc}",
                "rule": "smoke_launch_error",
            })
            continue
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
            # Trim to last 400 chars (where Python prints traceback)
            tail = stderr[-400:].strip()
            findings.append({
                "file": _rel(p, base),
                "detail": (
                    f"exit={proc.returncode}; stderr tail: {tail}"
                ),
                "rule": "smoke_nonzero_exit",
            })
    if not findings:
        return None
    return {
        "gate": "smoke_test",
        "reason": f"{len(findings)} executable deliverable(s) failed smoke test",
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


# Ordered cheap → expensive. LLM-based gates (critique, eval) stay in the
# legacy code path and run AFTER this pipeline.
NEW_GATE_PIPELINE: list[tuple[str, Callable[[list[Path], dict[str, Any]], dict[str, Any] | None]]] = [
    ("syntax_compile", syntax_compile_gate),
    ("schema", schema_gate),
    ("cross_reference", cross_reference_gate),
    ("success_criteria", success_criteria_gate),
    ("smoke_test", smoke_test_gate),
]

# Canonical first-failure-wins order for rejection reporting. Identical to
# the sequential pipeline order so telemetry and gate-repair loops observe
# the same reason regardless of the ``parallel_gate_chain`` toggle.
CANONICAL_GATE_ORDER: list[str] = [name for name, _ in NEW_GATE_PIPELINE]

# Parallel groups for the Phase-A gates.
#
# Dependency analysis (all gates take ``(paths, ctx)`` and return a verdict
# or None; none mutate ``ctx``; none read a prior gate's result):
#
#   * ``syntax_compile``   — reads ``paths`` + ``ctx['workflow_dir']``.
#   * ``schema``           — reads ``paths`` + ``ctx['plan']._subtasks``.
#   * ``cross_reference``  — reads ``paths`` only.
#   * ``success_criteria`` — reads ``paths`` + ``ctx['task_text']``.
#   * ``smoke_test``       — reads ``paths`` + ``ctx['plan']._subtasks`` AND
#                            executes subprocesses; must only run after the
#                            file-parse gates have had a chance to reject
#                            syntactically broken code, so non-parseable
#                            scripts never reach execution.
#
# Group 0 holds the four pure, file-local gates; Group 1 holds smoke_test.
# Within a group all gates share the same immutable ``ctx`` snapshot and
# never write to it, so parallel execution is race-free.
GATE_GROUPS: list[list[str]] = [
    ["syntax_compile", "schema", "cross_reference", "success_criteria"],
    ["smoke_test"],
]


def _gate_fn(name: str) -> Callable[[list[Path], dict[str, Any]], dict[str, Any] | None]:
    for gate_name, fn in NEW_GATE_PIPELINE:
        if gate_name == name:
            return fn
    raise KeyError(f"Unknown gate: {name}")


def _safe_run_gate(
    name: str, paths: list[Path], ctx: dict[str, Any]
) -> tuple[str, dict[str, Any] | None, BaseException | None]:
    """Invoke a single gate and capture any exception. Exceptions are
    treated as ``pass`` at the call-site — matching the sequential
    pipeline's fail-open behaviour for raising gates.
    """
    try:
        rej = _gate_fn(name)(paths, ctx)
    except BaseException as exc:  # noqa: BLE001 — re-raise is caller's choice
        return name, None, exc
    if rej is not None:
        rej.setdefault("gate", name)
    return name, rej, None


def run_new_completion_gates(
    paths: list[Path], ctx: dict[str, Any]
) -> dict[str, Any] | None:
    """Run the new Phase-A gates in pipeline order. Returns the first
    rejection or None if all pass.
    """
    for name, fn in NEW_GATE_PIPELINE:
        try:
            rej = fn(paths, ctx)
        except Exception:
            logger.warning("%s gate raised — treating as pass", name, exc_info=True)
            continue
        if rej is not None:
            rej.setdefault("gate", name)
            return rej
    return None


def run_new_completion_gates_parallel(
    paths: list[Path],
    ctx: dict[str, Any],
    *,
    per_gate_sink: Callable[[str, dict[str, Any] | None, BaseException | None], None] | None = None,
) -> dict[str, Any] | None:
    """Parallel variant of :func:`run_new_completion_gates`.

    Execution model:
      * Each :data:`GATE_GROUPS` entry runs concurrently on a bounded
        ``ThreadPoolExecutor``.
      * Groups are processed in order: a later group only starts when the
        previous group has fully joined AND has no rejections in canonical
        order.
      * First-failure-wins reporting uses :data:`CANONICAL_GATE_ORDER` so
        rejection reasons are independent of completion order.

    Side-effect contract:
      * Gates in :mod:`completion_gates` are pure wrt ``ctx``; the ctx
        object is the same reference for every gate but nothing in this
        module writes to it. This keeps the parallel group race-free even
        though the snapshot is not defensively copied.
      * ``smoke_test`` runs subprocesses which write to the filesystem;
        keeping it in its own group avoids accidental parallel launches
        under a future edit.

    ``per_gate_sink`` is an optional callback invoked after each gate
    returns (``(name, rejection_or_none, exception_or_none)``). The caller
    uses it to persist gate records — the callback always fires in the
    order gates *finish*, not canonical order, because persistence should
    reflect real timing.
    """
    # Pool size: cap at max-group-size, never exceed 8. Groups with a
    # single gate fall through to an inline call (no pool overhead).
    max_group = max(len(g) for g in GATE_GROUPS) if GATE_GROUPS else 1
    pool_size = max(1, min(max_group, 8))

    with ThreadPoolExecutor(
        max_workers=pool_size, thread_name_prefix="awp-gate-chain"
    ) as pool:
        for group in GATE_GROUPS:
            if not group:
                continue
            verdicts: dict[str, dict[str, Any] | None] = {}
            exceptions: dict[str, BaseException] = {}

            if len(group) == 1:
                name, rej, exc = _safe_run_gate(group[0], paths, ctx)
                if exc is not None:
                    logger.warning(
                        "%s gate raised — treating as pass", name, exc_info=exc
                    )
                    exceptions[name] = exc
                    verdicts[name] = None
                else:
                    verdicts[name] = rej
                if per_gate_sink is not None:
                    per_gate_sink(name, verdicts[name], exceptions.get(name))
            else:
                # map() would preserve submission order but we want the
                # sink to reflect true finish order, so iterate as_completed
                # via manual future tracking.
                futures = {
                    pool.submit(_safe_run_gate, name, paths, ctx): name
                    for name in group
                }
                from concurrent.futures import as_completed

                for fut in as_completed(futures):
                    name, rej, exc = fut.result()
                    if exc is not None:
                        logger.warning(
                            "%s gate raised — treating as pass",
                            name,
                            exc_info=exc,
                        )
                        exceptions[name] = exc
                    verdicts[name] = rej
                    if per_gate_sink is not None:
                        per_gate_sink(name, rej, exc)

            # First-failure-wins in canonical order.
            for canonical in CANONICAL_GATE_ORDER:
                if canonical in verdicts and verdicts[canonical] is not None:
                    return verdicts[canonical]
            # Group clean — advance to next group.

    return None
