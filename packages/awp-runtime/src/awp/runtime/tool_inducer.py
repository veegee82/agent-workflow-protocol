"""AWP Tool Inducer — Auto-synthesise dynamic tools from repeated
``code.execute`` patterns.

Closes a structural gap in the delegation loop: managers/workers almost
never invoke ``tool.create`` voluntarily, yet they repeatedly ask
``code.execute`` to run the same *shape* of code with different literal
values (paths, URLs, filenames). That wastes both budget and the
``DynamicToolFactory`` machinery which was built exactly for this case.

The :class:`ToolInducer` watches every ``code.execute`` call in a run,
computes an AST-skeleton signature for it (literals and identifiers
normalised away), and once the same signature is observed from
``N_DISTINCT_WORKERS`` different worker ids (default 3) it synthesises
a generalised tool and registers it via
:class:`~awp.runtime.dynamic_tool_factory.DynamicToolFactory`.

Key properties
--------------

- **Pure addition.** Observes post-hoc; never rejects, rewrites, or
  delays ``code.execute`` calls. If synthesis fails the run continues
  exactly as before.
- **No new user config.** Always on whenever a
  :class:`DynamicToolFactory` is wired in. The N threshold is a
  hardcoded constant (:data:`N_DISTINCT_WORKERS`).
- **Diversity-aware counter.** Counts unique ``worker_id`` values per
  signature — three calls from the same worker do NOT trigger
  induction. This avoids promoting a single worker's loop body into a
  shared tool.
- **Deterministic naming.** ``dynamic.induced_<first6chars_of_hash>``
  so the same pattern across runs gets the same name (idempotent via
  the factory's content-addressable cache).
- **Honest failure.** If the varying literal slots cannot be cleanly
  extracted (e.g. the varying parts are nested expressions, not plain
  ``Constant`` nodes), we log an INFO line and skip synthesis rather
  than produce a broken tool.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Hardcoded by design — CLAUDE.md forbids new user-facing config flags.
N_DISTINCT_WORKERS: int = 3


# ---------------------------------------------------------------------------
# Signature computation
# ---------------------------------------------------------------------------


class CodePatternSignature:
    """Deterministic structural fingerprint of a Python source snippet.

    The signature is computed from the AST *skeleton* — node types,
    attribute names, argument counts — with:

    - every :class:`ast.Constant` replaced by the token ``<const>``
    - every :class:`ast.Name` renamed to ``<vK>`` where ``K`` is the
      first-occurrence index of that identifier in the source

    This yields the same hash for two snippets that differ only in
    literal values or cosmetic identifier choices, but different
    hashes when the control flow, call graph, or import set differs.

    Only the hex digest is exposed — the full skeleton string is kept
    internally for debugging.
    """

    __slots__ = ("_skeleton", "_hash", "_literal_slots")

    def __init__(self, skeleton: str, literal_slots: list[dict[str, Any]]) -> None:
        self._skeleton = skeleton
        self._hash = hashlib.sha256(skeleton.encode("utf-8")).hexdigest()[:16]
        self._literal_slots = literal_slots

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def skeleton(self) -> str:
        return self._skeleton

    @property
    def literal_slots(self) -> list[dict[str, Any]]:
        return list(self._literal_slots)

    def __repr__(self) -> str:  # pragma: no cover
        return f"CodePatternSignature(hash={self._hash!r})"

    @classmethod
    def from_code(cls, code: str) -> Optional["CodePatternSignature"]:
        """Compute the signature for *code*. Returns ``None`` if the
        source cannot be parsed."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return None
        skeleton, slots = _build_skeleton(tree)
        return cls(skeleton, slots)


def _build_skeleton(tree: ast.AST) -> tuple[str, list[dict[str, Any]]]:
    """Emit a canonical skeleton string plus the list of literal slots.

    The walk is deterministic: ``ast.walk`` yields nodes in BFS order,
    but we use a manual pre-order traversal so the string reflects the
    source structure closely. Identifiers are numbered by
    first-appearance so equivalent snippets produce equivalent strings
    regardless of variable-name choice.
    """
    name_to_idx: dict[str, int] = {}
    literal_slots: list[dict[str, Any]] = []
    parts: list[str] = []

    def _emit(node: ast.AST, depth: int = 0) -> None:
        node_type = type(node).__name__
        # Replace literal values with a sentinel but capture them so the
        # synthesiser can know which slots vary across occurrences.
        if isinstance(node, ast.Constant):
            literal_slots.append(
                {
                    "depth": depth,
                    "value": node.value,
                    "value_type": type(node.value).__name__,
                    # 1-based line so it matches typical editor display.
                    "lineno": getattr(node, "lineno", 0),
                }
            )
            parts.append(f"{node_type}(<const>)")
            return
        if isinstance(node, ast.Name):
            idx = name_to_idx.setdefault(node.id, len(name_to_idx))
            parts.append(f"{node_type}(<v{idx}>)")
            return

        # Emit the node header with structural attributes that matter
        # for the skeleton. We deliberately ignore source positions.
        header_bits: list[str] = [node_type]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            header_bits.append(f"args={len(node.args.args)}")
            header_bits.append(f"kwonly={len(node.args.kwonlyargs)}")
        elif isinstance(node, ast.arguments):
            header_bits.append(f"n_pos={len(node.args)}")
            header_bits.append(f"n_kw={len(node.kwonlyargs)}")
        elif isinstance(node, ast.Call):
            header_bits.append(f"nargs={len(node.args)}")
            header_bits.append(f"nkwargs={len(node.keywords)}")
        elif isinstance(node, ast.Attribute):
            header_bits.append(f"attr={node.attr}")
        elif isinstance(node, ast.ImportFrom):
            header_bits.append(f"module={node.module or ''}")
        elif isinstance(node, (ast.alias,)):
            header_bits.append(f"name={node.name}")
            if node.asname:
                header_bits.append(f"as={node.asname}")
        elif isinstance(node, ast.keyword):
            header_bits.append(f"key={node.arg or '**'}")
        elif isinstance(node, ast.BinOp):
            header_bits.append(f"op={type(node.op).__name__}")
        elif isinstance(node, ast.Compare):
            header_bits.append(
                "ops=" + ",".join(type(o).__name__ for o in node.ops)
            )
        elif isinstance(node, ast.BoolOp):
            header_bits.append(f"op={type(node.op).__name__}")
        elif isinstance(node, ast.UnaryOp):
            header_bits.append(f"op={type(node.op).__name__}")

        parts.append("(" + " ".join(header_bits))
        for child in ast.iter_child_nodes(node):
            _emit(child, depth + 1)
        parts.append(")")

    _emit(tree)
    return " ".join(parts), literal_slots


# ---------------------------------------------------------------------------
# Observation / synthesis state machine
# ---------------------------------------------------------------------------


@dataclass
class _PatternState:
    """Per-signature accumulator.

    ``occurrences`` stores (worker_id, code) for the first few hits so
    we can later derive a template from the earliest snippet and
    compare literal slots across occurrences when deciding whether the
    pattern is "synthesisable" (all slots are plain constants at the
    same AST location across all observations).
    """

    first_code: str
    occurrences: list[tuple[str, str]] = field(default_factory=list)
    worker_ids: set[str] = field(default_factory=set)
    synthesised: bool = False


class ToolInducer:
    """Watches ``code.execute`` calls and auto-creates tools at N hits.

    Parameters
    ----------
    dynamic_tool_factory
        The runtime :class:`DynamicToolFactory` used to register the
        synthesised tool. May be ``None`` (e.g. when the workflow does
        not allow tool creation) — observations are still accumulated,
        but no synthesis happens.
    creator_agent
        Tag used as the "creator" on synthesised tool records. Defaults
        to a fixed sentinel so the induction origin is traceable.
    """

    def __init__(
        self,
        dynamic_tool_factory: Any = None,
        *,
        creator_agent: str = "tool_inducer",
    ) -> None:
        self._factory = dynamic_tool_factory
        self._creator_agent = creator_agent
        self._patterns: dict[str, _PatternState] = {}
        # Tools successfully induced during this run. Keys are FQNs;
        # values are a small record dict so the runner can expose them
        # in ``run_completion.json``.
        self._induced: list[dict[str, Any]] = []

    # -- Public surface --------------------------------------------------

    @property
    def induced_tools(self) -> list[dict[str, Any]]:
        """Snapshot list of tools auto-created during this run."""
        return list(self._induced)

    def observe(self, worker_id: str, code: str) -> Optional[str]:
        """Register one ``code.execute`` call.

        Returns the FQN of the tool that was just synthesised (if the
        threshold was crossed *on this call*), else ``None``.
        """
        if not isinstance(code, str) or not code.strip():
            return None
        if not isinstance(worker_id, str) or not worker_id:
            worker_id = "<anon>"

        sig = CodePatternSignature.from_code(code)
        if sig is None:
            return None

        state = self._patterns.get(sig.hash)
        if state is None:
            state = _PatternState(first_code=code)
            self._patterns[sig.hash] = state

        state.occurrences.append((worker_id, code))
        state.worker_ids.add(worker_id)

        logger.debug(
            "tool_inducer: observed pattern %s (worker=%s, distinct=%d)",
            sig.hash,
            worker_id,
            len(state.worker_ids),
        )

        if state.synthesised:
            # Already induced — nothing further to do, but we keep
            # accumulating observations for observability.
            return None
        if len(state.worker_ids) < N_DISTINCT_WORKERS:
            return None

        # Threshold crossed — try to synthesise.
        fqn = self._synthesise(sig, state)
        if fqn is not None:
            state.synthesised = True
        return fqn

    # -- Internals -------------------------------------------------------

    def _synthesise(
        self, sig: CodePatternSignature, state: _PatternState
    ) -> Optional[str]:
        """Attempt to induce and register a tool from *state*.

        Returns the new FQN on success, ``None`` if the pattern is not
        cleanly synthesisable (which we log but don't raise).
        """
        fqn = f"dynamic.induced_{sig.hash[:6]}"
        worker_list = sorted(state.worker_ids)[:N_DISTINCT_WORKERS]

        # Derive the extractable literal slots by diffing the first
        # N occurrences' ASTs. A slot is "clean" iff every observation
        # has a Constant at the exact same tree position AND the values
        # actually vary (constants that are identical across all
        # occurrences stay inline — they're not parameters).
        params_info = _extract_literal_parameters(
            [c for (_, c) in state.occurrences[:N_DISTINCT_WORKERS]]
        )
        if params_info is None:
            logger.info(
                "tool_inducer: pattern %s seen %d times but not synthesisable",
                sig.hash,
                len(state.occurrences),
            )
            return None

        tool_code, parameters_schema, slot_positions = _build_induced_tool(
            state.first_code, params_info
        )
        if tool_code is None:
            logger.info(
                "tool_inducer: pattern %s seen %d times but not synthesisable",
                sig.hash,
                len(state.occurrences),
            )
            return None

        description = (
            f"Auto-induced from N={N_DISTINCT_WORKERS} repeated code.execute "
            f"patterns. Observed in workers: {worker_list}. "
            f"Parameters: {slot_positions}."
        )

        if self._factory is None:
            # Observability path: record the would-be induction so the
            # surrounding run_completion.json still sees the signal,
            # even when tool creation is disabled.
            logger.info(
                "tool_inducer: pattern %s crossed N=%d (workers=%s) but no "
                "DynamicToolFactory is wired — skipping registration",
                sig.hash,
                N_DISTINCT_WORKERS,
                worker_list,
            )
            return None

        try:
            result = self._factory.create_tool(
                name=fqn,
                description=description,
                parameters=parameters_schema,
                code=tool_code,
                creator_agent=self._creator_agent,
                allowed_namespace="dynamic",
                meta={
                    "induced": True,
                    "pattern_hash": sig.hash,
                    "observed_in_workers": worker_list,
                    "n_occurrences": len(state.occurrences),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tool_inducer: DynamicToolFactory.create_tool raised for %s: %s",
                fqn,
                exc,
            )
            return None

        if not isinstance(result, dict) or not result.get("ok"):
            err = (result or {}).get("error", "unknown")
            logger.info(
                "tool_inducer: factory rejected induced tool %s: %s",
                fqn,
                err,
            )
            return None

        logger.info(
            "tool_inducer: synthesised %s from pattern %s (workers=%s)",
            fqn,
            sig.hash,
            worker_list,
        )
        self._induced.append(
            {
                "fqn": fqn,
                "pattern_hash": sig.hash,
                "observed_in_workers": worker_list,
                "n_occurrences": len(state.occurrences),
            }
        )
        return fqn


# ---------------------------------------------------------------------------
# Template / parameter extraction
# ---------------------------------------------------------------------------


def _walk_constants_in_order(tree: ast.AST) -> list[ast.Constant]:
    """Return every Constant node in deterministic pre-order."""
    out: list[ast.Constant] = []

    def _visit(node: ast.AST) -> None:
        if isinstance(node, ast.Constant):
            out.append(node)
            return
        for child in ast.iter_child_nodes(node):
            _visit(child)

    _visit(tree)
    return out


def _extract_literal_parameters(
    snippets: list[str],
) -> Optional[list[dict[str, Any]]]:
    """Compare literal constants across *snippets* (same signature).

    Returns a list of slot descriptors for the literals that *vary*
    across occurrences, or ``None`` if the AST shapes diverge in a way
    that makes parameter extraction unsafe (which should not happen
    for snippets that share a signature, but we defend anyway).

    Each descriptor has ``{"index", "values", "value_type"}`` — the
    index into the Constant-walk of the first snippet, the observed
    distinct values, and the Python type name.
    """
    if len(snippets) < 2:
        return None
    try:
        trees = [ast.parse(s) for s in snippets]
    except SyntaxError:
        return None
    constant_lists = [_walk_constants_in_order(t) for t in trees]
    lengths = {len(cs) for cs in constant_lists}
    if len(lengths) != 1:
        # Shouldn't happen if signatures match, but bail out safely.
        return None
    n = lengths.pop()

    slots: list[dict[str, Any]] = []
    for i in range(n):
        values = [cs[i].value for cs in constant_lists]
        value_types = {type(v).__name__ for v in values}
        if len(value_types) != 1:
            # Type mismatch across occurrences — not safely parametrisable.
            return None
        if len(set(values)) == 1:
            # Constant across occurrences — not a parameter.
            continue
        # Only parametrise simple scalar values we can round-trip
        # through a JSON schema + kwarg call.
        if value_types.pop() not in {"str", "int", "float", "bool"}:
            return None
        slots.append(
            {
                "index": i,
                "values": values,
                "value_type": type(values[0]).__name__,
            }
        )
    return slots


def _build_induced_tool(
    template_code: str, slots: list[dict[str, Any]]
) -> tuple[Optional[str], dict[str, Any], list[str]]:
    """Synthesise the ``def handler(*, ...)`` body.

    Returns ``(code, json_schema, param_names)`` or ``(None, {}, [])``
    when the template is too complex to rewrite (e.g. contains a
    top-level import — we'd need to hoist it, and that changes
    semantics).
    """
    if not slots:
        # Nothing varies — no point in creating a parametrised tool.
        return None, {}, []

    try:
        tree = ast.parse(template_code)
    except SyntaxError:
        return None, {}, []

    # Reject templates whose sandboxed execution would require
    # top-level imports. A pure code.execute body should contain plain
    # statements; imports typically belong at the tool wrapper level
    # and would be blocked by the dynamic-tool import policy anyway.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return None, {}, []
        # Reject templates that define their own ``handler`` — we are
        # about to wrap one around them.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "handler":
                return None, {}, []

    # Walk constants in the same deterministic order we used for the
    # slot-index computation, and replace each varying slot with an
    # ``ast.Name`` that references the synthesised kwarg.
    constants = _walk_constants_in_order(tree)
    param_names: list[str] = []
    type_map = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
    }
    properties: dict[str, Any] = {}
    required: list[str] = []
    slot_by_index = {s["index"]: s for s in slots}

    class _Rewriter(ast.NodeTransformer):
        def __init__(self) -> None:
            self._i = 0

        def visit_Constant(self, node: ast.Constant) -> Any:  # noqa: N802
            idx = self._i
            self._i += 1
            slot = slot_by_index.get(idx)
            if slot is None:
                return node
            pname = f"p{len(param_names)}"
            param_names.append(pname)
            properties[pname] = {
                "type": type_map[slot["value_type"]],
                "description": (
                    f"Parameter induced from varying constant "
                    f"(observed values: {slot['values']!r})"
                ),
            }
            required.append(pname)
            new = ast.Name(id=pname, ctx=ast.Load())
            return ast.copy_location(new, node)

    rewritten = _Rewriter().visit(tree)
    ast.fix_missing_locations(rewritten)

    try:
        body_src = ast.unparse(rewritten)
    except Exception:  # pragma: no cover — ast.unparse is stdlib since 3.9
        return None, {}, []

    # Indent each line by 4 spaces for the handler body.
    indented = "\n".join("    " + line if line else "" for line in body_src.splitlines())
    if not param_names:
        return None, {}, []
    sig = ", ".join(param_names)
    handler_src = (
        f"def handler(*, {sig}):\n"
        f"{indented}\n"
        f"    return {{'ok': True, 'status': 200, "
        f"'data': {{'induced': True, 'params': {{'{param_names[0]}': "
        f"{param_names[0]}"
        + (
            ", "
            + ", ".join(f"'{p}': {p}" for p in param_names[1:])
            if len(param_names) > 1
            else ""
        )
        + "}}, 'error': None, 'log': ''}\n"
    )

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    return handler_src, schema, param_names


__all__ = [
    "CodePatternSignature",
    "ToolInducer",
    "N_DISTINCT_WORKERS",
]
