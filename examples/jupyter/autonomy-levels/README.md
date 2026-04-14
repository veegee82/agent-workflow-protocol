# AWP Autonomy Levels — Interactive Guide

This directory contains five Jupyter notebooks — one per AWP autonomy level (A0–A4).
Each notebook explains **what** the level adds, **why** it matters, and lets you **run
a real example** against a live LLM.

## The Autonomy Spectrum

```
  A0            A1             A2               A3                A4
  Prescribed    Adaptive       Delegating       Self-Tooling      Self-Organizing
  ──────────────────────────────────────────────────────────────────────────────►
  static DAG    multi-agent    manager-worker   dynamic tool      recursive
  1+ agents     dependencies   delegation loop  creation          delegation
                state sharing  budget-bounded   safety envelope   hierarchical budgets
```

### Quick Comparison

| | A0 | A1 | A2 | A3 | A4 |
|---|---|---|---|---|---|
| **Engine** | DAG | DAG | Delegation Loop | Delegation Loop | Delegation Loop |
| **Agent creation** | Static | Static | Dynamic (manager spawns) | Dynamic | Dynamic + recursive |
| **State model** | Minimal | `share_output` chains | Manager accumulates | + tool artifacts | + hierarchical state |
| **Tool set** | Fixed | Fixed | Fixed | **Dynamic** (agents create tools) | Dynamic |
| **Delegation depth** | N/A | N/A | Flat (1 level) | Flat (1 level) | **Recursive** (`max_depth`) |
| **Budget required?** | No | No | **Yes** | Yes | Yes |
| **Observability** | Optional | Optional | Optional | Optional | **Mandatory** |
| **Key safety** | Schema (R1–R32) | + state strategy | + budget limits | + safety envelope | + depth cap |

### What Each Level Adds

**A0 → A1**: Dependencies between agents. State flows from one agent to the next via
`share_output`. The graph is still static — all agents and edges are defined in the YAML.

**A1 → A2**: The **paradigm shift**. Instead of a static graph, a manager agent (LLM)
decides at runtime what workers to spawn, what instructions to give them, and when the task
is complete. Budget controls become mandatory — without them, the loop could run forever.

**A2 → A3**: Workers gain the ability to **create new tools** at runtime. When a worker
encounters a need for a tool that doesn't exist, it writes one, the runtime validates it
against a safety envelope (allowed namespaces, denied operations, count limits), and
registers it for use.

**A3 → A4**: The manager can **promote workers to sub-managers**, creating a recursive
delegation tree. Each sub-manager receives a reserved subset of the parent's budget.
Observability becomes mandatory — tracing, metrics, and audit must be enabled to monitor
the delegation hierarchy.

## Notebooks

| Notebook | Level | Concepts | Estimated Runtime |
|----------|-------|----------|-------------------|
| [`A0_prescribed.ipynb`](A0_prescribed.ipynb) | A0 | Static DAG, single agent, output contract (R17) | ~30s |
| [`A1_adaptive.ipynb`](A1_adaptive.ipynb) | A1 | Multi-agent DAG, `depends_on`, `share_output`, state flow | ~60s |
| [`A2_delegating.ipynb`](A2_delegating.ipynb) | A2 | Delegation loop, budget enforcement, manager intelligence | ~2min |
| [`A3_self_tooling.ipynb`](A3_self_tooling.ipynb) | A3 | Dynamic tool creation, safety envelope, code execution | ~5min |
| [`A4_self_organizing.ipynb`](A4_self_organizing.ipynb) | A4 | Recursive delegation, sub-managers, budget distribution | ~10min |

## Prerequisites

```bash
# Install AWP (development mode)
pip install -e packages/awp-core/
pip install -e "packages/awp-runtime/[data]"

# OR install from PyPI
pip install awp-agents[data]
```

You need an LLM API key. Each notebook supports three providers:

| Provider | Setup | Cost |
|----------|-------|------|
| **Ollama** | Install from ollama.com, pull a model | Free (local) |
| **OpenRouter** | Set `OPENROUTER_API_KEY` env var | Pay-per-token |
| **Custom** | Any OpenAI-compatible endpoint | Varies |

## How to Use

1. Open a notebook in Jupyter Lab / VS Code / Colab
2. Set `PROVIDER` and your API key in the first code cell
3. Run cells top to bottom
4. Read the markdown cells — they explain what's happening and why

The notebooks are designed to be read **in order** (A0 → A4). Each one builds on concepts
from the previous level and explicitly calls out what's new.

## The Design Philosophy

AWP's autonomy spectrum is built on a simple principle:

> **More autonomy requires more guardrails.**

Each level unlocks a new capability but also demands a new safety mechanism:

```
Level    Capability added           Safety mechanism required
─────    ──────────────────         ──────────────────────────
A0       Static execution           Schema validation (R1-R32)
A1       Multi-agent collaboration   State sharing strategy
A2       Dynamic agent spawning      Mandatory budget limits
A3       Runtime tool creation       Safety envelope (namespaces, denied ops)
A4       Recursive delegation        Depth cap + mandatory observability
```

This is not accidental — it reflects the belief that **unguarded autonomy is not a feature,
it is a bug**. A system that can do anything but has no constraints on its behavior is not
more capable — it is less predictable. The autonomy spectrum gives you a graduated dial:
turn it up when you need more capability, but accept the corresponding safety obligations.

## Further Reading

- [`docs/compliance.md`](../../../docs/compliance.md) — Full autonomy level specification
- [`docs/orchestration.md`](../../../docs/orchestration.md) — DAG and delegation loop engines
- [`docs/ORCHESTRATION_ENGINES.md`](../../../docs/ORCHESTRATION_ENGINES.md) — Engine comparison
- [`docs/security.md`](../../../docs/security.md) — Safety envelope and budget enforcement
- [`examples/workflows/`](../../workflows/) — 18 complete workflow examples (A0–A4)
