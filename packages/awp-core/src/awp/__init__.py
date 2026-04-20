"""AWP — Agent Workflow Protocol core library.

Provides models, parser, validator, and tools for the AWP specification.
For the execution runtime, install ``awp-runtime``.
"""

import os
from pathlib import Path

def _get_version() -> str:
    """Read version from installed package metadata, fallback to default."""
    try:
        from importlib.metadata import version
        return version("awp-agents")
    except Exception:
        try:
            from importlib.metadata import version
            return version("awp-core")
        except Exception:
            return "0.0.0"

__version__ = _get_version()

# Extend __path__ to include awp-runtime submodules (namespace package support).
_core_dir = Path(__file__).parent
_runtime_dir = _core_dir.parent.parent.parent / "awp-runtime" / "src" / "awp"
if _runtime_dir.exists() and str(_runtime_dir) not in __path__:
    __path__.append(str(_runtime_dir))

from .agent import AWPAgent

__all__ = ["AWPAgent", "__version__"]
