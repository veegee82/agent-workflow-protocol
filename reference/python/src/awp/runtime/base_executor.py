"""AWP Base Executor -- Abstract interface for code execution sandboxes.

All executor implementations (subprocess, Docker, venv) implement this
interface so that the rest of the runtime can treat them interchangeably.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Pip package name validation
# ---------------------------------------------------------------------------

# PEP 508 package name: letters, digits, hyphens, underscores, dots.
# Version specifiers use ==, >=, <=, !=, ~=, <, > followed by version digits.
# Extras use [extra1,extra2].
_VALID_PIP_SPEC = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"  # package name
    r"(\[[A-Za-z0-9,._-]+\])?"                      # optional extras
    r"("
    r"(==|>=|<=|!=|~=|<|>)[A-Za-z0-9.*+!_-]+"       # version spec
    r"(,(==|>=|<=|!=|~=|<|>)[A-Za-z0-9.*+!_-]+)*"   # additional version specs
    r")?$"
)

# Patterns that indicate malicious or unsafe pip specifiers
_DANGEROUS_PIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^-"),                    # pip flags: --index-url, -r, --target, etc.
    re.compile(r"://"),                   # URLs: https://, git+https://, etc.
    re.compile(r"^git\+"),               # git refs
    re.compile(r"^svn\+"),               # svn refs
    re.compile(r"^hg\+"),                # mercurial refs
    re.compile(r"^bzr\+"),               # bazaar refs
    re.compile(r"[/\\]"),                 # local paths (unix or windows)
    re.compile(r"^\.\.*$"),              # relative paths: . or ..
    re.compile(r"\.tar\.gz$|\.whl$|\.zip$|\.egg$", re.IGNORECASE),  # local archives
    re.compile(r"#egg="),                 # egg fragments
    re.compile(r"@\s*http"),             # PEP 440 direct references
    re.compile(r"@\s*file"),             # file:// direct references
    re.compile(r"@\s*git\+"),            # git direct references
]


def sanitize_pip_specs(packages: list[str]) -> tuple[list[str], list[str]]:
    """Validate and sanitize pip package specifiers.

    Only allows standard PyPI package names with optional version constraints.
    Rejects URLs, local paths, pip flags, VCS references, and shell metacharacters.

    Args:
        packages: Raw list of pip specifiers from user/agent input.

    Returns:
        Tuple of (sanitized_packages, rejected_with_reasons).
    """
    sanitized: list[str] = []
    rejected: list[str] = []

    for raw in packages:
        pkg = raw.strip()
        if not pkg:
            continue

        # Block shell metacharacters
        _shell_chars = (";", "&", "|", "`", "$", "\n", "\r", "'", '"', "(", ")", "{", "}")
        if any(c in pkg for c in _shell_chars):
            rejected.append(f"{pkg}: contains shell metacharacters")
            continue

        # Block dangerous patterns
        blocked = False
        for pattern in _DANGEROUS_PIP_PATTERNS:
            if pattern.search(pkg):
                rejected.append(f"{pkg}: matches dangerous pattern {pattern.pattern}")
                blocked = True
                break
        if blocked:
            continue

        # Validate against PEP 508 package name format
        if not _VALID_PIP_SPEC.match(pkg):
            rejected.append(f"{pkg}: does not match valid package name format")
            continue

        # Length limit — no legitimate package name exceeds 128 chars
        if len(pkg) > 128:
            rejected.append(f"{pkg[:50]}...: exceeds maximum length")
            continue

        sanitized.append(pkg)

    return sanitized, rejected


class BaseExecutor(ABC):
    """Abstract base class for AWP code execution sandboxes.

    Every executor must implement ``execute()`` and ``cleanup()``.
    ``validate_code()`` has a default AST-based implementation that
    subclasses may override.
    """

    @abstractmethod
    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute Python code in the sandbox.

        Args:
            code: Python source code to execute.
            timeout: Timeout in seconds (capped by implementation limits).

        Returns:
            Standard AWP result format::

                {
                    "ok": bool,
                    "status": int,
                    "data": {"stdout": str, "stderr": str, "returncode": int},
                    "error": str | None,
                }
        """

    def validate_code(self, code: str) -> dict[str, Any]:
        """Validate Python code via AST parsing without execution.

        Args:
            code: Python source code to validate.

        Returns:
            Standard AWP result format with validation status.
        """
        import ast

        try:
            ast.parse(code)
            return {
                "ok": True,
                "status": 200,
                "data": {"valid": True},
                "error": None,
            }
        except SyntaxError as e:
            return {
                "ok": False,
                "status": 400,
                "data": {"valid": False},
                "error": f"Syntax error: {e}",
            }

    def install_runtime_packages(self, packages: list[str]) -> dict[str, Any]:
        """Install additional pip packages at runtime.

        The default implementation uses the current Python's pip.
        Subclasses may override for sandbox-specific installation.

        Args:
            packages: List of pip package specifiers to install.

        Returns:
            Standard AWP result format.
        """
        import subprocess
        import sys

        if not packages:
            return {
                "ok": True,
                "status": 200,
                "data": {"installed": []},
                "error": None,
            }

        # Robust sanitization: reject URLs, paths, flags, shell metacharacters
        sanitized, rejected = sanitize_pip_specs(packages)
        if rejected:
            import logging
            logging.getLogger(__name__).warning(
                "Rejected pip specs: %s", "; ".join(rejected)
            )
        if not sanitized:
            return {
                "ok": False,
                "status": 400,
                "data": {"rejected": rejected},
                "error": (
                    "No valid package names after sanitization. "
                    f"Rejected: {'; '.join(rejected)}"
                ),
            }

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + sanitized,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "installed": sanitized,
                    "stderr": result.stderr[:500] if result.stderr else "",
                },
                "error": None,
            }
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr[:500] if exc.stderr else str(exc)
            stdout = exc.stdout[:500] if exc.stdout else ""
            return {
                "ok": False,
                "status": 500,
                "data": {"stdout": stdout, "stderr": stderr},
                "error": f"pip install failed: {stderr}",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": 408,
                "data": {},
                "error": "pip install timed out after 300s",
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "status": 500,
                "data": {},
                "error": (
                    f"Python executable not found: {sys.executable}. "
                    f"pip cannot be invoked."
                ),
            }

    def cleanup(self) -> None:
        """Clean up sandbox resources. Called at workflow completion."""
