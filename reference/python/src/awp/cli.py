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
    from .runtime import WorkflowRunner

    runner = WorkflowRunner(args.path)
    print(f"Running workflow: {runner.name}")
    print(f"Task: {args.task}")
    print()

    result = runner.run(args.task)

    # Print results
    for key, value in result.items():
        if key.startswith("_") or key == "task":
            continue
        if isinstance(value, dict):
            print(f"--- {key} ---")
            print(json.dumps(value, indent=2, default=str))
            print()

    return 0


def _main() -> None:
    sys.exit(main())


if __name__ == "__main__":
    _main()
