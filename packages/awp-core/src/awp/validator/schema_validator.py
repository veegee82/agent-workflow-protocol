"""JSON Schema validation for AWP output schemas."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: ValidationResult) -> ValidationResult:
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


def validate_schema(schema_path: str | Path) -> ValidationResult:
    """Validate an output_schema.json file.

    Checks:
    - Valid JSON
    - type: "object" at root (R18)
    - Has "confidence" field with correct type (R17)
    - Has "properties" and "required" keys

    Args:
        schema_path: Path to output_schema.json

    Returns:
        ValidationResult with any errors found.
    """
    path = Path(schema_path)
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return ValidationResult(valid=False, errors=[f"Schema not found: {path}"])

    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return ValidationResult(valid=False, errors=[f"Invalid JSON: {e}"])

    if not isinstance(schema, dict):
        return ValidationResult(valid=False, errors=["Schema must be a JSON object"])

    # R18: Root type must be "object"
    if schema.get("type") != "object":
        errors.append("R18: Root schema type must be 'object'")

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    if not properties:
        errors.append("Schema must have at least one property")

    # R17: Must have confidence field
    if "confidence" not in properties:
        errors.append("R17: Schema must include a 'confidence' field")
    else:
        conf = properties["confidence"]
        if conf.get("type") != "number":
            errors.append("R17: 'confidence' field must have type 'number'")
        if conf.get("minimum") is not None and conf["minimum"] != 0.0:
            warnings.append("R17: 'confidence' minimum should be 0.0")
        if conf.get("maximum") is not None and conf["maximum"] != 1.0:
            warnings.append("R17: 'confidence' maximum should be 1.0")

    if "confidence" not in required:
        errors.append("R17: 'confidence' must be in 'required' array")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def validate_schema_desc(
    schema_path: str | Path,
    desc_path: str | Path,
) -> ValidationResult:
    """Validate output_schema_desc.json has keys for all schema properties (R12).

    Args:
        schema_path: Path to output_schema.json
        desc_path: Path to output_schema_desc.json
    """
    errors: list[str] = []

    schema_p = Path(schema_path)
    desc_p = Path(desc_path)

    if not schema_p.exists():
        return ValidationResult(valid=False, errors=[f"Schema not found: {schema_p}"])
    if not desc_p.exists():
        return ValidationResult(
            valid=False, errors=[f"Schema desc not found: {desc_p}"]
        )

    try:
        schema = json.loads(schema_p.read_text(encoding="utf-8"))
        desc = json.loads(desc_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return ValidationResult(valid=False, errors=[f"Invalid JSON: {e}"])

    properties = set(schema.get("properties", {}).keys())
    desc_keys = set(desc.keys())

    missing = properties - desc_keys
    if missing:
        errors.append(f"R12: Missing descriptions for fields: {sorted(missing)}")

    return ValidationResult(valid=len(errors) == 0, errors=errors)
