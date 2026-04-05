"""Parser for workflow.awp.yaml -> AWPManifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..models.communication import CommunicationConfig
from ..models.custom_tools import CustomToolsConfig
from ..models.evaluation import EvaluationConfig
from ..models.manifest import AWPManifest, DynamicToolsConfig
from ..models.memory import MemoryConfig
from ..models.observability import ObservabilityConfig
from ..models.orchestration import AWPOrchestrationConfig, DelegationLoopConfig
from ..models.security import SecurityConfig
from ..models.state import StateModel
from .template import resolve_templates


def parse_manifest(path: str | Path) -> AWPManifest:
    """Parse a workflow.awp.yaml file into an AWPManifest model.

    Args:
        path: Path to workflow.awp.yaml file.

    Returns:
        Validated AWPManifest instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        yaml.YAMLError: If YAML is malformed.
        pydantic.ValidationError: If schema validation fails.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Manifest must be a YAML mapping, got {type(raw).__name__}")

    # Build template context from workflow settings
    context = _build_context(raw)
    resolved = resolve_templates(raw, context)

    # Parse typed sub-sections before creating the manifest
    manifest_data = _extract_manifest_data(resolved)

    return AWPManifest(**manifest_data)


def _build_context(raw: dict[str, Any]) -> dict[str, Any]:
    """Build template resolution context from raw YAML."""
    context: dict[str, Any] = {}
    workflow = raw.get("workflow", {})
    context["workflow"] = workflow
    # Flatten settings.custom into context
    settings = workflow.get("settings", {})
    context["settings"] = settings
    return context


def _extract_manifest_data(resolved: dict[str, Any]) -> dict[str, Any]:
    """Extract and type-check manifest sections."""
    data: dict[str, Any] = {
        "awp": resolved["awp"],
        "workflow": resolved["workflow"],
    }

    # Parse optional typed sections
    if "orchestration" in resolved:
        orch_data = dict(resolved["orchestration"])
        # Parse delegation_loop sub-config if present
        if "delegation_loop" in orch_data and isinstance(
            orch_data["delegation_loop"], dict
        ):
            orch_data["delegation_loop"] = DelegationLoopConfig(
                **orch_data["delegation_loop"]
            )
        data["orchestration"] = AWPOrchestrationConfig(**orch_data)
    if "state" in resolved:
        data["state"] = StateModel(**resolved["state"])
    if "memory" in resolved:
        data["memory"] = MemoryConfig(**resolved["memory"])
    if "communication" in resolved:
        data["communication"] = CommunicationConfig(**resolved["communication"])
    if "observability" in resolved:
        obs_data = dict(resolved["observability"])
        if "evaluation" in obs_data and isinstance(obs_data["evaluation"], dict):
            obs_data["evaluation"] = EvaluationConfig(**obs_data["evaluation"])
        data["observability"] = ObservabilityConfig(**obs_data)
    if "custom_tools" in resolved:
        data["custom_tools"] = CustomToolsConfig(**resolved["custom_tools"])
    if "dynamic_tools" in resolved:
        data["dynamic_tools"] = DynamicToolsConfig(**resolved["dynamic_tools"])
    if "security" in resolved:
        data["security"] = SecurityConfig(**resolved["security"])

    # Pass through top-level env and settings
    if "env" in resolved:
        data["env"] = resolved["env"]
    if "settings" in resolved:
        data["settings"] = resolved["settings"]

    return data
