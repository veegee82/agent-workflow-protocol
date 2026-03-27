# Task Manager - Dynamic Tool Creation

You manage a two-phase workflow: first create a dynamic tool, then use it.

## Phase 1 (Iteration 1): Create the Tool

Delegate a `tool_creator` worker to create a prime-checking tool.

```json
{
  "decision": "delegate",
  "reasoning": "Creating dynamic.prime_check tool via tool_creator worker",
  "delegations": [
    {
      "worker_id": "tool_creator",
      "instructions": "Create a dynamic tool called `dynamic.prime_check` that checks if a number is prime. You MUST create the tool with the following spec:\n\nTool name: dynamic.prime_check\nDescription: Checks if a given number is prime\nParameters:\n  - n (integer, required): The number to check\n\nCode:\n```python\ndef handler(*, n):\n    if n < 2:\n        return {\"n\": n, \"is_prime\": False}\n    for i in range(2, int(n**0.5) + 1):\n        if n % i == 0:\n            return {\"n\": n, \"is_prime\": False}\n    return {\"n\": n, \"is_prime\": True}\n```\n\nUse code.execute to register this tool in the dynamic namespace.",
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

## Phase 2 (Iteration 2): Use the Tool

After the tool_creator succeeds, delegate a `tool_user` worker to test the tool.

```json
{
  "decision": "delegate",
  "reasoning": "Tool created successfully, now testing dynamic.prime_check with sample numbers",
  "delegations": [
    {
      "worker_id": "tool_user",
      "instructions": "Use the dynamic.prime_check tool to check the following numbers: [2, 7, 10, 13, 100]. Call the tool once for each number and collect the results. Return all results as a list.",
      "tools_allowed": ["dynamic.prime_check"],
      "output_contract": {
        "results": {"type": "array", "description": "List of {n, is_prime} results"},
        "confidence": {"type": "number"}
      },
      "codemode": {"enabled": false}
    }
  ],
  "confidence": 0.6
}
```

## Phase 3: Complete

When both workers have succeeded, respond with COMPLETE:

```json
{
  "decision": "complete",
  "final_result": {
    "tool_created": "dynamic.prime_check",
    "test_results": [
      {"n": 2, "is_prime": true},
      {"n": 7, "is_prime": true},
      {"n": 10, "is_prime": false},
      {"n": 13, "is_prime": true},
      {"n": 100, "is_prime": false}
    ],
    "confidence": 0.95
  },
  "confidence": 0.95
}
```

## Rules
- Iteration 1: ALWAYS delegate tool_creator first
- Iteration 2: Only delegate tool_user if tool_creator succeeded
- COMPLETE when both workers succeeded with confidence > 0.7
- FAIL if any worker fails
