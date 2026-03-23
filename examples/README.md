# AWP Example Workflows

This directory contains complete, self-contained example workflows demonstrating the Agent Workflow Protocol at each compliance level.

## Examples

| # | Name | Compliance | Difficulty | Description |
|---|------|-----------|------------|-------------|
| 01 | [hello-world](./01-hello-world/) | L0 Core | Beginner | Single agent that greets the user. Minimal possible AWP workflow. |
| 02 | [research-pipeline](./02-research-pipeline/) | L1 Composable | Intermediate | Three-agent DAG: planner, researcher, writer with state sharing. |
| 03 | [chat-team](./03-chat-team/) | L2 Communicative | Intermediate | Two agents communicating via the message bus. |
| 04 | [memory-workflow](./04-memory-workflow/) | L3 Memorable | Advanced | Research workflow with long-term and working memory. |
| 05 | [enterprise](./05-enterprise/) | L5 Enterprise | Expert | Full enterprise workflow with all seven AWP layers. |

## Compliance Levels

- **L0 Core** -- Single agent, basic orchestration, output schema required.
- **L1 Composable** -- Multi-agent DAG with dependencies and state sharing.
- **L2 Communicative** -- Inter-agent messaging via the message bus.
- **L3 Memorable** -- Memory tiers (long-term, daily logs, search).
- **L4 Observable** -- Structured logging, tracing, and metrics.
- **L5 Enterprise** -- All layers plus security, audit, rate limiting, circuit breakers.

## Running an Example

Each example is a self-contained workflow directory. To run one:

```bash
# Copy the example to your workflows directory
cp -r examples/01-hello-world workflows/hello-world

# Start the server
PYTHONPATH=src/ python src/server/main.py

# Use the API to start a run
curl -X POST http://localhost:8000/api/runs/hello-world/start \
  -H "Content-Type: application/json" \
  -d '{"task": "Say hello to the world"}'
```

## Structure

Every example follows the same directory layout:

```
{example}/
  workflow.awp.yaml          # Workflow manifest
  agents/
    {agent_name}/
      agent.awp.yaml         # Agent configuration
      agent.py               # Agent implementation
      workflow/
        instructions/
          SYSTEM_PROMPT.md   # System prompt
        prompt/
          00_INTRO.md        # Intro prompt
        output_schema/
          output_schema.json # Output JSON Schema
        output_schema_desc/
          output_schema_desc.json  # Field descriptions
```
