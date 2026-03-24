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

    # compliance
    p_comp = subparsers.add_parser("compliance", help="Check compliance level")
    p_comp.add_argument("path", help="Path to workflow directory")
    p_comp.add_argument("--level", default="L5", help="Target level (L0-L5)")

    # identity-card
    p_ic = subparsers.add_parser("identity-card", help="Generate Agent Identity Card")
    p_ic.add_argument("agent_path", help="Path to agent.awp.yaml")

    # run
    p_run = subparsers.add_parser("run", help="Run an AWP workflow (standalone runtime)")
    p_run.add_argument("path", help="Path to workflow directory")
    p_run.add_argument("--task", "-t", required=True, help="Task description")
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
    """Check compliance level."""
    from .parser import parse_manifest, parse_agent
    from .validator.compliance import check_compliance, ComplianceLevel

    wf_dir = Path(args.path)
    manifest = parse_manifest(wf_dir / "workflow.awp.yaml")

    agents = {}
    agents_dir = wf_dir / "agents"
    if agents_dir.exists():
        for agent_dir in sorted(agents_dir.iterdir()):
            awp_yaml = agent_dir / "agent.awp.yaml"
            if awp_yaml.exists():
                agents[agent_dir.name] = parse_agent(awp_yaml)

    level_map = {
        "L0": ComplianceLevel.L0_CORE,
        "L1": ComplianceLevel.L1_COMPOSABLE,
        "L2": ComplianceLevel.L2_COMMUNICATIVE,
        "L3": ComplianceLevel.L3_MEMORABLE,
        "L4": ComplianceLevel.L4_OBSERVABLE,
        "L5": ComplianceLevel.L5_ENTERPRISE,
    }
    target = level_map.get(args.level.upper(), ComplianceLevel.L5_ENTERPRISE)

    result = check_compliance(manifest, agents, wf_dir, target)

    print(f"Workflow: {manifest.workflow.name}")
    print(f"Target Level: {args.level}")
    print(f"Achieved Level: L{result.level}")
    print()

    for check, passed in result.checks.items():
        symbol = "[ok]" if passed else "[FAIL]"
        print(f"  {symbol} {check}")

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

    wf_dir = Path(args.path).resolve()
    debug = getattr(args, "debug", False)

    runner = WorkflowRunner(wf_dir)

    # -- Pre-run wizard ------------------------------------------------
    if sys.stdin.isatty():
        missing = runner.get_missing_secrets()
        if missing:
            _secrets_wizard(runner, missing, wf_dir)

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
    llm_model = os.getenv("LLM_MODEL", "(not set)")
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
                import yaml
                cfg = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
                model_name = cfg.get("model", {}).get("name", "(default)")
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

                    # Show output keys and sizes
                    for k, v in agent_result.items():
                        if k in ("confidence", "error"):
                            continue
                        if isinstance(v, list):
                            print(f"    Output:  {k} → {len(v)} items")
                        elif isinstance(v, dict):
                            print(f"    Output:  {k} → {len(v)} fields")
                        elif isinstance(v, str):
                            lines = v.count("\n") + 1
                            chars = len(v)
                            print(f"    Output:  {k} → {chars} chars ({lines} lines)")
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


def _main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    _main()
