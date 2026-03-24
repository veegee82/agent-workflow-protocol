# Runtime & Platform Integration

AWP is runtime-agnostic. This document describes the AWPAgent abstract interface, the standalone reference runtime, and how to integrate AWP with any platform.

## AWPAgent Abstract Interface

Every AWP-compliant platform must provide an agent class that implements this interface:

```python
from abc import ABC, abstractmethod
from typing import Any, Dict


class AWPAgent(ABC):
    """Minimal AWP agent contract."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier in the workflow DAG.

        Must match the identity.id field in agent.awp.yaml.
        """

    @abstractmethod
    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent.

        Args:
            task: Human-readable task description.
            state: Shared workflow state dictionary containing outputs
                   from previously executed agents (keyed by agent name)
                   and auto-injected fields from the manifest.

        Returns:
            A dict with at minimum {self.name: result_dict}.
            result_dict must include a 'confidence' field (float, 0.0-1.0)
            per validation rule R17.
        """
```

### Contract Requirements

1. The `name` property must return a string matching `identity.id` in `agent.awp.yaml`.
2. The `run` method receives the current task and shared state.
3. The return value must be a dict with at least one key equal to `self.name`.
4. The result dict under `self.name` must include a `confidence` field (number, 0.0-1.0).
5. Additional top-level keys may be included for metadata or logging.

### Example Implementation

```python
from awp.agent import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        # Your agent logic here
        findings = do_research(task)
        return {
            self.name: {
                "findings": findings,
                "summary": summarize(findings),
                "confidence": 0.85,
            }
        }
```

## Standalone Runtime

The `awp-protocol` package includes a minimal standalone runtime for executing AWP workflows without any external framework.

### Installation

```bash
pip install awp-protocol
```

### Components

#### StandaloneAgent

A concrete AWPAgent implementation that:
1. Reads `agent.awp.yaml` for configuration.
2. Loads system prompt from `workflow/instructions/SYSTEM_PROMPT.md`.
3. Loads user prompt from `workflow/prompt/00_INTRO.md`.
4. Builds context from previous agent outputs in state.
5. Calls the LLM via an OpenAI-compatible API.
6. Parses the response as JSON matching `output_schema.json`.
7. Returns `{agent_id: parsed_result}`.

```python
from awp.runtime.agent import StandaloneAgent
from pathlib import Path

agent = StandaloneAgent(
    agent_dir=Path("my-workflow/agents/researcher"),
    workflow_dir=Path("my-workflow"),
)
result = agent.run("Research quantum computing", state={})
# result == {"researcher": {"summary": "...", "confidence": 0.85}}
```

#### WorkflowRunner

A minimal DAG executor that reads `workflow.awp.yaml`, topologically sorts the agent graph, and executes agents in order.

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("path/to/my-workflow")
result = runner.run("Analyze the latest quarterly report")
print(result)
```

**Supported features:**
- Sequential and parallel execution modes
- DAG-based topological ordering
- State sharing between agents
- Basic error handling (continue / skip / abort)
- Auto-inject fields from the manifest

**Not supported (use a full runtime):**
- Loops and interactive agents
- Fan-out / Fan-in
- Subworkflows
- Message bus communication
- Memory curation
- Observability export

#### LLMClient

A minimal OpenAI-compatible chat completion client.

```python
from awp.runtime.llm import LLMClient

client = LLMClient(
    api_key="sk-...",
    base_url="https://openrouter.ai/api/v1",
    model="anthropic/claude-sonnet-4",
)

# Text response
text = client.chat_text([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
])

# JSON response
data = client.chat_json([
    {"role": "system", "content": "Respond in JSON."},
    {"role": "user", "content": "List three colors."},
])
```

### Running via CLI

```bash
awp run path/to/my-workflow --task "Research quantum computing"
```

### Running via Python API

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline")
result = runner.run("Research quantum computing trends in 2026")
print(result["writer"]["article"])
```

## Environment Variables

The standalone runtime reads these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key for the LLM provider. Falls back to `OPENROUTER_API_KEY`. | -- |
| `LLM_MODEL` | Model identifier (e.g., `"anthropic/claude-sonnet-4"`). | -- |
| `LLM_BASE_URL` | API base URL. | `https://openrouter.ai/api/v1` |

## Cloudflare Workers Runtime

AWP workflows can run on **Cloudflare Workers** using the Dynamic Workers adapter.
Each workflow deploys as a single Dispatch Worker that orchestrates the agent DAG.

### Architecture

- **Dispatch Worker** — Central orchestrator that reads the DAG, calls LLMs, validates outputs
- **KV Namespace** — Workflow state between agents
- **D1 (SQLite)** — Short-term memory and daily logs (L3+)
- **R2 Bucket** — Long-term memory / MEMORY.md (L3+)
- **Workers AI** — Optional LLM backend (alternative to external APIs)

### Installation & Deployment

```bash
# Install Wrangler CLI
npm install -g wrangler
wrangler login

# Generate workflow with Cloudflare adapter
# (tell the AWP skill: "use the Cloudflare adapter")

# Setup and deploy
cd my-workflow/
npm install
wrangler kv namespace create STATE
# → copy id into wrangler.toml
wrangler secret put LLM_API_KEY
wrangler deploy
```

### Running

```bash
# HTTP invocation
curl -X POST https://my-workflow.account.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"task": "Research quantum computing trends"}'

# Local development
wrangler dev
curl http://localhost:8787 -d '{"task": "..."}'

# Health check
curl https://my-workflow.account.workers.dev/health
```

### LLM Configuration

The Cloudflare adapter supports two LLM backends:

```yaml
# External (OpenAI-compatible) — default
model:
  name: "anthropic/claude-sonnet-4-20250514"

# Cloudflare Workers AI
model:
  provider: workers-ai
  name: "@cf/meta/llama-3.1-70b-instruct"
```

### Memory Mapping

| AWP Tier | Cloudflare Service | Lifecycle |
|----------|-------------------|-----------|
| Working | JS variables | Request-scoped |
| Short-term | D1 (SQLite) | Persistent, queryable |
| Long-term | R2 (Object Storage) | Unlimited |

For the full adapter reference, see [skill/adapters/cloudflare-dynamic-workers.md](../skill/adapters/cloudflare-dynamic-workers.md).

---

## Building a Platform Adapter

To run AWP workflows on a different platform (e.g., LangGraph, CrewAI, a custom framework), you need to:

1. **Parse the YAML.** Read `workflow.awp.yaml` and all `agent.awp.yaml` files. The `awp-protocol` package provides parsers you can reuse:

   ```python
   from awp.parser import parse_manifest, parse_agent

   manifest = parse_manifest("workflow.awp.yaml")
   agent_config = parse_agent("agents/researcher/agent.awp.yaml")
   ```

2. **Map to platform concepts.** Translate AWP graph nodes to your platform's agent system, AWP state sharing to your platform's state mechanism, and AWP tool definitions to your platform's tool interface.

3. **Implement `agent.py`.** Each agent's `agent.py` should extend your platform's base class while also conforming to the AWPAgent interface:

   ```python
   from awp.agent import AWPAgent
   from your_platform import PlatformAgent

   class Agent(AWPAgent, PlatformAgent):
       @property
       def name(self) -> str:
           return "researcher"

       def run(self, task: str, state: dict) -> dict:
           # Use platform-specific features
           result = self.platform_execute(task, state)
           return {self.name: result}
   ```

4. **Validate.** Use the AWP validator to check your workflow before execution:

   ```python
   from awp.validator import validate_workflow

   result = validate_workflow("path/to/workflow")
   if not result.passed:
       for error in result.errors:
           print(error)
   ```

5. **Write an adapter document.** Create a markdown file following the pattern in `skill/adapters/standalone.md` that describes how `agent.py` should be generated for your platform. This allows the AWP build skill to generate platform-specific code.

### Adapter Document Structure

Place your adapter in `skill/adapters/{platform}.md`:

```markdown
# AWP Platform Adapter: {Platform Name}

## When to Use
{When this adapter is appropriate.}

## agent.py Template
{The agent.py template with {{AGENT_ID}} placeholders.}

## How Execution Works
{How your platform executes agents.}

## Running a Workflow
{Python API and CLI examples.}

## Dependencies
{Installation instructions.}
```
