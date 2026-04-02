"""AWP — Agent Workflow Protocol core library.

Provides models, parser, validator, and tools for the AWP specification.
For the execution runtime, install ``awp-runtime``.
"""

__version__ = "1.0.0"

from .agent import AWPAgent

__all__ = ["AWPAgent", "__version__"]
