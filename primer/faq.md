# Frequently Asked Questions

## General

### Do I need Python to use AWP?

No. AWP is a specification, not a Python library. The `workflow.awp.yaml` and `agent.awp.yaml` files are plain YAML that any language can parse. The Python reference implementation in this repository is one possible runtime, but AWP workflows can be executed by any conforming runtime written in any language. If your runtime can parse YAML, call an LLM API, and execute tool functions, it can support AWP.

### Is AWP a runtime or a specification?

AWP is a **specification**. It defines the format and semantics of workflow manifests, agent configurations, and their interactions. A runtime is a program that reads an AWP manifest and executes it. This repository contains both the specification (in `spec/`) and a Python reference implementation, but they are separate concerns. You can implement your own runtime that conforms to the AWP spec.

### Is AWP production-ready?

AWP 1.0.0 is a stable specification suitable for production use. The protocol model, autonomy levels, and validation rules are fully defined. The reference implementation is functional and tested. That said, as with any 1.0 release, expect the ecosystem of runtimes and tooling to mature over time. The specification itself follows SemVer, so any breaking changes would require a 2.0 version.

### Who maintains AWP?

AWP is an open specification. Contributions are welcome via the process described in [CONTRIBUTING.md](../CONTRIBUTING.md). The specification evolves through RFCs proposed as GitHub issues and reviewed by the community.

## Compatibility

### Can I use AWP with LangChain, CrewAI, or AutoGen?

Yes, through adapters. AWP is runtime-agnostic, so any framework can serve as an execution backend. A LangChain adapter would map AWP agent definitions to LangChain agents, AWP tool declarations to LangChain tools, and AWP state to LangChain memory. The same applies to CrewAI, AutoGen, or any other framework. AWP describes the workflow; the framework executes it.

### How does AWP relate to MCP?

AWP uses MCP at Layer 2 (Capabilities). When an AWP agent declares `tools.allowed: ["web.search"]`, the runtime calls an MCP-compatible tool server to execute that tool. AWP does not replace MCP -- it incorporates it. Any existing MCP tool server works with AWP without modification. See [comparison.md](comparison.md) for a detailed breakdown.

### Can I convert existing workflows to AWP?

If your existing workflow has agents with defined roles, tools, and execution order, it can likely be expressed as AWP. The translation is manual today: map your agent definitions to `agent.awp.yaml`, your orchestration logic to the `agents` graph in `workflow.awp.yaml`, and your tool configurations to the capabilities section. Automated conversion tools for specific frameworks may be developed by the community.

## Workflow Design

### What is the minimum viable AWP workflow?

A valid AWP workflow requires only a manifest header and one agent:

```yaml
awp: 1.0.0
workflow:
  name: minimal
  version: 1.0.0
  description: Minimal workflow

agents:
  - name: agent-one
    role: Does one thing
    llm:
      model: openai/gpt-4o-mini
```

This is an A0 (Prescribed) workflow. It has no tools, no memory, no orchestration beyond a single agent. It is enough to validate the format and test a runtime.

### Can agents communicate outside the DAG?

Yes. The DAG defines the execution order, but Layer 3 (Communication) provides a message bus for agent-to-agent messaging that is independent of the graph topology. An agent can send a message to any other agent using the `agent.send_message` tool. The receiving agent retrieves messages using `agent.list_messages`. This is useful for advisory messages, status updates, or collaborative problem-solving that does not fit a strict sequential flow.

### How does memory work?

AWP defines four memory tiers at Layer 4:

| Tier | Scope | Persistence | Example |
|------|-------|-------------|---------|
| **Working** | Current run | In-memory only | Intermediate reasoning steps |
| **Short-term** | Daily | Append-only daily log files | Today's agent outputs and observations |
| **Long-term** | Cross-run | Curated MEMORY.md file | Stable facts, user preferences, learned policies |
| **Shared** | Cross-agent | Workspace directory | Files, datasets, artifacts accessible to all agents |

Memory is configured per agent in `agent.awp.yaml`. An agent with `memory.enabled: true` gets its long-term memory injected into every prompt. Agents can write to memory via the `memory.write` tool and search across memory via `memory.search`. The `memory.curate` tool uses an LLM to extract stable facts from daily logs into long-term memory.

### How do output contracts work?

Each agent declares `share_output` in the workflow manifest -- a list of field names from its output that downstream agents can access. When agent B declares `depends_on: [agent_a]`, the runtime makes agent A's shared output fields available in agent B's context. The output schema (`output_schema.json`) defines the JSON structure the agent must produce, and the runtime validates responses against it.

## Packaging and Sharing

### How do I share workflows?

AWP workflows can be packaged as `.awp.zip` files that contain the complete workflow: manifest, agent definitions, prompts, schemas, skills, and project-local tools. The package format is:

```
workflow.awp.zip
  workflow.awp.yaml
  agents/
    agent-one/
      agent.awp.yaml
      agent.py
      workflow/
        ...
```

Share the ZIP file directly, publish it to a registry, or store it in version control. Any AWP-compatible runtime can extract and execute it.

### What are autonomy levels?

Autonomy levels (A0 through A4) measure how autonomous a workflow is. They allow runtimes to advertise their capabilities and workflows to declare their requirements:

| Level | Name | What It Measures |
|-------|------|-----------------|
| A0 | Prescribed | Static DAG, predefined agents, fixed tools |
| A1 | Adaptive | Conditional execution, loops, fan-out |
| A2 | Delegating | Manager spawns workers dynamically (budget required) |
| A3 | Self-Tooling | Agents create tools at runtime (safety envelope required) |
| A4 | Self-Organizing | Recursive delegation, budget distribution (observability required) |

Communication, memory, observability, and security are cross-cutting features available at any autonomy level. A simple A0 workflow can have full observability; an A4 workflow must have it. This prevents the "all or nothing" problem where a simple workflow is forced to deal with enterprise features it does not need.

## Validation and Debugging

### How does validation work?

AWP defines 32 validation rules (R1-R32) that can be checked before execution. The `awp validate` command checks:

- YAML syntax and schema conformance
- Agent reference integrity (every agent in the graph has a directory)
- Dependency graph acyclicity (no circular `depends_on`)
- Output schema validity (valid JSON Schema)
- Tool reference validity (allowed tools exist)
- State field consistency (shared fields are defined)

Validation catches configuration errors before any LLM calls are made, saving time and API costs.

### How do I debug a failing workflow?

AWP provides several debugging tools:

1. **Validation**: Run `awp validate` first to catch structural errors.
2. **Agent logs**: Check `runs/{project}/{run_id}/agent_loop.log` for per-run output.
3. **State inspection**: Examine `runs/{project}/{run_id}/state.json` for the current state.
4. **LLM prompt logs**: Review `logs/llm_prompts/` to see exactly what was sent to the LLM.
5. **Tool call logs**: Check `logs/tools/` for successful and failed tool calls.
6. **Trace context**: Every log entry includes `run_id`, `project`, and `agent` fields for correlation.

Set `debug.agent: true` in the agent configuration for verbose agent-level logging.
