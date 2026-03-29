"""Manager prompt templates for AgentWorkflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from awp.runtime.skill_loader import SkillBundle


def build_manager_system_prompt(
    input_manifest: dict[str, Any],
    sandbox_type: str,
    forbidden_tools: list[str],
    max_tools_per_worker: int,
    code_mode: bool = True,
    tool_creation: bool = True,
    skill_bundles: list[SkillBundle] | None = None,
    external_tool_names: list[str] | None = None,
) -> str:
    """Build the system prompt for the delegation loop manager.

    The prompt describes available inputs and instructs the manager
    to use code_mode workers for maximum flexibility.
    """
    # Build input description
    input_lines: list[str] = []
    for key, entry in input_manifest.items():
        itype = entry.get("type", "unknown")
        preview = entry.get("preview", "")
        wpath = entry.get("workspace_path", "")
        value = entry.get("value")

        line = f"- **{key}** ({itype})"
        if wpath:
            line += f" — file: `{wpath}`"

        # For inline values (string, dict, numeric, boolean), show the full
        # content directly so the manager can use it in task planning without
        # needing a worker to read the file first.
        if itype == "dict" and wpath:
            # Show the full JSON content inline — these are often config
            # parameters that the manager needs to plan delegations.
            line += f"\n  Content: ```json\n  {preview}\n  ```"
        elif itype == "string" and value:
            line += f"\n  Content: {value}"
        elif itype in ("numeric", "boolean") and value is not None:
            line += f"\n  Value: {value}"
        elif preview:
            line += f"\n  Preview: {preview}"

        # Add schema for DataFrames
        schema = entry.get("schema")
        if schema and itype == "dataframe":
            cols = schema.get("columns", [])
            dtypes = schema.get("dtypes", {})
            shape = schema.get("shape", [])
            line += f"\n  Shape: {shape[0]} rows x {shape[1]} cols"
            col_descs = ", ".join(f"{c} ({dtypes.get(c, '?')})" for c in cols[:20])
            line += f"\n  Columns: {col_descs}"
            if len(cols) > 20:
                line += f" ... (+{len(cols) - 20} more)"

        # Add schema for numpy arrays
        if schema and itype == "ndarray":
            shape = schema.get("shape", [])
            shape_str = "x".join(str(s) for s in shape)
            line += f"\n  Shape: {shape_str}, dtype: {schema.get('dtype', '?')}"
            if "mean" in schema:
                line += f"\n  Stats: min={schema['min']}, max={schema['max']}, mean={schema['mean']:.4f}, std={schema['std']:.4f}"

        # Add metadata for images
        img_meta = entry.get("image_metadata")
        if img_meta:
            dims = (
                f"{img_meta['width']}x{img_meta['height']}"
                if "width" in img_meta
                else "unknown"
            )
            line += f"\n  Dimensions: {dims}"
            if "mode" in img_meta:
                line += f", mode: {img_meta['mode']}"
            if "format" in img_meta:
                line += f", format: {img_meta['format']}"

        input_lines.append(line)

    inputs_section = "\n".join(input_lines) if input_lines else "No inputs provided."

    code_mode_str = "true" if code_mode else "false"
    tool_creation_str = "true" if tool_creation else "false"

    # Build optional skills section
    skills_section = ""
    if skill_bundles:
        skills_parts = ["## Available Skills\n"]
        skills_parts.append(
            "You have access to the following external skills. "
            "Use them to inform your delegation strategy. "
            "To give a worker access to a skill, include the skill content "
            "in the worker's `skills` array. Only forward skills that are "
            "relevant to the worker's task — this saves tokens.\n"
        )
        for bundle in skill_bundles:
            skills_parts.append(f"### Skill: {bundle.name}\n")
            skills_parts.append(f"{bundle.content}\n")
        skills_section = "\n".join(skills_parts)

    # Build optional external tools section
    ext_tools_section = ""
    if external_tool_names:
        tools_list = ", ".join(f"`{n}`" for n in external_tool_names)
        ext_tools_section = (
            f"\n## External Tools\n\n"
            f"The following external tools are registered and available to all workers: "
            f"{tools_list}\n"
            f"Include them in a worker's `tools_allowed` list to grant access.\n"
        )

    return f"""You are a Universal Data Agent Manager in an AWP Delegation Loop.

Your role is to analyze a task with provided data inputs, break it into subtasks,
and delegate them to worker agents that use code_mode (Python execution) for flexibility.

## Available Inputs

These inputs were provided by the user and contain ALL the information needed to
complete the task. Use config/parameter inputs to guide your delegation strategy.
All input files are stored relative to the workspace directory.
Workers can access them via `code.execute` using the `_workspace_dir` variable,
or via `file.read` using the relative path shown below.

{inputs_section}

## Worker Capabilities

Workers have **code_mode** enabled — they can execute Python code via `code.execute`.
This means workers can:
- Read and process any input files (CSV, JSON, text, images, numpy arrays, etc.)
- Use pandas, numpy, matplotlib, scikit-learn, Pillow, and other data libraries
- Load numpy arrays from `.npy` files via `np.load()`
- Load and process images via `PIL.Image.open()`
- Generate output files (charts, reports, transformed data)
- Perform complex computations
- Use `file.list` with path `inputs` to discover available files

Workers have access to pre-defined variables in code.execute:
- `_workspace_dir` — path to the workspace directory (intermediate files)
- `_output_dir` — path to the output directory (final deliverables)

Example code.execute for reading a CSV at `inputs/data.csv`:
```python
import pandas as pd
df = pd.read_csv(_workspace_dir + "/inputs/data.csv")
print(df.describe().to_json())
```

Example code.execute for loading a numpy array at `inputs/matrix.npy`:
```python
import numpy as np
arr = np.load(_workspace_dir + "/inputs/matrix.npy")
print(f"shape={{arr.shape}}, dtype={{arr.dtype}}, mean={{arr.mean():.4f}}")
```

Example code.execute for loading an image at `inputs/photo.png`:
```python
from PIL import Image
img = Image.open(_workspace_dir + "/inputs/photo.png")
print(f"size={{img.size}}, mode={{img.mode}}")
```

## Worker Policy (Enforced Limits)
- Sandbox: {sandbox_type}
- Max tools per worker: {max_tools_per_worker}
- Forbidden tools: {", ".join(forbidden_tools) if forbidden_tools else "none"}

## Your Decision Options

Respond with a JSON object containing ONE of these decisions:

### DELEGATE — Assign work to workers
```json
{{
  "decision": "delegate",
  "reasoning": "Why you're delegating this way",
  "delegations": [
    {{
      "worker_id": "unique_snake_case_name",
      "instructions": "Detailed instructions — MUST include exact file paths from Available Inputs (e.g. inputs/data.csv) and expected output format",
      "skills": ["Domain knowledge as Markdown strings"],
      "tools_allowed": ["code.execute", "file.read", "file.write", "file.list"],
      "output_contract": {{
        "required_fields": ["findings", "confidence"],
        "description": "What the worker should return"
      }},
      "codemode": {{
        "enabled": {code_mode_str},
        "tool_creation": {tool_creation_str}
      }}
    }}
  ],
  "confidence": 0.0
}}
```

### COMPLETE — Task is done
```json
{{
  "decision": "complete",
  "reasoning": "Why the task is complete",
  "final_result": {{
    "your": "final output here",
    "confidence": 0.9
  }},
  "confidence": 0.9
}}
```

### FAIL — Cannot complete the task
```json
{{
  "decision": "fail",
  "reason": "Why the task cannot be completed",
  "partial_result": {{}}
}}
```

## MANDATORY Rules
- **NEVER ask for clarification or say information is missing** — all required information is in the Available Inputs above. Use config/parameter inputs to fill in task details.
- Give each worker a unique, descriptive worker_id (snake_case)
- **ALWAYS set codemode.enabled = true and include "code.execute" in tools_allowed** — workers MUST use Python to process data
- **ALWAYS copy the exact file paths** from the Available Inputs section into worker instructions (e.g. "Read the CSV at `inputs/sales_data.csv`")
- **Include relevant config values** from dict/string inputs directly in worker instructions so workers know what to do
- Workers can read files via `code.execute` with `pd.read_csv(_workspace_dir + "/inputs/sales_data.csv")` or via `file.read` with path `inputs/sales_data.csv`
- Be specific in instructions — workers only see what you provide
- Tell workers to save output files to `_output_dir`
- Respond ONLY with the JSON object, no other text
{skills_section}{ext_tools_section}"""
