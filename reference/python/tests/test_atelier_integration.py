"""Tests for awp.atelier_integration helpers.

These cover the convention-side guarantees AWP-workers rely on when
running inside AtelierOS:

  * extract_engine_factory: returns the callable, None on missing /
    wrong type / non-callable
  * extract_engine_id: reads state["meta"]["engine_id"], falls back
  * resolve_engine: factory + call composed; returns None gracefully
    when factory missing OR factory raises
  * has_atelier_context: True iff factory is present and callable

Pure-Python, no AWP-runtime dependency, sub-millisecond per case.

Run: python -m unittest reference.python.tests.test_atelier_integration
"""
from __future__ import annotations

import unittest

from awp.atelier_integration import (
    WORKER_ENGINE_FACTORY_KEY,
    extract_engine_factory,
    extract_engine_id,
    has_atelier_context,
    resolve_engine,
)


class _StubEngine:
    """Stand-in for a WorkerEngine — just enough to be identifiable."""

    def __init__(self, engine_id: str):
        self.engine_id = engine_id


def _factory(engine_id: str | None = None) -> _StubEngine | None:
    """Stand-in worker_engine_factory."""
    if engine_id is None:
        engine_id = "claude_code"  # the convention's default
    if engine_id in ("claude_code", "codex_cli"):
        return _StubEngine(engine_id)
    return None


def _raising_factory(engine_id: str | None = None):
    raise RuntimeError("malformed factory")


class ExtractEngineFactoryTests(unittest.TestCase):
    def test_returns_callable_when_present(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _factory}
        out = extract_engine_factory(state)
        self.assertIs(out, _factory)

    def test_missing_key_returns_none(self):
        self.assertIsNone(extract_engine_factory({}))

    def test_non_dict_state_returns_none(self):
        self.assertIsNone(extract_engine_factory(None))  # type: ignore[arg-type]
        self.assertIsNone(extract_engine_factory("not a dict"))  # type: ignore[arg-type]
        self.assertIsNone(extract_engine_factory([]))  # type: ignore[arg-type]

    def test_non_callable_value_returns_none(self):
        self.assertIsNone(extract_engine_factory({WORKER_ENGINE_FACTORY_KEY: "string"}))
        self.assertIsNone(extract_engine_factory({WORKER_ENGINE_FACTORY_KEY: 42}))
        self.assertIsNone(extract_engine_factory({WORKER_ENGINE_FACTORY_KEY: None}))

    def test_reserved_key_constant_value(self):
        # Spec layer-04 names this exact key. Changing it is a breaking
        # convention change.
        self.assertEqual(WORKER_ENGINE_FACTORY_KEY, "worker_engine_factory")


class ExtractEngineIdTests(unittest.TestCase):
    def test_returns_meta_engine_id(self):
        state = {"meta": {"engine_id": "claude_code"}}
        self.assertEqual(extract_engine_id(state), "claude_code")

    def test_missing_meta_returns_default(self):
        self.assertIsNone(extract_engine_id({}))
        self.assertEqual(extract_engine_id({}, "fallback"), "fallback")

    def test_meta_not_a_dict(self):
        self.assertIsNone(extract_engine_id({"meta": "not a dict"}))
        self.assertEqual(
            extract_engine_id({"meta": [1, 2, 3]}, "fallback"),
            "fallback",
        )

    def test_engine_id_not_a_string(self):
        self.assertIsNone(extract_engine_id({"meta": {"engine_id": 42}}))
        self.assertIsNone(extract_engine_id({"meta": {"engine_id": ""}}))

    def test_non_dict_state(self):
        self.assertIsNone(extract_engine_id(None))  # type: ignore[arg-type]
        self.assertEqual(
            extract_engine_id("not a dict", "fallback"),  # type: ignore[arg-type]
            "fallback",
        )


class ResolveEngineTests(unittest.TestCase):
    def test_resolves_default_engine(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _factory}
        engine = resolve_engine(state)
        self.assertIsNotNone(engine)
        self.assertEqual(engine.engine_id, "claude_code")

    def test_resolves_specific_engine(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _factory}
        engine = resolve_engine(state, "codex_cli")
        self.assertIsNotNone(engine)
        self.assertEqual(engine.engine_id, "codex_cli")

    def test_unknown_engine_id_returns_none(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _factory}
        self.assertIsNone(resolve_engine(state, "nonexistent"))

    def test_no_factory_returns_none(self):
        self.assertIsNone(resolve_engine({}))
        self.assertIsNone(resolve_engine({}, "claude_code"))

    def test_raising_factory_returns_none_graceful(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _raising_factory}
        self.assertIsNone(resolve_engine(state))
        self.assertIsNone(resolve_engine(state, "claude_code"))

    def test_non_dict_state(self):
        self.assertIsNone(resolve_engine(None))  # type: ignore[arg-type]


class HasAtelierContextTests(unittest.TestCase):
    def test_true_when_factory_present(self):
        state = {WORKER_ENGINE_FACTORY_KEY: _factory}
        self.assertTrue(has_atelier_context(state))

    def test_false_when_missing(self):
        self.assertFalse(has_atelier_context({}))

    def test_false_when_non_callable(self):
        self.assertFalse(has_atelier_context({WORKER_ENGINE_FACTORY_KEY: "x"}))

    def test_false_when_state_is_not_a_dict(self):
        self.assertFalse(has_atelier_context(None))  # type: ignore[arg-type]
        self.assertFalse(has_atelier_context([]))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
