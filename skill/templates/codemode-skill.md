# Code Mode Execution

You have access to a **typed SDK** instead of individual tool calls.
Write code that uses the SDK to complete your task, then return the result
as a JSON object matching your output schema.

## SDK API

{{SDK_TYPE_DEFINITIONS}}

## Rules

1. Write a **single async function** that receives the SDK and returns your result.
2. The return value **MUST** match your output schema (including `confidence`).
3. Do **NOT** use global variables, dynamic imports, or direct `fetch()` calls.
4. The SDK is your **only** interface to external systems. Network access is blocked.
5. Handle errors gracefully — catch exceptions and return them in an error field.
6. Keep code concise — chain operations instead of writing verbose loops.

## Example

```{{LANGUAGE}}
{{CODE_EXAMPLE}}
```

## Available SDK Methods

{{SDK_METHOD_LIST}}

## Dynamic Tool Creation

If your agent has `tool_creation: true` enabled, you can create, list, and
remove tools at runtime via the `sdk.tools` namespace. Created tools become
available to downstream agents in the workflow DAG.

### sdk.tools.create(name, description, parameters, code, meta?)

Create and register a new tool. The `code` must contain a `def handler(*, ...)`
function that returns the standard AWP result format.

```python
await sdk.tools.create(
    name="scoring.quality",
    description="Score item quality on a 0-1 scale",
    parameters={
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"]
    },
    code="""
def handler(*, value):
    score = min(value / 100.0, 1.0)
    return {"ok": True, "status": 200, "data": {"score": score}, "error": None}
""",
    meta={"side_effects": False, "deterministic": True}
)
```

### sdk.tools.list(namespace?)

List all dynamic tools, optionally filtered by namespace.

### sdk.tools.remove(name)

Remove a dynamic tool you created. You can only remove your own tools.

### Rules for dynamic tool code

- MUST contain exactly one `def handler(*, ...)` function
- MUST return `{"ok": bool, "status": int, "data": {...}, "error": str|None}`
- MUST NOT import os, subprocess, sys, socket, or other system modules
- Tools run in a subprocess sandbox — no direct access to the SDK or registry
- Dynamic tools have no secrets access — use the proxy pattern (call static
  tools that have secrets via your own codemode SDK calls)

## Output Schema

Your function must return a JSON object with these fields:

{{OUTPUT_SCHEMA_FIELDS}}
