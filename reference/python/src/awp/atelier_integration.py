"""AtelierOS integration helpers.

AtelierOS (https://github.com/veegee82/AtelierOS) wraps a single LLM-CLI
agent (Claude Code, Codex CLI, Gemini CLI, ...) into a multi-channel,
multi-persona service with audit-evident hash-chain logging. When
AtelierOS dispatches a complex task to AWP via ``AWPAgent.run(task,
state)``, it injects two optional auto-fields into the state dict so
AWP-workers can route their LLM calls through the AtelierOS Engine
layer instead of bypassing it:

  * ``state["worker_engine_factory"]`` — a callable
        ``factory(engine_id: str | None = None) -> WorkerEngine | None``
    The worker calls the factory to obtain a configured engine instance
    (Claude Code, Codex CLI, ...) for its LLM step. Calling without an
    arg returns the chat's default engine; passing a specific id
    overrides per worker step (Phase-4 multi-engine workflows).

  * ``state["meta"]["engine_id"]`` — the resolved default engine id for
    audit attribution. AtelierOS uses this to verify the integrity rule
    "every audit event with engine_id has an enclosing awp_task_id".

Both fields are **optional**. Workers that do not honour the convention
keep working — they just bypass the AtelierOS Engine layer and run
whatever LLM their internals reach for. This module exists to make the
honoured path easy to write: import the helpers, the boilerplate is
done.

This module has zero hard dependencies on AtelierOS — it works against
any caller that follows the same convention.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# The reserved state-key carrying the engine factory. Spec layer-04
# section 2.2 names this as a reserved key (workers MUST NOT write to
# it; the orchestrator owns it).
WORKER_ENGINE_FACTORY_KEY: str = "worker_engine_factory"

# The conventional location for the engine_id label in state.meta.
META_ENGINE_ID_PATH: tuple = ("meta", "engine_id")


def extract_engine_factory(state: Dict[str, Any]) -> Optional[Callable[..., Any]]:
    """Return the worker_engine_factory callable from state, or None.

    Safe to call on any state dict — missing key, wrong type, or
    non-callable value all return None gracefully. Workers can therefore
    write::

        factory = extract_engine_factory(state)
        if factory is None:
            # No AtelierOS context — fall back to internal LLM client.
            engine = None
        else:
            engine = factory("claude_code")  # or factory() for default
        # ... use engine to make the LLM call ...
    """
    if not isinstance(state, dict):
        return None
    value = state.get(WORKER_ENGINE_FACTORY_KEY)
    if value is None or not callable(value):
        return None
    return value


def extract_engine_id(state: Dict[str, Any],
                      default: Optional[str] = None) -> Optional[str]:
    """Return state["meta"]["engine_id"] or default.

    Useful for workers that want to log/audit which engine they ended up
    using without forcing the factory call.
    """
    if not isinstance(state, dict):
        return default
    meta = state.get("meta")
    if not isinstance(meta, dict):
        return default
    eid = meta.get("engine_id")
    if isinstance(eid, str) and eid:
        return eid
    return default


def resolve_engine(state: Dict[str, Any],
                   engine_id: Optional[str] = None) -> Optional[Any]:
    """Convenience: pull the factory from state and call it once.

    Returns the WorkerEngine instance for ``engine_id`` (or the chat's
    default if engine_id is None), or None if either:

      * the factory is missing from state (caller has no AtelierOS
        context), OR
      * the factory exists but returns None for the requested engine
        (engine binary not installed on this host, etc.).

    Workers that want a specific engine for *this step* (e.g. a code-
    generation step that prefers ``claude_code`` even when the chat
    defaults to ``codex_cli``) should pass an explicit engine_id.
    """
    factory = extract_engine_factory(state)
    if factory is None:
        return None
    try:
        return factory(engine_id) if engine_id else factory()
    except Exception:
        # Factory contract is "fail graceful, return None on missing".
        # Wrap defensively in case a malformed factory raises.
        return None


def has_atelier_context(state: Dict[str, Any]) -> bool:
    """True iff this state was injected by an AtelierOS-style caller.

    Useful for branching code that should behave differently when AWP
    runs standalone vs. inside AtelierOS — e.g. emitting AtelierOS-
    audit-compatible events only when the context is present.
    """
    return extract_engine_factory(state) is not None


__all__ = [
    "WORKER_ENGINE_FACTORY_KEY",
    "META_ENGINE_ID_PATH",
    "extract_engine_factory",
    "extract_engine_id",
    "resolve_engine",
    "has_atelier_context",
]
