"""Output contract validation for AWP agents."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.agent import AWPAgent, OutputField
from ..models.orchestration import AWPOrchestrationConfig, ConditionalDependency


@dataclass
class ValidationResult:
    """Result of a validation check."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_contracts(
    agents: dict[str, AWPAgent],
    orchestration: AWPOrchestrationConfig | None = None,
) -> ValidationResult:
    """Validate output contracts across all agents.

    Checks:
    - R17: Every agent has 'confidence' field in contract
    - R8: Every share_input field is declared as shareable in source agent
    - Contract fields have valid types

    Args:
        agents: Dict of agent_id -> AWPAgent
        orchestration: Optional orchestration config for share_input checks.

    Returns:
        ValidationResult with any errors found.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for agent_id, agent in agents.items():
        contract = agent.output.contract

        # R17: Confidence field required
        if "confidence" not in contract:
            errors.append(
                f"R17: Agent '{agent_id}' output.contract must include 'confidence' field"
            )
        else:
            conf = contract["confidence"]
            if conf.type != "number":
                errors.append(
                    f"R17: Agent '{agent_id}' confidence field must have type 'number'"
                )
            if conf.minimum is not None and conf.minimum != 0.0:
                warnings.append(
                    f"R17: Agent '{agent_id}' confidence minimum should be 0.0"
                )
            if conf.maximum is not None and conf.maximum != 1.0:
                warnings.append(
                    f"R17: Agent '{agent_id}' confidence maximum should be 1.0"
                )

    # R8: Validate share_input references
    if orchestration:
        for node in orchestration.graph:
            for source_agent, fields in node.share_input.items():
                if source_agent not in agents:
                    errors.append(
                        f"R8: Agent '{node.id}' share_input references "
                        f"unknown agent '{source_agent}'"
                    )
                    continue

                source_contract = agents[source_agent].output.contract
                for field_name in fields:
                    if field_name not in source_contract:
                        errors.append(
                            f"R8: Agent '{node.id}' requests field '{field_name}' "
                            f"from '{source_agent}', but it's not in the output contract"
                        )
                    elif not source_contract[field_name].shareable:
                        errors.append(
                            f"R8: Agent '{node.id}' requests field '{field_name}' "
                            f"from '{source_agent}', but it's not marked as shareable"
                        )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
