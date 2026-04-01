"""AgentWorkflow — Programmatic A4 delegation loop for arbitrary data + tasks."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from awp.data.inputs import prepare_workspace
from awp.data.prompts import build_manager_system_prompt
from awp.models.capabilities import SandboxConfig
from awp.models.orchestration import (
    CodeModeEnforcement,
    DelegationBudget,
    DelegationLoggingConfig,
    DelegationLoopConfig,
    DelegationLoopModels,
    HistoryConfig,
    RateLimitEnforcement,
    SandboxEnforcement,
    StallDetectionConfig,
    ValidationConfig,
    WorkerPolicy,
    WorkerPolicyEnforced,
)
from awp.runtime.delegation_loop_runner import DelegationLoopRunner
from awp.runtime.executor_factory import create_executor
from awp.runtime.external_tools import ExternalToolSpec, normalize_external_tools
from awp.runtime.skill_loader import SkillBundle, load_external_skills
from awp.runtime.tools import ToolRegistry

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Universal agent workflow that takes arbitrary inputs + task and returns a JSON dict.

    Wraps AWP's A4 DelegationLoopRunner with a simple programmatic API.
    No YAML workflow files required.

    Parameters
    ----------
    inputs : dict[str, Any]
        Arbitrary inputs. Values can be DataFrames, numpy ndarrays,
        image file paths (str to .png/.jpg/etc.), general file paths (str),
        dicts, lists, strings, numbers, bytes, or None. Each is automatically
        classified and prepared for the agent workspace.
    task : str
        Human-readable task description.
    model : str
        LLM model identifier (e.g. "openrouter/anthropic/claude-sonnet-4").
        Required — no default.
    api_key : str, optional
        LLM API key. Falls back to LLM_API_KEY env var.
    worker_model : str, optional
        Model for worker agents. Defaults to ``model``.
    max_loops : int
        Maximum delegation loop iterations.
    max_total_tokens : int
        Maximum total LLM tokens.
    max_wall_time : int
        Maximum wall time in seconds.
    max_tool_calls : int
        Maximum tool invocations.
    max_total_workers : int
        Maximum worker agents spawned.
    max_depth : int
        Maximum recursive delegation depth.
    sandbox : str
        Sandbox type: "subprocess", "docker", "venv", or "none".
    packages : list[str]
        Extra pip packages to install in the sandbox.
    output_dir : str, optional
        Directory for output artifacts. If None, uses a temp directory.
    verbose : bool
        Enable verbose logging.
    code_mode : bool
        Enable code_mode for workers (Python execution). Default True.
    tool_creation : bool
        Enable dynamic tool creation for workers. Default True.
    tools : list[str], optional
        Tools available to workers. Defaults to code.execute + file tools.
    forbidden_tools : list[str], optional
        Tools workers may not use.
    secrets : dict[str, str], optional
        API keys and secrets injected into the tool registry. Merged with
        secrets from secrets.yaml / .env / environment variables. Tools
        declare which secrets they need — the manager never sees secret values.
    skills : list[str | Path], optional
        External skills for the manager agent. Each entry can be:
        - A path to a .md file (single skill)
        - A path to a directory with SKILL.md + optional references/ and examples/
        - A path to a .zip or .skill archive containing the same structure
        The manager sees all skills and selectively forwards them to workers.
    external_tools : list, optional
        External tools available to all agents. Each entry can be:
        - An ExternalToolSpec instance
        - A dict with name, handler, and optional description/parameters/secrets
        - A decorated callable (@ExternalTool)
        - A list of ExternalToolSpec from ExternalTool.from_mcp()
    """

    def __init__(
        self,
        inputs: dict[str, Any],
        task: str,
        model: str,
        *,
        api_key: str | None = None,
        worker_model: str | None = None,
        max_loops: int = 100,
        max_total_tokens: int = 1_000_000,
        max_wall_time: int = 3000,
        max_tool_calls: int = 100,
        max_total_workers: int = 100,
        max_depth: int = 10,
        sandbox: str = "subprocess",
        packages: list[str] | None = None,
        output_dir: str | None = None,
        verbose: bool = False,
        code_mode: bool = True,
        tool_creation: bool = True,
        tools: list[str] | None = None,
        forbidden_tools: list[str] | None = None,
        secrets: dict[str, str] | None = None,
        skills: list[str | Path] | None = None,
        external_tools: list[Any] | None = None,
        experiment_context: str | None = None,
    ) -> None:
        if not model:
            raise ValueError(
                "model is required (e.g. 'openrouter/anthropic/claude-sonnet-4')"
            )
        if not task:
            raise ValueError("task is required")

        self.inputs = inputs or {}
        self.task = task
        self.model = model
        self.api_key = api_key
        self.worker_model = worker_model or model
        self.max_loops = max_loops
        self.max_total_tokens = max_total_tokens
        self.max_wall_time = max_wall_time
        self.max_tool_calls = max_tool_calls
        self.max_total_workers = max_total_workers
        self.max_depth = max_depth
        self.sandbox = sandbox
        self.packages = packages or []
        self.output_dir = output_dir
        self.verbose = verbose
        self.code_mode = code_mode
        self.tool_creation = tool_creation
        self.tools = tools if tools is not None else [
            "code.execute",
            "file.read",
            "file.write",
            "file.list",
            "file.delete",
            "arithmetic.add",
            "arithmetic.subtract",
            "arithmetic.multiply",
            "arithmetic.divide",
        ]
        self.forbidden_tools = forbidden_tools if forbidden_tools is not None else [
            "shell.execute",
            "file.write_outside_workspace",
        ]
        self.secrets = secrets or {}
        self.skills = skills or []
        self.external_tools = external_tools or []
        self.experiment_context = experiment_context

    def run(self) -> dict[str, Any]:
        """Execute the workflow and return results as a dict.

        Returns
        -------
        dict with keys:
            - status: "complete" | "failed" | "budget_exceeded" | "error"
            - result: arbitrary result dict from the manager
            - artifacts: list of output file paths
            - logs: list of iteration log strings
            - metadata: dict with loops, tokens_used, wall_time, workers_spawned
        """
        if self.verbose:
            logging.basicConfig(level=logging.DEBUG)
            # Suppress noisy HTTP transport logs — keep AWP + httpx request lines
            for noisy in (
                "httpcore",
                "httpcore.connection",
                "httpcore.http11",
                "hpack",
            ):
                logging.getLogger(noisy).setLevel(logging.WARNING)
        else:
            logging.basicConfig(level=logging.INFO)

        # Set API key if provided
        if self.api_key:
            os.environ["LLM_API_KEY"] = self.api_key

        # Create workspace
        if self.output_dir:
            workspace_dir = Path(self.output_dir).resolve()
            workspace_dir.mkdir(parents=True, exist_ok=True)
            temp_dir_obj = None
        else:
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="awp_data_")
            workspace_dir = Path(temp_dir_obj.name)

        try:
            return self._execute(workspace_dir)
        finally:
            if temp_dir_obj is not None:
                temp_dir_obj.cleanup()

    def _execute(self, workspace_dir: Path) -> dict[str, Any]:
        """Internal execution logic."""
        # Prepare sub-directories
        (workspace_dir / "workspace").mkdir(exist_ok=True)
        (workspace_dir / "output").mkdir(exist_ok=True)

        # 0. Resolve Source objects in inputs (fetch remote data)
        from awp.data.sources import Source

        has_sources = any(isinstance(v, Source) for v in self.inputs.values())
        if has_sources:
            from awp.data.resolver import InputResolver

            resolver = InputResolver(
                secrets=self.secrets,
                cache_dir=workspace_dir / ".source_cache",
            )
            resolved_inputs = resolver.resolve_all(self.inputs)
            logger.info("Resolved %d Source inputs", sum(
                1 for v in self.inputs.values() if isinstance(v, Source)
            ))
        else:
            resolved_inputs = self.inputs

        # 1. Prepare inputs
        logger.info("Preparing inputs in workspace: %s", workspace_dir)
        input_manifest = prepare_workspace(resolved_inputs, workspace_dir / "workspace")

        # 2. Build delegation loop config
        config = self._build_config()

        # 2b. Load external skills
        skill_bundles: list[SkillBundle] = []
        if self.skills:
            skill_bundles = load_external_skills(self.skills)
            logger.info("Loaded %d external skills", len(skill_bundles))

        # 2c. Normalize external tools
        ext_tool_specs: list[ExternalToolSpec] = []
        if self.external_tools:
            ext_tool_specs = normalize_external_tools(self.external_tools)
            logger.info("Normalized %d external tools", len(ext_tool_specs))

        # 3. Build custom manager system prompt (with skills)
        manager_prompt = build_manager_system_prompt(
            input_manifest=input_manifest,
            sandbox_type=self.sandbox,
            forbidden_tools=self.forbidden_tools,
            max_tools_per_worker=config.worker_policy.enforced.codemode.max_tools_per_worker,
            code_mode=self.code_mode,
            tool_creation=self.tool_creation,
            skill_bundles=skill_bundles,
            external_tool_names=[s.name for s in ext_tool_specs],
            has_experiment_context=bool(self.experiment_context),
        )

        # Append experiment context (previous run results, memory) if available
        if self.experiment_context:
            manager_prompt += "\n" + self.experiment_context

        # Write manager prompt to workspace for the DelegationLoopRunner
        manager_dir = workspace_dir / "agents" / "manager"
        manager_dir.mkdir(parents=True, exist_ok=True)
        self._write_manager_agent(manager_dir, manager_prompt)

        # 4. Build tool registry with code executor
        tool_registry = ToolRegistry(workflow_dir=workspace_dir)
        sandbox_cfg = SandboxConfig(
            enabled=True,
            type=self.sandbox,
            packages=self.packages,
            pip_install=bool(self.packages),
        )
        code_executor = create_executor(
            sandbox_cfg, working_dir=workspace_dir / "workspace"
        )
        tool_registry.set_code_executor(code_executor)

        # 4b. Inject secrets
        if self.secrets:
            tool_registry.inject_secrets(self.secrets)
            logger.info("Injected %d secrets into tool registry", len(self.secrets))

        # 4c. Register external tools
        for spec in ext_tool_specs:
            tool_registry._register(
                spec.name,
                spec.handler,
                spec.parameters,
                spec.description,
                secrets_keys=spec.secrets if spec.secrets else None,
            )
            logger.info("Registered external tool: %s", spec.name)

        # 5. Run the delegation loop
        logger.info("Starting delegation loop: task=%s", self.task[:80])
        runner = DelegationLoopRunner(
            workflow_dir=workspace_dir,
            config=config,
            tool_registry=tool_registry,
            manager_model=self.model,
            worker_model=self.worker_model,
        )

        raw_result = runner.run(self.task)
        run_id = runner._run_id

        # 5b. Print debug report (same as `awp run --debug`)
        if self.verbose:
            self._print_debug_report(workspace_dir, runner)

        # 6. Collect artifacts (run_id-isolated output directory)
        output_dir = workspace_dir / "output" / run_id
        if not output_dir.exists():
            # Fallback to flat output/ for backwards compatibility
            output_dir = workspace_dir / "output"
        artifacts = self._collect_artifacts(output_dir)

        # 7. Build response
        loop_result = raw_result.get("delegation_loop", {})
        budget = runner._budget

        status = self._determine_status(loop_result)

        return {
            "status": status,
            "result": loop_result,
            "artifacts": artifacts,
            "metadata": {
                "run_id": run_id,
                "loops": budget.loops_used,
                "tokens_used": budget.tokens_consumed,
                "wall_time": round(budget.wall_time_elapsed, 2),
                "workers_spawned": budget.workers_spawned,
                "tool_calls": budget.tool_calls_used,
                "workspace": str(workspace_dir),
                "output_dir": str(output_dir),
            },
        }

    def _build_config(self) -> DelegationLoopConfig:
        """Build a DelegationLoopConfig from the user's parameters."""
        return DelegationLoopConfig(
            manager="agents/manager",
            models=DelegationLoopModels(
                manager=self.model,
                worker=self.worker_model,
            ),
            budget=DelegationBudget(
                max_loops=self.max_loops,
                max_total_workers=self.max_total_workers,
                max_total_tokens=self.max_total_tokens,
                max_wall_time=self.max_wall_time,
                max_tool_calls=self.max_tool_calls,
                max_depth=self.max_depth,
            ),
            worker_policy=WorkerPolicy(
                enforced=WorkerPolicyEnforced(
                    sandbox=SandboxEnforcement(
                        type=self.sandbox,
                    ),
                    codemode=CodeModeEnforcement(
                        max_tools_per_worker=10,
                    ),
                    rate_limiting=RateLimitEnforcement(),
                    forbidden_tools=self.forbidden_tools,
                ),
                manager_controlled=[
                    "instructions",
                    "skills",
                    "tools_allowed",
                    "output_contract",
                    "codemode.enabled",
                    "codemode.tool_creation",
                ],
            ),
            termination=StallDetectionConfig(
                enabled=True,
                window=3,
                min_confidence_delta=0.05,
                action="warn_then_stop",
            ),
            validation=ValidationConfig(),
            history=HistoryConfig(
                rolling_summary=True,
                full_results_window=3,
                persist_to_disk=True,
            ),
            logging=DelegationLoggingConfig(
                format="dual",
                persist_artifacts=True,
            ),
        )

    def _write_manager_agent(self, manager_dir: Path, system_prompt: str) -> None:
        """Write a minimal agent.awp.yaml for the manager agent."""
        import yaml

        # Write system prompt to a file (prompt.system is a file path)
        prompt_path = manager_dir / "system_prompt.md"
        prompt_path.write_text(system_prompt, encoding="utf-8")

        agent_config = {
            "awp_agent": "1.0.0",
            "identity": {
                "id": "manager",
                "role": "Data Workflow Manager",
                "version": "1.0.0",
                "description": "Universal data workflow manager agent",
            },
            "runtime": {
                "class_name": "Agent",
                "strategy_folder": "workflow",
            },
            "model": {
                "name": self.model,
                "temperature": 0.2,
                "max_tokens": 4096,
            },
            "prompt": {
                "system": "system_prompt.md",
            },
            "output": {
                "format": "json",
            },
        }

        config_path = manager_dir / "agent.awp.yaml"
        config_path.write_text(
            yaml.dump(agent_config, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _collect_artifacts(self, output_dir: Path) -> list[str]:
        """Collect all files in the output directory."""
        if not output_dir.exists():
            return []
        artifacts = []
        for p in sorted(output_dir.rglob("*")):
            if p.is_file():
                artifacts.append(str(p))
        return artifacts

    @staticmethod
    def _determine_status(loop_result: dict[str, Any]) -> str:
        """Map delegation loop result to a status string."""
        if loop_result.get("error"):
            return "error"
        if loop_result.get("partial"):
            reason = loop_result.get("termination_reason", "")
            if "budget" in reason:
                return "budget_exceeded"
            if "stall" in reason:
                return "stall_detected"
            return "partial"
        if loop_result.get("confidence", 0) > 0:
            return "complete"
        return "failed"

    def _print_debug_report(
        self, workspace_dir: Path, runner: DelegationLoopRunner
    ) -> None:
        """Print delegation loop debug report (same output as `awp run --debug`)."""

        total_time = runner._budget.wall_time_elapsed

        # Header
        config = self._build_config()
        b = config.budget
        print(f"\n{'=' * 60}")
        print("  AWP DELEGATION LOOP DEBUG REPORT")
        print(f"{'=' * 60}")
        print(f"  Model:         {self.model}")
        print(f"  Worker model:  {self.worker_model}")
        print(
            f"  Budget:        loops={b.max_loops}, workers={b.max_total_workers}, "
            f"tokens={b.max_total_tokens:,}, "
            f"wall_time={b.max_wall_time}s, depth={b.max_depth}"
        )
        print()

        # Reuse CLI's _print_delegation_loop_details
        try:
            from awp.cli import _print_delegation_loop_details
        except ImportError:
            print("  [WARN] Could not import debug printer from awp.cli")
            return

        # Find the latest run directory
        runs_base = workspace_dir / "workspace" / "runs"
        if not runs_base.exists():
            # DelegationLoopRunner writes to workspace_dir directly
            runs_base = workspace_dir / "runs"

        run_dirs = sorted(runs_base.glob("*")) if runs_base.exists() else []
        latest_run = run_dirs[-1] if run_dirs else None

        if latest_run:
            _print_delegation_loop_details(latest_run, total_time)
        else:
            print("  [WARN] No workspace run logs found.")
