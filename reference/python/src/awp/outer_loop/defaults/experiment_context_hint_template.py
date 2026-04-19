"""v0 default for the ``experiment_context_hint_template`` artifact.

This is the body of ``_build_experiment_context_hint(has_context=True)``.
The wrapper function prepends nothing and returns "" when the caller does
not have context — so the artifact only captures the positive-case body.
"""

from __future__ import annotations

CONTENT = (
    "\n## Experiment History (Previous Runs)\n\n"
    "This run is part of an ongoing experiment. Previous run results and output "
    "files are available for you to build upon.\n\n"
    "### Accessing Prior Results\n\n"
    "**Structured data** — the `_experiment_context/` directory in the workspace contains:\n"
    "- `experiment_brief.md` — complete human-readable summary of all previous work\n"
    "- `run_NNN_summary.json` — per-run task, full result, model, status, and "
    "output file listings\n"
    "- `memory.json` — accumulated findings, observations, and decisions\n"
    "- `experiment.json` — experiment metadata (title, hypothesis, description)\n\n"
    "**Output files from prior runs** — previous runs may have produced CSV tables, "
    "images, code files, and other artifacts. Their absolute paths are listed in the "
    "experiment context below and in each `run_NNN_summary.json` under `output_files`. "
    "Workers can read these files directly via `code.execute` (e.g. `pd.read_csv(path)`) "
    "or `file.read`.\n\n"
    "### Reusing Dynamic Tools from Prior Runs\n\n"
    "Dynamic tools created by workers in previous runs are **automatically persisted** "
    "in `workspace/dynamic_tools/` and loaded for the current run. Workers can call them "
    "directly — there is no need to recreate tools that already exist. The experiment "
    "context below lists all available dynamic tools with their descriptions.\n\n"
    "### Reusing Skills from Prior Runs\n\n"
    "Skills generated in prior runs are persisted in `workspace/skills/` and listed "
    "in the manager prompt. Reference them by name in a worker's `skills` array — the "
    "runtime loads the full content automatically. To update a skill, provide new "
    "markdown with the same `# Skill: Name` heading.\n\n"
    "### How to Use Prior Results\n\n"
    "- **Reuse tools**: Dynamic tools from previous runs are already registered — "
    "just use them, don't recreate\n"
    "- **Reuse data**: If a previous run produced a CSV, dataframe, or analysis result, "
    "load it directly instead of recomputing\n"
    "- **Reuse skills**: Provide relevant prior skills to workers for continuity\n"
    "- **Iterate**: Refine, extend, or correct prior outputs — each run should advance "
    "the experiment\n"
    "- **Avoid repetition**: Check what has already been done before spawning workers\n"
    "- **Reference**: When building on prior work, note which run you are extending\n"
)
