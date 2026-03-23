"""Provider-agnostic LLM client for the AWP standalone runtime.

Supports any OpenAI-compatible API (OpenAI, OpenRouter, Ollama, Anthropic
via proxy, vLLM, LiteLLM, Together, Groq, Fireworks, etc.).

Provider detection order:
1. Explicit base_url parameter
2. LLM_BASE_URL environment variable
3. Auto-detect from model name prefix (openai/, anthropic/, ollama/, etc.)
4. Fallback: check which API key env vars are set

No provider lock-in. Any endpoint that speaks the OpenAI chat completions
protocol works out of the box.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Known provider base URLs (all OpenAI-compatible)
PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "perplexity": "https://api.perplexity.ai",
}

# Environment variable names per provider
PROVIDER_KEY_VARS: dict[str, list[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "fireworks": ["FIREWORKS_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
}


def _detect_provider(model: str) -> Optional[str]:
    """Detect provider from model name prefix like 'openai/gpt-4o'."""
    if "/" in model:
        prefix = model.split("/")[0].lower()
        if prefix in PROVIDER_URLS:
            return prefix
        # Common aliases
        aliases = {
            "gpt": "openai",
            "o1": "openai",
            "claude": "openrouter",  # Claude via OpenRouter
            "llama": "ollama",
            "qwen": "openrouter",
            "gemma": "ollama",
        }
        if prefix in aliases:
            return aliases[prefix]
    return None


def _find_api_key(provider: Optional[str] = None) -> tuple[str, str]:
    """Find API key from environment, return (key, provider_name).

    Checks in order:
    1. LLM_API_KEY (universal override)
    2. Provider-specific key (if provider known)
    3. All known provider keys (first one found)
    """
    # Universal override
    key = os.getenv("LLM_API_KEY", "")
    if key:
        return key, provider or "custom"

    # Provider-specific
    if provider and provider in PROVIDER_KEY_VARS:
        for var in PROVIDER_KEY_VARS[provider]:
            key = os.getenv(var, "")
            if key:
                return key, provider

    # Scan all providers
    for prov, vars_ in PROVIDER_KEY_VARS.items():
        for var in vars_:
            key = os.getenv(var, "")
            if key:
                return key, prov

    return "", provider or "unknown"


def _find_base_url(provider: Optional[str]) -> str:
    """Determine base URL from provider or environment."""
    env_url = os.getenv("LLM_BASE_URL", "")
    if env_url:
        return env_url.rstrip("/")
    if provider and provider in PROVIDER_URLS:
        return PROVIDER_URLS[provider]
    return PROVIDER_URLS["openrouter"]  # safe default


class LLMClient:
    """Provider-agnostic OpenAI-compatible chat completion client.

    Auto-detects the provider from model name, environment variables,
    or explicit configuration. Supports tool calling.

    Configuration priority:
    1. Constructor parameters (highest)
    2. Environment variables (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
    3. Provider-specific env vars (OPENAI_API_KEY, OPENROUTER_API_KEY, ...)
    4. Auto-detection from model name prefix

    Examples::

        # Auto-detect everything from env vars
        client = LLMClient()

        # Explicit provider
        client = LLMClient(model="gpt-4o", base_url="https://api.openai.com/v1")

        # Ollama (no API key needed)
        client = LLMClient(model="llama3", base_url="http://localhost:11434/v1")

        # OpenRouter with model prefix
        client = LLMClient(model="openai/gpt-4o")  # auto-detects OpenRouter
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self.model = model or os.getenv("LLM_MODEL", "")

        # Detect provider from model name
        detected = _detect_provider(self.model) if self.model else None

        # Resolve API key
        if api_key:
            self.api_key = api_key
        else:
            self.api_key, detected = _find_api_key(detected)

        # Resolve base URL
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = _find_base_url(detected)

        self.timeout = timeout
        self._provider = detected

        # Ollama doesn't need an API key
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            if not self.api_key:
                self.api_key = "ollama"  # placeholder

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Args:
            messages: Chat messages.
            model: Override model for this call.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            tools: Tool definitions (OpenAI function calling format).
            response_format: Structured output schema.

        Returns:
            Raw API response dict.
        """
        use_model = model or self.model
        if not use_model:
            raise RuntimeError(
                "No model configured. Set LLM_MODEL env var or pass model=."
            )

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["response_format"] = response_format

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.debug("LLM request: model=%s, messages=%d, tools=%d",
                      use_model, len(messages), len(tools or []))

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()

        return resp.json()

    def chat_text(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Return just the assistant's text content."""
        data = self.chat(messages, **kwargs)
        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "") or ""

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Parse the assistant's response as JSON."""
        text = self.chat_text(messages, **kwargs)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        return json.loads(cleaned)

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: Any,
        max_rounds: int = 10,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Chat with automatic tool calling loop.

        Sends messages to LLM. If LLM requests tool calls, executes
        them via tool_executor and feeds results back. Repeats until
        LLM produces a final text response or max_rounds is reached.

        Args:
            messages: Initial messages.
            tools: Tool definitions in OpenAI format.
            tool_executor: Callable(name, arguments) -> result dict.
            max_rounds: Max tool-calling rounds.

        Returns:
            Final assistant message dict with 'content'.
        """
        current_messages = list(messages)

        for round_num in range(max_rounds):
            data = self.chat(current_messages, tools=tools, **kwargs)
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg

            # Append assistant message with tool calls
            current_messages.append(msg)

            # Execute each tool call
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                logger.info("Tool call [%d]: %s(%s)", round_num, tool_name, args)

                try:
                    result = tool_executor(tool_name, args)
                except Exception as exc:
                    result = {"ok": False, "status": 500, "data": {}, "error": str(exc)}

                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, default=str),
                })

        # Max rounds reached -- return last message
        logger.warning("Tool calling loop reached max rounds (%d)", max_rounds)
        return current_messages[-1] if current_messages else {}
