"""Pre-promotion venv smoke-test gate (B3).

Before a generated dynamic tool is registered, run a *smoke test* in an
isolated venv. The contract is:

  - The smoke test only needs to prove that the handler **runs without
    raising an exception** for at least one valid input set. This is the
    Option (c) policy: ad-hoc generated tools get a smoke test, while
    pattern-instantiated tools carry their own pre-verified test snippet
    from ``awp.patterns``.

  - One automatic repair retry is permitted by the caller; the gate
    itself is single-shot. After two failures the caller must escalate
    (re-plan, switch capability), not loop indefinitely.

The gate uses ``VenvExecutor`` so the test runs in real Python with the
declared packages installed. We never trust the live process to validate
generated code.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def smoke_test_tool(
    code: str,
    *,
    smoke_snippet: str,
    packages: Optional[list[str]] = None,
    working_dir: Optional[Path] = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Run handler ``code`` followed by ``smoke_snippet`` in a venv.

    Args:
        code: Python source defining ``handler(...)``.
        smoke_snippet: Python source that exercises ``handler`` and asserts
            on the result. For pattern-instantiated tools this is the
            ``pattern.smoke_test`` field; for ad-hoc tools the caller may
            pass a minimal ``handler(**fixture); print("PATTERN_OK adhoc")``
            snippet built from the contract.
        packages: pip packages required by the tool body.
        working_dir: Optional working directory; a temp dir is created if
            omitted so the venv is fully isolated and removable.
        timeout: Per-test timeout in seconds.

    Returns:
        Standard AWP result dict::

            {
                "ok": bool,
                "status": int,
                "data": {"stdout": str, "stderr": str, "returncode": int},
                "error": str | None,
            }
    """
    from .venv_executor import VenvExecutor

    cleanup_dir: Optional[Path] = None
    if working_dir is None:
        cleanup_dir = Path(tempfile.mkdtemp(prefix="awp_smoke_"))
        working_dir = cleanup_dir

    full_program = code.rstrip() + "\n\n# ---- smoke test ----\n" + smoke_snippet

    executor = VenvExecutor(
        max_timeout=max(timeout, 10),
        working_dir=working_dir,
        packages=list(packages or []),
        pip_install=True,
    )

    try:
        result = executor.execute(full_program, timeout=timeout)
    except Exception as exc:  # pragma: no cover
        logger.exception("smoke_test_tool: venv execution crashed")
        result = {
            "ok": False,
            "status": 500,
            "data": {},
            "error": f"venv smoke test crashed: {exc}",
        }
    finally:
        if cleanup_dir is not None:
            try:
                executor.cleanup()
            except Exception:
                pass

    if result.get("ok"):
        stdout = result.get("data", {}).get("stdout", "")
        if "PATTERN_OK" not in stdout and "SMOKE_OK" not in stdout:
            # Did not raise, but also did not print the success marker —
            # treat as soft pass with a warning so the caller can decide.
            result["warning"] = (
                "smoke test exited 0 but did not print PATTERN_OK / SMOKE_OK marker"
            )
    return result


class RecipeReplayExecutor:
    """Executor adapter for :func:`awp.patterns.recipe.replay_gate`.

    The replay gate expects an object with a ``run_smoke(code,
    smoke_test, packages)`` method that returns a dict with at least
    an ``ok`` key.  This thin wrapper delegates to
    :func:`smoke_test_tool` and is the canonical way to run a recipe
    replay before promotion.
    """

    def __init__(self, *, timeout: int = 30) -> None:
        self._timeout = timeout

    def run_smoke(
        self,
        *,
        code: str,
        smoke_test: str,
        packages: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        result = smoke_test_tool(
            code,
            smoke_snippet=smoke_test,
            packages=list(packages),
            timeout=self._timeout,
        )
        return {
            "ok": bool(result.get("ok")),
            "stdout": result.get("data", {}).get("stdout", ""),
            "stderr": result.get("data", {}).get("stderr", ""),
            "error": result.get("error"),
        }


__all__ = ["smoke_test_tool", "RecipeReplayExecutor"]
