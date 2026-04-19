"""Built-in tools that live in their own module (Phase 3.4 onward).

The classic built-in tools (``file.read``, ``web.search``, ``board.post``,
``digest.fetch`` …) are still registered inline in
:meth:`awp.runtime.tools.ToolRegistry._register_builtins` for historical
reasons. Tools introduced from Phase 3 onward land here so the registry
file does not keep growing without bound.

Currently exports:

* :func:`repo_fact` — TF-IDF snippet lookup over the run's input
  workspace. Opt-in via ``tools_allowed``; never auto-registered into
  default workflows.
"""

from .repo_fact import RepoFactIndex, repo_fact

__all__ = ["RepoFactIndex", "repo_fact"]
