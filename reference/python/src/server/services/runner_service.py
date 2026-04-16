"""Runner service — wraps AgentWorkflow and emits real-time events."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.event_bus import event_bus
from server.models import EventType, RunEvent

logger = logging.getLogger(__name__)

# Sequence counter per run (thread-safe)
_seq_counters: dict[str, int] = {}
_seq_lock = threading.Lock()


def _next_seq(run_id: str) -> int:
    """Return the next sequence number for a run_id (thread-safe)."""
    with _seq_lock:
        val = _seq_counters.get(run_id, 0) + 1
        _seq_counters[run_id] = val
        return val


def _make_event(
    run_id: str, event_type: EventType, data: dict[str, Any] | None = None
) -> RunEvent:
    return RunEvent(
        run_id=run_id,
        seq=_next_seq(run_id),
        type=event_type,
        data=data or {},
        timestamp=datetime.now(tz=timezone.utc),
    )


_FULL_DETAIL_RUNS = 3   # Show last N runs with full results in prompt
_MEDIUM_DETAIL_RUNS = 7  # Runs FULL+1..FULL+MEDIUM get a shorter result snippet
_MAX_RESULT_CHARS = 2000  # Full-detail result snippet size
_MEDIUM_RESULT_CHARS = 400  # Medium-detail result snippet size
_MAX_CONTEXT_CHARS = 40_000  # Emergency cap — fold to summaries if exceeded

# Jaccard threshold above which a prior run's task is considered a
# near-duplicate of the current one. When matched, its output files are
# surfaced in a REUSE CANDIDATES block at the top of the experiment
# context so the manager reads them instead of regenerating drafts from
# scratch. 0.45 chosen empirically: matches the common case where the
# current task differs only in a refinement directive (e.g. "add PDF")
# while still rejecting truly unrelated tasks.
_REUSE_SIMILARITY_THRESHOLD = 0.30

# File extensions that typically contain reusable draft/analysis content
# (as opposed to infrastructure metadata like budget_snapshot.json).
_REUSE_CONTENT_SUFFIXES = (".md", ".txt", ".tex", ".bib", ".csv", ".json")


def _task_similarity(a: str, b: str) -> float:
    """Similarity over meaningful word-tokens (length > 3, lowercased).

    Returns the max of Jaccard and overlap-coefficient (Szymkiewicz–
    Simpson). Overlap is chosen because the common reuse case is "prior
    task is a sub-goal of the current task (or vice versa)" — pure
    Jaccard punishes that asymmetry and misses genuine reuse candidates.
    Cheap, deterministic, no embeddings. Returns 0.0 on empty input.
    """
    def _tokens(s: str) -> set[str]:
        import re as _re
        return {t for t in _re.findall(r"[A-Za-zÄÖÜäöüß]+", s.lower()) if len(t) > 3}

    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    jaccard = inter / len(ta | tb)
    overlap = inter / min(len(ta), len(tb))
    return max(jaccard, overlap)


def _pick_reusable_artifacts(output_dir: str, limit: int = 12) -> list[str]:
    """Return relative paths of files under *output_dir* likely to contain
    reusable content (draft text, analyses, bibliographies).
    """
    p = Path(output_dir)
    if not p.is_dir():
        return []
    candidates: list[tuple[float, str]] = []
    for f in p.rglob("*"):
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.suffix.lower() not in _REUSE_CONTENT_SUFFIXES:
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size < 200:  # skip empty stubs
            continue
        # Score: larger text files and obvious draft names rank higher.
        score = float(size)
        name_lower = f.name.lower()
        for keyword in (
            "abstract", "introduction", "methodology", "draft",
            "paper", "report", "summary", "analysis", "references",
            "bibliography", "conclusion", "results",
        ):
            if keyword in name_lower:
                score *= 2.0
                break
        try:
            candidates.append((score, str(f.relative_to(p))))
        except ValueError:
            pass
    candidates.sort(reverse=True)
    return [rel for _, rel in candidates[:limit]]


def _list_output_artifacts(output_dir: str) -> list[str]:
    """List output artifact files from a prior run's output directory."""
    p = Path(output_dir)
    if not p.is_dir():
        return []
    artifacts: list[str] = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            try:
                rel = str(f.relative_to(p))
                size_kb = f.stat().st_size / 1024
                artifacts.append(f"{rel} ({size_kb:.1f} KB)")
            except (ValueError, OSError):
                pass
    return artifacts


def _build_experiment_context(
    session_id: str,
    current_task: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch session data from the store and build prompt context + state files.

    Runs synchronously (called from a background thread) by creating a
    temporary event loop with a fresh DB connection to avoid sharing the
    async connection across threads.

    Returns (prompt_context_string, state_files_dict).
    """
    import asyncio

    from server.services.store import StoreService

    async def _fetch() -> tuple[dict | None, list, list, list]:
        store = StoreService()
        await store.init_db()
        try:
            session = await store.get_session(session_id)
            history = await store.get_session_history(session_id)
            memory = await store.get_memory_entries(session_id)
            runs = await store.get_session_runs(session_id)
            return session, history, memory, runs
        finally:
            await store.close()

    loop = asyncio.new_event_loop()
    try:
        session, history, memory, runs = loop.run_until_complete(_fetch())
    finally:
        loop.close()

    if not session:
        return "", {}

    # Build a run_id→run_data map for artifact lookup
    run_map: dict[str, dict[str, Any]] = {}
    for run in runs:
        run_map[run["run_id"]] = run

    # ── Approach 1: Build prompt context string ──────────────────────
    parts: list[str] = ["## Experiment Context\n"]

    # Reuse-candidate detection: if any prior run's task is
    # near-identical to the current task, surface its reusable output
    # files in a prominent block BEFORE the generic run history so the
    # manager treats them as the starting point for this run rather
    # than regenerating content from scratch. This closes the gap that
    # caused earlier runs to ignore already-produced drafts like
    # subtask_2_abstract.md from a previous attempt.
    if current_task:
        reuse_blocks: list[str] = []
        for run in runs:
            rid = run.get("run_id", "")
            # run row exposes the submitted user task text directly.
            prior_task = run.get("task") or ""
            if not prior_task:
                continue
            sim = _task_similarity(current_task, prior_task)
            if sim < _REUSE_SIMILARITY_THRESHOLD:
                continue
            result_meta = run.get("result") or {}
            metadata = (
                result_meta.get("metadata", {})
                if isinstance(result_meta, dict)
                else {}
            )
            out_dir = metadata.get("output_dir", "")
            internal_rid = metadata.get("run_id", "")
            if out_dir and internal_rid:
                od = Path(out_dir)
                cand = od / "output" / internal_rid
                if cand.is_dir():
                    out_dir = str(cand)
                elif od.name == "output":
                    cand2 = od / internal_rid
                    if cand2.is_dir():
                        out_dir = str(cand2)
            reusable = _pick_reusable_artifacts(out_dir) if out_dir else []
            if not reusable:
                continue
            status = run.get("status", "")
            reuse_blocks.append(
                f"- Prior run `{rid}` (status: {status}, task similarity "
                f"{sim:.2f}) produced these reusable artifacts under "
                f"`{out_dir}`:"
            )
            for rel in reusable:
                reuse_blocks.append(f"    - {rel}")
        if reuse_blocks:
            parts.append("### 🔁 REUSE CANDIDATES (read these FIRST)\n")
            parts.append(
                "A prior run in this experiment has produced output files "
                "that are highly relevant to the current task. You MUST "
                "read them BEFORE delegating any work, and build upon them "
                "instead of regenerating from scratch. These files are also "
                "symlinked under `workspace/_experiment_context/prior_outputs/` "
                "for direct access by workers. When instructing workers, "
                "copy the absolute path into the instructions so the worker "
                "reads the existing draft via `file.read` or `code.execute`.\n"
            )
            parts.extend(reuse_blocks)
            parts.append("")

    parts.append(f"**Experiment:** {session.get('title', 'Untitled')}")
    if session.get("hypothesis"):
        parts.append(f"**Hypothesis:** {session['hypothesis']}")
    if session.get("description"):
        parts.append(f"**Description:** {session['description']}")
    parts.append("")

    # Group history into (task, result) pairs
    run_pairs: list[dict[str, Any]] = []
    i = 0
    while i < len(history) - 1:
        if history[i]["role"] == "user" and history[i + 1]["role"] == "assistant":
            rid = history[i].get("run_id", "")
            run_data = run_map.get(rid, {})
            # Extract output paths from run result metadata
            result_meta = run_data.get("result") or {}
            metadata = result_meta.get("metadata", {}) if isinstance(result_meta, dict) else {}
            output_dir = metadata.get("output_dir", "")
            workspace = metadata.get("workspace", "")
            internal_run_id = metadata.get("run_id", "")

            # Resolve output_dir to the run-specific subdirectory if it
            # points to the experiment base (legacy data before the fix).
            if output_dir and internal_run_id:
                od = Path(output_dir)
                candidate = od / "output" / internal_run_id
                if candidate.is_dir():
                    output_dir = str(candidate)
                elif od.name == "output":
                    candidate2 = od / internal_run_id
                    if candidate2.is_dir():
                        output_dir = str(candidate2)

            run_pairs.append({
                "task": history[i]["content"],
                "result": history[i + 1]["content"],
                "run_id": rid,
                "timestamp": history[i].get("timestamp", ""),
                "status": run_data.get("status", ""),
                "model": run_data.get("model", ""),
                "output_dir": output_dir,
                "workspace": workspace,
            })
            i += 2
        else:
            i += 1

    if run_pairs:
        total = len(run_pairs)
        parts.append(f"### Previous Run Results ({total} total, most recent first)\n")

        # Phase 4.1: three-tier detail so the prompt stays bounded for long
        # histories. Full detail for the 3 most recent; medium (short result
        # snippet, no artifact listing) for the next 7; summary-only beyond.
        full_detail = list(reversed(run_pairs[-_FULL_DETAIL_RUNS:]))
        medium_start = max(0, total - _FULL_DETAIL_RUNS - _MEDIUM_DETAIL_RUNS)
        medium_end = total - _FULL_DETAIL_RUNS
        medium_detail = list(reversed(run_pairs[medium_start:medium_end]))
        older = list(reversed(run_pairs[:medium_start])) if medium_start > 0 else []

        for idx, pair in enumerate(full_detail):
            run_num = total - idx
            task_preview = pair["task"][:200]
            result_preview = pair["result"][:_MAX_RESULT_CHARS]
            if len(pair["result"]) > _MAX_RESULT_CHARS:
                result_preview += "\n... (truncated — full result in `_experiment_context/` files)"
            parts.append(f"#### Run {run_num} — \"{task_preview}\"")
            if pair.get("timestamp"):
                parts.append(f"*{pair['timestamp']}* | model: {pair.get('model', '?')} | status: {pair.get('status', '?')}")
            parts.append(f"\n**Result:**\n{result_preview}\n")

            # List output artifacts from this run
            if pair.get("output_dir"):
                artifacts = _list_output_artifacts(pair["output_dir"])
                if artifacts:
                    parts.append(f"**Output files** (`{pair['output_dir']}`):")
                    for a in artifacts[:20]:
                        parts.append(f"  - {a}")
                    if len(artifacts) > 20:
                        parts.append(f"  - ... and {len(artifacts) - 20} more files")
                    parts.append("")

        if medium_detail:
            parts.append("### Recent Runs (medium detail)\n")
            for idx, pair in enumerate(medium_detail):
                run_num = total - _FULL_DETAIL_RUNS - idx
                snippet = pair["result"][:_MEDIUM_RESULT_CHARS]
                if len(pair["result"]) > _MEDIUM_RESULT_CHARS:
                    snippet += "…"
                parts.append(
                    f"- Run {run_num}: \"{pair['task'][:120]}\" — "
                    f"{pair.get('status', '?')} — {snippet}"
                )

        if older:
            parts.append("\n### Earlier Runs (summary)\n")
            for idx, pair in enumerate(older):
                run_num = total - _FULL_DETAIL_RUNS - _MEDIUM_DETAIL_RUNS - idx
                parts.append(f"- Run {run_num}: \"{pair['task'][:80]}\" — {pair.get('status', '?')}")

    parts.append("")

    # Memory entries
    if memory:
        parts.append("### Experiment Memory\n")
        for entry in memory:
            parts.append(f"- [{entry['type']}] {entry['content'][:300]}")
        parts.append("")

    # Instructions for the manager
    parts.append("### Instructions for Continuing This Experiment\n")
    parts.append(
        "You are continuing an existing experiment. Use the previous results to:\n"
        "- **Build upon successful findings** — do not repeat work that has already been done\n"
        "- **Reference and reuse prior output files** — CSV tables, code, images from previous runs "
        "are available on disk (paths listed above). Read them via `code.execute` or `file.read`\n"
        "- **Refine or correct** earlier results if the current task asks for it\n"
        "- **Accumulate knowledge** across runs — each run should advance the experiment\n"
        "- Full previous results and structured run data are in `_experiment_context/` workspace files:\n"
        "  - `experiment_brief.md` — complete human-readable summary of all runs\n"
        "  - `run_NNN_summary.json` — per-run task, full result, and output file listings\n"
        "  - `memory.json` — accumulated findings from the experiment\n"
        "  - `experiment.json` — experiment metadata\n"
    )

    # List persisted dynamic tools from prior runs
    # Dynamic tools persist in workspace/dynamic_tools/ (or shared/dynamic_tools/
    # under the new per-run isolation layout) and are automatically loaded by the
    # DynamicToolFactory. Tell the manager about them.
    workspace_base = run_pairs[0].get("workspace", "") if run_pairs else ""

    # Resolve dynamic_tools directory: prefer shared/ (new layout), fall back
    # to workspace/ (legacy layout).
    dynamic_tools_dir: Path | None = None
    if workspace_base:
        ws_path = Path(workspace_base)
        # New layout: workspace is experiment_dir/runs/{run_id} →
        # experiment_dir = ws_path.parent.parent
        candidate_exp = ws_path.parent.parent
        shared_dt = candidate_exp / "shared" / "dynamic_tools"
        if shared_dt.is_dir():
            dynamic_tools_dir = shared_dt
        else:
            legacy_dt = ws_path / "workspace" / "dynamic_tools"
            if legacy_dt.is_dir():
                dynamic_tools_dir = legacy_dt

    if dynamic_tools_dir and dynamic_tools_dir.is_dir():
            tool_files = sorted(dynamic_tools_dir.glob("*.json"))
            if tool_files:
                parts.append("### Available Dynamic Tools from Previous Runs\n")
                parts.append(
                    "These tools were created in previous runs and are **automatically "
                    "available** to workers in the current run. Workers can call them "
                    "directly without recreating them.\n"
                )
                for tf in tool_files[:30]:
                    try:
                        tool_data = json.loads(tf.read_text(encoding="utf-8"))
                        fqn = tool_data.get("fqn", tf.stem)
                        desc = tool_data.get("description", "")[:120]
                        creator = tool_data.get("provenance", {}).get("creator_agent", "")
                        parts.append(f"- **`{fqn}`**: {desc}")
                        if creator:
                            parts.append(f"  (created by: {creator})")
                    except (json.JSONDecodeError, OSError):
                        parts.append(f"- `{tf.stem}`")
                parts.append("")

    # List persisted skills from the skill registry
    skills_dir: Path | None = None
    if workspace_base:
        ws_path = Path(workspace_base)
        candidate_exp = ws_path.parent.parent
        shared_sk = candidate_exp / "shared" / "skills"
        if shared_sk.is_dir():
            skills_dir = shared_sk
        else:
            legacy_sk = ws_path / "workspace" / "skills"
            if legacy_sk.is_dir():
                skills_dir = legacy_sk

    if skills_dir and skills_dir.is_dir():
            skill_files = sorted(skills_dir.glob("*.md"))
            if skill_files:
                parts.append("### Available Skills (from previous runs)\n")
                parts.append(
                    "These skills are persisted in `workspace/skills/` and automatically "
                    "loaded by name when referenced in a worker's `skills` array. The "
                    "manager can also update them by providing new content with the same heading.\n"
                )
                for sf in skill_files[:30]:
                    try:
                        content = sf.read_text(encoding="utf-8")
                        # Extract first non-empty line as description
                        desc = ""
                        for line in content.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                desc = line[:150]
                                break
                        parts.append(f"- **`{sf.stem}`**: {desc}" if desc else f"- **`{sf.stem}`**")
                    except OSError:
                        parts.append(f"- **`{sf.stem}`**")
                parts.append("")

    prompt_context = "\n".join(parts)

    # Phase 4.1 emergency cap: if the context somehow still exceeds the
    # budget (e.g. dozens of runs with large tasks), collapse to a
    # summary-only form. Manager can always consult _experiment_context/
    # files directly on disk for full detail.
    if len(prompt_context) > _MAX_CONTEXT_CHARS:
        logger.warning(
            "experiment_context %d chars exceeds cap %d — collapsing to summary",
            len(prompt_context), _MAX_CONTEXT_CHARS,
        )
        summary = [
            f"## Experiment: {session.get('title', '?')}",
            f"Hypothesis: {session.get('hypothesis') or '(none)'}",
            f"",
            f"### {len(run_pairs)} previous runs (collapsed — read "
            f"`_experiment_context/run_NNN_summary.json` for any specific run)",
        ]
        for idx, pair in enumerate(reversed(run_pairs)):
            run_num = len(run_pairs) - idx
            summary.append(
                f"- Run {run_num}: \"{pair['task'][:100]}\" — {pair.get('status', '?')}"
            )
        prompt_context = "\n".join(summary)

    # ── Approach 2: Build state files dict ───────────────────────────
    state_files: dict[str, Any] = {
        "experiment.json": {
            "id": session.get("id"),
            "title": session.get("title"),
            "hypothesis": session.get("hypothesis"),
            "description": session.get("description"),
            "tags": session.get("tags"),
            "created_at": session.get("created_at"),
        },
        "memory.json": memory,
        "runs": [],
    }

    # Build per-run summaries for file output (all runs, not truncated)
    for idx, pair in enumerate(run_pairs):
        run_summary: dict[str, Any] = {
            "run_number": idx + 1,
            "run_id": pair.get("run_id", ""),
            "task": pair["task"],
            "result": pair["result"],  # Full result, not truncated
            "model": pair.get("model", ""),
            "status": pair.get("status", ""),
            "timestamp": pair.get("timestamp", ""),
        }
        # Include output artifact listings
        if pair.get("output_dir"):
            run_summary["output_dir"] = pair["output_dir"]
            run_summary["output_files"] = _list_output_artifacts(pair["output_dir"])
        state_files["runs"].append(run_summary)

    # Build the markdown brief (complete, not truncated)
    brief_parts = [f"# Experiment: {session.get('title', 'Untitled')}\n"]
    if session.get("hypothesis"):
        brief_parts.append(f"**Hypothesis:** {session['hypothesis']}\n")
    if session.get("description"):
        brief_parts.append(f"**Description:** {session['description']}\n")
    brief_parts.append(f"## Runs ({len(run_pairs)} total)\n")
    for idx, pair in enumerate(run_pairs):
        brief_parts.append(f"### Run {idx + 1}: {pair['task'][:120]}")
        brief_parts.append(f"*Model: {pair.get('model', '?')} | Status: {pair.get('status', '?')}*\n")
        brief_parts.append(f"{pair['result']}\n")
        if pair.get("output_dir"):
            artifacts = _list_output_artifacts(pair["output_dir"])
            if artifacts:
                brief_parts.append("**Output files:**")
                for a in artifacts:
                    brief_parts.append(f"- `{a}`")
                brief_parts.append("")
    if memory:
        brief_parts.append("## Memory\n")
        for entry in memory:
            brief_parts.append(f"- [{entry['type']}] {entry['content']}\n")
    state_files["experiment_brief.md"] = "\n".join(brief_parts)

    return prompt_context, state_files


def _atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (tmp + replace).

    Used for files the UI / graph_builder may read concurrently. A reader
    that opens *path* either sees the previous full version or the new
    full version, never a half-written byte stream.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _write_experiment_state_files(
    workspace_dir: Path, state_files: dict[str, Any]
) -> None:
    """Write experiment state files to the workspace for worker access."""
    ctx_dir = workspace_dir / "workspace" / "_experiment_context"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    # experiment.json
    _atomic_write_text(
        ctx_dir / "experiment.json",
        json.dumps(state_files.get("experiment.json", {}), indent=2, default=str),
    )

    # memory.json
    _atomic_write_text(
        ctx_dir / "memory.json",
        json.dumps(state_files.get("memory.json", []), indent=2, default=str),
    )

    # Per-run summaries
    for run_data in state_files.get("runs", []):
        num = run_data.get("run_number", 0)
        fname = f"run_{num:03d}_summary.json"
        _atomic_write_text(
            ctx_dir / fname,
            json.dumps(run_data, indent=2, default=str),
        )

    # Markdown brief
    brief = state_files.get("experiment_brief.md", "")
    if brief:
        _atomic_write_text(ctx_dir / "experiment_brief.md", brief)

    # Symlink prior run output directories for easy worker access
    prior_outputs_dir = ctx_dir / "prior_outputs"
    prior_outputs_dir.mkdir(exist_ok=True)
    for run_data in state_files.get("runs", []):
        output_dir = run_data.get("output_dir", "")
        if output_dir and Path(output_dir).is_dir():
            num = run_data.get("run_number", 0)
            link_name = prior_outputs_dir / f"run_{num:03d}"
            if not link_name.exists():
                try:
                    link_name.symlink_to(Path(output_dir).resolve())
                except OSError:
                    # Symlinks may not be supported; copy a manifest instead
                    artifacts = _list_output_artifacts(output_dir)
                    if artifacts:
                        (prior_outputs_dir / f"run_{num:03d}_files.txt").write_text(
                            f"# Output files from run {num}\n"
                            f"# Directory: {output_dir}\n\n"
                            + "\n".join(artifacts),
                            encoding="utf-8",
                        )

    logger.info(
        "Wrote experiment context to %s (%d runs, %d memory entries)",
        ctx_dir,
        len(state_files.get("runs", [])),
        len(state_files.get("memory.json", [])),
    )


def _setup_run_isolation(
    workspace_dir: Path, experiment_dir: str | None, session_id: str | None = None
) -> None:
    """Set up per-run directory with symlinks to shared experiment state.

    Creates the ``shared/`` directory structure at the experiment level and
    symlinks ``dynamic_tools`` and ``skills`` from ``shared/`` into this
    run's ``workspace/`` so that tools and skills persist across runs while
    delegation loop state is fully isolated.

    On first call for a legacy experiment (flat ``workspace/`` + ``output/``
    at experiment root), migrates shared state and removes old run data.
    """
    import shutil

    if not experiment_dir:
        return

    exp = Path(experiment_dir)
    shared = exp / "shared"
    old_workspace = exp / "workspace"
    new_runs = exp / "runs"

    # --- Migration from old flat structure ---
    if old_workspace.exists() and not shared.exists():
        logger.info("Migrating experiment %s to per-run isolation", exp)
        shared.mkdir(parents=True, exist_ok=True)
        # Move dynamic_tools and skills to shared/
        for subdir in ("dynamic_tools", "skills"):
            old_dir = old_workspace / subdir
            new_dir = shared / subdir
            if old_dir.exists() and not new_dir.exists():
                try:
                    shutil.copytree(str(old_dir), str(new_dir))
                except Exception as exc:
                    logger.warning("Failed to migrate %s: %s", subdir, exc)
        # Move inputs to shared/
        old_inputs = exp / "inputs"
        if old_inputs.exists() and not (shared / "inputs").exists():
            try:
                shutil.copytree(str(old_inputs), str(shared / "inputs"))
            except Exception:
                pass
        # Move memory to shared/
        old_memory = exp / "memory"
        if old_memory.exists() and not (shared / "memory").exists():
            try:
                shutil.copytree(str(old_memory), str(shared / "memory"))
            except Exception:
                pass
        # Remove old workspace and output (runs will be recreated per-run)
        for old_dir in (old_workspace, exp / "output", exp / "logs"):
            if old_dir.exists():
                try:
                    shutil.rmtree(str(old_dir))
                except Exception as exc:
                    logger.warning("Failed to remove old %s: %s", old_dir.name, exc)
        # Delete old DB runs for this session
        if session_id:
            try:
                from server.services.store import StoreService

                async def _delete_old_runs():
                    store = StoreService()
                    await store.init_db()
                    try:
                        await store.delete_session_runs(session_id)
                    finally:
                        await store.close()

                import asyncio
                asyncio.run(_delete_old_runs())
            except Exception as exc:
                logger.warning("Failed to delete old DB runs: %s", exc)

    # --- Create shared directories (idempotent) ---
    # Phase 2.2: called on EVERY run-start, not only first. Safe because all
    # ops are idempotent (mkdir exist_ok, symlink repair below).
    for subdir in ("dynamic_tools", "skills", "memory", "inputs"):
        (shared / subdir).mkdir(parents=True, exist_ok=True)

    # --- Create workspace and symlink shared resources ---
    ws = workspace_dir / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    for subdir in ("dynamic_tools", "skills"):
        link = ws / subdir
        target = (shared / subdir).resolve()
        # Phase 2.3: symlink repair. Path.exists() returns False for a
        # dangling symlink, so the previous guard "if not link.exists()"
        # skipped broken links entirely — leaving runs with neither a
        # usable dir nor a usable link. Use lstat() to detect symlinks
        # regardless of target validity, then repair.
        try:
            st = link.lstat()
        except FileNotFoundError:
            st = None

        if st is None:
            # Nothing there — create fresh symlink
            try:
                link.symlink_to(target)
                continue
            except OSError:
                pass  # fall through to copytree fallback
        elif link.is_symlink():
            # Symlink exists — check target matches; if broken or wrong, replace
            try:
                current = link.resolve(strict=False)
                if current != target:
                    link.unlink()
                    link.symlink_to(target)
            except OSError:
                pass
            continue
        else:
            # Real dir already present (e.g. from older layout). Leave it.
            continue

        # Symlinks not supported — copy instead (one-time)
        import shutil as _sh
        try:
            _sh.copytree(str(target), str(link))
        except Exception:
            pass


class _RunDirWatcher:
    """Watches the delegation loop run directory for new files and emits events.

    The DelegationLoopRunner writes JSON files to disk as it progresses:
      - run_manifest.json (at start)
      - iterations/001/manager_decision.json
      - iterations/001/delegations/<worker>/envelope.json
      - iterations/001/delegations/<worker>/result.json
      - iterations/001/budget_snapshot.json
      - run_completion.json (at end)

    This watcher polls for new files and translates them into RunEvent objects.
    """

    def __init__(self, run_id: str, workspace_dir: Path) -> None:
        self._run_id = run_id
        self._workspace_dir = workspace_dir
        self._seen_files: set[str] = set()
        self._stop = threading.Event()
        self._pinned_run_dir: Path | None = None
        # Snapshot existing run directories at init time so _find_run_dir
        # can distinguish pre-existing dirs (from previous runs in the same
        # experiment) from the new directory created by the current run.
        runs_dir = self._workspace_dir / "workspace" / "runs"
        if runs_dir.exists():
            self._pre_existing_dirs = {
                d.name for d in runs_dir.iterdir() if d.is_dir()
            }
        else:
            self._pre_existing_dirs: set[str] = set()

    def stop(self) -> None:
        self._stop.set()

    def _find_run_dir(self) -> Path | None:
        """Locate the delegation loop run directory under workspace/runs/.

        Pins to the first NEW directory discovered (ignoring pre-existing
        dirs from previous runs) so that later sub-manager runs (which
        create sibling directories with newer timestamps) don't cause the
        watcher to jump away from the root run.  The root run directory
        contains the full recursive tree of sub-runs inside its
        ``iterations/*/delegations/*/runs/`` hierarchy.
        """
        if self._pinned_run_dir is not None:
            return self._pinned_run_dir if self._pinned_run_dir.exists() else None
        runs_dir = self._workspace_dir / "workspace" / "runs"
        if not runs_dir.exists():
            return None
        # Only consider directories that did NOT exist when the watcher
        # started.  This prevents pinning to a stale run directory from
        # a previous experiment run that shares the same workspace.
        candidates = sorted(
            [
                d
                for d in runs_dir.iterdir()
                if d.is_dir() and d.name not in self._pre_existing_dirs
            ],
            key=lambda d: d.name,
        )
        if candidates:
            # Pick the first new directory (the root run).  Sub-manager
            # dirs appear later (higher timestamps) and are also nested
            # inside the root run's iteration tree.
            self._pinned_run_dir = candidates[0]
            # Phase 5.1: expose a deterministic `canonical_run` symlink
            # at the output_dir level so graph_builder, UI live-poll and
            # anything else can read one fixed path instead of guessing
            # the inner timestamped directory.
            try:
                canon = self._workspace_dir / "canonical_run"
                if canon.is_symlink() or canon.exists():
                    try:
                        canon.unlink()
                    except OSError:
                        pass
                canon.symlink_to(self._pinned_run_dir.resolve())
            except OSError:
                pass
            return self._pinned_run_dir
        return None

    def _read_json(self, path: Path) -> dict[str, Any] | list[Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None

    @staticmethod
    def _parse_depth(parts: list[str]) -> tuple[int, str | None]:
        """Return (depth, parent_worker_id) from path parts.

        depth=0 for the root run, depth=1 for a sub-run inside a worker, etc.
        parent_worker_id is the worker directory name that owns the sub-run.
        """
        depth = 0
        parent_worker: str | None = None
        for i, p in enumerate(parts):
            if p == "runs" and i >= 2:
                depth += 1
                # The worker dir is 2 levels up: .../delegations/<worker>/runs/...
                if i >= 1:
                    parent_worker = parts[i - 1]
        return depth, parent_worker

    def _process_file(self, path: Path, rel: str) -> None:
        """Translate a newly-observed file into one or more events."""
        if rel in self._seen_files:
            return
        self._seen_files.add(rel)

        parts = rel.replace("\\", "/").split("/")
        depth, parent_worker_id = self._parse_depth(parts)

        # run_manifest.json -> run.start (or delegation.start for sub-runs)
        if parts[-1] == "run_manifest.json":
            data = self._read_json(path)
            if data:
                if depth == 0:
                    event_bus.emit_threadsafe(
                        self._run_id,
                        _make_event(self._run_id, EventType.RUN_START, data),
                    )
                else:
                    # Sub-run: emit as delegation.start so the frontend
                    # creates a sub-manager node linked to the parent worker
                    models = data.get("models", {})
                    event_bus.emit_threadsafe(
                        self._run_id,
                        _make_event(
                            self._run_id,
                            EventType.DELEGATION_START,
                            {
                                "parent_id": parent_worker_id,
                                "depth": depth,
                                "model": models.get("manager", "?"),
                                "models": models,
                                "task": data.get("task", ""),
                                **{k: v for k, v in data.items()
                                   if k not in ("models", "task")},
                            },
                        ),
                    )
            return

        # iterations/NNN/manager_decision.json -> iteration.start + iteration.decision
        elif "manager_decision.json" in rel:
            data = self._read_json(path)
            if data:
                # For sub-runs, find the iteration number from the correct
                # "iterations/NNN" segment (the last one in the path)
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                # Prefix iteration with parent worker for uniqueness in sub-runs
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                unique_iter = f"{iter_key}{iteration}"
                # Emit iteration.start for this iteration (if not already emitted)
                iter_start_key = f"_iter_start_{unique_iter}"
                if iter_start_key not in self._seen_files:
                    self._seen_files.add(iter_start_key)
                    event_bus.emit_threadsafe(
                        self._run_id,
                        _make_event(
                            self._run_id,
                            EventType.ITERATION_START,
                            {
                                "iteration": unique_iter,
                                "depth": depth,
                                "parent_id": parent_worker_id,
                            },
                        ),
                    )
                # Extract delegations info for richer detail
                delegations = data.get("delegations", [])
                delegation_summaries = []
                for d in delegations if isinstance(delegations, list) else []:
                    if isinstance(d, dict):
                        delegation_summaries.append({
                            "worker": d.get("worker_id", d.get("id", "?")),
                            "task": str(d.get("instructions", d.get("task", "")))[:200],
                            "tools": d.get("tools_allowed", []),
                        })
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.ITERATION_DECISION,
                        {
                            "iteration": unique_iter,
                            "depth": depth,
                            "parent_id": parent_worker_id,
                            "delegations": delegation_summaries,
                            **data,
                        },
                    ),
                )

        # iterations/NNN/budget_snapshot.json -> budget.update
        elif "budget_snapshot.json" in rel:
            data = self._read_json(path)
            if data:
                iteration = parts[1] if len(parts) >= 3 else "?"
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.BUDGET_UPDATE,
                        {"iteration": iteration, **data},
                    ),
                )

        # iterations/NNN/validation.json -> log (validation results)
        elif "validation.json" in rel:
            data = self._read_json(path)
            if data:
                iteration = parts[1] if len(parts) >= 3 else "?"
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.LOG,
                        {
                            "kind": "validation",
                            "iteration": iteration,
                            "message": f"Validation results for iteration {iteration}",
                            "validation": data,
                        },
                    ),
                )

        # delegations/<worker>/envelope.json -> worker.spawn
        elif rel.endswith("envelope.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                # Find the iteration number from the nearest iterations/NNN ancestor
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                unique_iter = f"{iter_key}{iteration}"
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.WORKER_SPAWN,
                        {
                            "worker_id": worker_id,
                            "iteration": unique_iter,
                            "depth": depth,
                            "parent_id": parent_worker_id,
                            "instructions": str(data.get("instructions", "")),
                            "tools_allowed": data.get("tools_allowed", []),
                            "skills": [
                                str(s)[:200] for s in data.get("skills", [])
                            ] if data.get("skills") else [],
                            "code_mode": data.get("tool_config", {}).get(
                                "code_mode", data.get("code_mode")
                            ),
                        },
                    ),
                )

        # delegations/<worker>/result.json -> worker.complete
        elif rel.endswith("result.json") and "delegations" in rel:
            data = self._read_json(path)
            if data:
                worker_id = path.parent.name
                iteration = "?"
                for i in range(len(parts) - 1, -1, -1):
                    if i > 0 and parts[i - 1] == "iterations":
                        iteration = parts[i]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                unique_iter = f"{iter_key}{iteration}"
                # Extract all findings
                findings = data.get("findings", data.get("result", data))
                tools_created = data.get("tools_created", [])
                worker_event_data: dict[str, Any] = {
                    "worker_id": worker_id,
                    "iteration": unique_iter,
                    "depth": depth,
                    "confidence": data.get("confidence"),
                    "error": data.get("error"),
                    "has_error": bool(data.get("error")),
                    "result": findings,
                    "tools_created": [
                        t if isinstance(t, str) else t.get("name", "?")
                        for t in tools_created
                    ] if isinstance(tools_created, list) else [],
                }
                # Include eval scores if present
                if data.get("_eval_score") is not None:
                    worker_event_data["eval_score"] = data["_eval_score"]
                    worker_event_data["eval_action"] = data.get("_eval_action", "")
                    worker_event_data["eval_metrics"] = data.get("_eval_metrics", [])
                # Include critique scores if present
                if data.get("_critique_score") is not None:
                    worker_event_data["critique_score"] = data["_critique_score"]
                    worker_event_data["critique_summary"] = data.get("_critique_summary", "")
                    worker_event_data["critique_defects"] = data.get("_critique_defects", [])
                    worker_event_data["critique_repairs"] = data.get("_critique_repairs", [])
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.WORKER_COMPLETE,
                        worker_event_data,
                    ),
                )

        # tool_calls.json -> tool.call (one per call). Two layouts exist:
        #   (a) delegations/<worker>/tool_calls.json
        #         -> path.parent.name = <worker>
        #   (b) artifacts/tools/<worker>_tool_calls.json
        #         -> path.parent.name = "tools", worker is in the file stem
        elif rel.endswith("tool_calls.json"):
            data = self._read_json(path)
            if isinstance(data, list):
                if path.parent.name == "tools":
                    # Layout (b): strip "_tool_calls" suffix from filename
                    worker_id = path.stem
                    if worker_id.endswith("_tool_calls"):
                        worker_id = worker_id[: -len("_tool_calls")]
                else:
                    # Layout (a)
                    worker_id = path.parent.name
                # Extract iteration number from path
                iteration = "?"
                for i_part in range(len(parts) - 1, -1, -1):
                    if i_part > 0 and parts[i_part - 1] == "iterations":
                        iteration = parts[i_part]
                        break
                iter_key = f"{parent_worker_id}_" if parent_worker_id else ""
                unique_iter = f"{iter_key}{iteration}"
                for i, tc in enumerate(data):
                    if isinstance(tc, dict):
                        result = tc.get("result", {})
                        result_data = result if isinstance(result, dict) else {"value": result}
                        event_bus.emit_threadsafe(
                            self._run_id,
                            _make_event(
                                self._run_id,
                                EventType.TOOL_CALL,
                                {
                                    "worker_id": worker_id,
                                    "iteration": unique_iter,
                                    "depth": depth,
                                    "call_index": i,
                                    "tool": tc.get("tool", "unknown"),
                                    "arguments": tc.get("arguments", tc.get("args", {})),
                                    "ok": result_data.get("ok", True) if isinstance(result_data, dict) else True,
                                    "output": str(result_data.get("output", result_data.get("stdout", "")))[:1000] if isinstance(result_data, dict) else str(result)[:1000],
                                    "error": str(result_data.get("error", result_data.get("stderr", "")))[:500] if isinstance(result_data, dict) else None,
                                },
                            ),
                        )

        # critique.json -> critique.result (per-iteration or per-worker)
        elif rel.endswith("critique.json"):
            data = self._read_json(path)
            if data:
                # Per-worker critique: delegations/<worker>/critique.json
                if "delegations" in rel:
                    worker_id = path.parent.name
                    event_bus.emit_threadsafe(
                        self._run_id,
                        _make_event(
                            self._run_id,
                            EventType.CRITIQUE_RESULT,
                            {
                                "worker_id": worker_id,
                                "depth": depth,
                                "score": data.get("score"),
                                "summary": data.get("summary", ""),
                                "defect_count": len(data.get("defects", [])),
                                "critical_count": data.get("critical_count", 0),
                                "effort": data.get("effort_estimate", ""),
                                "prescriptions": data.get("prescriptions", [])[:3],
                            },
                        ),
                    )
                else:
                    # Iteration-level critique summary
                    critiques = data.get("critiques", [])
                    summary = data.get("summary", {})
                    repairs = summary.get("repair_history", [])
                    event_bus.emit_threadsafe(
                        self._run_id,
                        _make_event(
                            self._run_id,
                            EventType.CRITIQUE_RESULT,
                            {
                                "kind": "iteration_summary",
                                "depth": depth,
                                "worker_count": len(critiques),
                                "repair_count": len(repairs),
                                "pattern_count": len(summary.get("patterns", {})),
                            },
                        ),
                    )

        # rolling_summary.json -> log (confidence trend)
        elif rel.endswith("rolling_summary.json"):
            data = self._read_json(path)
            if data:
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(
                        self._run_id,
                        EventType.LOG,
                        {
                            "kind": "rolling_summary",
                            "message": f"Confidence trend: iteration {data.get('current_iteration', '?')}",
                            "confidence": data.get("confidence"),
                            "history": data.get("history", []),
                        },
                    ),
                )

        # run_completion.json -> run.complete
        elif rel == "run_completion.json":
            data = self._read_json(path)
            if data:
                event_bus.emit_threadsafe(
                    self._run_id,
                    _make_event(self._run_id, EventType.RUN_COMPLETE, data),
                )

    def watch(self) -> None:
        """Poll the run directory until stop() is called or completion is detected."""
        while not self._stop.is_set():
            run_dir = self._find_run_dir()
            if run_dir and run_dir.exists():
                self._scan_dir(run_dir)
                # If we see completion, do one final scan and stop
                if "run_completion.json" in self._seen_files:
                    self._scan_dir(run_dir)
                    break
            self._stop.wait(timeout=0.2)

    def _scan_dir(self, run_dir: Path) -> None:
        """Walk the run directory for JSON and markdown files.

        Files are sorted so that run_completion.json is always processed
        LAST — otherwise a bulk scan can emit 'run.complete' before
        iteration/worker events, causing WebSocket clients to disconnect
        before they receive the full event stream.
        """
        try:
            all_paths: list[tuple[str, Path]] = []
            for pattern in ("*.json", "*.md"):
                for path in run_dir.rglob(pattern):
                    try:
                        rel = str(path.relative_to(run_dir))
                    except ValueError:
                        continue
                    all_paths.append((rel, path))

            # Sort: run_manifest first, then iterations in order
            # (manager_decision → envelope → result → budget),
            # rolling_summary late, run_completion last.
            def _sort_key(item: tuple[str, Path]) -> tuple[int, str]:
                rel = item[0]
                if rel == "run_manifest.json":
                    return (0, rel)
                if rel == "run_completion.json":
                    return (99, rel)
                if "rolling_summary" in rel:
                    return (98, rel)
                # Within iterations: manager_decision → envelope → result →
                # tool_calls → validation → budget_snapshot
                basename = Path(rel).name
                file_order = {
                    "manager_decision.json": 0,
                    "envelope.json": 1,
                    "result.json": 3,
                    "tool_calls.json": 4,
                    "validation.json": 5,
                    "budget_snapshot.json": 6,
                }
                priority = file_order.get(basename, 2)
                return (1, f"{rel.split('/')[1] if '/' in rel else '000'}_{priority:02d}_{rel}")

            all_paths.sort(key=_sort_key)

            for rel, path in all_paths:
                self._process_file(path, rel)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Active runs registry (for stop support)
# ---------------------------------------------------------------------------

_active_runs: dict[str, dict[str, Any]] = {}
_active_lock = threading.Lock()


class RunnerService:
    """Orchestrates AgentWorkflow runs with event streaming."""

    def __init__(self) -> None:
        pass

    def start_run(
        self,
        run_id: str,
        config: dict[str, Any],
        session_id: str | None = None,
    ) -> str:
        """Launch an AgentWorkflow run in a background thread.

        Parameters
        ----------
        run_id : str
            Unique run identifier (pre-generated by the caller).
        config : dict
            WorkflowConfig fields (task, model, budget params, etc.).
        session_id : str, optional
            Session/experiment ID. When provided, previous run results
            and experiment memory are injected into the manager prompt.

        Returns
        -------
        str
            The run_id.
        """
        thread = threading.Thread(
            target=self._run_workflow,
            args=(run_id, config, session_id),
            daemon=True,
            name=f"awp-run-{run_id[:8]}",
        )
        # Track the output_dir so stop_run can drop a stop-sentinel inside it.
        # The runner threads observe this sentinel cooperatively (delegation
        # loop checks it once per iteration) and unwind through the normal
        # finalizer path — Python threads cannot be killed from outside, so
        # this cooperative protocol is the only correct mechanism here.
        out_dir = config.get("output_dir") or ""
        with _active_lock:
            _active_runs[run_id] = {
                "thread": thread,
                "stop": False,
                "output_dir": out_dir,
            }
        thread.start()
        return run_id

    def stop_run(self, run_id: str) -> bool:
        """Stop a run: cooperative sentinel + abort in-flight HTTP.

        Python threads cannot be killed from outside, so stopping is a
        two-pronged cooperative protocol:

        1. Drop a ``_stop_requested`` sentinel into the run's output_dir.
           The delegation-loop runner checks it at each iteration top and
           unwinds via the Fix-E finalizer path.
        2. Call ``LLMClient.close_all()`` to abort any in-flight HTTP
           request. Without this, a thread blocked on a slow LLM response
           would sit in ``socket.recv()`` until the OS times it out and
           the stop sentinel would not be observed for minutes.

        Returns True if the run was found in the active registry.
        """
        with _active_lock:
            info = _active_runs.get(run_id)
            if info is None:
                return False
            info["stop"] = True
            out_dir = info.get("output_dir") or ""
        if out_dir:
            try:
                sentinel = Path(out_dir) / "_stop_requested"
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(
                    f"{datetime.now(tz=timezone.utc).isoformat()}\nuser_stop\n",
                    encoding="utf-8",
                )
            except Exception:
                logger.warning(
                    "stop_run: failed to write stop sentinel for %s", run_id,
                    exc_info=True,
                )
        # Phase 3 (pragmatic): abort in-flight LLM HTTP calls so the worker
        # thread unsticks immediately and reaches the next iteration
        # boundary (where the sentinel check fires). This mirrors the
        # signal-watchdog pattern the runner uses internally for SIGTERM.
        #
        # Caveat: LLMClient.close_all() is process-wide — if other runs
        # are executing concurrently, their in-flight HTTP calls also get
        # aborted and will retry. Only fire it when this run is the only
        # active one, so concurrent runs are not disturbed.
        with _active_lock:
            active_count = sum(
                1 for i in _active_runs.values()
                if i.get("thread") and i["thread"].is_alive()
            )
        if active_count <= 1:
            try:
                from awp.runtime.llm import LLMClient
                aborted = LLMClient.close_all()
                if aborted:
                    logger.info(
                        "stop_run: aborted %d in-flight LLM client(s) for %s",
                        aborted, run_id,
                    )
            except Exception:
                logger.debug("stop_run: LLMClient.close_all failed", exc_info=True)
        else:
            logger.info(
                "stop_run: %d concurrent runs active — relying on sentinel only "
                "(LLM abort skipped to not disturb other runs)", active_count,
            )
        return True

    def is_running(self, run_id: str) -> bool:
        with _active_lock:
            info = _active_runs.get(run_id)
            if info is None:
                return False
            return info["thread"].is_alive()

    def _run_workflow(self, run_id: str, config: dict[str, Any], session_id: str | None = None) -> None:
        """Execute the workflow synchronously in a background thread."""
        from server.services.store import StoreService

        result: dict[str, Any] | None = None
        status = "failed"

        # Emit run.start (mask secrets and api_key to avoid leaking in logs)
        safe_config = dict(config)
        safe_config.pop("api_key", None)
        if "secrets" in safe_config:
            safe_config["secrets"] = {
                k: "***" for k in safe_config["secrets"]
            }
        event_bus.emit_threadsafe(
            run_id,
            _make_event(run_id, EventType.RUN_START, {"run_id": run_id, **safe_config}),
        )

        try:
            # Lazy import to avoid circular deps and allow running without AWP installed
            from awp.data.workflow import AgentWorkflow

            # Build AgentWorkflow kwargs from config
            wf_kwargs = self._config_to_workflow_kwargs(config)

            # Inject secrets as environment variables so LLMClient can find API keys
            _injected_env_keys: list[str] = []
            for key, value in wf_kwargs.get("secrets", {}).items():
                if key.endswith("_API_KEY") or key.endswith("_KEY"):
                    if key not in os.environ or not os.environ[key]:
                        os.environ[key] = value
                        _injected_env_keys.append(key)

            # If no explicit api_key, detect the correct key from
            # the model string using provider-routing rules:
            #   provider/model  → OpenRouter  (OPENROUTER_API_KEY)
            #   gpt-*, o1-*, o3 → OpenAI     (OPENAI_API_KEY)
            #   claude-*        → Anthropic   (ANTHROPIC_API_KEY)
            #   ollama/*        → local       (no key)
            if not wf_kwargs.get("api_key"):
                model = wf_kwargs.get("model", "")
                model_lower = model.lower().strip()
                secrets_dict = wf_kwargs.get("secrets", {})

                # Determine which key name this model needs
                import re
                if model_lower.startswith("ollama/") or model_lower.startswith("localhost"):
                    # Local Ollama – no key needed, set dummy to skip validation
                    wf_kwargs["api_key"] = "ollama-local"
                elif re.match(r"^(gpt-|o[0-9]|dall-e|text-|tts-|whisper)", model_lower):
                    # Direct OpenAI model
                    preferred_key = "OPENAI_API_KEY"
                    wf_kwargs["api_key"] = (
                        secrets_dict.get(preferred_key, "")
                        or os.environ.get(preferred_key, "")
                    )
                elif model_lower.startswith("claude-"):
                    # Direct Anthropic model
                    preferred_key = "ANTHROPIC_API_KEY"
                    wf_kwargs["api_key"] = (
                        secrets_dict.get(preferred_key, "")
                        or os.environ.get(preferred_key, "")
                    )
                else:
                    # provider/model format → OpenRouter
                    preferred_key = "OPENROUTER_API_KEY"
                    wf_kwargs["api_key"] = (
                        secrets_dict.get(preferred_key, "")
                        or os.environ.get(preferred_key, "")
                    )

                # Fallback: try any *_API_KEY from secrets
                if not wf_kwargs.get("api_key"):
                    for key, value in secrets_dict.items():
                        if key.endswith("_API_KEY") and value:
                            wf_kwargs["api_key"] = value
                            break

            # Validate that we actually have an API key before starting
            is_local = wf_kwargs.get("api_key") == "ollama-local"
            if not is_local and not wf_kwargs.get("api_key") and not os.environ.get("LLM_API_KEY"):
                raise ValueError(
                    "No API key configured. Add the required key "
                    "in the Settings panel (API Keys section) or set the "
                    "LLM_API_KEY environment variable."
                )

            # Create output_dir for watching
            output_dir = wf_kwargs.get("output_dir")
            if not output_dir:
                import tempfile

                tmp = tempfile.mkdtemp(prefix="awp_ui_run_")
                wf_kwargs["output_dir"] = tmp
                output_dir = tmp

            workspace_dir = Path(output_dir)

            # Set up per-run isolation with shared experiment state
            experiment_dir = config.get("_experiment_dir")
            _setup_run_isolation(workspace_dir, experiment_dir, session_id=session_id)

            # Inject experiment context from previous runs (if in a session)
            if session_id:
                try:
                    current_task = (
                        wf_kwargs.get("task")
                        or config.get("task")
                        or ""
                    )
                    ctx, files = _build_experiment_context(
                        session_id, current_task=current_task
                    )
                    if ctx:
                        wf_kwargs["experiment_context"] = ctx
                    if files:
                        _write_experiment_state_files(workspace_dir, files)
                except Exception as exc:
                    logger.warning("Failed to load experiment context: %s", exc)

            # Write early metadata so the graph endpoint can find the
            # workspace while the run is still in progress.
            try:
                from server.services.store import StoreService

                async def _write_early_meta():
                    store = StoreService()
                    await store.init_db()
                    try:
                        early = {"metadata": {"workspace": str(workspace_dir), "output_dir": str(output_dir)}}
                        await store.update_run(run_id, result=early)
                    finally:
                        await store.close()

                import asyncio
                asyncio.run(_write_early_meta())
            except Exception as exc:
                logger.debug("Failed to write early metadata: %s", exc)

            # Start the directory watcher
            watcher = _RunDirWatcher(run_id, workspace_dir)
            watcher_thread = threading.Thread(
                target=watcher.watch,
                daemon=True,
                name=f"awp-watcher-{run_id[:8]}",
            )
            watcher_thread.start()

            # Execute the workflow (blocking)
            wf = AgentWorkflow(**wf_kwargs)
            result = wf.run()

            # Do a final scan to catch any files the watcher missed, then stop
            run_dir = watcher._find_run_dir()
            if run_dir and run_dir.exists():
                watcher._scan_dir(run_dir)
            watcher.stop()
            watcher_thread.join(timeout=3)

            status = result.get("status", "complete")

            # Inject workspace path into result metadata for graph builder.
            # Use setdefault so we don't overwrite the run-specific output_dir
            # that AgentWorkflow already set (workspace/output/<run_id>).
            if result and isinstance(result, dict):
                metadata = result.setdefault("metadata", {})
                metadata.setdefault("workspace", str(workspace_dir))
                metadata.setdefault("output_dir", str(output_dir))
                # Store the specific run directory so the graph builder can
                # find the correct root run (not a sub-manager run that
                # happens to have a later timestamp in workspace/runs/).
                if run_dir and run_dir.exists():
                    metadata.setdefault("run_dir", str(run_dir))

            # Emit agent.complete with the result
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id,
                    EventType.AGENT_COMPLETE,
                    {
                        "agent_name": "Manager",
                        "node_id": "manager",
                        "result": result.get("result", result),
                        "confidence": result.get("result", {}).get("confidence")
                        if isinstance(result.get("result"), dict)
                        else None,
                    },
                ),
            )

        except ImportError as exc:
            logger.error(
                "AWP runtime not installed: %s. "
                "Install with: pip install -e packages/awp-runtime/",
                exc,
            )
            status = "failed"
            result = {"error": f"AWP runtime not available: {exc}"}
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id, EventType.ERROR, {"message": str(exc)}
                ),
            )

        except Exception as exc:
            logger.exception("Run %s failed with exception", run_id)
            status = "failed"
            result = {"error": str(exc)}
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id, EventType.ERROR, {"message": str(exc)}
                ),
            )

        finally:
            # Clean up injected environment variables
            for key in _injected_env_keys:
                os.environ.pop(key, None)

            # Fix H: canonicalize the status so the UI only ever sees
            # {complete, partial, failed, aborted}. If the inner runner
            # already stamped a terminal_status on the result, trust it.
            canon_reason = ""
            if isinstance(result, dict):
                dl = result.get("delegation_loop") if isinstance(
                    result.get("delegation_loop"), dict
                ) else None
                if dl and dl.get("_terminal_status"):
                    status = dl["_terminal_status"]
                    canon_reason = str(dl.get("_terminal_reason") or "")
                elif result.get("_terminal_status"):
                    status = result["_terminal_status"]
                    canon_reason = str(result.get("_terminal_reason") or "")
            _canon_map = {
                "error": "failed",
                "eval_fail": "failed",
                "fail": "failed",
                "partial_complete": "partial",
                "budget_exhausted": "partial",
                "stall_detected": "partial",
                "interrupted": "aborted",
                "unknown": "aborted",
            }
            status = _canon_map.get(status, status)
            if status not in ("complete", "partial", "failed", "aborted"):
                status = "partial"

            # Emit run.complete — guaranteed to fire on every exit path
            # (Fix E). Payload carries both the canonical status and the
            # diagnostic reason so clients can distinguish cap-forced
            # partials from abrupt aborts.
            event_bus.emit_threadsafe(
                run_id,
                _make_event(
                    run_id,
                    EventType.RUN_COMPLETE,
                    {
                        "status": status,
                        "reason": canon_reason
                        or ("process_exit_without_terminal_event"
                            if status == "aborted" else ""),
                        "result": result,
                    },
                ),
            )
            # Close the event bus channel for this run
            event_bus.close_run_threadsafe(run_id)

            # Persist result to DB (best-effort from background thread)
            try:
                import asyncio

                loop = event_bus._loop
                if loop and not loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._persist_result(run_id, status, result, session_id),
                        loop,
                    ).result(timeout=30)
            except Exception:
                logger.warning(
                    "Failed to persist result for run %s", run_id, exc_info=True
                )

            # Cleanup active runs
            with _active_lock:
                _active_runs.pop(run_id, None)
            with _seq_lock:
                _seq_counters.pop(run_id, None)

    @staticmethod
    async def _persist_result(
        run_id: str,
        status: str,
        result: dict[str, Any] | None,
        session_id: str | None = None,
    ) -> None:
        """Persist the final result to SQLite."""
        # Import lazily to avoid circular refs at module level
        from server.app import store

        # If the user already marked this run as 'stopped' via the stop endpoint,
        # do not overwrite that terminal status with the thread's natural exit
        # status — otherwise the sidebar would flip back to 'running'/'complete'
        # after a stop.
        try:
            existing = await store.get_run(run_id)
            existing_status = (
                existing.get("status") if isinstance(existing, dict) else getattr(existing, "status", None)
            )
            if existing_status == "stopped":
                await store.update_run(run_id, result=result)
                return
        except Exception:
            pass

        await store.update_run(
            run_id,
            status=status,
            result=result,
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
        )

        # Also update the parent session status so the sidebar reflects
        # the terminal state (complete / partial / failed / error).
        if session_id:
            try:
                await store.update_session(session_id, status=status)
            except Exception:
                pass

    @staticmethod
    def _config_to_workflow_kwargs(config: dict[str, Any]) -> dict[str, Any]:
        """Map a WorkflowConfig dict to AgentWorkflow constructor kwargs."""
        kwargs: dict[str, Any] = {}

        # Required
        kwargs["task"] = config["task"]
        kwargs["model"] = config["model"]

        # Optional string/none fields
        for key in ("api_key", "worker_model", "output_dir"):
            if config.get(key):
                kwargs[key] = config[key]

        # Budget ints
        for key in (
            "max_loops",
            "max_total_tokens",
            "max_wall_time",
            "max_tool_calls",
            "max_total_workers",
            "max_depth",
        ):
            if key in config:
                kwargs[key] = config[key]

        # Sandbox
        if "sandbox" in config:
            kwargs["sandbox"] = config["sandbox"]
        if config.get("packages"):
            kwargs["packages"] = config["packages"]

        # Tools
        if config.get("tools") is not None:
            kwargs["tools"] = config["tools"]
        if config.get("forbidden_tools") is not None:
            kwargs["forbidden_tools"] = config["forbidden_tools"]

        # Booleans
        for key in ("code_mode", "tool_creation", "verbose", "trace_enabled"):
            if key in config:
                kwargs[key] = config[key]

        # Manager Intelligence features — only pass if AgentWorkflow supports them
        # Always inject defaults for MI keys not present in config
        _mi_defaults = {
            "critique_enabled": True,
            "critique_max_repair_attempts": 2,
            "planning_enabled": True,
            "planning_max_subtasks": 10,
            "diagnosis_enabled": True,
            "diagnosis_max_hypotheses": 3,
            "diagnosis_confidence_threshold": 0.3,
            "strategy_switching_enabled": True,
            "budget_reservation_enabled": True,
            "decision_journal_enabled": True,
            "decision_journal_max_entries": 20,
        }
        for k, v in _mi_defaults.items():
            config.setdefault(k, v)
        _mi_keys = (
            "critique_enabled",
            "critique_max_repair_attempts",
            "planning_enabled",
            "planning_max_subtasks",
            "diagnosis_enabled",
            "diagnosis_max_hypotheses",
            "diagnosis_confidence_threshold",
            "strategy_switching_enabled",
            "budget_reservation_enabled",
            "decision_journal_enabled",
            "decision_journal_max_entries",
        )
        try:
            import inspect
            from awp.data.workflow import AgentWorkflow as _AW
            _sig = inspect.signature(_AW.__init__)
            _supported = set(_sig.parameters.keys())
            for key in _mi_keys:
                if key in config and key in _supported:
                    kwargs[key] = config[key]
        except Exception:
            pass  # AgentWorkflow doesn't support MI yet — skip gracefully

        # Dict/list fields
        if config.get("secrets"):
            kwargs["secrets"] = config["secrets"]
        # Skills: explicit list or scanned from skills_dir
        skills_list = list(config.get("skills") or [])
        skills_dir = config.get("skills_dir", "")
        if skills_dir:
            from pathlib import Path as _P

            sd = _P(skills_dir).expanduser().resolve()
            if sd.is_dir():
                for entry in sorted(sd.iterdir()):
                    if entry.name.startswith("."):
                        continue
                    if entry.is_file() and entry.suffix.lower() in (".md", ".zip", ".skill"):
                        skills_list.append(str(entry))
                    elif entry.is_dir() and (entry / "SKILL.md").exists():
                        skills_list.append(str(entry))
        if skills_list:
            kwargs["skills"] = skills_list

        # Inputs: merge dict inputs and file paths
        inputs: dict[str, Any] = dict(config.get("inputs", {}))
        for i, fpath in enumerate(config.get("input_files", [])):
            name = Path(fpath).stem or f"file_{i}"
            inputs[name] = fpath
        kwargs["inputs"] = inputs

        # Experiment context (injected by session-aware runs)
        if config.get("experiment_context"):
            kwargs["experiment_context"] = config["experiment_context"]

        # Raw runtime overrides (critique.defect_category_hard_cap, …).
        # Forwarded only if AgentWorkflow actually accepts the parameter —
        # older versions without extra_config simply ignore it.
        if config.get("extra_config"):
            try:
                import inspect as _ins
                from awp.data.workflow import AgentWorkflow as _AW2
                if "extra_config" in _ins.signature(_AW2.__init__).parameters:
                    kwargs["extra_config"] = config["extra_config"]
            except Exception:
                pass

        return kwargs


# Module-level singleton
runner_service = RunnerService()
