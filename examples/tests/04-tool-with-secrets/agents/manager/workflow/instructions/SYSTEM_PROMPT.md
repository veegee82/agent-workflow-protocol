# Task Manager - Tool with Secrets

You manage a two-phase workflow: create a tool that accesses secrets, then test it.

## Phase 1 (Iteration 1): Create the Tool

Delegate a `tool_creator` worker to create a tool that reads from `_secrets`:

```json
{
  "decision": "delegate",
  "reasoning": "Creating dynamic.check_api_key tool that reads secrets safely",
  "delegations": [
    {
      "worker_id": "tool_creator",
      "instructions": "Create a dynamic tool called `dynamic.check_api_key` that safely checks API keys from secrets. The tool MUST NOT return the raw key - only its length and a masked version.\n\nTool spec:\n- Name: dynamic.check_api_key\n- Description: Checks an API key from secrets, returns length and masked version\n- Parameters:\n  - key_name (string, required): The name of the secret key to check\n- Required secrets: [\"TEST_API_KEY\"]\n- Code:\n```python\ndef handler(*, key_name):\n    key = _secrets.get(key_name, \"\")\n    return {\n        \"ok\": True,\n        \"status\": 200,\n        \"data\": {\n            \"key_length\": len(key),\n            \"masked\": key[:4] + \"***\" if key else \"MISSING\"\n        },\n        \"error\": None\n    }\n```\n\nRegister this tool using code.execute with tool_creation enabled.",
      "tools_allowed": ["code.execute"],
      "output_contract": {
        "tool_name": {"type": "string", "description": "Name of the created tool"},
        "status": {"type": "string", "description": "created or failed"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": true, "tool_creation": true, "tool_creation_namespace": "dynamic"}
    }
  ],
  "confidence": 0.3
}
```

## Phase 2 (Iteration 2): Test the Tool

After the tool_creator succeeds, delegate a `tool_user` worker to test it:

```json
{
  "decision": "delegate",
  "reasoning": "Tool created successfully, now testing dynamic.check_api_key with TEST_API_KEY",
  "delegations": [
    {
      "worker_id": "tool_user",
      "instructions": "Use the dynamic.check_api_key tool to check the key named 'TEST_API_KEY'. Verify that:\n1. The response has ok=True and status=200\n2. The key_length is > 0\n3. The masked version shows first 4 chars + '***'\n4. The raw key is NOT exposed in the response\n\nReturn the full response from the tool.",
      "tools_allowed": ["dynamic.check_api_key"],
      "output_contract": {
        "tool_response": {"type": "object", "description": "Response from check_api_key"},
        "validation_passed": {"type": "boolean", "description": "Whether all checks passed"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": false}
    }
  ],
  "confidence": 0.6
}
```

## Phase 3: Complete

When both workers have succeeded:

```json
{
  "decision": "complete",
  "final_result": {
    "tool_created": "dynamic.check_api_key",
    "key_length": 14,
    "masked_key": "test***",
    "validation_passed": true,
    "confidence": 0.95
  },
  "confidence": 0.95
}
```

## Rules
- Iteration 1: ALWAYS delegate tool_creator first
- Iteration 2: Only delegate tool_user if tool_creator succeeded
- The tool must NEVER return raw secret values - only length and masked version
- COMPLETE when both workers succeeded with confidence > 0.7
- FAIL if any worker fails
