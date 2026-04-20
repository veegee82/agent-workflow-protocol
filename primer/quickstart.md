# Quickstart: Build Your First Workflow in 5 Minutes

> **See also** — **Parent (primer)**: [README.md](README.md), [concepts.md](concepts.md) · **Authoritative YAML references**: [docs/manifest.md](../docs/manifest.md) (workflow.awp.yaml — Layer 0), [docs/agent.md](../docs/agent.md) (agent.awp.yaml — Layer 1), [docs/orchestration.md](../docs/orchestration.md) (Layer 5) · **On-disk layout**: [docs/file-structure.md](../docs/file-structure.md) · **Validate before running**: [docs/validation.md](../docs/validation.md) (R1–R32) · **Run & observe**: [docs/runtime.md](../docs/runtime.md), [docs/observability.md](../docs/observability.md), [docs/ui.md](../docs/ui.md) · **Next in primer**: [faq.md](faq.md)

This guide walks you through creating a minimal AWP workflow from scratch. By the end, you will have a valid, executable workflow with one agent, a prompt file, and an output schema.

## Prerequisites

- A text editor
- Python 3.10+ (for the reference implementation)
- An LLM API key (OpenRouter, OpenAI, or a local Ollama instance)

## Step 1: Create the Directory Structure

```bash
mkdir -p hello-world/agents/greeter/workflow/instructions
mkdir -p hello-world/agents/greeter/workflow/output_schema
```

Your directory will look like this:

```
hello-world/
  workflow.awp.yaml           (step 2)
  agents/
    greeter/
      agent.awp.yaml          (step 3)
      agent.py                (step 4)
      workflow/
        instructions/
          SYSTEM_PROMPT.md    (step 5)
        output_schema/
          output_schema.json  (step 6)
```

## Step 2: Create the Workflow Manifest

Create `hello-world/workflow.awp.yaml`:

```yaml
awp: 1.0.0

workflow:
  name: hello-world
  version: 1.0.0
  description: A single agent that generates a greeting

agents:
  - name: greeter
    role: Generates a friendly, personalized greeting
    agent_path: agents/greeter
    llm:
      model: openai/gpt-4o-mini
      temperature: 0.7

execution:
  mode: sequential
```

This is a valid A0 workflow. It declares one agent with an explicit model and a sequential execution mode.

## Step 3: Create the Agent Configuration

Create `hello-world/agents/greeter/agent.awp.yaml`:

```yaml
agent:
  name: greeter
  description: >
    A friendly agent that generates personalized greetings.
    Given a user's name and preferred language, it produces
    a warm, culturally appropriate greeting.

llm:
  model:
    executor: openai/gpt-4o-mini
  temperature: 0.7
  reasoning:
    enabled: false

tools:
  execute: false
  max_calls: 0
  allowed: []

memory:
  enabled: false

debug:
  agent: false
  data: false
```

The agent configuration specifies the LLM model, disables tools (this agent only generates text), and turns off memory. For a first workflow, simplicity is the goal.

## Step 4: Create the Agent Implementation

Create `hello-world/agents/greeter/agent.py`:

```python
"""Greeter agent -- minimal AWP implementation."""

from __future__ import annotations

from typing import Any, Dict

from awp.agent import AWPAgent


class Agent(AWPAgent):
    """A simple agent that generates greetings."""

    @property
    def name(self) -> str:
        return "greeter"

    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the greeting task.

        When using WorkflowRunner, the runtime handles LLM calls,
        prompt assembly, and response parsing automatically.
        Override this method only for custom logic.
        """
        state = state or {}
        return {self.name: {"greeting": "Hello!", "confidence": 0.9}}
```

The agent class extends `AWPAgent` from the `awp-agents` package. The `name` property must match the `identity.id` in `agent.awp.yaml`. When using the standalone runtime (`awp.runtime.WorkflowRunner`), the runner handles LLM calls automatically -- `agent.py` serves as a class definition and optional override point.

For other platforms, use the appropriate adapter template from `skill/adapters/`.

## Step 5: Create the System Prompt

Create `hello-world/agents/greeter/workflow/instructions/SYSTEM_PROMPT.md`:

```markdown
# Greeter Agent

You are a friendly greeting agent. Your job is to generate warm,
personalized greetings.

## Instructions

1. Read the user's request carefully.
2. Identify the name to greet and any language preference.
3. Generate a culturally appropriate greeting.
4. If no language is specified, default to English.

## Output Format

Always respond with valid JSON matching the output schema.
```

The system prompt is injected as the first message in the LLM conversation. It defines the agent's personality and behavioral constraints.

## Step 6: Create the Output Schema

Create `hello-world/agents/greeter/workflow/output_schema/output_schema.json`:

```json
{
  "type": "object",
  "properties": {
    "greeting": {
      "type": "string",
      "description": "The generated greeting message"
    },
    "language": {
      "type": "string",
      "description": "ISO 639-1 language code used for the greeting"
    },
    "tone": {
      "type": "string",
      "enum": ["formal", "casual", "enthusiastic"],
      "description": "The tone of the greeting"
    }
  },
  "required": ["greeting", "language"]
}
```

The output schema defines the JSON structure the agent must produce. AWP runtimes validate agent output against this schema and reject non-conforming responses.

## Step 7: Validate the Workflow

Run the AWP validator to check your workflow before execution:

```bash
awp validate hello-world/
```

Expected output:

```
[OK] workflow.awp.yaml -- valid AWP 1.0.0 manifest
[OK] agents/greeter/agent.awp.yaml -- valid agent configuration
[OK] agents/greeter/workflow/output_schema/output_schema.json -- valid JSON schema
[OK] Validation passed (3 files checked, 0 errors)
```

The validator checks YAML syntax, schema conformance, agent reference integrity (every agent in the graph has a corresponding directory), and output schema validity.

## Step 8: Run the Workflow

With an AWP-compatible runtime installed:

```bash
awp run hello-world/ --task "Greet Alice in Spanish"
```

Expected output:

```json
{
  "greeter": {
    "decision": "greet",
    "greeting": "Hola Alice, es un placer conocerte!",
    "language": "es",
    "tone": "enthusiastic"
  }
}
```

## Complete Example

For a fully worked version of this workflow with additional comments and variations, see `examples/workflows/01-hello-world/` in this repository.

## Next Steps

- **Add tools**: Enable web search or file access by setting `tools.execute: true` in the agent config and listing allowed tools. See the [specification](../spec/) for tool configuration.
- **Add a second agent**: Create another agent directory, add it to the `agents` list in the manifest, and use `depends_on` to create a DAG.
- **Enable memory**: Set `memory.enabled: true` in the agent config to give your agent persistent memory across runs.
- **Read the comparison**: See [comparison.md](comparison.md) to understand how AWP relates to MCP, A2A, and other standards.
