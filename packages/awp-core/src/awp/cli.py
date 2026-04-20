"""AWP CLI -- Command-line interface for AWP operations.

Usage:
    awp validate <path>
    awp pack <path> [-o <output>]
    awp unpack <file> [-o <output>]
    awp visualize <path> [--format mermaid|ascii]
    awp identity-card <agent-path>
    awp compliance <path> [--level L0|L1|L2|L3|L4|L5]
    awp studio [--port 8420] [--dev]
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime.runner import WorkflowRunner
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
    p_comp.add_argument(
        "--level",
        default="A4",
        help="Target autonomy level (A0-A4, legacy L0-L5 also accepted)",
    )

    # identity-card
    p_ic = subparsers.add_parser("identity-card", help="Generate Agent Identity Card")
    p_ic.add_argument("agent_path", help="Path to agent.awp.yaml")

    # studio (GUI)
    p_studio = subparsers.add_parser(
        "studio",
        help="Launch AWP Workflow Studio (browser UI)",
    )
    p_studio.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    p_studio.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Port number (default: 8420)",
    )
    p_studio.add_argument(
        "--dev",
        action="store_true",
        help="Development mode: enable auto-reload and Vite dev server",
    )
    p_studio.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open browser automatically",
    )
    p_studio.add_argument(
        "--auto-update",
        action="store_true",
        help="Accepted for backwards compatibility (auto-update is now the default)",
    )
    p_studio.add_argument(
        "--no-auto-update",
        action="store_true",
        help="Skip the PyPI upgrade at startup (default: auto-update on)",
    )

    # run
    p_run = subparsers.add_parser(
        "run", help="Run an AWP workflow (standalone runtime)"
    )
    p_run.add_argument("path", help="Path to workflow directory")
    p_run.add_argument("--task", "-t", required=True, help="Task description")
    p_run.add_argument(
        "--target",
        default=None,
        help="Attach this run to a task in the hierarchy (format: <experiment_id>:<task_id>)",
    )
    p_run.add_argument(
        "--model", "-m", help="LLM model to use (skips model wizard, sets LLM_MODEL)"
    )
    p_run.add_argument(
        "--manager-model",
        help="LLM model for the manager agent (delegation_loop engine)",
    )
    p_run.add_argument(
        "--worker-model", help="LLM model for worker agents (delegation_loop engine)"
    )
    p_run.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug mode (verbose output)"
    )
    p_run.add_argument(
        "--auto-update",
        action="store_true",
        help="Automatically upgrade awp-agents from PyPI at startup (default: off)",
    )
    p_run.add_argument(
        "--eval",
        action="store_true",
        help="Enable evaluation scoring (override YAML config)",
    )

    # eval (view evaluation artifacts)
    p_eval = subparsers.add_parser(
        "eval", help="View evaluation artifact for a workflow run"
    )
    p_eval.add_argument("path", help="Path to workflow directory")
    p_eval.add_argument(
        "--run-id", help="Run ID to view (default: latest)"
    )

    # optimize (outer loop, Phase A3 — TextGrad opt-in via --with-textgrad)
    p_opt = subparsers.add_parser(
        "optimize",
        help="Run a task suite and (optionally) apply TextGrad artifact updates",
    )
    p_opt.add_argument("suite", help="Path to a *.suite.yaml file")
    p_opt.add_argument(
        "--epochs",
        type=int,
        default=1,
        help="Number of epochs to run (A3: TextGrad proposes one update per epoch)",
    )
    p_opt.add_argument(
        "--output-dir",
        default=None,
        help="Where to place per-task workspaces (default: ~/.awp/outer_loop_runs/<suite>/)",
    )
    p_opt.add_argument(
        "--learning-rate",
        type=float,
        default=0.5,
        help="TextGrad learning rate (0..1). Halved on each regression rollback.",
    )
    p_opt.add_argument(
        "--with-textgrad",
        action="store_true",
        default=False,
        help="Enable TextGrad artifact optimisation between epochs (opt-in, A3).",
    )
    p_opt.add_argument(
        "--no-rollback",
        action="store_true",
        default=False,
        help="Disable automatic rollback when mean_loss regresses (A3).",
    )
    p_opt.add_argument(
        "--manager-model",
        default=None,
        help="Model to use for the TextGrad optimizer (default: $LLM_MODEL or openai/gpt-5-mini).",
    )
    p_opt.add_argument(
        "--db",
        default=None,
        help="Outer-loop SQLite DB path (default: $AWP_OUTER_LOOP_DB or ~/.awp/outer_loop.db)",
    )
    p_opt.add_argument(
        "--target",
        default=None,
        help="Attach optimization to a task: <experiment_id>:<task_id>. "
             "Sets --db and --output-dir from the task's hierarchy.",
    )

    # optimize-inspect (read-only view of past epochs or artifact versions)
    p_opt_inspect = subparsers.add_parser(
        "optimize-inspect",
        help="Inspect epochs for a suite OR the version history of an artifact",
    )
    p_opt_inspect.add_argument(
        "suite_id_or_name",
        nargs="?",
        default=None,
        help="Suite id (uuid) or name. If omitted, lists all suites.",
    )
    p_opt_inspect.add_argument(
        "--artifact",
        default=None,
        help="Artifact name — print its version history with unified diffs.",
    )
    p_opt_inspect.add_argument(
        "--db",
        default=None,
        help="Outer-loop SQLite DB path (default: $AWP_OUTER_LOOP_DB or ~/.awp/outer_loop.db)",
    )

    # refine (task-local iterative refinement — y-axis optimization)
    p_refine = subparsers.add_parser(
        "refine",
        help="Iteratively refine a completed run's deliverable (task-local SGD on y)",
    )
    p_refine.add_argument(
        "seed",
        nargs="?",
        default=None,
        help="Seed run directory (or use --target)",
    )
    p_refine.add_argument(
        "--target",
        default=None,
        help="Attach refinement to a task: <experiment_id>:<task_id>",
    )
    p_refine.add_argument(
        "--iterations",
        "-n",
        type=int,
        default=3,
        help="Max refinement iterations, clamped to [1, 10] (default: 3)",
    )
    p_refine.add_argument(
        "--model",
        default=None,
        help="Manager model override (default: inherit from seed run). "
             "Ignored when any --tier-* flag is given.",
    )
    p_refine.add_argument(
        "--worker-model",
        default=None,
        help="Worker model override (default: inherit from seed run). "
             "Ignored when any --tier-* flag is given.",
    )
    # Model tiering (spec 2026-04-20). Format: "manager:worker", either
    # side may be empty. Multiple flags may be combined; unspecified
    # tiers fall back to the seed's model per §7.
    p_refine.add_argument(
        "--tier-low",
        default=None,
        metavar="MANAGER:WORKER",
        help="Low tier model pair (early iterations). Format 'manager:worker'. "
             "Either side may be empty. Example: ':deepseek/deepseek-chat-v3.1'",
    )
    p_refine.add_argument(
        "--tier-mid",
        default=None,
        metavar="MANAGER:WORKER",
        help="Mid tier model pair. Format 'manager:worker'.",
    )
    p_refine.add_argument(
        "--tier-high",
        default=None,
        metavar="MANAGER:WORKER",
        help="High tier model pair (late iterations). Format 'manager:worker'.",
    )

    # optimize-rollback (manual rollback of an artifact's active version)
    p_opt_rollback = subparsers.add_parser(
        "optimize-rollback",
        help="Roll back an artifact to a prior version (outer loop, A3)",
    )
    p_opt_rollback.add_argument("artifact_name", help="Name of the artifact")
    p_opt_rollback.add_argument(
        "version",
        type=int,
        help="Version to roll back to (0 clears the DB active pointer)",
    )
    p_opt_rollback.add_argument(
        "--db",
        default=None,
        help="Outer-loop SQLite DB path (default: $AWP_OUTER_LOOP_DB or ~/.awp/outer_loop.db)",
    )

    # experiment
    p_exp = subparsers.add_parser("experiment", help="Manage experiments")
    exp_sub = p_exp.add_subparsers(dest="experiment_cmd", required=True)

    p_exp_create = exp_sub.add_parser("create", help="Create a new experiment")
    p_exp_create.add_argument("name")
    p_exp_create.add_argument("--goal", default="")

    exp_sub.add_parser("list", help="List experiments")

    p_exp_show = exp_sub.add_parser("show", help="Show experiment detail")
    p_exp_show.add_argument("experiment_id")

    p_exp_delete = exp_sub.add_parser("delete", help="Delete an experiment")
    p_exp_delete.add_argument("experiment_id")
    p_exp_delete.add_argument("--yes", action="store_true", help="skip confirmation")

    p_exp_purge = exp_sub.add_parser(
        "purge-legacy",
        help="Delete flat-layout (pre-hierarchy) experiment directories and orphan runs rows",
    )
    p_exp_purge.add_argument("--yes", action="store_true", help="skip confirmation")

    # task
    p_task = subparsers.add_parser("task", help="Manage tasks within an experiment")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)

    p_task_create = task_sub.add_parser("create", help="Create a task")
    p_task_create.add_argument("experiment_id")
    p_task_create.add_argument("prompt", help="user_prompt (seed) or user_feedback (continuation)")
    p_task_create.add_argument("--continuation", action="store_true")
    p_task_create.add_argument(
        "--from-task",
        action="append",
        default=[],
        help="source task_id (continuation only; may repeat)",
    )
    p_task_create.add_argument(
        "--primary",
        default=None,
        help="primary bundle path (defaults to BEST/ when --from-task given; continuation only)",
    )
    p_task_create.add_argument(
        "--reference",
        action="append",
        default=[],
        help="reference path under source task (may repeat; continuation only)",
    )

    p_task_list = task_sub.add_parser("list", help="List tasks in an experiment")
    p_task_list.add_argument("experiment_id")

    p_task_show = task_sub.add_parser("show", help="Show task detail")
    p_task_show.add_argument("task_key", help="<experiment_id>:<task_id>")

    p_task_delete = task_sub.add_parser("delete", help="Delete a task")
    p_task_delete.add_argument("task_key", help="<experiment_id>:<task_id>")
    p_task_delete.add_argument("--yes", action="store_true")

    p_task_set_best = task_sub.add_parser("set-best", help="Pick the best run of a task")
    p_task_set_best.add_argument("task_key", help="<experiment_id>:<task_id>")
    grp = p_task_set_best.add_mutually_exclusive_group(required=True)
    grp.add_argument("--run", dest="run_id", help="pin this run as BEST (user override)")
    grp.add_argument("--auto", action="store_true", help="clear override, reselect automatically")

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
        elif args.command == "studio":
            return cmd_studio(args)
        elif args.command == "run":
            return cmd_run(args)
        elif args.command == "eval":
            return cmd_eval(args)
        elif args.command == "optimize":
            return cmd_optimize(args)
        elif args.command == "optimize-inspect":
            return cmd_optimize_inspect(args)
        elif args.command == "optimize-rollback":
            return cmd_optimize_rollback(args)
        elif args.command == "refine":
            return cmd_refine(args)
        elif args.command == "experiment":
            from .experiment.cli_handlers import handle_experiment_command

            return handle_experiment_command(args)
        elif args.command == "task":
            from .experiment.cli_handlers import handle_task_command

            return handle_task_command(args)
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
    print(
        f"[ok] Manifest parsed: {manifest.workflow.name} v{manifest.workflow.version}"
    )

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
    from .validator.compliance import (
        check_compliance,
        AutonomyLevel,
        LEVEL_ALIASES,
        LEVEL_NAMES,
    )

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
    if (
        agent.capabilities
        and hasattr(agent.capabilities, "tools")
        and agent.capabilities.tools.enabled
    ):
        if agent.capabilities.tools.allowed:
            card["identity_card"]["capabilities"] = agent.capabilities.tools.allowed
        else:
            card["identity_card"]["capabilities"] = ["all_tools"]

    # Produces from output contract
    for name, field in agent.output.contract.items():
        if field.shareable:
            card["identity_card"]["produces"].append(
                {
                    "field": name,
                    "type": field.type,
                    "description": field.description,
                }
            )

    # Vision
    if agent.vision.enabled:
        card["identity_card"]["accepts"].append(
            {
                "type": "images",
                "formats": agent.vision.supported_formats,
            }
        )

    print(yaml.dump(card, default_flow_style=False, allow_unicode=True))
    return 0


def _auto_update_awp() -> None:
    """Upgrade awp-agents from PyPI (opt-in via --auto-update)."""
    import subprocess as _sp

    try:
        result = _sp.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "awp-agents"],
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        if "Successfully installed" in output:
            import re
            pkgs = re.findall(r"awp[_-]\S+", output)
            print(f"  Updated: {', '.join(pkgs) if pkgs else 'awp-agents'}")
        else:
            print("  Already up to date.")
    except Exception as exc:
        print(f"  Update check failed ({exc}), continuing with current version.")


def _check_for_update_hint() -> None:
    """Lightweight, non-blocking PyPI version check.

    Prints a one-line hint if a newer awp-agents is available on PyPI.
    Silently swallows any error (network offline, PyPI down, etc.).
    Timeout is capped at 3 seconds so startup is never delayed noticeably.
    """
    try:
        from importlib.metadata import version as _pkg_version
        import json as _json
        import urllib.request as _urlreq

        try:
            current = _pkg_version("awp-agents")
        except Exception:
            return  # not installed as awp-agents (e.g. dev checkout) — skip

        req = _urlreq.Request(
            "https://pypi.org/pypi/awp-agents/json",
            headers={"User-Agent": "awp-cli"},
        )
        with _urlreq.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        latest = data.get("info", {}).get("version")
        if not latest or latest == current:
            return

        # Only hint if latest is strictly newer (simple tuple compare on numeric parts).
        def _parse(v: str) -> tuple[int, ...]:
            parts = []
            for chunk in v.split("."):
                num = ""
                for ch in chunk:
                    if ch.isdigit():
                        num += ch
                    else:
                        break
                parts.append(int(num) if num else 0)
            return tuple(parts)

        try:
            if _parse(latest) <= _parse(current):
                return
        except Exception:
            return

        print(
            f"  A newer version of awp-agents is available ({latest}). "
            f"Run `pip install --upgrade awp-agents` to update."
        )
    except Exception:
        # Never let a version check break the CLI.
        return


def _kill_port_processes(port: int) -> None:
    """Kill any process listening on *port* (Linux/macOS)."""
    import os as _os
    import signal as _sig
    import subprocess as _sp

    try:
        result = _sp.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        pids = [p for p in result.stdout.strip().split() if p.isdigit()]
        for pid in pids:
            try:
                _os.kill(int(pid), _sig.SIGTERM)
            except ProcessLookupError:
                pass
        if pids:
            import time as _t

            _t.sleep(0.5)
            for pid in pids:
                try:
                    _os.kill(int(pid), _sig.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
    except FileNotFoundError:
        pass


def _flush_awp_modules() -> None:
    """Remove cached awp.* and server.* modules to guarantee fresh code on reload."""
    stale = [name for name in sys.modules if name.startswith("awp") or name.startswith("server")]
    for name in stale:
        del sys.modules[name]


def cmd_studio(args: argparse.Namespace) -> int:
    """Launch AWP Workflow Studio (browser-based UI)."""
    import socket

    # --- Pre-flight: auto-update from PyPI (default: on; skip with --no-auto-update or --dev) ---
    if not getattr(args, "dev", False) and not getattr(args, "no_auto_update", False):
        print("  Checking for updates...")
        _auto_update_awp()

    # --- Pre-flight: add awp-ui/server to path if running from source ---
    # When running `python -m awp studio` from a dev checkout, the awp-ui
    # server package may not be on sys.path.  Try known locations.
    _flush_awp_modules()  # clear stale modules before importing
    try:
        from server.app import create_app  # noqa: F401
    except ImportError:
        # Try to locate packages/awp-ui relative to the awp package or CWD
        _cli_file = Path(__file__).resolve()
        _candidates = [
            _cli_file.parent.parent.parent.parent / "awp-ui",       # packages/awp-core/src/awp → packages/awp-ui
            Path.cwd() / "packages" / "awp-ui",                     # repo root
            _cli_file.parent.parent.parent.parent.parent / "awp-ui",
        ]
        _found = False
        for _c in _candidates:
            if (_c / "server" / "app.py").exists():
                if str(_c) not in sys.path:
                    sys.path.insert(0, str(_c))
                # Force Python to re-discover 'server' from the new path
                # by clearing the namespace package from the module cache
                for _k in [k for k in sys.modules if k == "server" or k.startswith("server.")]:
                    del sys.modules[_k]
                # Also invalidate the import finder caches
                import importlib
                importlib.invalidate_caches()
                _found = True
                break
        if not _found:
            print(
                "Error: The AWP Studio server module could not be loaded.\n"
                "\n"
                "If you installed awp-core only, install the UI package:\n"
                "\n"
                "    pip install -e packages/awp-ui/\n"
                "\n"
                "Or install the all-in-one PyPI package:\n"
                "\n"
                "    pip install awp-agents\n",
                file=sys.stderr,
            )
            return 1
        # Re-try the import
        try:
            from server.app import create_app  # noqa: F401
        except ImportError as exc:
            print(f"Error: Could not import server.app: {exc}", file=sys.stderr)
            return 1

    # --- Pre-flight: check uvicorn is available ---
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is not installed.\n"
            "\n"
            "Install it with:\n"
            "\n"
            "    pip install 'uvicorn[standard]'\n",
            file=sys.stderr,
        )
        return 1

    import logging
    import subprocess
    import threading
    import webbrowser

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    host = args.host
    port = args.port
    url = f"http://{host}:{port}" if host != "0.0.0.0" else f"http://localhost:{port}"

    # --- Pre-flight: kill existing server on this port ---
    bind_addr = host if host != "0.0.0.0" else "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex((bind_addr, port)) == 0:
            print(f"  Port {port} in use — stopping existing server...")
            _kill_port_processes(port)
            import time as _t
            for _ in range(10):
                _t.sleep(0.3)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                    if s2.connect_ex((bind_addr, port)) != 0:
                        break
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s3:
                if s3.connect_ex((bind_addr, port)) == 0:
                    print(
                        f"Error: Could not free port {port}.\n"
                        f"Stop the process manually or use:\n"
                        f"    awp studio --port {port + 1}\n",
                        file=sys.stderr,
                    )
                    return 1
            print(f"  Port {port} freed.")

    # Resolve version dynamically
    try:
        from importlib.metadata import version as _pkg_version
        _version = _pkg_version("awp-agents")
    except Exception:
        _version = "dev"

    print(f"\n  AWP Workflow Studio v{_version}")
    print(f"  {'─' * 40}")
    print(f"  URL:   {url}")
    print(f"  Mode:  {'development' if args.dev else 'production'}")
    print(f"  {'─' * 40}")
    print(f"  Press Ctrl+C to stop\n")

    vite_proc: subprocess.Popen[bytes] | None = None

    if args.dev:
        # Start Vite dev server for hot-reload
        ui_pkg = Path(__file__).resolve().parent
        # Walk up to find packages/awp-ui/frontend
        for candidate in [
            ui_pkg.parent.parent.parent / "awp-ui" / "frontend",
            Path.cwd() / "packages" / "awp-ui" / "frontend",
        ]:
            if candidate.is_dir() and (candidate / "package.json").exists():
                print(f"  Starting Vite dev server in {candidate}")
                try:
                    vite_proc = subprocess.Popen(
                        ["npm", "run", "dev"],
                        cwd=str(candidate),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                except FileNotFoundError:
                    print(
                        "  Warning: npm not found; skipping Vite dev server.",
                        file=sys.stderr,
                    )
                break

    # Auto-open browser after a short delay
    if not args.no_open:

        def _open_browser() -> None:
            import time

            time.sleep(1.5)
            webbrowser.open(url)

        t = threading.Thread(target=_open_browser, daemon=True)
        t.start()

    # Flush cached modules so uvicorn loads the latest code
    _flush_awp_modules()

    # Build reload_dirs: watch awp-core/src, awp-runtime/src, and awp-ui/server.
    # Discover via editable install locations and known relative paths.
    reload_dirs: list[str] = []
    _cli_path = Path(__file__).resolve()
    # awp-core/src/awp/cli.py → packages/awp-core/src
    _core_src = _cli_path.parent.parent
    if (_core_src / "awp").is_dir():
        reload_dirs.append(str(_core_src))
    # packages/awp-runtime/src (sibling of awp-core)
    _runtime_src = _core_src.parent.parent / "awp-runtime" / "src"
    if (_runtime_src / "awp").is_dir():
        reload_dirs.append(str(_runtime_src))
    # server dir (already on sys.path from earlier)
    try:
        import server as _srv
        _srv_file = getattr(_srv, "__file__", None)
        if _srv_file:
            _srv_dir = str(Path(_srv_file).resolve().parent)
            if _srv_dir not in reload_dirs:
                reload_dirs.append(_srv_dir)
    except Exception:
        pass

    try:
        uvicorn.run(
            "server.app:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
            reload_dirs=reload_dirs or None,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n  Shutting down AWP Workflow Studio")
    finally:
        if vite_proc is not None:
            vite_proc.terminate()
            try:
                vite_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite_proc.kill()

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run an AWP workflow using the standalone runtime."""
    # --- Task target validation (--target <exp>:<task_id>) ---
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import validate_task_key_for_run

        rc = validate_task_key_for_run(args.target)
        if rc != 0:
            return rc

    # --- Dispatch to task-aware path if --target is set ---
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import run_task_aware

        return run_task_aware(args)

    # --- Pre-flight: auto-update from PyPI (opt-in) ---
    if getattr(args, "auto_update", False):
        print("  Checking for updates...")
        _auto_update_awp()
    else:
        _check_for_update_hint()

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

    runner = WorkflowRunner(
        wf_dir, manager_model=manager_model, worker_model=worker_model
    )

    # --eval flag: force-enable evaluation on the manifest
    if getattr(args, "eval", False):
        obs = getattr(runner._manifest, "observability", None)
        if obs:
            eval_cfg = getattr(obs, "evaluation", None)
            if eval_cfg:
                eval_cfg.enabled = True
            else:
                from .models.evaluation import EvaluationConfig

                obs.evaluation = EvaluationConfig(enabled=True)
        else:
            from .models.observability import ObservabilityConfig
            from .models.evaluation import EvaluationConfig

            runner._manifest.observability = ObservabilityConfig(
                evaluation=EvaluationConfig(enabled=True)
            )

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

        # Print evaluation summary if present
        eval_summary = result.get("_evaluation")
        if eval_summary:
            _print_eval_summary(eval_summary)

    return 0


def _print_eval_summary(eval_summary: dict) -> None:
    """Print a formatted evaluation summary."""
    print()
    print("=" * 50)
    score = eval_summary.get("final_score", 0.0)
    action = eval_summary.get("action", "")
    print(f"  Evaluation: {score:.2f} / 1.00  ({action})")
    print("-" * 50)
    for m in eval_summary.get("metrics", []):
        sym = "[ok]" if m["score"] >= 0.65 else "[WARN]" if m["score"] >= 0.4 else "[FAIL]"
        print(f"    {sym}  {m['name']:<20s} {m['score']:.2f}  (weight {m['weight']:.1f})")
    retries = eval_summary.get("retries_used", 0)
    if retries:
        print(f"  Retries used: {retries}")
    print("=" * 50)
    print()


def cmd_eval(args: argparse.Namespace) -> int:
    """View evaluation artifacts for a workflow run."""
    wf_dir = Path(args.path).resolve()
    eval_dir = wf_dir / "data" / "evaluation"

    if not eval_dir.exists():
        print(f"No evaluation artifacts found in {eval_dir}")
        return 1

    run_id = getattr(args, "run_id", None)
    if run_id:
        artifact_path = eval_dir / f"{run_id}.json"
    else:
        # Find latest artifact
        artifacts = sorted(eval_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not artifacts:
            print(f"No evaluation artifacts found in {eval_dir}")
            return 1
        artifact_path = artifacts[-1]

    if not artifact_path.exists():
        print(f"Artifact not found: {artifact_path}")
        return 1

    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    print(f"  Run ID:     {data.get('run_id', '?')}")
    print(f"  Artifact:   {artifact_path}")
    print()

    final_score = data.get("final_score")
    if final_score is not None:
        print(f"  Final Score: {final_score:.4f}")
        print(f"  Action:      {data.get('final_action', '?')}")
        print(f"  Retries:     {data.get('retries_used', 0)}")
    else:
        print("  No final score recorded.")

    # Print step records
    steps = data.get("step_records", [])
    if steps:
        print()
        print(f"  Step evaluations ({len(steps)}):")
        for step in steps:
            r = step.get("result", {})
            print(
                f"    [{step.get('hook', '?')}] "
                f"agent={step.get('agent_id', '?')} "
                f"score={r.get('score', 0):.4f} "
                f"action={r.get('action', '?')}"
            )

    # Print final metric breakdown
    final_result = data.get("final_result")
    if final_result and "metric_scores" in final_result:
        print()
        print("  Metric breakdown:")
        for ms in final_result["metric_scores"]:
            sym = "[ok]" if ms["score"] >= 0.65 else "[WARN]" if ms["score"] >= 0.4 else "[FAIL]"
            print(
                f"    {sym}  {ms['name']:<20s} {ms['score']:.4f}  "
                f"(weight={ms['weight']:.1f}, kind={ms['kind']})"
            )
            if ms.get("evidence"):
                print(f"         {ms['evidence'][:100]}")

    print()
    return 0


# -- Debug mode --------------------------------------------------------


def _print_header(runner: WorkflowRunner, wf_dir: Path, task: str, debug: bool) -> None:
    print()
    print(f"  Workflow:  {runner.name}")
    print(f"  Task:      {task}")
    print(f"  Path:      {wf_dir}")
    if debug:
        print("  Mode:      DEBUG (verbose)")
    print()


def _print_debug_config(runner: WorkflowRunner, wf_dir: Path) -> None:
    """Print workflow configuration summary in debug mode."""
    import os
    import yaml as _yaml

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
        print("    All secrets OK")

    # List all registered tool names
    print("  Tool names:")
    for tname in runner._tools.tool_names:
        print(f"    - {tname}")

    # Tool definitions (full schemas)
    all_defs = runner._tools.get_definitions()
    if all_defs:
        print(f"  Tool definitions ({len(all_defs)}):")
        for tdef in all_defs:
            func = tdef.get("function", tdef)
            fname = func.get("name", "?")
            fdesc = func.get("description", "")
            params = func.get("parameters", {})
            param_names = list(params.get("properties", {}).keys())
            required = params.get("required", [])
            print(f"    {fname}: {fdesc}")
            if param_names:
                for pn in param_names:
                    pdef = params["properties"][pn]
                    ptype = pdef.get("type", "any")
                    pdesc = pdef.get("description", "")
                    req_mark = " (REQUIRED)" if pn in required else ""
                    print(f"      - {pn} ({ptype}){req_mark}: {pdesc}")

    # Run budget
    orch = runner._manifest.orchestration
    if orch and orch.run_budget:
        rb = orch.run_budget
        print("  Run Budget:")
        print(f"    max_wall_time:    {rb.max_wall_time}s")
        print(f"    max_total_tokens: {rb.max_total_tokens:,}")
        print(f"    max_tool_calls:   {rb.max_tool_calls}")
        print(f"    max_agent_runs:   {rb.max_agent_runs}")
        print(f"    max_cost_usd:     ${rb.max_cost_usd}")
        print(f"    enabled_limits:   {', '.join(rb.enabled_limits)}")

    # Delegation loop config
    if (
        orch
        and getattr(orch, "engine", "dag") == "delegation_loop"
        and orch.delegation_loop
    ):
        dl = orch.delegation_loop
        print("  Delegation Loop:")
        print(f"    Manager:          {dl.manager}")
        if dl.models.manager:
            print(f"    Manager model:    {dl.models.manager}")
        if dl.models.worker:
            print(f"    Worker model:     {dl.models.worker}")
        b = dl.budget
        print("    Budget:")
        print(f"      max_loops:         {b.max_loops}")
        print(f"      max_total_workers: {b.max_total_workers}")
        print(f"      max_total_tokens:  {b.max_total_tokens:,}")
        print(f"      max_wall_time:     {b.max_wall_time}s")
        print(f"      max_tool_calls:    {b.max_tool_calls}")
        print(f"      max_depth:         {b.max_depth}")
        if dl.termination:
            print(
                f"    Stall detection:  window={dl.termination.window}, "
                f"min_delta={dl.termination.min_confidence_delta}, "
                f"action={dl.termination.action}"
            )
        print(
            f"    Validation:       deterministic={dl.validation.deterministic.always}, "
            f"llm={dl.validation.llm.enabled}"
        )
        print(
            f"    Logging:          format={dl.logging.format}, "
            f"artifacts={dl.logging.persist_artifacts}"
        )
        # Worker policy
        wp = dl.worker_policy
        print("    Worker policy:")
        print(f"      Forbidden tools:   {', '.join(wp.enforced.forbidden_tools)}")
        print(f"      Manager controls:  {', '.join(wp.manager_controlled)}")
        print(
            f"      Sandbox:           type={wp.enforced.sandbox.type}, "
            f"mem={wp.enforced.sandbox.max_memory_mb}MB, "
            f"cpu={wp.enforced.sandbox.max_cpu_seconds}s, "
            f"net={wp.enforced.sandbox.network}"
        )

    # Files
    secrets_yaml = wf_dir / "secrets.yaml"
    env_file = wf_dir / ".env"
    memory_file = wf_dir / "workspace" / "MEMORY.md"
    print(f"  secrets.yaml:  {'exists' if secrets_yaml.exists() else 'not found'}")
    print(f"  .env:          {'exists' if env_file.exists() else 'not found'}")
    print(f"  MEMORY.md:     {'exists' if memory_file.exists() else 'not found'}")

    # Skills (project-level)
    skills_dir = wf_dir / "skills"
    if skills_dir.exists():
        skill_names = []
        for sd in sorted(skills_dir.iterdir()):
            if sd.is_dir():
                sf = sd / "SKILL.md"
                if sf.exists():
                    skill_names.append(sd.name)
            elif sd.suffix in (".md", ".skill"):
                skill_names.append(sd.stem)
        if skill_names:
            print(f"  Project skills: {len(skill_names)} ({', '.join(skill_names)})")

    # Agents with full config
    agents_dir = wf_dir / "agents"
    if agents_dir.exists():
        agents = sorted(d.name for d in agents_dir.iterdir() if d.is_dir())
        print(f"  Agents:        {len(agents)} ({', '.join(agents)})")
        for agent_name in agents:
            agent_yaml = agents_dir / agent_name / "agent.awp.yaml"
            if agent_yaml.exists():
                try:
                    cfg = _yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
                    identity = cfg.get("identity", {})
                    model = cfg.get("model", {})
                    caps = cfg.get("capabilities", {})
                    cfg.get("prompt", {})

                    print(f"    [{agent_name}]")
                    if identity.get("role"):
                        print(f"      Role:         {identity['role']}")
                    if identity.get("description"):
                        desc = identity["description"]
                        print(f"      Description:  {desc}")
                    model_name = model.get("name", os.getenv("LLM_MODEL", "(default)"))
                    print(f"      Model:        {model_name}")
                    params = model.get("parameters", {})
                    if params:
                        print(
                            f"      Params:       temp={params.get('temperature', 'default')}, "
                            f"max_tokens={params.get('max_tokens', 'default')}"
                        )
                    tools_cfg = caps.get("tools", {})
                    if tools_cfg.get("enabled"):
                        allowed = tools_cfg.get("allowed", [])
                        max_calls = tools_cfg.get("max_calls", 10)
                        print(f"      Tools:        enabled (max_calls={max_calls})")
                        if allowed:
                            print(f"        Allowed:    {', '.join(allowed)}")
                        else:
                            print("        Allowed:    ALL")
                    else:
                        print("      Tools:        disabled")
                    # Agent-level skills
                    agent_skills_dir = agents_dir / agent_name / "workflow" / "skills"
                    if agent_skills_dir.exists():
                        ask = list(agent_skills_dir.rglob("*.md"))
                        if ask:
                            print(f"      Skills:       {len(ask)} agent-level")
                            for sf in ask:
                                print(f"        - {sf.name}")
                    # System prompt file
                    sys_prompt_file = (
                        agents_dir
                        / agent_name
                        / "workflow"
                        / "instructions"
                        / "SYSTEM_PROMPT.md"
                    )
                    if sys_prompt_file.exists():
                        sp_size = sys_prompt_file.stat().st_size
                        print(
                            f"      System prompt: {sys_prompt_file.name} ({sp_size}B)"
                        )
                    # Output schema
                    schema_file = (
                        agents_dir
                        / agent_name
                        / "workflow"
                        / "output_schema"
                        / "output_schema.json"
                    )
                    if schema_file.exists():
                        try:
                            schema = json.loads(schema_file.read_text(encoding="utf-8"))
                            fields = list(schema.get("properties", {}).keys())
                            print(f"      Output schema: {', '.join(fields)}")
                        except Exception:
                            print("      Output schema: (present)")
                except Exception:
                    pass

    print("=" * 60)
    print()


def _run_with_debug(runner: "WorkflowRunner", task: str, wf_dir: Path) -> dict:
    """Execute workflow with rich debug output per agent."""
    import time as _time
    from .runtime.agent import StandaloneAgent

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
                state[agent_id] = {
                    "error": "Agent directory not found",
                    "confidence": 0.0,
                }
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
                    agent_dir,
                    wf_dir,
                    llm=runner._llm,
                    tool_registry=runner._tools,
                )

                # ── DEBUG TRACE: INPUTS ─────────────────────────────
                print(f"    {'─' * 52}")
                print("    INPUT TRACE")
                print(f"    {'─' * 52}")

                # System prompt (instructions + skills + memory)
                try:
                    sys_prompt = agent._build_system_prompt()
                    sys_lines = sys_prompt.count("\n") + 1
                    print(
                        f"    System Prompt ({len(sys_prompt)} chars, {sys_lines} lines):"
                    )
                    for line in sys_prompt.splitlines():
                        print(f"      | {line}")
                except Exception as _sp_err:
                    print(f"    System Prompt: (error: {_sp_err})")

                # User message (template + context + schema + task)
                try:
                    user_msg = agent._build_user_message(task, state)
                    um_lines = user_msg.count("\n") + 1
                    print(
                        f"    User Message ({len(user_msg)} chars, {um_lines} lines):"
                    )
                    for line in user_msg.splitlines():
                        print(f"      | {line}")
                except Exception as _um_err:
                    print(f"    User Message: (error: {_um_err})")

                # Skills
                try:
                    skills_text = agent._load_skills()
                    if skills_text:
                        print(f"    Skills ({len(skills_text)} chars):")
                        for line in skills_text.splitlines():
                            print(f"      | {line}")
                    else:
                        print("    Skills: (none)")
                except Exception:
                    print("    Skills: (none)")

                # Tool definitions
                try:
                    caps = agent._config.capabilities
                    if caps and hasattr(caps, "tools") and caps.tools.enabled:
                        allowed = caps.tools.allowed or None
                        tool_defs = runner._tools.get_definitions(allowed)
                        print(f"    Tools ({len(tool_defs)} definitions):")
                        for td in tool_defs:
                            func = td.get("function", td)
                            print(
                                f"      - {func.get('name', '?')}: {func.get('description', '')}"
                            )
                            params = func.get("parameters", {})
                            for pn, pdef in params.get("properties", {}).items():
                                print(
                                    f"          {pn} ({pdef.get('type', '?')}): {pdef.get('description', '')}"
                                )
                    else:
                        print("    Tools: disabled")
                except Exception:
                    print("    Tools: (error reading)")

                # Output schema
                try:
                    schema = agent._load_output_schema()
                    if schema:
                        print("    Output Schema:")
                        print(
                            f"      {json.dumps(schema, indent=2, default=str, ensure_ascii=False)}"
                        )
                    else:
                        print("    Output Schema: (none)")
                except Exception:
                    print("    Output Schema: (none)")

                # State context passed to agent
                state_keys = [k for k in state if not k.startswith("_") and k != "task"]
                if state_keys:
                    print(f"    State Context ({len(state_keys)} entries):")
                    for sk in state_keys:
                        sv = state[sk]
                        if isinstance(sv, dict):
                            print(
                                f"      {sk}: {json.dumps(sv, indent=2, default=str, ensure_ascii=False)}"
                            )
                        else:
                            print(f"      {sk}: {sv}")
                else:
                    print("    State Context: (empty)")

                print(f"    {'─' * 52}")
                print("    EXECUTING...")
                print(f"    {'─' * 52}")

                # ── EXECUTE AGENT ───────────────────────────────────
                result = agent.run(task, state)
                elapsed = _time.time() - agent_start
                state.update(result)
                completed += 1

                agent_result = result.get(agent_id, {})
                confidence = agent_result.get("confidence", "N/A")
                has_error = "error" in agent_result

                # ── DEBUG TRACE: OUTPUTS ────────────────────────────
                print(f"    {'─' * 52}")
                print("    OUTPUT TRACE")
                print(f"    {'─' * 52}")

                if has_error:
                    error_msg = agent_result["error"]
                    print(f"    Status:  ERROR ({elapsed:.1f}s)")
                    print(f"    Error:   {error_msg}")
                else:
                    print(f"    Status:  OK ({elapsed:.1f}s, confidence: {confidence})")

                    # Show full output (no truncation in debug mode)
                    for k, v in agent_result.items():
                        if k in ("confidence", "error"):
                            continue
                        if isinstance(v, list):
                            print(f"    Output:  {k} → {len(v)} items")
                            for i, item in enumerate(v):
                                prefix = f"      [{i}] "
                                if isinstance(item, dict):
                                    print(
                                        f"{prefix}{json.dumps(item, indent=2, default=str, ensure_ascii=False)}"
                                    )
                                else:
                                    print(f"{prefix}{item}")
                        elif isinstance(v, dict):
                            print(f"    Output:  {k} → {len(v)} fields")
                            print(
                                f"      {json.dumps(v, indent=2, default=str, ensure_ascii=False)}"
                            )
                        elif isinstance(v, str):
                            lines = v.count("\n") + 1
                            chars = len(v)
                            print(f"    Output:  {k} → {chars} chars ({lines} lines)")
                            for line in v.splitlines():
                                print(f"      {line}")
                        else:
                            print(f"    Output:  {k} → {v}")

                # Full JSON dump of agent result
                print("    Full Result JSON:")
                print(
                    f"      {json.dumps(agent_result, indent=2, default=str, ensure_ascii=False)}"
                )
                print(f"    {'─' * 52}")

                # Memory auto-write and show path
                runner._auto_write_memory(agent_id, agent_result)
                from datetime import datetime, timezone

                mem_file = (
                    wf_dir
                    / "workspace"
                    / "memory"
                    / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
                )
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
        print("  Observability:")
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
            print(
                f"    {key:20s}  {status:5s}  confidence={conf}  fields=[{', '.join(fields)}]"
            )

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

    print("  Engine:        delegation_loop")
    if dl:
        b = getattr(dl, "budget", None)
        if b:
            print(
                f"  Budget:        loops={b.max_loops}, workers={b.max_total_workers}, "
                f"tokens={b.max_total_tokens:,}, "
                f"wall_time={b.max_wall_time}s, depth={b.max_depth}, "
                f"tool_calls={b.max_tool_calls}"
            )
        print(f"  Manager:       {dl.manager}")
        if dl.models.manager:
            print(f"  Manager model: {dl.models.manager}")
        if dl.models.worker:
            print(f"  Worker model:  {dl.models.worker}")

        # Manager agent config
        manager_dir = wf_dir / dl.manager
        if manager_dir.exists():
            agent_yaml = manager_dir / "agent.awp.yaml"
            if agent_yaml.exists():
                try:
                    import yaml as _yaml

                    mgr_cfg = _yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
                    identity = mgr_cfg.get("identity", {})
                    print(f"  Manager role:  {identity.get('role', '?')}")
                    print(f"  Manager desc:  {identity.get('description', '?')}")
                except Exception:
                    pass

            # Manager system prompt
            sys_prompt_file = (
                manager_dir / "workflow" / "instructions" / "SYSTEM_PROMPT.md"
            )
            if sys_prompt_file.exists():
                content = sys_prompt_file.read_text(encoding="utf-8")
                print(f"  Manager System Prompt ({len(content)} chars):")
                for line in content.splitlines():
                    print(f"    | {line}")

            # Manager skills
            mgr_skills_dir = manager_dir / "workflow" / "skills"
            if mgr_skills_dir.exists():
                skill_files = list(mgr_skills_dir.rglob("*.md"))
                if skill_files:
                    print(f"  Manager Skills ({len(skill_files)}):")
                    for sf in skill_files:
                        sc = sf.read_text(encoding="utf-8")
                        print(f"    [{sf.name}] ({len(sc)} chars):")
                        for line in sc.splitlines():
                            print(f"      | {line}")

            # Manager output schema
            schema_file = (
                manager_dir / "workflow" / "output_schema" / "output_schema.json"
            )
            if schema_file.exists():
                try:
                    schema = json.loads(schema_file.read_text(encoding="utf-8"))
                    print("  Manager Output Schema:")
                    for line in json.dumps(schema, indent=2, default=str).splitlines():
                        print(f"    {line}")
                except Exception:
                    pass

        # Worker policy
        wp = dl.worker_policy
        print("  Worker policy:")
        print(f"    Forbidden tools:  {', '.join(wp.enforced.forbidden_tools)}")
        print(f"    Manager controls: {', '.join(wp.manager_controlled)}")
        print(
            f"    Sandbox:          type={wp.enforced.sandbox.type}, "
            f"mem={wp.enforced.sandbox.max_memory_mb}MB"
        )

        # Validation config
        print(
            f"  Validation:    deterministic={dl.validation.deterministic.always}, "
            f"llm={dl.validation.llm.enabled}"
        )
        if dl.termination:
            print(
                f"  Stall detect:  window={dl.termination.window}, "
                f"delta={dl.termination.min_confidence_delta}, "
                f"action={dl.termination.action}"
            )

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
    result.get("delegation_loop", {})
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

                print(f"    {'─' * 48}")
                print("    MANAGER DECISION")
                print(f"    {'─' * 48}")
                print(f"    Decision:    {dec_type}")
                if reasoning:
                    print("    Reasoning:")
                    if isinstance(reasoning, str):
                        for line in reasoning.splitlines():
                            print(f"      | {line}")
                    else:
                        print(f"      {reasoning}")

                # Full manager decision JSON
                print("    Full Manager Decision JSON:")
                for line in json.dumps(
                    decision, indent=2, default=str, ensure_ascii=False
                ).splitlines():
                    print(f"      {line}")

                # Show delegations with FULL inputs
                delegations = decision.get("delegations", decision.get("workers", []))
                if delegations:
                    print(f"    {'─' * 48}")
                    print(f"    WORKER INPUTS ({len(delegations)} workers)")
                    print(f"    {'─' * 48}")
                    for w in delegations:
                        wid = w.get("worker_id", w.get("id", "?"))
                        instr = w.get("instructions", "")
                        skills = w.get("skills", [])
                        tools = w.get("tools_allowed", [])
                        codemode = w.get("codemode", {})
                        output_contract = w.get("output_contract", {})
                        budget = w.get("budget", {})

                        print(f"      ▶ {wid}")

                        # Full instructions (no truncation)
                        if instr:
                            print(f"        Instructions ({len(instr)} chars):")
                            for line in instr.splitlines():
                                print(f"          | {line}")

                        # Full skills content
                        if skills:
                            total_chars = sum(
                                len(s) for s in skills if isinstance(s, str)
                            )
                            print(
                                f"        Skills ({len(skills)}, {total_chars} chars total):"
                            )
                            for si, skill in enumerate(skills):
                                if isinstance(skill, str):
                                    print(
                                        f"          [Skill {si}] ({len(skill)} chars):"
                                    )
                                    for line in skill.splitlines():
                                        print(f"            | {line}")
                                else:
                                    print(f"          [Skill {si}]: {skill}")

                        # Full tools list
                        if tools:
                            print(f"        Tools allowed ({len(tools)}):")
                            for t in tools:
                                print(f"          - {t}")
                        else:
                            print("        Tools allowed: ALL")

                        # Output contract
                        if output_contract:
                            print("        Output contract:")
                            for line in json.dumps(
                                output_contract, indent=2, default=str
                            ).splitlines():
                                print(f"          {line}")

                        # Codemode
                        if codemode:
                            print(
                                f"        CodeMode: enabled={codemode.get('enabled', False)}"
                            )
                            if codemode.get("tool_creation"):
                                ns = codemode.get("tool_creation_namespace", "dynamic")
                                print(f"          tool_creation: {ns}.*")
                                max_tools = codemode.get("max_tools", "?")
                                print(f"          max_tools: {max_tools}")

                        # Worker budget
                        if budget:
                            print(f"        Budget: {json.dumps(budget, default=str)}")

                        print()
            except Exception:
                pass

        # Worker results
        deleg_dir = iter_dir / "delegations"
        if deleg_dir.exists():
            print()
            print(f"    {'─' * 48}")
            print("    WORKER OUTPUTS")
            print(f"    {'─' * 48}")
            for worker_dir in sorted(deleg_dir.iterdir()):
                if not worker_dir.is_dir():
                    continue
                wid = worker_dir.name

                # Envelope (worker input as stored on disk)
                envelope_file = worker_dir / "envelope.json"
                if envelope_file.exists():
                    try:
                        envelope = json.loads(envelope_file.read_text(encoding="utf-8"))
                        if envelope:
                            print(f"    ▶ {wid} — ENVELOPE (stored input):")
                            # Show instructions
                            env_instr = envelope.get("instructions", "")
                            if env_instr:
                                print(f"        Instructions ({len(env_instr)} chars):")
                                for line in env_instr.splitlines():
                                    print(f"          | {line}")
                            # Show skills
                            env_skills = envelope.get("skills", [])
                            if env_skills:
                                print(f"        Skills ({len(env_skills)}):")
                                for si, sk in enumerate(env_skills):
                                    if isinstance(sk, str):
                                        print(
                                            f"          [Skill {si}] ({len(sk)} chars):"
                                        )
                                        for line in sk.splitlines():
                                            print(f"            | {line}")
                                    else:
                                        print(f"          [Skill {si}]: {sk}")
                            # Show tools
                            env_tools = envelope.get("tools_allowed", [])
                            if env_tools:
                                print(f"        Tools: {', '.join(env_tools)}")
                            # Show output contract
                            env_oc = envelope.get("output_contract", {})
                            if env_oc:
                                print("        Output contract:")
                                for line in json.dumps(
                                    env_oc, indent=2, default=str
                                ).splitlines():
                                    print(f"          {line}")
                            # Show codemode
                            env_cm = envelope.get("codemode", {})
                            if env_cm:
                                print(
                                    f"        CodeMode: {json.dumps(env_cm, default=str)}"
                                )
                    except Exception:
                        pass

                # Result (full output, no truncation)
                result_file = worker_dir / "result.json"
                if result_file.exists():
                    try:
                        w_result = json.loads(result_file.read_text(encoding="utf-8"))
                        conf = w_result.get("confidence", "?")
                        has_error = "error" in w_result
                        status = "ERROR" if has_error else "OK"

                        print(f"    ← {wid}: {status} (confidence: {conf})")

                        if has_error:
                            print("        Error:")
                            err = str(w_result["error"])
                            for line in err.splitlines():
                                print(f"          {line}")
                        else:
                            # Show ALL output fields fully (no truncation)
                            result_keys = [
                                k for k in w_result if k not in ("confidence", "error")
                            ]
                            for rk in result_keys:
                                val = w_result[rk]
                                if isinstance(val, str):
                                    lines = val.count("\n") + 1
                                    print(
                                        f"        {rk} ({len(val)} chars, {lines} lines):"
                                    )
                                    for line in val.splitlines():
                                        print(f"          {line}")
                                elif isinstance(val, list):
                                    print(f"        {rk} ({len(val)} items):")
                                    for li, litem in enumerate(val):
                                        if isinstance(litem, dict):
                                            print(
                                                f"          [{li}] {json.dumps(litem, indent=2, default=str, ensure_ascii=False)}"
                                            )
                                        else:
                                            print(f"          [{li}] {litem}")
                                elif isinstance(val, dict):
                                    print(f"        {rk} ({len(val)} fields):")
                                    for line in json.dumps(
                                        val, indent=2, default=str, ensure_ascii=False
                                    ).splitlines():
                                        print(f"          {line}")
                                else:
                                    print(f"        {rk}: {val}")

                        # Full JSON dump
                        print("        Full Result JSON:")
                        for line in json.dumps(
                            w_result, indent=2, default=str, ensure_ascii=False
                        ).splitlines():
                            print(f"          {line}")

                        # Tools created (raw LLM output)
                        tc = w_result.get("tools_created", [])
                        if isinstance(tc, list) and tc:
                            print(f"        tools_created ({len(tc)} from LLM):")
                            for ti, tspec in enumerate(tc):
                                if isinstance(tspec, dict):
                                    tname = tspec.get("name", f"tool_{ti}")
                                    print(f"          [{ti}] {tname}")
                                    tdesc = tspec.get("description", "")
                                    if tdesc:
                                        print(f"              Description: {tdesc}")
                                    treqs = tspec.get("required_secrets", [])
                                    if treqs:
                                        print(
                                            f"              Required secrets: {', '.join(treqs)}"
                                        )
                                    tparams = tspec.get("parameters", {})
                                    if tparams:
                                        print("              Parameters:")
                                        for line in json.dumps(
                                            tparams, indent=2, default=str
                                        ).splitlines():
                                            print(f"                {line}")
                                    tcode = tspec.get("code", "")
                                    if tcode:
                                        print(
                                            f"              Code ({len(tcode)} chars):"
                                        )
                                        for line in tcode.splitlines():
                                            print(f"                | {line}")

                        # Tools registered (enriched with registration status)
                        tr = w_result.get("tools_registered", [])
                        if isinstance(tr, list) and tr:
                            print(f"        tools_registered ({len(tr)}):")
                            for ti, trec in enumerate(tr):
                                if isinstance(trec, dict):
                                    tname = trec.get("name", f"tool_{ti}")
                                    registered = trec.get("registered", False)
                                    status_str = "OK" if registered else "FAILED"
                                    print(f"          [{ti}] {tname}: {status_str}")
                                    if not registered:
                                        terr = trec.get(
                                            "error", trec.get("reason", "?")
                                        )
                                        print(f"              Error: {terr}")
                                        vr = trec.get("validation_result", {})
                                        if vr:
                                            print("              Validation:")
                                            for line in json.dumps(
                                                vr, indent=2, default=str
                                            ).splitlines():
                                                print(f"                {line}")
                                    treqs = trec.get("required_secrets", [])
                                    if treqs:
                                        print(
                                            f"              Required secrets: {', '.join(treqs)}"
                                        )
                                    # Show code from enriched record
                                    tcode = trec.get("code", "")
                                    if tcode:
                                        print(
                                            f"              Code ({len(tcode)} chars):"
                                        )
                                        for line in tcode.splitlines():
                                            print(f"                | {line}")
                                    tparams = trec.get("parameters", {})
                                    if tparams:
                                        print("              Parameters:")
                                        for line in json.dumps(
                                            tparams, indent=2, default=str
                                        ).splitlines():
                                            print(f"                {line}")

                    except Exception:
                        pass

                # Generated skills (full content)
                skills_dir = worker_dir / "generated_skills"
                if skills_dir.exists():
                    skill_files = list(skills_dir.glob("*.md"))
                    if skill_files:
                        print(f"        Generated Skills ({len(skill_files)}):")
                        for sf in skill_files:
                            content = sf.read_text(encoding="utf-8")
                            title = (
                                content.split("\n")[0].strip("# ").strip()
                                if content
                                else sf.name
                            )
                            print(f"          Skill: {title} ({sf.stat().st_size}B)")
                            for line in content.splitlines():
                                print(f"            | {line}")

                # Generated tools (full content)
                tools_dir = worker_dir / "generated_tools"
                if tools_dir.exists():
                    tool_files = list(tools_dir.glob("*.json"))
                    if tool_files:
                        print(f"        Generated Tools ({len(tool_files)}):")
                        for tf in tool_files:
                            try:
                                tdata = json.loads(tf.read_text(encoding="utf-8"))
                                tname = tdata.get("name", tf.stem)
                                tdesc = tdata.get("description", "")
                                print(f"          Tool: {tname}")
                                print(f"            Description: {tdesc}")
                                treqs = tdata.get("required_secrets", [])
                                if treqs:
                                    print(
                                        f"            Required secrets: {', '.join(treqs)}"
                                    )
                                params = tdata.get("parameters", {})
                                if params:
                                    print("            Parameters:")
                                    for line in json.dumps(
                                        params, indent=2, default=str
                                    ).splitlines():
                                        print(f"              {line}")
                                code = tdata.get("code", tdata.get("source", ""))
                                if code:
                                    print(f"            Code ({len(code)} chars):")
                                    for line in code.splitlines():
                                        print(f"              | {line}")
                            except Exception:
                                print(f"          Tool: {tf.name}")

                print()

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
                print(
                    f"    Budget:  {remaining}% remaining | "
                    f"loops: {loops_used} | workers: {workers_spawned} | "
                    f"wall: {wall}s"
                )
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
            print(
                f"  Workers:     {fb.get('workers', {}).get('spawned', '?')}"
                f"/{fb.get('workers', {}).get('max', '?')}"
            )
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
                trend = " → ".join(f"{h.get('confidence', '?')}" for h in entries)
                print(f"  Confidence:  {trend}")
        except Exception:
            pass

    # Artifacts
    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists():
        skills = (
            list((artifacts_dir / "skills").glob("*.md"))
            if (artifacts_dir / "skills").exists()
            else []
        )
        tools = (
            list((artifacts_dir / "tools").glob("*.json"))
            if (artifacts_dir / "tools").exists()
            else []
        )
        if skills:
            print(f"  Skills:      {len(skills)} generated")
            for s in skills:
                content = s.read_text(encoding="utf-8")
                title = (
                    content.split("\n")[0].strip("# ").strip() if content else s.name
                )
                print(f"    Skill: {s.name}: {title} ({s.stat().st_size}B)")
                for line in content.splitlines():
                    print(f"      | {line}")
        if tools:
            print(f"  Tools:       {len(tools)} generated")
            for t in tools:
                try:
                    tdata = json.loads(t.read_text(encoding="utf-8"))
                    tname = tdata.get("name", t.stem)
                    tdesc = tdata.get("description", "")
                    registered = tdata.get("registered", None)
                    reg_str = ""
                    if registered is True:
                        reg_str = " [REGISTERED]"
                    elif registered is False:
                        reg_str = f" [FAILED: {tdata.get('error', '?')}]"

                    print(f"    Tool: {tname}{reg_str}")
                    if tdesc:
                        print(f"      Description: {tdesc}")
                    treqs = tdata.get("required_secrets", [])
                    if treqs:
                        print(f"      Required secrets: {', '.join(treqs)}")

                    # Worker info
                    worker_id = tdata.get("worker_id", "")
                    if worker_id:
                        print(f"      Worker: {worker_id}")
                    prov = tdata.get("provenance", {})
                    if prov:
                        print(
                            f"      Creator: {prov.get('creator_agent', '?')}, "
                            f"Created: {prov.get('created_at', '?')}"
                        )

                    # Parameters
                    tparams = tdata.get("parameters", {})
                    if tparams:
                        print("      Parameters:")
                        for line in json.dumps(
                            tparams, indent=2, default=str
                        ).splitlines():
                            print(f"        {line}")

                    # Code (full)
                    tcode = tdata.get("code", tdata.get("source", ""))
                    if tcode:
                        print(f"      Code ({len(tcode)} chars):")
                        for line in tcode.splitlines():
                            print(f"        | {line}")

                    # Validation result (if failed)
                    vr = tdata.get("validation_result", {})
                    if vr:
                        print("      Validation result:")
                        for line in json.dumps(vr, indent=2, default=str).splitlines():
                            print(f"        {line}")

                    # If this is a manifest file, show all tools in it
                    manifest_tools = tdata.get("tools", [])
                    if isinstance(manifest_tools, list) and manifest_tools:
                        print(f"      Manifest ({len(manifest_tools)} tools):")
                        for mt in manifest_tools:
                            if isinstance(mt, dict):
                                print(
                                    f"        - {mt.get('name', '?')}: "
                                    f"registered={mt.get('registered', '?')}"
                                )
                            else:
                                print(f"        - {mt}")

                except Exception:
                    print(f"    Tool: {t.name}")

    # Dynamic tools directory (workspace/dynamic_tools — persisted by factory)
    dynamic_tools_dir = run_dir.parent.parent / "dynamic_tools"
    if dynamic_tools_dir.exists():
        dt_files = list(dynamic_tools_dir.glob("*.json"))
        if dt_files:
            print(f"  Persisted dynamic tools: {len(dt_files)}")
            for dt in dt_files:
                try:
                    dtdata = json.loads(dt.read_text(encoding="utf-8"))
                    print(
                        f"    {dtdata.get('fqn', dt.stem)}: {dtdata.get('description', '')}"
                    )
                    prov = dtdata.get("provenance", {})
                    if prov:
                        print(
                            f"      Creator: {prov.get('creator_agent', '?')}, "
                            f"Created: {prov.get('created_at', '?')}"
                        )
                    dtcode = dtdata.get("code", "")
                    if dtcode:
                        print(f"      Code ({len(dtcode)} chars):")
                        for line in dtcode.splitlines():
                            print(f"        | {line}")
                except Exception:
                    print(f"    {dt.name}")

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
            custom = input(
                "  Enter model name (e.g. openrouter/meta/llama-3-70b): "
            ).strip()
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
    import os as _os

    from .models.orchestration import RunBudgetLimits

    orch = getattr(runner._manifest, "orchestration", None)
    if not orch:
        return

    # Create run_budget if it doesn't exist yet (user can still opt out)
    budget: RunBudgetLimits = getattr(orch, "run_budget", None) or RunBudgetLimits()

    # Detect free model — cost limits are meaningless for free models
    model = _os.getenv("LLM_MODEL", "")
    is_free = ":free" in model.lower()

    # Auto-adjust defaults for free models: disable cost, ensure tokens ON
    if is_free:
        enabled_set = set(budget.enabled_limits)
        if "max_cost_usd" in enabled_set:
            enabled_set.discard("max_cost_usd")
        if "max_total_tokens" not in enabled_set:
            enabled_set.add("max_total_tokens")
        budget.enabled_limits = sorted(enabled_set)

    # Limit metadata: (field, label, unit, description)
    ALL_LIMITS = [
        ("max_wall_time", "Max Wall Time", "s", "total execution time"),
        ("max_total_tokens", "Max Tokens", "", "LLM token cap"),
        ("max_tool_calls", "Max Tool Calls", "", "total tool invocations"),
        ("max_agent_runs", "Max Agent Runs", "", "total agent executions"),
        ("max_cost_usd", "Max Cost", "USD", "estimated cost cap"),
    ]

    print()
    print("=" * 60)
    print("  Run Budget Limits")
    print("=" * 60)

    if is_free:
        print()
        print("  ⚠ Free model detected — cost limit disabled, token limit is primary.")

    print()

    enabled = set(budget.enabled_limits)

    for idx, (field, label, unit, desc) in enumerate(ALL_LIMITS, 1):
        val = getattr(budget, field)
        active = field in enabled
        marker = "ON " if active else "OFF"
        unit_str = f" {unit}" if unit else ""
        note = ""
        if is_free and field == "max_cost_usd" and not active:
            note = "  ← disabled (free model)"
        elif is_free and field == "max_total_tokens" and active:
            note = "  ← primary limit"
        print(f"  {idx}) [{marker}] {label:<18} {val:>10}{unit_str}    ({desc}){note}")

    print()
    print("=" * 60)

    try:
        ans = input(
            "\n  Toggle or adjust limits? Enter numbers (e.g. 1,3) or [N]: "
        ).strip()
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
            toggle = input(
                f"     {label} is {'ON' if currently_on else 'OFF'}. Toggle? [y/N]: "
            ).strip()
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
    print(
        f"     Max Workers:     {budget.max_total_workers:>6}     (total workers spawned)"
    )
    print(f"     Max Wall Time:   {budget.max_wall_time:>5}s    (total execution time)")
    print(
        f"     Max Depth:       {budget.max_depth:>6}     (recursive delegation depth)"
    )

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
        print(
            f"     Deterministic:   {'on' if (det and det.always) else 'off':>6}     (schema, confidence, budget checks)"
        )
        if llm_val:
            print(
                f"     LLM Validation:  {'on' if llm_val.enabled else 'off':>6}     (semantic check — costs extra tokens)"
            )
            if llm_val.enabled:
                print(
                    f"     Skip above:      {llm_val.skip_when_confidence_above:>6}     (skip LLM validation when confident)"
                )

    # Stall Detection
    stall_cfg = getattr(dl, "termination", None)
    if stall_cfg:
        print()
        print("  3) Stall Detection")
        print(
            f"     Enabled:         {'on' if stall_cfg.enabled else 'off':>6}     (auto-stop when no progress)"
        )
        if stall_cfg.enabled:
            print(
                f"     Window:          {stall_cfg.window:>6}     (iterations to compare)"
            )
            print(
                f"     Min Delta:       {stall_cfg.min_confidence_delta:>6}     (minimum confidence improvement)"
            )

    # Logging
    log_cfg = getattr(dl, "logging", None)
    if log_cfg:
        print()
        print("  4) Logging")
        print(f"     Format:          {log_cfg.format:>6}     (dual=JSON+MD, json, md)")
        print(
            f"     Artifacts:       {'on' if log_cfg.persist_artifacts else 'off':>6}     (save generated skills & tools)"
        )

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
        budget.max_wall_time = _ask_int(
            "Max Wall Time (seconds)", budget.max_wall_time, rec_wall
        )
        budget.max_depth = _ask_int("Max Depth", budget.max_depth)
        changes.append(
            f"budget: loops={budget.max_loops}, workers={budget.max_total_workers}, "
            f"wall_time={budget.max_wall_time}s"
        )

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
            stall_cfg.min_confidence_delta = _ask_float(
                "Min Delta", stall_cfg.min_confidence_delta
            )
        changes.append(f"stall: {'on' if stall_cfg.enabled else 'off'}")

    # 4) Logging
    if "4" in sections and log_cfg:
        print("\n  -- Logging --")
        log_cfg.format = _ask_str("Format", log_cfg.format, ["dual", "json", "md"])
        log_cfg.persist_artifacts = _ask_bool(
            "Save artifacts (skills & tools)", log_cfg.persist_artifacts
        )
        changes.append(
            f"logging: {log_cfg.format}, artifacts={'on' if log_cfg.persist_artifacts else 'off'}"
        )

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


# ---------------------------------------------------------------------------
# awp optimize / awp optimize-inspect — Outer Loop (Phase A2)
# ---------------------------------------------------------------------------


def _resolve_outer_loop_db(arg_db: str | None) -> str:
    """Resolve the outer-loop SQLite DB path.

    Precedence: ``--db`` arg > ``$AWP_OUTER_LOOP_DB`` > ``~/.awp/outer_loop.db``.
    """
    import os as _os

    if arg_db:
        return arg_db
    env = _os.environ.get("AWP_OUTER_LOOP_DB")
    if env:
        return env
    return str(Path.home() / ".awp" / "outer_loop.db")


def _format_loss_table(epoch_result) -> str:
    """Render an :class:`EpochResult` as the canonical fixed-width table."""
    rows = epoch_result.as_table_rows()
    header = (
        f"Epoch {epoch_result.epoch_num} — Suite: {epoch_result.suite_name}"
    )
    sep = "─" * 75
    cols = f"{'Task':<18}{'Status':<12}{'Loss':<9}{'Eval':<8}{'Critique':<10}{'Rejections':<10}"
    lines = [header, sep, cols, sep]
    for r in rows:
        lines.append(
            f"{str(r['task'])[:17]:<18}"
            f"{str(r['status'])[:11]:<12}"
            f"{r['loss']:<9.4f}"
            f"{r['eval']:<8.3f}"
            f"{r['critique']:<10.3f}"
            f"{r['rejections']:<10d}"
        )
    lines.append(sep)
    if epoch_result.mean_loss is not None:
        lines.append(f"Mean loss: {epoch_result.mean_loss:.4f}")
    else:
        lines.append("Mean loss: n/a")
    return "\n".join(lines)


def cmd_optimize(args: argparse.Namespace) -> int:
    """Run a task suite per-epoch; with ``--with-textgrad`` apply updates (A3)."""
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import optimize_task_aware
        return optimize_task_aware(args)

    # Lazy imports — `awp optimize` lives in awp-core but the implementation
    # is in awp-runtime; both share the ``awp.*`` namespace.
    from awp.outer_loop import (  # type: ignore[import-not-found]
        ArtifactRegistry,
        SuiteRunner,
        TextGradOptimizer,
        load_suite,
    )
    from awp.outer_loop.store import SqliteArtifactStore  # type: ignore[import-not-found]

    suite_path = Path(args.suite)
    suite = load_suite(suite_path)

    db_path = _resolve_outer_loop_db(args.db)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    registry = ArtifactRegistry(db_path=db_path)
    store = SqliteArtifactStore(db_path)
    runner = SuiteRunner(registry=registry, store=store)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    epochs = max(1, int(args.epochs))
    with_textgrad = bool(getattr(args, "with_textgrad", False))
    rollback_on_regression = not bool(getattr(args, "no_rollback", False))
    learning_rate = float(getattr(args, "learning_rate", 0.5))

    if with_textgrad:
        # Lazy-import LLMClient to keep `awp optimize` dependency-free when
        # --with-textgrad is not passed (the ArtifactRegistry path has no
        # httpx/requests dependency by itself).
        from awp.runtime.llm import LLMClient  # type: ignore[import-not-found]

        import os as _os

        manager_model = (
            getattr(args, "manager_model", None)
            or _os.environ.get("LLM_MODEL")
            or "openai/gpt-5-mini"
        )
        try:
            llm_client = LLMClient(model=manager_model)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[error] Could not initialise LLMClient for --with-textgrad: {exc}",
                file=sys.stderr,
            )
            return 1
        optimizer = TextGradOptimizer(llm_client=llm_client, registry=registry)
        results = runner.optimize(
            suite,
            n_epochs=epochs,
            learning_rate=learning_rate,
            optimizer=optimizer,
            output_dir=output_dir,
            rollback_on_regression=rollback_on_regression,
        )
    else:
        # A2-compatible path: same suite run N times, no artifact updates.
        # We deliberately do NOT go through `runner.optimize()` with
        # ``optimizer=None`` because that would still rewrite
        # ``child_artifacts_json`` to the richer A3 envelope and surprise
        # callers that parse the A2 format.
        parent_artifacts: dict[str, int] = {}
        for name in registry.list_artifacts():
            baseline = suite.baseline_artifacts.get(name)
            if baseline is not None:
                parent_artifacts[name] = int(baseline)
            else:
                parent_artifacts[name] = registry.get_active(name).version
        if learning_rate != 0.5:
            print(
                f"[note] --learning-rate={learning_rate} accepted but ignored "
                "(no --with-textgrad — no artifact updates).",
                file=sys.stderr,
            )
        results = []
        for epoch_num in range(1, epochs + 1):
            epoch_out = (
                output_dir / f"epoch_{epoch_num}" if output_dir is not None else None
            )
            result = runner.run_epoch(
                suite,
                epoch_num=epoch_num,
                parent_artifacts=parent_artifacts,
                output_dir=epoch_out,
            )
            results.append(result)

    for i, result in enumerate(results):
        print(_format_loss_table(result))
        if i < len(results) - 1:
            print()

    if not results:
        return 1
    return 0


def cmd_optimize_inspect(args: argparse.Namespace) -> int:
    """Print the epoch history for a suite (or a single artifact's versions)."""
    from awp.outer_loop.store import SqliteArtifactStore  # type: ignore[import-not-found]

    db_path = _resolve_outer_loop_db(args.db)
    if not Path(db_path).exists():
        print(f"No outer-loop DB found at {db_path}", file=sys.stderr)
        return 1
    store = SqliteArtifactStore(db_path)

    # --- Artifact history mode (Phase A3) --------------------------------
    artifact_name = getattr(args, "artifact", None)
    if artifact_name:
        return _inspect_artifact_history(db_path, artifact_name)

    target = args.suite_id_or_name
    if target is None:
        # List every known suite.
        with store._lock:  # type: ignore[attr-defined]
            cur = store._conn.execute(  # type: ignore[attr-defined]
                "SELECT id, name, created_at FROM task_suites ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
        if not rows:
            print("No suites recorded yet.")
            return 0
        print(f"{'Suite ID':<38}  {'Name':<30}  Created")
        print("-" * 90)
        for r in rows:
            print(f"{r['id']:<38}  {str(r['name'])[:29]:<30}  {r['created_at']}")
        return 0

    suite_row = store.get_task_suite(target) or store.find_task_suite_by_name(target)
    if suite_row is None:
        print(f"No suite matching {target!r}", file=sys.stderr)
        return 1

    epochs = store.list_epochs(suite_row["id"])
    print(f"Suite: {suite_row['name']} ({suite_row['id']})")
    print(f"Created: {suite_row['created_at']}")
    print(f"Epochs:  {len(epochs)}")
    print()
    for ep in epochs:
        ep_runs = store.list_epoch_runs(ep["id"])
        mean = ep["mean_loss"]
        mean_s = f"{mean:.4f}" if isinstance(mean, (int, float)) else "n/a"
        print(
            f"Epoch {ep['epoch_num']} — id={ep['id']} — "
            f"started={ep['started_at']} — mean_loss={mean_s}"
        )
        sep = "─" * 75
        print(sep)
        print(f"{'Task':<18}{'Run ID':<38}{'Loss':<9}")
        print(sep)
        for run in ep_runs:
            loss = run["loss"]
            loss_s = f"{loss:.4f}" if isinstance(loss, (int, float)) else "n/a"
            print(
                f"{str(run['task_name'])[:17]:<18}"
                f"{str(run['run_id'])[:37]:<38}"
                f"{loss_s:<9}"
            )
        print(sep)
        print()
    return 0


def _inspect_artifact_history(db_path: str, artifact_name: str) -> int:
    """Print the full version history for one artifact with unified diffs."""
    import difflib

    from awp.outer_loop import ArtifactRegistry  # type: ignore[import-not-found]

    registry = ArtifactRegistry(db_path=db_path)
    try:
        versions = registry.list_versions(artifact_name)
    except KeyError:
        print(f"Unknown artifact: {artifact_name!r}", file=sys.stderr)
        return 1
    try:
        active = registry.get_active(artifact_name)
    except KeyError:
        active = None

    print(f"Artifact: {artifact_name}")
    print(f"Versions: {len(versions)}")
    active_v = active.version if active is not None else None
    print(f"Active:   v{active_v if active_v is not None else 'n/a'}")
    print()
    for i, v in enumerate(versions):
        marker = "  (ACTIVE)" if active_v is not None and v.version == active_v else ""
        header = (
            f"── v{v.version}{marker}  "
            f"parent=v{v.parent_version if v.parent_version is not None else '-'}  "
            f"created_at={v.created_at}  "
            f"epoch_id={v.epoch_id or '-'}"
        )
        print(header)
        if i == 0:
            # First version — just show a content preview.
            preview = v.content[:400]
            suffix = "..." if len(v.content) > 400 else ""
            print(preview + suffix)
        else:
            prev = versions[i - 1]
            diff = difflib.unified_diff(
                prev.content.splitlines(keepends=False),
                v.content.splitlines(keepends=False),
                fromfile=f"v{prev.version}",
                tofile=f"v{v.version}",
                lineterm="",
                n=2,
            )
            diff_text = "\n".join(diff)
            if not diff_text.strip():
                print("(no textual change)")
            else:
                print(diff_text)
        print()
    return 0


def cmd_optimize_rollback(args: argparse.Namespace) -> int:
    """Manually roll back an artifact to a prior version (A3)."""
    from awp.outer_loop import ArtifactRegistry  # type: ignore[import-not-found]

    db_path = _resolve_outer_loop_db(args.db)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    registry = ArtifactRegistry(db_path=db_path)

    try:
        before = registry.get_active(args.artifact_name)
    except KeyError:
        print(
            f"Unknown artifact: {args.artifact_name!r}",
            file=sys.stderr,
        )
        return 1

    try:
        registry.rollback_to(args.artifact_name, int(args.version))
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    after = registry.get_active(args.artifact_name)
    print(f"Artifact: {args.artifact_name}")
    print(f"Active before: v{before.version}")
    print(f"Active after:  v{after.version}")
    return 0


def cmd_refine(args: argparse.Namespace) -> int:
    """Run the refinement loop against a completed seed run.

    Exit codes:
      0 — at least one iteration improved loss; BEST/ updated.
      0 — empty gradient (nothing to refine).
      1 — no iteration improved loss; BEST still points at seed.
      2 — setup failure (seed missing, malformed, no FINAL/).
    """
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import refine_task_aware
        return refine_task_aware(args)
    if args.seed is None:
        print("awp refine: either a seed path or --target is required", file=sys.stderr)
        return 2

    seed_path = Path(args.seed)
    if not seed_path.exists():
        print(f"error: seed run not found: {seed_path}", file=sys.stderr)
        return 2
    if not (seed_path / "run_completion.json").exists():
        print(f"error: seed has no run_completion.json: {seed_path}", file=sys.stderr)
        return 2
    if not (seed_path / "FINAL").exists():
        print(f"error: seed has no FINAL/: {seed_path}", file=sys.stderr)
        return 2

    try:
        from awp.refinement.loop import NothingToRefine, RefinementLoop
        from awp.refinement.tiers import ModelPair, TierPlan
    except ImportError as exc:
        print(f"error: awp.refinement is not available: {exc}", file=sys.stderr)
        return 2

    # Tier flag parsing. Spec 2026-04-20 §15.5: format is ``manager:worker``
    # (split on first colon). Either side may be empty. A value with no
    # colon is treated as manager, worker empty.
    tier_low_raw = getattr(args, "tier_low", None)
    tier_mid_raw = getattr(args, "tier_mid", None)
    tier_high_raw = getattr(args, "tier_high", None)
    has_any_tier = any(v is not None for v in (tier_low_raw, tier_mid_raw, tier_high_raw))

    tier_plan: TierPlan | None = None
    if has_any_tier:
        if args.model or args.worker_model:
            # Match the API's mixed-body contract: tier_* wins, legacy
            # fields are silently ignored (no exit error).
            print(
                "warning: --tier-* set; ignoring --model/--worker-model "
                "(they are superseded by the tier plan)",
                file=sys.stderr,
            )

        seed_manager, seed_worker = _parse_seed_models_for_cli(seed_path)

        tier_plan = TierPlan(
            low=_parse_tier_flag(tier_low_raw),
            mid=_parse_tier_flag(tier_mid_raw),
            high=_parse_tier_flag(tier_high_raw),
            seed_manager=seed_manager,
            seed_worker=seed_worker,
        )

    if tier_plan is not None:
        loop = RefinementLoop(
            seed_run_dir=seed_path,
            model=None,
            worker_model=None,
            tier_plan=tier_plan,
        )
    else:
        loop = RefinementLoop(
            seed_run_dir=seed_path,
            model=args.model,
            worker_model=args.worker_model,
        )
    try:
        result = loop.run(iterations=int(args.iterations))
    except NothingToRefine as exc:
        print(f"nothing to refine: {exc}")
        return 0

    print(f"session_id:  {result.session_id}")
    print(f"stop_reason: {result.stop_reason}")
    print(f"seed_loss:   {result.seed_loss:.4f}")
    print(
        f"best_loss:   {result.best_loss:.4f} "
        f"(iter {result.best_iter if result.best_iter > 0 else 'seed'})"
    )
    for it in result.iterations:
        print(
            f"  iter {it.k}: run_id={it.run_id} "
            f"loss={it.loss:.4f} status={it.status}"
        )

    if result.best_iter == 0:
        return 1
    return 0


def _parse_tier_flag(raw: str | None):
    """Parse a ``--tier-*`` flag value into a :class:`ModelPair`.

    Format: ``manager:worker`` — split on the FIRST colon. Either side
    may be empty (``""`` / ``None``), which maps to ``None`` in the pair
    so the loop's per-role seed fallback applies. A value with no colon
    is treated as manager-only (worker empty).

    Returns a fresh empty :class:`ModelPair` when ``raw`` is ``None``.
    """
    from awp.refinement.tiers import ModelPair

    if raw is None:
        return ModelPair()
    if ":" in raw:
        manager, _, worker = raw.partition(":")
    else:
        manager, worker = raw, ""
    return ModelPair(
        manager=(manager.strip() or None),
        worker=(worker.strip() or None),
    )


def _parse_seed_models_for_cli(seed_path: Path) -> tuple[str | None, str | None]:
    """Read ``<seed>/run_completion.json`` and extract the seed models.

    Mirrors the API's ``_parse_seed_models`` helper — the CLI builds the
    same ``TierPlan`` fallback the route does, so the two entry points
    behave identically for the same seed.
    """
    rc = seed_path / "run_completion.json"
    if not rc.exists():
        return None, None
    try:
        data = json.loads(rc.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}

    manager = (
        models.get("manager")
        or data.get("model")
        or config.get("model")
        or None
    )
    worker = (
        models.get("worker")
        or data.get("worker_model")
        or config.get("worker_model")
        or None
    )
    return (str(manager) if manager else None, str(worker) if worker else None)


def _check_awp_on_path() -> None:
    """Print a one-time hint if the ``awp`` console script isn't on PATH.

    Common on Windows after ``pip install --user`` because
    ``%APPDATA%\\Python\\PythonXX\\Scripts`` is not added to PATH
    by the Python installer by default.
    """
    import shutil
    import os
    import sysconfig

    if shutil.which("awp") is not None:
        return  # already on PATH, nothing to do

    scripts_dir = sysconfig.get_path("scripts")
    platform = sys.platform

    print(
        "\n"
        "  ╔══════════════════════════════════════════════════════════════╗\n"
        "  ║  TIP: The 'awp' command is not on your PATH.               ║\n"
        "  ║  You can always use:  python -m awp  instead.              ║\n"
        "  ╚══════════════════════════════════════════════════════════════╝\n"
    )

    if platform == "win32":
        # On Windows, scripts go to Scripts/ in the Python install or venv
        user_scripts = os.path.join(
            os.environ.get("APPDATA", ""),
            "Python",
            f"Python{sys.version_info.major}{sys.version_info.minor}",
            "Scripts",
        )
        print(f"  To fix permanently on Windows, add the Scripts folder to PATH:")
        print()
        if os.path.isdir(user_scripts):
            print(f"    setx PATH \"%PATH%;{user_scripts}\"")
        elif scripts_dir:
            print(f"    setx PATH \"%PATH%;{scripts_dir}\"")
        print()
        print(f"  Or reinstall Python and check 'Add Python to PATH' in the installer.")
    elif platform == "darwin":
        # macOS: typically ~/Library/Python/X.Y/bin or ~/.local/bin
        user_bin = os.path.expanduser(f"~/Library/Python/{sys.version_info.major}.{sys.version_info.minor}/bin")
        local_bin = os.path.expanduser("~/.local/bin")
        if os.path.isdir(user_bin):
            target = user_bin
        elif os.path.isdir(local_bin):
            target = local_bin
        else:
            target = scripts_dir or "/usr/local/bin"
        print(f"  To fix on macOS, add to your shell profile (~/.zshrc):")
        print()
        print(f"    echo 'export PATH=\"{target}:$PATH\"' >> ~/.zshrc && source ~/.zshrc")
    else:
        # Linux
        local_bin = os.path.expanduser("~/.local/bin")
        if os.path.isdir(local_bin):
            target = local_bin
        else:
            target = scripts_dir or "~/.local/bin"
        print(f"  To fix on Linux, add to your shell profile (~/.bashrc):")
        print()
        print(f"    echo 'export PATH=\"{target}:$PATH\"' >> ~/.bashrc && source ~/.bashrc")

    print()
    print(f"  Quick alternative (works everywhere, no PATH needed):")
    print(f"    python -m awp studio")
    print(f"    python -m awp validate <path>")
    print()


def _main() -> None:
    # Check PATH only when invoked via python -m awp (not via the awp script)
    # The awp script sets sys.argv[0] to the script path; __main__.py doesn't
    if not sys.argv[0].endswith(("awp", "awp.exe")):
        _check_awp_on_path()
    sys.exit(main())


if __name__ == "__main__":
    _main()
