"""Generate output_schema.json and output_schema_desc.json from AWP output.contract."""

from __future__ import annotations

from typing import Any

from .models.agent import OutputField


def generate_output_schema(contract: dict[str, OutputField]) -> dict[str, Any]:
    """Generate output_schema.json from AWP output.contract.

    Enforces R17 (confidence) and R18 (valid JSON Schema draft-07).

    Args:
        contract: Dict of field_name -> OutputField from agent.awp.yaml

    Returns:
        JSON Schema draft-07 compatible dict.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, f in contract.items():
        prop: dict[str, Any] = {"type": f.type, "description": f.description}

        if f.minimum is not None:
            prop["minimum"] = f.minimum
        if f.maximum is not None:
            prop["maximum"] = f.maximum
        if f.max_length is not None:
            prop["maxLength"] = f.max_length
        if f.items is not None:
            prop["items"] = f.items
        if f.default is not None:
            prop["default"] = f.default

        properties[name] = prop

        if f.required:
            required.append(name)

    # R17: Ensure confidence field
    if "confidence" not in properties:
        properties["confidence"] = {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score for the result (0.0-1.0)",
        }
    if "confidence" not in required:
        required.append("confidence")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def generate_output_schema_desc(contract: dict[str, OutputField]) -> dict[str, str]:
    """Generate output_schema_desc.json from AWP output.contract.

    R12: Every field in output_schema.json has a description entry.

    Args:
        contract: Dict of field_name -> OutputField from agent.awp.yaml

    Returns:
        Dict of field_name -> description string.
    """
    desc: dict[str, str] = {}
    for name, f in contract.items():
        desc[name] = f.description or f"The {name} field."

    if "confidence" not in desc:
        desc["confidence"] = (
            "Overall confidence score between 0.0 (no confidence) "
            "and 1.0 (fully confident)."
        )

    return desc
