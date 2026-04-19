# E2E Tests (Detail Runbook)

Authoritative E2E runbook. Referenced from `CLAUDE.md` §"E2E Tests"; read this when writing, running, or debugging an E2E. `CLAUDE.md` keeps the non-negotiable rules (definition, rubric, storage/DB registration, LLM-trace mandate); this file carries the operational detail.

## Pass Rubric (not a string match)

LLM outputs are variable by nature. A binary "output equals expected string" check turns every release into a flake hunt. Instead, an E2E run passes iff **all** of the following hold:

| Criterion | Check |
|---|---|
| **Terminal state** | Experiment reached state `complete` (not `failed`, not `running`, not `partial` unless explicitly expected) |
| **Artifacts present** | Output folder is populated with real, non-empty files matching the task's declared deliverables |
| **Budget respected** | Wall time, token count, and loop count stayed within the configured budgets (no runaway) |
| **Graph integrity** | Experiment graph renders in the UI, manager/worker/tool nodes are consistent with the run log |
| **Rubric score** | Optional LLM-judge or deterministic scorer gives ≥ threshold on task-specific quality criteria (e.g. "did the synthesized report cover all required sections") |

Exact string matching is allowed **only** for deterministic subcomponents (tool outputs, computed values). For synthesized/generated content, use the rubric, not equality.

## Tags (MANDATORY)

Every E2E test **MUST** have one or more **tags**. Tags are passed to `run_e2e(tags=[...])` in `examples/e2e/_harness.py`. The `"e2e"` tag is added automatically; additional tags describe the test's focus areas.

| Tag | When to use |
|---|---|
| `e2e` | Always (auto-added by harness) |
| `s5` | S5-level features (delegation, tool creation, critique, etc.) |
| `tool-creation` | Test exercises dynamic tool factory |
| `critique` | Test exercises critique loop |
| `sub-manager` | Test exercises recursive delegation / sub-managers |
| `memory` | Test exercises cross-run memory persistence |
| `planning` | Test exercises manager planning features |
| `quick` | Lightweight smoke test (≤5 loops, ≤1M tokens) |

An E2E test without tags is not valid. Tags are machine-readable metadata for filtering, reporting, and regression tracking.

## Live Monitoring

Every E2E run is tracked live in the UI. The E2E harness:

1. **Registers** the experiment (session + run) in the SQLite DB **before** starting, with `status=running`.
2. **Streams events** (iterations, worker spawns/completions, tool calls, budget updates, critique results) to the DB in real time via `_E2ERunDirWatcher`.
3. **Finalizes** status to `complete | partial | failed` when done.

To watch an E2E test live while it runs:

```bash
# Terminal 1: start the UI server
python packages/awp-ui/start_debug.py --skip-build --no-reload

# Terminal 2: run the E2E test
python examples/e2e/deep_research_tree.py
```

The experiment appears immediately in the sidebar with a pulsing "running" indicator. Click it to see the graph build up, workers spawn, tool calls execute, and budget decrease — all in real time.

## LLM Trace — Debug Protocol

The LLM trace is mandatory (see `CLAUDE.md` §"E2E Tests"). This section is the operational walkthrough for **using** it during debugging.

When an E2E fails, partially completes, or produces a wrong output, diagnosis starts by reading the trace, not by re-running with more logging. The 5-Why-by-Layer protocol (`CLAUDE.md` §3) extends for E2E as follows:

1. Before hypothesizing about code, open the trace and locate the **first** manager/worker/gate interaction where the run diverges from the expected trajectory (wrong plan, malformed output, rejected completion, hallucinated tool call, drifted format).
2. Read the **full prompt that produced the bad response** — system + user + any injected state / gate feedback / repair nudges. Most E2E bugs are contract-enforcement bugs (missing field in the prompt, stale state section, gate feedback never surfaced) and are visible directly in the trace.
3. Read the **raw response** verbatim. Do not trust parsed / normalized fields alone — a format drift or partial JSON often shows up in the raw text but is hidden after parsing.
4. Attribute the failure to a structural origin using the trace evidence (which contract, which layer, which prompt section). "The model was bad" is never an acceptable root cause — the trace either shows the model violating a contract we should have enforced, or shows us feeding the model a prompt that made the bad output inevitable.
5. The fix lands at the layer identified in step 4 (prompt builder, gate, state compressor, contract enforcement), and the regression test asserts against the **trace content**, not only the final artifact.

A fix proposed without reading the trace is a symptom patch and is rejected.

## Framing

Treat the run output as a **loss function** and the code fix as **backpropagation**: if the run fails or the output diverges from expectation, locate the root cause in the code and fix it. Iterate until the loss is zero. Always make fixes **production-ready** — no patches, no shortcuts, no "works on my machine".

The guiding question for every E2E run: **"Would this system reach `complete` for an arbitrary task?"** If the answer is no, it is not shippable.
