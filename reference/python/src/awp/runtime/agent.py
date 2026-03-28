"""Standalone AWP Agent -- Full-featured, runs without external framework.

Implements all AWP agent capabilities:
- Config loading from agent.awp.yaml
- System prompt + user prompt assembly
- Skill injection (project-level and agent-level)
- Memory injection (MEMORY.md into system prompt)
- Output schema validation
- Tool calling loop (built-in + custom MCP tools)
- Context from previous agents (share_input)
- Output contract enforcement (R17 confidence)

Usage::

    from awp.runtime.agent import StandaloneAgent

    agent = StandaloneAgent(
        agent_dir=Path("my-workflow/agents/researcher"),
        workflow_dir=Path("my-workflow"),
    )
    result = agent.run("Research quantum computing", state={})
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ..agent import AWPAgent
from ..parser import parse_agent
from ..parser.manifest_parser import parse_manifest
from .llm import LLMClient
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def _resolve_model_name(config_name: str) -> str:
    """Resolve the effective model name.

    If the agent config has an empty or unset model name, fall back to
    the ``LLM_MODEL`` environment variable (typically set by the run
    wizard or the user's shell).
    """
    if config_name:
        return config_name
    env_model = os.getenv("LLM_MODEL", "")
    if env_model:
        return env_model
    return ""


class StandaloneAgent(AWPAgent):
    """AWP agent that runs standalone with full protocol support.

    Supports:
    - Loading config from agent.awp.yaml
    - System prompt + skills + memory injection
    - Tool calling via built-in + custom MCP tools
    - Output schema enforcement
    - Context from previous agents

    Args:
        agent_dir: Path to agent directory (containing agent.awp.yaml).
        workflow_dir: Path to workflow root directory.
        llm: Optional pre-configured LLMClient.
        tool_registry: Optional shared ToolRegistry.
    """

    def __init__(
        self,
        agent_dir: str | Path,
        workflow_dir: str | Path,
        llm: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self._agent_dir = Path(agent_dir)
        self._workflow_dir = Path(workflow_dir)
        self._config = parse_agent(self._agent_dir / "agent.awp.yaml")
        resolved_model = _resolve_model_name(self._config.model.name)
        self._llm = llm or LLMClient(model=resolved_model)
        if tool_registry:
            self._tools = tool_registry
        else:
            from .secrets import load_secrets

            secrets = load_secrets(self._workflow_dir)
            self._tools = ToolRegistry(self._workflow_dir, secrets=secrets)

        # Load manifest for memory/skill config
        manifest_path = self._workflow_dir / "workflow.awp.yaml"
        self._manifest = (
            parse_manifest(manifest_path) if manifest_path.exists() else None
        )

    @property
    def name(self) -> str:
        return self._config.identity.id

    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent with full AWP capabilities.

        1. Build system prompt (base + skills + memory)
        2. Build user message (template + context + schema + task)
        3. Determine if tools are enabled
        4. If tools: use tool calling loop
        5. If no tools: single LLM call, parse as JSON
        6. Enforce output contract (R17 confidence)
        7. Return {self.name: result}
        """
        state = state or {}

        # Build prompts
        system_prompt = self._build_system_prompt()
        user_content = self._build_user_message(task, state)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        llm_kwargs: dict[str, Any] = {
            "model": _resolve_model_name(self._config.model.name),
            "temperature": self._config.model.parameters.temperature,
            "max_tokens": self._config.model.parameters.max_tokens,
        }

        # Check if tools are enabled
        tools_enabled = False
        tool_defs: list[dict[str, Any]] = []
        caps = self._config.capabilities
        if caps and hasattr(caps, "tools") and caps.tools.enabled:
            tools_enabled = True
            allowed = caps.tools.allowed or None  # empty list = all
            tool_defs = self._tools.get_definitions(allowed)

        if tools_enabled and tool_defs:
            # Tool calling loop
            result = self._run_with_tools(messages, tool_defs, **llm_kwargs)
        else:
            # Single call, parse as JSON
            result = self._run_simple(messages, **llm_kwargs)

        # Enforce R17: confidence field
        if "confidence" not in result:
            result["confidence"] = 0.5

        return {self.name: result}

    # -- Execution modes ----------------------------------------------

    def _run_simple(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """Single LLM call, parse response as JSON."""
        try:
            return self._llm.chat_json(messages, **kwargs)
        except json.JSONDecodeError:
            # Try to extract JSON from within the response text
            text = self._llm.chat_text(messages, **kwargs)
            extracted = self._extract_json(text)
            if extracted is not None:
                return extracted
            logger.warning("Agent %s: non-JSON response, wrapping", self.name)
            return {"result": text, "confidence": 0.5}
        except Exception as exc:
            logger.error("Agent %s LLM error: %s", self.name, exc)
            return {"error": str(exc), "confidence": 0.0}

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Try to extract a JSON object from text that may contain extra content."""
        if not text:
            return None
        # Try the full text first
        stripped = text.strip()
        # Strip markdown fences
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            stripped = "\n".join(lines).strip()
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        # Find first { ... } block
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(text[start : i + 1])
                        if isinstance(result, dict):
                            return result
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
        return None

    def _run_with_tools(
        self, messages: list[dict], tool_defs: list[dict], **kwargs: Any
    ) -> dict[str, Any]:
        """LLM call with tool calling loop."""
        max_calls = 10
        tool_choice = None
        parallel_calls = None
        caps = self._config.capabilities
        if caps and hasattr(caps, "tools"):
            max_calls = caps.tools.max_calls or 10
            tool_choice = getattr(caps.tools, "tool_choice", None)
            parallel_calls = getattr(caps.tools, "parallel_calls", None)

        try:
            final_msg = self._llm.chat_with_tools(
                messages,
                tools=tool_defs,
                tool_executor=self._tools.call,
                max_rounds=max_calls,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_calls,
                **kwargs,
            )

            content = final_msg.get("content", "")
            if not content:
                return {"result": "No response", "confidence": 0.0}

            # Parse as JSON (try robust extraction)
            extracted = self._extract_json(content)
            if extracted is not None:
                return extracted
            return {"result": content, "confidence": 0.5}

        except Exception as exc:
            logger.error("Agent %s tool loop error: %s", self.name, exc)
            return {"error": str(exc), "confidence": 0.0}

    # -- Prompt building ----------------------------------------------

    def _build_system_prompt(self) -> str:
        """Assemble system prompt: base + skills + memory."""
        parts: list[str] = []

        # 1. Base system prompt — try config path first, then convention path
        base = ""
        if self._config.prompt.system:
            base = self._load_file(self._config.prompt.system)
        if not base:
            base = self._load_file("workflow/instructions/SYSTEM_PROMPT.md")
        if base:
            parts.append(base)
        else:
            parts.append(
                f"You are {self._config.identity.role}. "
                f"{self._config.identity.description}"
            )

        # 2. Skills injection
        skills = self._load_skills()
        if skills:
            parts.append("\n---\n\n## Skills\n")
            parts.append(skills)

        # 3. Memory injection (MEMORY.md)
        memory = self._load_memory()
        if memory:
            parts.append("\n---\n\n## Long-term Memory\n")
            parts.append(memory)

        return "\n".join(parts)

    def _build_user_message(self, task: str, state: Dict[str, Any]) -> str:
        """Assemble user message: template + context + schema + task."""
        parts: list[str] = []

        # User prompt template
        template = self._load_file("workflow/prompt/00_INTRO.md")
        if template:
            parts.append(template)

        # Additional prompt files
        if self._config.prompt.additional:
            for extra_path in self._config.prompt.additional:
                extra = self._load_file(f"workflow/{extra_path}")
                if extra:
                    parts.append(extra)

        # Context from previous agents
        context = self._extract_context(state)
        if context:
            parts.append("\n## Context from Previous Agents\n")
            parts.append(context)

        # Output schema instruction
        schema = self._load_output_schema()
        if schema:
            props = schema.get("properties", {})
            required = schema.get("required", [])
            parts.append("\n## Required Output Format\n")
            parts.append("Respond with a valid JSON object containing these fields:\n")
            for fname, fdef in props.items():
                req = " (REQUIRED)" if fname in required else ""
                desc = fdef.get("description", "")
                ftype = fdef.get("type", "any")
                parts.append(f"- `{fname}` ({ftype}){req}: {desc}")
            parts.append("\nRespond ONLY with the JSON object, no other text.")

        # Task
        parts.append(f"\n## Task\n\n{task}")

        return "\n".join(parts)

    # -- Loaders ------------------------------------------------------

    def _load_file(self, relative_path: str) -> str:
        """Load a text file relative to the agent directory."""
        p = self._agent_dir / relative_path
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    def _load_output_schema(self) -> Optional[dict[str, Any]]:
        p = self._agent_dir / "workflow" / "output_schema" / "output_schema.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def _load_skills(self) -> str:
        """Load and concatenate skills (project-level + agent-level)."""
        parts: list[str] = []

        # Project-level skills
        project_skills_dir = self._workflow_dir / "skills"
        if project_skills_dir.exists():
            for skill_dir in sorted(project_skills_dir.iterdir()):
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        parts.append(f"### {skill_dir.name}\n")
                        parts.append(skill_file.read_text(encoding="utf-8"))
                        parts.append("")
                elif skill_dir.suffix in (".md", ".skill"):
                    parts.append(skill_dir.read_text(encoding="utf-8"))
                    parts.append("")

        # Agent-level skills
        agent_skills_dir = self._agent_dir / "workflow" / "skills"
        if agent_skills_dir.exists():
            for skill_file in sorted(agent_skills_dir.rglob("*.md")):
                parts.append(skill_file.read_text(encoding="utf-8"))
                parts.append("")

        return "\n".join(parts).strip()

    def _load_memory(self) -> str:
        """Load MEMORY.md for injection into system prompt."""
        # Check agent-level memory config
        mem_cfg = self._config.memory
        if mem_cfg and hasattr(mem_cfg, "enabled") and not mem_cfg.enabled:
            return ""
        if mem_cfg and hasattr(mem_cfg, "long_term"):
            lt = mem_cfg.long_term
            if hasattr(lt, "inject") and not lt.inject:
                return ""

        # Check manifest-level memory config
        if self._manifest and self._manifest.memory:
            m = self._manifest.memory
            if hasattr(m, "enabled") and not m.enabled:
                return ""

        # Load MEMORY.md
        workspace = self._workflow_dir / "workspace"
        mem_file = workspace / "MEMORY.md"
        if mem_file.exists():
            content = mem_file.read_text(encoding="utf-8")
            # Truncate if needed
            max_tokens = 2000
            if (
                mem_cfg
                and hasattr(mem_cfg, "long_term")
                and hasattr(mem_cfg.long_term, "max_tokens")
            ):
                max_tokens = mem_cfg.long_term.max_tokens
            if len(content) > max_tokens * 4:  # rough char-to-token ratio
                content = content[: max_tokens * 4] + "\n...(truncated)"
            return content

        return ""

    def _extract_context(self, state: Dict[str, Any]) -> str:
        """Extract context from previous agent outputs respecting share_input."""
        context_parts: list[str] = []

        for key, value in state.items():
            if key.startswith("_") or key == "task":
                continue
            if isinstance(value, dict):
                context_parts.append(f"### {key}\n```json")
                context_parts.append(json.dumps(value, indent=2, default=str))
                context_parts.append("```\n")

        return "\n".join(context_parts)
