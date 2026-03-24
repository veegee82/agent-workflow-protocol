"""AWP Secrets Loader -- Resolves secrets from secrets.yaml, .env, and os.environ.

Loads secrets with priority: secrets.yaml > .env > os.environ.
Supports ``{{ env.VAR_NAME }}`` template syntax in secrets.yaml values
to reference environment variables without hardcoding them.

Usage::

    from awp.runtime.secrets import load_secrets

    secrets = load_secrets(Path("my-workflow"))
    # {"SEARCH_API_KEY": "sk-abc123", "DB_URL": "postgres://..."}
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_RE = re.compile(r"\{\{\s*env\.(\w+)\s*\}\}")


def _get_global_env_path() -> Path:
    """Return the path to the global AWP .env file (~/.awp/.env)."""
    return Path.home() / ".awp" / ".env"


def load_secrets(workflow_dir: Path) -> dict[str, str]:
    """Load secrets with priority: secrets.yaml > .env > global .env > os.environ.

    Resolution order (later wins):
    1. ``os.environ`` -- system / CI environment
    2. ``~/.awp/.env`` -- global AWP configuration (fallback)
    3. ``.env`` file in workflow root -- common local development pattern
    4. ``secrets.yaml`` in workflow root -- explicit project secrets

    Returns:
        Flat dict of secret name → value.
    """
    merged: dict[str, str] = {}

    # Layer 1: os.environ (base)
    merged.update(os.environ)

    # Layer 2: global ~/.awp/.env (fallback defaults)
    global_env_path = _get_global_env_path()
    if global_env_path.exists():
        global_dotenv = _load_dotenv_file(global_env_path)
        if global_dotenv:
            merged.update(global_dotenv)
            logger.debug("Loaded %d entries from global %s", len(global_dotenv), global_env_path)

    # Layer 3: .env file in workflow dir
    dotenv = _load_dotenv(workflow_dir)
    if dotenv:
        merged.update(dotenv)
        logger.debug("Loaded %d entries from .env", len(dotenv))

    # Layer 4: secrets.yaml (highest priority)
    yaml_secrets = _load_secrets_yaml(workflow_dir, merged)
    if yaml_secrets:
        merged.update(yaml_secrets)
        logger.debug("Loaded %d entries from secrets.yaml", len(yaml_secrets))

    return merged


def _load_secrets_yaml(
    workflow_dir: Path, env: dict[str, str],
) -> dict[str, str]:
    """Parse secrets.yaml and resolve ``{{ env.VAR }}`` templates.

    Expected format::

        secrets:
          SEARCH_API_KEY: "sk-abc123"
          DATABASE_URL: "{{ env.PROD_DATABASE_URL }}"

    Args:
        workflow_dir: Workflow root directory.
        env: Current environment dict used to resolve templates.

    Returns:
        Dict of resolved secret name → value.

    Raises:
        ValueError: If a ``{{ env.VAR }}`` references an undefined variable.
    """
    secrets_file = workflow_dir / "secrets.yaml"
    if not secrets_file.exists():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # Fallback: simple YAML parsing for the flat secrets format
        return _parse_simple_yaml(secrets_file, env)

    with secrets_file.open(encoding="utf-8") as f:
        data: Any = yaml.safe_load(f)

    if not isinstance(data, dict) or "secrets" not in data:
        logger.warning("secrets.yaml has no 'secrets' key -- skipping")
        return {}

    raw: dict[str, Any] = data["secrets"]
    if not isinstance(raw, dict):
        return {}

    resolved: dict[str, str] = {}
    for key, value in raw.items():
        resolved[str(key)] = _resolve_template(str(value), env)

    return resolved


def _parse_simple_yaml(
    path: Path, env: dict[str, str],
) -> dict[str, str]:
    """Minimal YAML parser for flat secrets format (no PyYAML dependency).

    Handles only::

        secrets:
          KEY: "value"
          KEY2: value
    """
    result: dict[str, str] = {}
    in_secrets = False

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "secrets:":
            in_secrets = True
            continue
        if in_secrets and line.startswith("  "):
            # Indented under secrets:
            match = re.match(r"^\s+(\w+)\s*:\s*(.+)$", line)
            if match:
                key = match.group(1)
                val = match.group(2).strip().strip("'\"")
                result[key] = _resolve_template(val, env)
        elif not line.startswith(" "):
            in_secrets = False

    return result


def _load_dotenv_file(env_file: Path) -> dict[str, str]:
    """Parse a .env file into dict (KEY=VALUE per line).

    Supports:
    - Comments (lines starting with #)
    - Blank lines
    - Quoted values (single or double quotes stripped)
    - No shell expansion or interpolation
    """
    if not env_file.exists():
        return {}

    result: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            result[key] = value

    return result


def _load_dotenv(workflow_dir: Path) -> dict[str, str]:
    """Parse .env file from workflow directory."""
    return _load_dotenv_file(workflow_dir / ".env")


def _resolve_template(value: str, env: dict[str, str]) -> str:
    """Resolve ``{{ env.VAR_NAME }}`` references in a string.

    Args:
        value: String possibly containing template references.
        env: Environment dict to resolve against.

    Returns:
        String with all templates resolved.

    Raises:
        ValueError: If a referenced variable is not found in env.
    """
    def _replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in env:
            raise ValueError(
                f"secrets.yaml references undefined variable: "
                f"{{{{ env.{var_name} }}}}. "
                f"Set it as an environment variable or in .env."
            )
        return env[var_name]

    return _TEMPLATE_RE.sub(_replacer, value)
