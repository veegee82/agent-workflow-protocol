"""AWP CLI -- Command-line interface for AWP operations.

Usage:
    awp validate <path>
    awp pack <path> [-o <output>]
    awp unpack <file> [-o <output>]
    awp visualize <path> [--format mermaid|ascii]
    awp identity-card <agent-path>
    awp compliance <path> [--level L0|L1|L2|L3|L4|L5]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def main(argv: list[str] | None = None) -> int:
    """AWP CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="awp",
        description="Agent Workflow Protocol CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate an AWP workflow")
    p_validate.add_argument("path", help="Path to workflow directory")
    p_validate.add_argument("--level", default="L0", help="Compliance level (L0-L5)")

    # pack
    p_pack = subparsers.add_parser("pack", help="Pack workflow as .awp.zip")
    p_pack.add_argument("path", help="Path to workflow directory")
    p_pack.add_argument("-o", "--output", help="Output .awp.zip path")

    # unpack
    p_unpack = subparsers.add_parser("unpack", help="Unpack .awp.zip archive")
    p_unpack.add_argument("file", help="Path to .awp.zip file")
    p_unpack.add_argument("-o", "--output", help="Output directory")

    # visualize
    p_vis = subparsers.add_parser("visualize", help="Visualize workflow DAG")
    p_vis.add_argument("path", help="Path to workflow directory")
    p_vis.add_argument("--format", default="ascii", choices=["ascii", "mermaid"])

    # compliance (autonomy level)
    p_comp = subparsers.add_parser("compliance", help="Check autonomy level (A0-A4)")
    p_comp.add_argument("path", help="Path to workflow directory")
    p_comp.add_argument("--level", default="A4", help="Target autonomy level (A0-A4, legacy L0-L5 also accepted)")

    # identity-card
    p_ic = subparsers.add_parser("identity-card", help="Generate Agent Identity Card")
    p_ic.add_argument("agent_path", help="Path to agent.awp.yaml")

    # run
    p_run = subparsers.add_parser("run", help="Run an AWP workflow (standalone runtime)")
    p_run.add_argument("path", help="Path to workflow directory")
    p_run.add_argument("--task", "-t", required=True, help="Task description")
    p_run.add_argument("--model", "-m", help="LLM model to use (skips model wizard, sets LLM_MODEL)")
    p_run.add_argument("--manager-model", help="LLM model for the manager agent (delegation_loop engine)")
    p_run.add_argument("--worker-model", help="LLM model for worker agents (delegation_loop engine)")
    p_run.add_argument("--debug", "-d", action="store_true", help="Enable debug mode (verbose output)")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "validate":
            return cmd_validate(args)
        elif args.command == "pack":
            return cmd_pack(args)
        elif args.command == "unpack":
            return cmd_unpack(args)
        elif args.command == "visualize":
            return cmd_visualize(args)
        elif args.command == "compliance":
            return cmd_compliance(args)
        elif args.command == "identity-card":
            return cmd_identity_card(args)
        elif args.command == "run":
            return cmd_run(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate an AWP workflow."""
    from .parser import parse_manifest, parse_agent
    from .validator import validate_graph, validate_contracts, validate_rules

    wf_dir = Path(args.path)
    manifest_file = wf_dir / "workflow.awp.yaml"

    if not manifest_file.exists():
        print(f"Error: workflow.awp.yaml not found in {wf_dir}", file=sys.stderr)
        return 1

    manifest = parse_manifest(manifest_file)
    print(f"[ok] Manifest parsed: {manifest.workflow.name} v{manifest.workflow.version}")

    # Load agents
    agents = {}
    agents_dir = wf_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            awp_yaml = agent_dir / "agent.awp.yaml"
            if awp_yaml.exists():
                agents[agent_dir.name] = parse_agent(awp_yaml)
                print(f"[ok] Agent parsed: {agent_dir.name}")

    # Validate graph
    if manifest.orchestration:
        result = validate_graph(manifest.orchestration)
        if result.errors:
            for err in result.errors:
                print(f"[FAIL] {err}", file=sys.stderr)
        else:
            print("[ok] Graph valid")

    # Validate contracts
    result = validate_contracts(agents, manifest.orchestration)
    if result.errors:
        for err in result.errors:
            print(f"[FAIL] {err}", file=sys.stderr)
    else:
        print("[ok] Contracts valid")

    # Rules
    result = validate_rules(manifest, agents, wf_dir)
    if result.errors:
        for err in result.errors:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1
    else:
        print("[ok] Rules passed")

    print(f"\nValidation passed for {manifest.workflow.name}")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    """Pack workflow as .awp.zip."""
    from .packager import pack_workflow

    output = pack_workflow(args.path, args.output)
    print(f"[ok] Packed: {output}")
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    """Unpack .awp.zip archive."""
    from .packager import unpack_workflow

    output = unpack_workflow(args.file, args.output)
    print(f"[ok] Unpacked: {output}")
    return 0


def cmd_visualize(args: argparse.Namespace) -> int:
    """Visualize workflow DAG."""
    from .parser import parse_manifest
    from .visualizer import to_mermaid, to_ascii

    wf_dir = Path(args.path)
    manifest = parse_manifest(wf_dir / "workflow.awp.yaml")

    if not manifest.orchestration:
        print("No orchestration graph defined")
        return 1

    if args.format == "mermaid":
        print(to_mermaid(manifest.orchestration))
    else:
        print(to_ascii(manifest.orchestration))

    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    """Check autonomy level."""
    from .parser import parse_manifest, parse_agent
    from .validator.compliance import check_compliance, AutonomyLevel, LEVEL_ALIASES, LEVEL_NAMES

    wf_dir = Path(args.path)
    manifest = parse_manifest(wf_dir / "workflow.awp.yaml")

    agents = {}
    agents_dir = wf_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            awp_yaml = agent_dir / "agent.awp.yaml"
            if awp_yaml.exists():
                agents[agent_dir.name] = parse_agent(awp_yaml)

    target = LEVEL_ALIASES.get(args.level.upper(), AutonomyLevel.A4_SELF_ORGANIZING)

    result = check_compliance(manifest, agents, wf_dir, target)

    level_name = LEVEL_NAMES.get(result.level, "Unknown")
    target_name = LEVEL_NAMES.get(target, "Unknown")
    print(f"Workflow: {manifest.workflow.name}")
    print(f"Target:   A{int(target)} {target_name}")
    print(f"Achieved: A{int(result.level)} {level_name}")
    print()

    # Cross-cutting concerns
    if result.cross_cutting:
        print("  Cross-Cutting (all levels):")
        for check, passed in result.cross_cutting.items():
            symbol = "[ok]" if passed else "[WARN]"
            print(f"    {symbol} {check}")
        print()

    for check, passed in result.checks.items():
        symbol = "[ok]" if passed else "[FAIL]"
        print(f"  {symbol} {check}")

    if result.warnings:
        print()
        for warn in result.warnings:
            print(f"  [WARN] {warn}")

    if result.errors:
        print()
        for err in result.errors:
            print(f"  [FAIL] {err}")

    return 0 if result.level >= target else 1


def cmd_identity_card(args: argparse.Namespace) -> int:
    """Generate Agent Identity Card."""
    from .parser import parse_agent

    agent = parse_agent(args.agent_path)

    card = {
        "identity_card": {
            "id": agent.identity.id,
            "role": agent.identity.role,
            "version": agent.identity.version,
            "capabilities": [],
            "accepts": [
                {"type": "task", "format": "text"},
                {"type": "state", "fields": []},
            ],
            "produces": [],
            "constraints": {
                "max_tokens": agent.model.parameters.max_tokens,
                "idempotent": False,
                "deterministic": False,
            },
        }
    }

    # Capabilities from tools
    if agent.capabilities and hasattr(agent.capabilities, "tools") and agent.capabilities.tools.enabled:
        if agent.capabilities.tools.allowed:
            card["identity_card"]["capabilities"] = agent.capabilities.tools.allowed
        else:
            card["identity_card"]["capabilities"] = ["all_tools"]

    # Produces from output contract
    for name, field in agent.output.contract.items():
        if field.shareable:
            card["identity_card"]["produces"].append({
                "field": name,
                "type": field.type,
                "description": field.description,
            })

    # Vision
    if agent.vision.enabled:
        card["identity_card"]["accepts"].append({
            "type": "images",
            "formats": agent.vision.supported_formats,
        })

    print(yaml.dump(card, default_flow_style=False, allow_unicode=True))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run an AWP workflow using the standalone runtime."""
    import time as _time
    from .runtime import WorkflowRunner

    import os as _os

    wf_dir = Path(args.path).resolve()
    debug = getattr(args, "debug", False)

    # --model flag sets LLM_MODEL before anything else
    if getattr(args, "model", None):
        _os.environ["LLM_MODEL"] = args.model

    # Resolve manager/worker models
    manager_model = getattr(args, "manager_model", None)
    worker_model = getattr(args, "worker_model", None)

    runner = WorkflowRunner(wf_dir, manager_model=manager_model, worker_model=worker_model)

    # -- Pre-run wizard ------------------------------------------------
    if sys.stdin.isatty():
        # Model wizard: let user choose LLM model if not already set
        _model_wizard()

        missing = runner.get_missing_secrets()
        if missing:
            _secrets_wizard(runner, missing, wf_dir)

        # Limits wizard: choose which global budget limits apply
        _limits_wizard(runner)

        # Budget wizard for delegation loop workflows
        _budget_wizard(runner)

        # Ask about debug mode if not set via flag
        if not debug:
            try:
                ans = input("  Enable debug mode? (verbose output) [y/N]: ").strip()
                debug = ans.lower() in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                pass
    else:
        # Non-interactive: just check secrets
        missing = runner.get_missing_secrets()

    # -- Header --------------------------------------------------------
    _print_header(runner, wf_dir, args.task, debug)

    if debug:
        _print_debug_config(runner, wf_dir)

    # -- Execute -------------------------------------------------------
    if debug:
        result = _run_with_debug(runner, args.task, wf_dir)
    else:
        result = runner.run(args.task)

        # Print results (normal mode)
        for key, value in result.items():
            if key.startswith("_") or key == "task":
                continue
            if isinstance(value, dict):
                print(f"--- {key} ---")
                print(json.dumps(value, indent=2, default=str))
                print()

    return 0


# -- Debug mode --------------------------------------------------------


def _print_header(runner: "WorkflowRunner", wf_dir: Path, task: str, debug: bool) -> None:
    print()
    print(f"  Workflow:  {runner.name}")
    print(f"  Task:      {task}")
    print(f"  Path:      {wf_dir}")
    if debug:
        print(f"  Mode:      DEBUG (verbose)")
    print()


def _print_debug_config(runner: "WorkflowRunner", wf_dir: Path) -> None:
    """Print workflow configuration summary in debug mode."""
    import os

    print("=" * 60)
    print("  CONFIGURATION")
    print("=" * 60)

    # LLM settings
    llm_model = os.getenv("LLM_MODEL", "(not set — use run wizard or set LLM_MODEL)")
    llm_provider = os.getenv("LLM_PROVIDER", "(auto)")
    llm_fallback = os.getenv("LLM_PROVIDER_FALLBACK", "(none)")
    print(f"  LLM Model:     {llm_model}")
    print(f"  LLM Provider:  {llm_provider}")
    print(f"  Fallback:      {llm_fallback}")

    # Secrets status
    missing = runner.get_missing_secrets()
    tool_count = len(runner._tools.tool_names)
    print(f"  Tools:         {tool_count} registered")
    if missing:
        for tool, keys in missing.items():
            print(f"    {tool}: MISSING {', '.join(keys)}")
    else:
        print(f"    All secrets OK")

    # Files
    secrets_yaml = wf_dir / "secrets.yaml"
    env_file = wf_dir / ".env"
    memory_file = wf_dir / "workspace" / "MEMORY.md"
    print(f"  secrets.yaml:  {'exists' if secrets_yaml.exists() else 'not found'}")
    print(f"  .env:          {'exists' if env_file.exists() else 'not found'}")
    print(f"  MEMORY.md:     {'exists' if memory_file.exists() else 'not found'}")

    # Agents
    agents_dir = wf_dir / "agents"
    if agents_dir.exists():
        agents = sorted(d.name for d in agents_dir.iterdir() if d.is_dir())
        print(f"  Agents:        {len(agents)} ({', '.join(agents)})")

    print("=" * 60)
    print()


def _run_with_debug(runner: "WorkflowRunner", task: str, wf_dir: Path) -> dict:
    """Execute workflow with rich debug output per agent."""
    import time as _time
    from .runtime.agent import StandaloneAgent
    from .runtime.llm import LLMClient

    state: dict = {"task": task}
    runner._tools.validate_secrets()

    # Auto-inject
    if runner._manifest.state and hasattr(runner._manifest.state, "auto_inject"):
        for key, value in runner._manifest.state.auto_inject.items():
            state.setdefault(key, value)

    orch = runner._manifest.orchestration

    # Delegation loop engine: delegate to runner.run() which handles it
    if orch and getattr(orch, "engine", "dag") == "delegation_loop":
        return _run_delegation_loop_debug(runner, task, wf_dir, state)

    if not orch or not hasattr(orch, "graph") or not orch.graph:
        print("  [WARN] No orchestration graph — nothing to run.")
        return state

    levels = runner._topological_levels(orch)
    total_agents = sum(len(lv) for lv in levels)
    workflow_start = _time.time()

    print(f"  Execution plan: {total_agents} agents in {len(levels)} levels")
    print()

    completed = 0
    for level_idx, level in enumerate(levels):
        parallel = " (parallel)" if len(level) > 1 else ""
        print(f"  Level {level_idx}{parallel}")
        print(f"  {'─' * 56}")

        for agent_id in level:
            node = runner._get_node(orch, agent_id)
            if node and not node.enabled:
                print(f"  ⊘ {agent_id} — skipped (disabled)")
                continue

            agent_dir = wf_dir / "agents" / agent_id
            if not agent_dir.exists():
                print(f"  ✗ {agent_id} — agent directory not found: {agent_dir}")
                state[agent_id] = {"error": "Agent directory not found", "confidence": 0.0}
                continue

            # Read agent config for debug info
            agent_yaml = agent_dir / "agent.awp.yaml"
            model_name = "(default)"
            try:
                import os as _os
                import yaml
                cfg = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
                cfg_model = cfg.get("model", {}).get("name", "")
                if cfg_model:
                    model_name = cfg_model
                else:
                    model_name = _os.getenv("LLM_MODEL", "(not set)") + " (from env)"
            except Exception:
                pass

            print(f"  ▶ {agent_id}")
            print(f"    Model:   {model_name}")

            agent_start = _time.time()
            try:
                agent = StandaloneAgent(
                    agent_dir, wf_dir,
                    llm=runner._llm,
                    tool_registry=runner._tools,
                )
                result = agent.run(task, state)
                elapsed = _time.time() - agent_start
                state.update(result)
                completed += 1

                agent_result = result.get(agent_id, {})
                confidence = agent_result.get("confidence", "N/A")
                has_error = "error" in agent_result

                if has_error:
                    error_msg = agent_result["error"]
                    if len(error_msg) > 120:
                        error_msg = error_msg[:120] + "..."
                    print(f"    Status:  ERROR ({elapsed:.1f}s)")
                    print(f"    Error:   {error_msg}")
                else:
                    print(f"    Status:  OK ({elapsed:.1f}s, confidence: {confidence})")

                    # Show output keys and content (expanded in debug)
                    for k, v in agent_result.items():
                        if k in ("confidence", "error"):
                            continue
                        if isinstance(v, list):
                            print(f"    Output:  {k} → {len(v)} items")
                            for i, item in enumerate(v):
                                prefix = f"      [{i}] "
                                if isinstance(item, dict):
                                    print(f"{prefix}{json.dumps(item, indent=2, default=str, ensure_ascii=False)}")
                                else:
                                    item_str = str(item)
                                    if len(item_str) > 200:
                                        item_str = item_str[:200] + "..."
                                    print(f"{prefix}{item_str}")
                        elif isinstance(v, dict):
                            print(f"    Output:  {k} → {len(v)} fields")
                            for fk, fv in v.items():
                                fv_str = str(fv)
                                if len(fv_str) > 200:
                                    fv_str = fv_str[:200] + "..."
                                print(f"      {fk}: {fv_str}")
                        elif isinstance(v, str):
                            lines = v.count("\n") + 1
                            chars = len(v)
                            print(f"    Output:  {k} → {chars} chars ({lines} lines)")
                            for line in v.splitlines():
                                print(f"      {line}")
                        else:
                            print(f"    Output:  {k} → {v}")

                # Memory auto-write and show path
                runner._auto_write_memory(agent_id, agent_result)
                from datetime import datetime, timezone
                mem_file = wf_dir / "workspace" / "memory" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
                if mem_file.exists():
                    print(f"    Memory:  {mem_file}")

            except Exception as exc:
                elapsed = _time.time() - agent_start
                print(f"    Status:  EXCEPTION ({elapsed:.1f}s)")
                print(f"    Error:   {exc}")
                on_failure = node.on_failure if node else "continue"
                if on_failure == "abort":
                    raise
                state[agent_id] = {"error": str(exc), "confidence": 0.0}

            print()

    # -- Summary -------------------------------------------------------
    total_time = _time.time() - workflow_start
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Agents:    {completed}/{total_agents} completed")
    print(f"  Duration:  {total_time:.1f}s")

    # Show generated files
    generated_files = []
    workspace = wf_dir / "workspace"
    if workspace.exists():
        for f in sorted(workspace.rglob("*")):
            if f.is_file():
                generated_files.append(f)
    data_dir = wf_dir / "data"
    if data_dir.exists():
        for f in sorted(data_dir.rglob("*")):
            if f.is_file():
                generated_files.append(f)

    if generated_files:
        print(f"  Files:     {len(generated_files)} generated")
        for f in generated_files:
            size = f.stat().st_size
            if size < 1024:
                size_str = f"{size}B"
            else:
                size_str = f"{size / 1024:.1f}KB"
            print(f"    {f.relative_to(wf_dir)}  ({size_str})")

    # Observability files
    obs_dirs = ["data/traces", "data/metrics", "data/audit", "data/state"]
    obs_files = []
    for d in obs_dirs:
        obs_path = wf_dir / d
        if obs_path.exists():
            for f in sorted(obs_path.rglob("*")):
                if f.is_file():
                    obs_files.append(f)
    if obs_files:
        print(f"  Observability:")
        for f in obs_files:
            size = f.stat().st_size
            size_str = f"{size}B" if size < 1024 else f"{size / 1024:.1f}KB"
            print(f"    {f.relative_to(wf_dir)}  ({size_str})")

    # Per-agent confidence summary
    print()
    print("  Results:")
    for key, value in state.items():
        if key.startswith("_") or key == "task":
            continue
        if isinstance(value, dict):
            conf = value.get("confidence", "?")
            has_err = "error" in value
            status = "ERROR" if has_err else "OK"
            fields = [k for k in value if k not in ("confidence", "error")]
            print(f"    {key:20s}  {status:5s}  confidence={conf}  fields=[{', '.join(fields)}]")

    print("=" * 60)
    print()

    # Full JSON output
    print("  Full output (JSON):")
    print()
    for key, value in state.items():
        if key.startswith("_") or key == "task":
            continue
        if isinstance(value, dict):
            print(f"--- {key} ---")
            print(json.dumps(value, indent=2, default=str, ensure_ascii=False))
            print()

    return state


def _run_delegation_loop_debug(
    runner: "WorkflowRunner", task: str, wf_dir: Path, state: dict
) -> dict:
    """Execute delegation loop workflow with rich debug output.

    After execution, reads the workspace logs and displays detailed
    per-iteration, per-worker output including skills, tools, results,
    and confidence trends.
    """
    import time as _time

    orch = runner._manifest.orchestration
    dl = getattr(orch, "delegation_loop", None)

    print(f"  Engine:        delegation_loop")
    if dl:
        b = getattr(dl, "budget", None)
        if b:
            print(f"  Budget:        loops={b.max_loops}, workers={b.max_total_workers}, "
                  f"wall_time={b.max_wall_time}s, depth={b.max_depth}")
        print(f"  Manager:       {dl.manager}")
    print()
    print("  Running... (this may take a while)")
    print()

    workflow_start = _time.time()
    result = runner.run(task, state)
    total_time = _time.time() - workflow_start

    # -- Read workspace logs for detailed output ---------------------------
    workspace = wf_dir / "workspace"
    run_dirs = sorted(workspace.glob("runs/*")) if workspace.exists() else []
    latest_run = run_dirs[-1] if run_dirs else None

    if latest_run:
        _print_delegation_loop_details(latest_run, total_time)
    else:
        print("  [WARN] No workspace logs found.")

    # -- Final result JSON -------------------------------------------------
    dl_result = result.get("delegation_loop", {})
    print()
    print("  Full output (JSON):")
    print()
    for key, value in result.items():
        if key.startswith("_") or key == "task":
            continue
        if isinstance(value, dict):
            print(f"--- {key} ---")
            out = json.dumps(value, indent=2, default=str, ensure_ascii=False)
            if len(out) > 5000:
                print(out[:5000])
                print("...(truncated)")
            else:
                print(out)
            print()

    return result


def _print_delegation_loop_details(run_dir: Path, total_time: float) -> None:
    """Print detailed per-iteration debug output from workspace logs."""

    # -- Per-iteration details ---------------------------------------------
    iters_dir = run_dir / "iterations"
    if not iters_dir.exists():
        return

    iter_dirs = sorted(iters_dir.iterdir())
    confidence_trend: list[str] = []

    for iter_dir in iter_dirs:
        iter_num = iter_dir.name
        print(f"  {'─' * 56}")
        print(f"  Iteration {iter_num}")
        print(f"  {'─' * 56}")

        # Manager decision
        decision_file = iter_dir / "manager_decision.json"
        if decision_file.exists():
            try:
                decision = json.loads(decision_file.read_text(encoding="utf-8"))
                dec_type = decision.get("decision", "?")
                reasoning = decision.get("reasoning", decision.get("plan", ""))
                if isinstance(reasoning, str) and len(reasoning) > 200:
                    reasoning = reasoning[:200] + "..."
                print(f"    Decision:    {dec_type}")
                if reasoning:
                    print(f"    Reasoning:   {reasoning}")

                # Show delegations overview
                delegations = decision.get("delegations", decision.get("workers", []))
                if delegations:
                    print(f"    Workers:     {len(delegations)}")
                    for w in delegations:
                        wid = w.get("worker_id", w.get("id", "?"))
                        instr = w.get("instructions", "")[:80]
                        skills = w.get("skills", [])
                        tools = w.get("tools_allowed", [])
                        codemode = w.get("codemode", {})
                        print(f"      ▶ {wid}")
                        if instr:
                            print(f"        Task:    {instr}...")
                        if skills:
                            total_chars = sum(len(s) for s in skills if isinstance(s, str))
                            print(f"        Skills:  {len(skills)} injected ({total_chars} chars)")
                        if tools:
                            print(f"        Tools:   {', '.join(tools[:5])}")
                        if codemode.get("tool_creation"):
                            ns = codemode.get("tool_creation_namespace", "dynamic")
                            print(f"        CodeMode: tool_creation ({ns}.*)")
            except Exception:
                pass

        # Worker results
        deleg_dir = iter_dir / "delegations"
        if deleg_dir.exists():
            print()
            for worker_dir in sorted(deleg_dir.iterdir()):
                if not worker_dir.is_dir():
                    continue
                wid = worker_dir.name

                # Result
                result_file = worker_dir / "result.json"
                if result_file.exists():
                    try:
                        w_result = json.loads(result_file.read_text(encoding="utf-8"))
                        conf = w_result.get("confidence", "?")
                        has_error = "error" in w_result
                        status = "ERROR" if has_error else "OK"

                        result_keys = [k for k in w_result if k not in ("confidence", "error")]
                        print(f"    ← {wid}: {status} (confidence: {conf})")

                        if has_error:
                            err = str(w_result["error"])[:150]
                            print(f"        Error: {err}")
                        else:
                            # Show key output fields
                            for rk in result_keys[:5]:
                                val = w_result[rk]
                                if isinstance(val, str):
                                    display = val[:120] + "..." if len(val) > 120 else val
                                    display = display.replace("\n", " ")
                                    print(f"        {rk}: {display}")
                                elif isinstance(val, list):
                                    print(f"        {rk}: [{len(val)} items]")
                                elif isinstance(val, dict):
                                    print(f"        {rk}: {{{len(val)} fields}}")
                                else:
                                    print(f"        {rk}: {val}")
                    except Exception:
                        pass

                # Generated skills
                skills_dir = worker_dir / "generated_skills"
                if skills_dir.exists():
                    skill_files = list(skills_dir.glob("*.md"))
                    if skill_files:
                        for sf in skill_files:
                            content = sf.read_text(encoding="utf-8")
                            title = content.split("\n")[0].strip("# ").strip() if content else sf.name
                            print(f"        📖 Skill: {title} ({sf.stat().st_size}B)")

                # Generated tools
                tools_dir = worker_dir / "generated_tools"
                if tools_dir.exists():
                    tool_files = list(tools_dir.glob("*.json"))
                    if tool_files:
                        for tf in tool_files:
                            try:
                                tdata = json.loads(tf.read_text(encoding="utf-8"))
                                tname = tdata.get("name", tf.stem)
                                tdesc = tdata.get("description", "")[:60]
                                print(f"        🔧 Tool: {tname} — {tdesc}")
                            except Exception:
                                print(f"        🔧 Tool: {tf.name}")

        # Budget snapshot
        budget_file = iter_dir / "budget_snapshot.json"
        if budget_file.exists():
            try:
                bsnap = json.loads(budget_file.read_text(encoding="utf-8"))
                remaining = bsnap.get("budget_remaining_pct", "?")
                loops_used = bsnap.get("loops", {}).get("used", "?")
                workers_spawned = bsnap.get("workers", {}).get("spawned", "?")
                wall = bsnap.get("wall_time", {}).get("elapsed_s", "?")
                confidence_trend.append(f"Iter {iter_num}")
                print()
                print(f"    Budget:  {remaining}% remaining | "
                      f"loops: {loops_used} | workers: {workers_spawned} | "
                      f"wall: {wall}s")
            except Exception:
                pass

        # Validation
        val_file = iter_dir / "validation.json"
        if val_file.exists():
            try:
                vdata = json.loads(val_file.read_text(encoding="utf-8"))
                if isinstance(vdata, list) and vdata:
                    val_summary = []
                    for v in vdata:
                        fb = v.get("feedback", "ok")
                        if isinstance(fb, str) and len(fb) > 60:
                            fb = fb[:60] + "..."
                        val_summary.append(f"{v.get('worker_id', '?')}: {fb}")
                    print(f"    Valid.:  {'; '.join(val_summary)}")
            except Exception:
                pass

        print()

    # -- Summary -----------------------------------------------------------
    print("=" * 60)
    print("  DELEGATION LOOP SUMMARY")
    print("=" * 60)
    print(f"  Duration:    {total_time:.1f}s")

    # Read completion
    comp_file = run_dir / "run_completion.json"
    if comp_file.exists():
        try:
            comp = json.loads(comp_file.read_text(encoding="utf-8"))
            print(f"  Status:      {comp.get('status', '?')}")
            print(f"  Iterations:  {comp.get('total_iterations', '?')}")
            fb = comp.get("final_budget", {})
            print(f"  Workers:     {fb.get('workers', {}).get('spawned', '?')}"
                  f"/{fb.get('workers', {}).get('max', '?')}")
            print(f"  Budget:      {fb.get('budget_remaining_pct', '?')}% remaining")
        except Exception:
            pass

    # Confidence trend
    history_file = run_dir / "history" / "rolling_summary.json"
    if history_file.exists():
        try:
            hist = json.loads(history_file.read_text(encoding="utf-8"))
            entries = hist.get("history", [])
            if entries:
                trend = " → ".join(
                    f"{h.get('confidence', '?')}" for h in entries
                )
                print(f"  Confidence:  {trend}")
        except Exception:
            pass

    # Artifacts
    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists():
        skills = list((artifacts_dir / "skills").glob("*.md")) if (artifacts_dir / "skills").exists() else []
        tools = list((artifacts_dir / "tools").glob("*.json")) if (artifacts_dir / "tools").exists() else []
        if skills:
            print(f"  Skills:      {len(skills)} generated")
            for s in skills:
                content = s.read_text(encoding="utf-8")
                title = content.split("\n")[0].strip("# ").strip() if content else s.name
                print(f"    📖 {s.name}: {title}")
        if tools:
            print(f"  Tools:       {len(tools)} generated")
            for t in tools:
                try:
                    tdata = json.loads(t.read_text(encoding="utf-8"))
                    print(f"    🔧 {tdata.get('name', t.stem)}: {tdata.get('description', '')[:50]}")
                except Exception:
                    print(f"    🔧 {t.name}")

    # All generated files
    all_files = list(run_dir.rglob("*"))
    file_count = sum(1 for f in all_files if f.is_file())
    total_size = sum(f.stat().st_size for f in all_files if f.is_file())
    size_str = f"{total_size / 1024:.1f}KB" if total_size > 1024 else f"{total_size}B"
    print(f"  Files:       {file_count} ({size_str})")
    print(f"  Run dir:     {run_dir}")

    print("=" * 60)


_MODEL_CHOICES: list[tuple[str, str]] = [
    ("openrouter/anthropic/claude-sonnet-4", "Claude Sonnet 4 via OpenRouter"),
    ("openrouter/anthropic/claude-opus-4", "Claude Opus 4 via OpenRouter"),
    ("openrouter/google/gemini-2.5-pro", "Gemini 2.5 Pro via OpenRouter"),
    ("openrouter/deepseek/deepseek-r1", "DeepSeek R1 via OpenRouter"),
    ("ollama/llama3", "Llama 3 (lokal via Ollama)"),
]


def _model_wizard() -> None:
    """Interactive wizard to select the LLM model for this run.

    Sets the ``LLM_MODEL`` environment variable so that all agents
    resolve it at runtime. Skipped when ``LLM_MODEL`` is already set.
    """
    import os

    current = os.getenv("LLM_MODEL", "")
    if current:
        print(f"  LLM Model: {current} (from LLM_MODEL env)")
        print()
        return

    print("=" * 60)
    print("  LLM Model Selection")
    print("=" * 60)
    print("  No LLM_MODEL environment variable set.")
    print("  Choose a model for this run:\n")

    for idx, (model_id, label) in enumerate(_MODEL_CHOICES, 1):
        print(f"    {idx}) {model_id}")
        print(f"       {label}")
    print(f"    {len(_MODEL_CHOICES) + 1}) Custom model (enter manually)")
    print()

    try:
        choice = input(f"  Select [1-{len(_MODEL_CHOICES) + 1}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Skipping model selection — agents will fail without a model.\n")
        return

    if not choice:
        print("  No selection — agents will fail without a model.\n")
        return

    try:
        idx = int(choice)
    except ValueError:
        # Treat as custom model name
        os.environ["LLM_MODEL"] = choice
        print(f"  → Using model: {choice}\n")
        return

    if 1 <= idx <= len(_MODEL_CHOICES):
        model_id = _MODEL_CHOICES[idx - 1][0]
        os.environ["LLM_MODEL"] = model_id
        print(f"  → Using model: {model_id}\n")
    elif idx == len(_MODEL_CHOICES) + 1:
        try:
            custom = input("  Enter model name (e.g. openrouter/meta/llama-3-70b): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipping.\n")
            return
        if custom:
            os.environ["LLM_MODEL"] = custom
            print(f"  → Using model: {custom}\n")
        else:
            print("  No model entered.\n")
    else:
        print(f"  Invalid choice: {idx}\n")


def _secrets_wizard(
    runner: "WorkflowRunner",  # noqa: F821
    missing: dict[str, list[str]],
    workflow_dir: Path,
) -> None:
    """Interactive wizard to collect missing MCP tool secrets.

    Prompts the user for each missing secret key, injects them into
    the runner, and offers to save them to the project's secrets.yaml.
    """
    # Collect all unique missing keys
    all_keys: dict[str, list[str]] = {}  # key → list of tools needing it
    for tool, keys in missing.items():
        for key in keys:
            all_keys.setdefault(key, []).append(tool)

    print("=" * 60)
    print("  Missing secrets detected")
    print("=" * 60)
    for key, tools in all_keys.items():
        print(f"  {key}  (used by: {', '.join(tools)})")
    print()
    print("You can enter them now, or press Enter to skip (tools will")
    print("use free/unauthenticated fallbacks where available).")
    print()

    provided: dict[str, str] = {}

    for key, tools in all_keys.items():
        hint = _get_secret_hint(key)
        prompt = f"  {key}"
        if hint:
            prompt += f" ({hint})"
        prompt += ": "

        try:
            value = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipping remaining secrets.")
            break

        if value:
            provided[key] = value

    if provided:
        # Inject into the running tool registry
        runner.inject_secrets(provided)
        print()

        # Offer to save to secrets.yaml
        try:
            save = input("  Save to project secrets.yaml? [Y/n]: ").strip()
        except (EOFError, KeyboardInterrupt):
            save = "n"

        if save.lower() != "n":
            _save_secrets_yaml(workflow_dir, provided)
            print(f"  [ok] Saved {len(provided)} secret(s) to secrets.yaml")
        print()
    else:
        print("  No secrets provided — using fallbacks.\n")


def _get_secret_hint(key: str) -> str:
    """Return a helpful hint for known secret key names."""
    hints = {
        "SEARCH_API_KEY": "optional, DuckDuckGo works without key",
        "AUTH_TOKEN": "optional, for authenticated HTTP requests",
        "OPENROUTER_API_KEY": "get free at openrouter.ai/keys",
        "OPENAI_API_KEY": "from platform.openai.com",
        "GROQ_API_KEY": "get free at console.groq.com",
        "OLLAMA_API_KEY": "from ollama.com",
        "LLM_API_KEY": "universal LLM key override",
    }
    return hints.get(key, "")


def _save_secrets_yaml(workflow_dir: Path, secrets: dict[str, str]) -> None:
    """Save or update secrets in the project's secrets.yaml."""
    secrets_file = workflow_dir / "secrets.yaml"
    existing: dict[str, str] = {}

    # Load existing secrets if file exists
    if secrets_file.exists():
        try:
            data = yaml.safe_load(secrets_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "secrets" in data:
                existing = dict(data["secrets"])
        except Exception:
            pass

    # Merge new secrets
    existing.update(secrets)

    # Write back
    output = {"secrets": existing}
    secrets_file.write_text(
        "# AWP Secrets — Auto-generated by awp run wizard\n"
        "# NEVER commit this file to version control.\n\n"
        + yaml.dump(output, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Ensure secrets.yaml is in .gitignore
    gitignore = workflow_dir / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if "secrets.yaml" not in content:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\nsecrets.yaml\n")
    else:
        gitignore.write_text("secrets.yaml\n", encoding="utf-8")


def _limits_wizard(runner: "WorkflowRunner") -> None:
    """Interactive wizard to choose and configure global run budget limits.

    Applies to **any** workflow (DAG or delegation loop).  The user can
    toggle individual limits on/off and adjust their values.
    """
    from .models.orchestration import RunBudgetLimits

    orch = getattr(runner._manifest, "orchestration", None)
    if not orch:
        return

    # Create run_budget if it doesn't exist yet (user can still opt out)
    budget: RunBudgetLimits = getattr(orch, "run_budget", None) or RunBudgetLimits()

    # Limit metadata: (field, label, unit, description)
    ALL_LIMITS = [
        ("max_wall_time",    "Max Wall Time",   "s",   "total execution time"),
        ("max_total_tokens", "Max Tokens",      "",    "LLM token cap"),
        ("max_tool_calls",   "Max Tool Calls",  "",    "total tool invocations"),
        ("max_agent_runs",   "Max Agent Runs",  "",    "total agent executions"),
        ("max_cost_usd",     "Max Cost",        "USD", "estimated cost cap"),
    ]

    print()
    print("=" * 60)
    print("  Run Budget Limits")
    print("=" * 60)
    print()

    enabled = set(budget.enabled_limits)

    for idx, (field, label, unit, desc) in enumerate(ALL_LIMITS, 1):
        val = getattr(budget, field)
        active = field in enabled
        marker = "ON " if active else "OFF"
        unit_str = f" {unit}" if unit else ""
        print(f"  {idx}) [{marker}] {label:<18} {val:>10}{unit_str}    ({desc})")

    print()
    print("=" * 60)

    try:
        ans = input("\n  Toggle or adjust limits? Enter numbers (e.g. 1,3) or [N]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not ans or ans.lower() == "n":
        # Keep defaults — attach budget to orchestration
        orch.run_budget = budget
        print()
        return

    sections = {c.strip() for c in ans.replace(" ", ",").split(",") if c.strip()}

    changes: list[str] = []
    for idx, (field, label, unit, _desc) in enumerate(ALL_LIMITS, 1):
        if str(idx) not in sections:
            continue

        # Toggle on/off
        currently_on = field in enabled
        try:
            toggle = input(f"     {label} is {'ON' if currently_on else 'OFF'}. Toggle? [y/N]: ").strip()
        except (EOFError, KeyboardInterrupt):
            toggle = ""

        if toggle.lower() in ("y", "yes"):
            if currently_on:
                enabled.discard(field)
                changes.append(f"{label}: OFF")
                continue
            else:
                enabled.add(field)
                changes.append(f"{label}: ON")

        # If now enabled, let user adjust value
        if field in enabled:
            current = getattr(budget, field)
            try:
                new_val = input(f"     {label} [{current}]: ").strip()
                if new_val:
                    if isinstance(current, float):
                        setattr(budget, field, float(new_val))
                    else:
                        setattr(budget, field, int(new_val))
                    changes.append(f"{label}={new_val}")
            except (EOFError, KeyboardInterrupt, ValueError):
                pass

    budget.enabled_limits = sorted(enabled)
    orch.run_budget = budget

    if changes:
        print()
        print(f"  ✓ Updated: {', '.join(changes)}")
    print()


def _budget_wizard(runner: "WorkflowRunner") -> None:
    """Interactive wizard to review and adjust delegation loop settings.

    Only shown when the workflow uses engine=delegation_loop. Displays
    current settings and lets the user adjust budget, validation,
    stall detection, logging, and model configuration.
    """
    import os as _os

    orch = getattr(runner._manifest, "orchestration", None)
    if not orch or getattr(orch, "engine", "dag") != "delegation_loop":
        return

    dl = getattr(orch, "delegation_loop", None)
    if not dl:
        return

    budget = getattr(dl, "budget", None)
    if not budget:
        return

    model = _os.getenv("LLM_MODEL", "")
    is_free = ":free" in model.lower()

    # -- Display current settings ------------------------------------------

    print("=" * 60)
    print("  Delegation Loop Settings")
    print("=" * 60)

    # Budget
    print()
    print("  1) Budget")
    print(f"     Max Loops:       {budget.max_loops:>6}     (manager iterations)")
    print(f"     Max Workers:     {budget.max_total_workers:>6}     (total workers spawned)")
    print(f"     Max Wall Time:   {budget.max_wall_time:>5}s    (total execution time)")
    print(f"     Max Depth:       {budget.max_depth:>6}     (recursive delegation depth)")

    if is_free:
        est_time = budget.max_loops * 2 * 90
        print()
        print(f"     ⚠ Free model: ~{est_time // 60}min estimated")
        if budget.max_wall_time < est_time:
            print(f"     ⚡ Recommended wall time: {min(est_time + 300, 3600)}s")

    # Validation
    val_cfg = getattr(dl, "validation", None)
    if val_cfg:
        det = getattr(val_cfg, "deterministic", None)
        llm_val = getattr(val_cfg, "llm", None)
        print()
        print("  2) Validation")
        print(f"     Deterministic:   {'on' if (det and det.always) else 'off':>6}     (schema, confidence, budget checks)")
        if llm_val:
            print(f"     LLM Validation:  {'on' if llm_val.enabled else 'off':>6}     (semantic check — costs extra tokens)")
            if llm_val.enabled:
                print(f"     Skip above:      {llm_val.skip_when_confidence_above:>6}     (skip LLM validation when confident)")

    # Stall Detection
    stall_cfg = getattr(dl, "termination", None)
    if stall_cfg:
        print()
        print("  3) Stall Detection")
        print(f"     Enabled:         {'on' if stall_cfg.enabled else 'off':>6}     (auto-stop when no progress)")
        if stall_cfg.enabled:
            print(f"     Window:          {stall_cfg.window:>6}     (iterations to compare)")
            print(f"     Min Delta:       {stall_cfg.min_confidence_delta:>6}     (minimum confidence improvement)")

    # Logging
    log_cfg = getattr(dl, "logging", None)
    if log_cfg:
        print()
        print("  4) Logging")
        print(f"     Format:          {log_cfg.format:>6}     (dual=JSON+MD, json, md)")
        print(f"     Artifacts:       {'on' if log_cfg.persist_artifacts else 'off':>6}     (save generated skills & tools)")

    # Models
    mgr_model = runner._manager_model or _os.getenv("LLM_MODEL", "(not set)")
    wkr_model = runner._worker_model or mgr_model
    print()
    print("  5) Models")
    print(f"     Manager:         {mgr_model}")
    print(f"     Worker:          {wkr_model}")

    print()
    print("=" * 60)

    # -- Ask what to adjust ------------------------------------------------

    try:
        ans = input("\n  Adjust settings? Enter numbers (e.g. 1,5) or [N]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not ans or ans.lower() == "n":
        print()
        return

    sections = {c.strip() for c in ans.replace(" ", ",").split(",") if c.strip()}

    def _ask_int(prompt: str, current: int, recommended: int = 0) -> int:
        rec = f" (empfohlen: {recommended})" if recommended else ""
        try:
            val = input(f"     {prompt} [{current}]{rec}: ").strip()
            if val:
                return int(val)
        except (EOFError, KeyboardInterrupt, ValueError):
            pass
        return current

    def _ask_float(prompt: str, current: float) -> float:
        try:
            val = input(f"     {prompt} [{current}]: ").strip()
            if val:
                return float(val)
        except (EOFError, KeyboardInterrupt, ValueError):
            pass
        return current

    def _ask_bool(prompt: str, current: bool) -> bool:
        cur = "y" if current else "n"
        try:
            val = input(f"     {prompt} [{'Y/n' if current else 'y/N'}]: ").strip()
            if val:
                return val.lower() in ("y", "yes", "on", "true", "1")
        except (EOFError, KeyboardInterrupt):
            pass
        return current

    def _ask_str(prompt: str, current: str, options: list[str] | None = None) -> str:
        hint = f" ({'/'.join(options)})" if options else ""
        try:
            val = input(f"     {prompt}{hint} [{current}]: ").strip()
            if val:
                return val
        except (EOFError, KeyboardInterrupt):
            pass
        return current

    changes: list[str] = []

    # 1) Budget
    if "1" in sections:
        print("\n  -- Budget --")
        rec_wall = min(budget.max_loops * 2 * 90 + 300, 3600) if is_free else 0
        budget.max_loops = _ask_int("Max Loops", budget.max_loops)
        budget.max_total_workers = _ask_int("Max Workers", budget.max_total_workers)
        budget.max_wall_time = _ask_int("Max Wall Time (seconds)", budget.max_wall_time, rec_wall)
        budget.max_depth = _ask_int("Max Depth", budget.max_depth)
        changes.append(f"budget: loops={budget.max_loops}, workers={budget.max_total_workers}, "
                       f"wall_time={budget.max_wall_time}s")

    # 2) Validation
    if "2" in sections and val_cfg:
        print("\n  -- Validation --")
        llm_val = getattr(val_cfg, "llm", None)
        if llm_val:
            llm_val.enabled = _ask_bool("LLM Validation", llm_val.enabled)
            if llm_val.enabled:
                llm_val.skip_when_confidence_above = _ask_float(
                    "Skip LLM when confidence above", llm_val.skip_when_confidence_above
                )
            changes.append(f"validation: llm={'on' if llm_val.enabled else 'off'}")

    # 3) Stall Detection
    if "3" in sections and stall_cfg:
        print("\n  -- Stall Detection --")
        stall_cfg.enabled = _ask_bool("Enabled", stall_cfg.enabled)
        if stall_cfg.enabled:
            stall_cfg.window = _ask_int("Window (iterations)", stall_cfg.window)
            stall_cfg.min_confidence_delta = _ask_float("Min Delta", stall_cfg.min_confidence_delta)
        changes.append(f"stall: {'on' if stall_cfg.enabled else 'off'}")

    # 4) Logging
    if "4" in sections and log_cfg:
        print("\n  -- Logging --")
        log_cfg.format = _ask_str("Format", log_cfg.format, ["dual", "json", "md"])
        log_cfg.persist_artifacts = _ask_bool("Save artifacts (skills & tools)", log_cfg.persist_artifacts)
        changes.append(f"logging: {log_cfg.format}, artifacts={'on' if log_cfg.persist_artifacts else 'off'}")

    # 5) Models
    if "5" in sections:
        print("\n  -- Models --")
        print("     Available via --manager-model / --worker-model CLI flags.")
        print("     Or set here for this run:")
        new_mgr = _ask_str("Manager model", mgr_model)
        new_wkr = _ask_str("Worker model", wkr_model)
        if new_mgr != mgr_model:
            runner._manager_model = new_mgr
            changes.append(f"manager-model: {new_mgr}")
        if new_wkr != wkr_model:
            runner._worker_model = new_wkr
            changes.append(f"worker-model: {new_wkr}")

    # Summary
    if changes:
        print()
        print(f"  ✓ Updated: {', '.join(changes)}")
    print()


def _main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    _main()
