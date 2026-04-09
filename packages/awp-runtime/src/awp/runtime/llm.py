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
    "ollama": ["OLLAMA_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "together": ["TOGETHER_API_KEY"],
    "fireworks": ["FIREWORKS_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
}


def _detect_provider(model: str) -> Optional[str]:
    """Detect provider from model name prefix like 'openai/gpt-4o'.

    Routing rules (per AWP spec):
    - ``provider/model-name`` format → always OpenRouter (the slash indicates
      an OpenRouter model path, even if the prefix is ``openai/`` or ``anthropic/``).
    - ``ollama/*`` → local Ollama.
    - Bare model names (``gpt-4o``, ``claude-sonnet-4``) → direct provider.
    """
    if "/" in model:
        prefix = model.split("/")[0].lower()
        # Only route to local providers for known local prefixes
        if prefix == "ollama":
            return "ollama"
        # Everything else with a slash is OpenRouter (provider/model format)
        return "openrouter"

    # Bare model names → direct provider
    lower = model.lower()
    if lower.startswith(("gpt-", "o1-", "o3", "dall-e", "text-", "tts-", "whisper")):
        return "openai"
    if lower.startswith("claude-"):
        return "anthropic"
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


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix from model name if present.

    E.g. ``openrouter/anthropic/claude-sonnet-4`` → ``anthropic/claude-sonnet-4``
    """
    if not model:
        return model
    detected = _detect_provider(model)
    if detected and model.startswith(f"{detected}/"):
        return model[len(detected) + 1 :]
    return model


def _get_fallback_model(failed_model: str) -> Optional[str]:
    """Get fallback model from global config.

    Checks ``LLM_MODEL`` env var. If it resolves to the same model that
    failed, also tries ``OPENROUTER_MODEL`` and ``OLLAMA_MODEL``.
    """
    candidates = [
        os.getenv("LLM_MODEL", ""),
        os.getenv("OPENROUTER_MODEL", ""),
        os.getenv("OLLAMA_MODEL", ""),
    ]
    for raw in candidates:
        candidate = _strip_provider_prefix(raw)
        if candidate and candidate != failed_model:
            return candidate
    return None


def _sanitize_tool_names(
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Sanitize tool names for LLM API compatibility.

    Some providers (Anthropic) require tool names to match
    ``^[a-zA-Z0-9_-]{1,128}$``. AWP uses dotted names like ``web.search``.

    Returns:
        Tuple of (sanitized tools list, mapping of sanitized→original names).
    """
    sanitized: list[dict[str, Any]] = []
    name_map: dict[str, str] = {}  # sanitized → original
    for tool in tools:
        t = dict(tool)
        if "function" in t:
            fn = dict(t["function"])
            original = fn["name"]
            safe = original.replace(".", "_")
            if safe != original:
                name_map[safe] = original
            fn["name"] = safe
            t["function"] = fn
        sanitized.append(t)
    return sanitized, name_map


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
        raw_model = model or os.getenv("LLM_MODEL", "")

        # Detect provider from model name
        detected = _detect_provider(raw_model) if raw_model else None

        # Strip provider prefix
        self.model = _strip_provider_prefix(raw_model)

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
        self.total_tokens_used: int = 0

        # Local models (Ollama) need longer timeouts and no API key
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            if not self.api_key:
                self.api_key = "ollama"  # placeholder
            if timeout == 120:  # only bump if user didn't set explicitly
                self.timeout = 600

        # Persistent HTTP client for connection pooling (reused across calls)
        self._client = httpx.Client(
            timeout=self.timeout,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )

    def close(self) -> None:
        """Close the persistent HTTP client."""
        self._client.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def chat(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[dict[str, Any]] = None,
        tool_choice: Optional[str | dict[str, Any]] = None,
        parallel_tool_calls: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Send a chat completion request with automatic fallback.

        If the primary model fails with a client error (400-499), retries
        once with the global fallback model from ``LLM_MODEL`` env var.

        Args:
            messages: Chat messages.
            model: Override model for this call.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            tools: Tool definitions (OpenAI function calling format).
            response_format: Structured output schema.
            tool_choice: Tool selection strategy — ``"auto"``, ``"none"``,
                ``"required"``, or a specific tool name.
            parallel_tool_calls: Whether the model may issue multiple tool
                calls in a single response. ``None`` = provider default.

        Returns:
            Raw API response dict.
        """
        # Only strip prefix from explicit overrides; self.model is already
        # stripped during __init__, so stripping again would mangle model
        # names like "openai/gpt-5-mini" into just "gpt-5-mini".
        if model:
            use_model = _strip_provider_prefix(model)
        else:
            use_model = self.model
        if not use_model:
            raise RuntimeError(
                "No model configured. Set LLM_MODEL env var or pass model=."
            )

        try:
            return self._do_chat(
                use_model,
                messages,
                temperature,
                max_tokens,
                tools,
                response_format,
                tool_choice,
                parallel_tool_calls,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if 400 <= status < 500:
                fallback = _get_fallback_model(use_model)
                if fallback and fallback != use_model:
                    logger.warning(
                        "Model '%s' failed (%d), falling back to '%s'",
                        use_model,
                        status,
                        fallback,
                    )
                    return self._do_chat(
                        fallback,
                        messages,
                        temperature,
                        max_tokens,
                        tools,
                        response_format,
                        tool_choice,
                        parallel_tool_calls,
                    )
            raise

    def _do_chat(
        self,
        use_model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: Optional[int],
        tools: Optional[list[dict[str, Any]]],
        response_format: Optional[dict[str, Any]],
        tool_choice: Optional[str | dict[str, Any]] = None,
        parallel_tool_calls: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Execute a single chat completion request."""
        # Apply prompt caching for OpenRouter: mark system messages so the
        # provider can cache the (large, mostly-static) system prompt across
        # calls within the same session.
        if self._provider == "openrouter" and messages:
            messages = self._apply_prompt_caching(messages)

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            sanitized_tools, _ = _sanitize_tool_names(tools)
            payload["tools"] = sanitized_tools
        if response_format is not None:
            payload["response_format"] = response_format

        # Tool calling control parameters (OpenRouter / OpenAI compatible)
        if tool_choice is not None:
            if isinstance(tool_choice, str) and tool_choice not in (
                "auto",
                "none",
                "required",
            ):
                # Specific tool name → force that tool
                safe_name = tool_choice.replace(".", "_")
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": safe_name},
                }
            else:
                payload["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = parallel_tool_calls

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"

        # OpenRouter-specific headers for better rate-limiting and tracking
        if self._provider == "openrouter":
            headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "AWP Runtime")
            app_url = os.getenv("OPENROUTER_APP_URL", "")
            if app_url:
                headers["HTTP-Referer"] = app_url

        logger.debug(
            "LLM request: model=%s, messages=%d, tools=%d",
            use_model,
            len(messages),
            len(tools or []),
        )

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()

        result = resp.json()

        # Accumulate token usage from API response
        usage = result.get("usage")
        if isinstance(usage, dict):
            total = usage.get("total_tokens", 0)
            # Fallback: sum prompt + completion if total is missing/zero
            if not total:
                prompt = usage.get("prompt_tokens", 0)
                completion = usage.get("completion_tokens", 0)
                total = (prompt or 0) + (completion or 0)
            # Accept int, float, or numeric string
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = 0
            self.total_tokens_used += total

        return result

    @staticmethod
    def _apply_prompt_caching(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Add cache_control to system messages for provider-side caching.

        OpenRouter and Anthropic support prompt caching via a
        ``cache_control`` field on message content blocks.  This marks
        system messages as cacheable so repeated calls with the same
        system prompt (the common case in the delegation loop) can skip
        re-processing the prompt prefix.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system" and isinstance(msg.get("content"), str):
                out.append({
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": msg["content"],
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                })
            else:
                out.append(msg)
        return out

    def chat_stream_text(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Stream a chat completion, returning the full text when done.

        Uses SSE streaming to get faster time-to-first-token. The full
        text is still returned as a single string (streaming is used for
        network efficiency, not incremental processing).
        """
        use_model = model or self.model
        if not use_model:
            raise RuntimeError("No model configured")

        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "ollama":
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self._provider == "openrouter":
            headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "AWP Runtime")

        chunks: list[str] = []
        with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    # Try to get usage from the final chunk
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        chunks.append(content)
                    # Capture usage from final chunk (OpenRouter sends it)
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        total = usage.get("total_tokens", 0)
                        if not total:
                            total = (usage.get("prompt_tokens", 0) or 0) + (
                                usage.get("completion_tokens", 0) or 0
                            )
                        try:
                            self.total_tokens_used += int(total)
                        except (TypeError, ValueError):
                            pass
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

        return "".join(chunks)

    def chat_stream_json(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Stream a chat completion and parse the result as JSON."""
        text = self.chat_stream_text(messages, **kwargs)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
        logger.warning("chat_stream_json: could not parse JSON, wrapping raw text")
        return {"result": text, "confidence": 0.0, "_parse_failure": True}

    def chat_text(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        """Return just the assistant's text content.

        Handles reasoning models that may put output in the ``reasoning``
        field when ``content`` is null or empty.
        """
        data = self.chat(messages, **kwargs)
        choices = data.get("choices", [])
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        content = msg.get("content", "") or ""
        if not content:
            # Reasoning models (e.g. Nemotron) may return content in
            # the reasoning field when max_tokens is constrained
            reasoning = msg.get("reasoning", "")
            if reasoning:
                content = reasoning
        return content

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Parse the assistant's response as JSON with robust fallback."""
        text = self.chat_text(messages, **kwargs)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        # Strategy 1: direct parse
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass
        # Strategy 2: extract first {...} block via brace matching
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
        # Strategy 3: return wrapped text so callers don't crash
        logger.warning("chat_json: could not parse JSON, wrapping raw text")
        return {"result": text, "confidence": 0.0, "_parse_failure": True}

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_executor: Any,
        max_rounds: int = 10,
        tool_choice: Optional[str | dict[str, Any]] = None,
        parallel_tool_calls: Optional[bool] = None,
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
            tool_choice: Tool selection strategy (``"auto"``, ``"none"``,
                ``"required"``, or a specific tool name).
            parallel_tool_calls: Allow parallel tool calls per response.

        Returns:
            Final assistant message dict with 'content'.
        """
        current_messages = list(messages)

        # Build sanitized→original name mapping for tool executor
        _, name_map = _sanitize_tool_names(tools)

        # Repeat-detector: if the model issues the same (tool, args) call
        # 3 times in a row, the loop is stuck (model not learning from
        # the error response). Abort early with an explicit hint instead
        # of burning all max_rounds.
        recent_calls: list[tuple[str, str]] = []
        REPEAT_THRESHOLD = 3

        for round_num in range(max_rounds):
            # On the first round, force tool usage when caller didn't specify
            # a preference. This prevents weaker models from skipping tools
            # entirely and returning empty text responses.
            effective_choice = tool_choice
            if effective_choice is None and round_num == 0 and tools:
                effective_choice = "required"

            data = self.chat(
                current_messages,
                tools=tools,
                tool_choice=effective_choice,
                parallel_tool_calls=parallel_tool_calls,
                **kwargs,
            )
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "")

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg

            # Log warning if finish_reason is inconsistent with tool_calls
            if finish_reason and finish_reason != "tool_calls":
                logger.warning(
                    "Got tool_calls but finish_reason='%s' (expected 'tool_calls')",
                    finish_reason,
                )

            # Append assistant message with tool calls
            current_messages.append(msg)

            # Execute each tool call
            for tc in tool_calls:
                fn = tc.get("function", {})
                sanitized_name = fn.get("name", "")
                # Map back to original dotted name for the tool registry
                tool_name = name_map.get(sanitized_name, sanitized_name)
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as jde:
                    logger.warning(
                        "Tool call [%d]: %s has malformed arguments: %s",
                        round_num, tool_name, raw_args[:200],
                    )
                    result = {
                        "ok": False,
                        "status": 400,
                        "data": {},
                        "error": (
                            f"Invalid JSON in tool arguments: {jde}. "
                            f"Raw arguments: {raw_args[:300]}. "
                            "Please retry with valid JSON arguments."
                        ),
                    }
                    current_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(result, default=str),
                        }
                    )
                    continue

                logger.info("Tool call [%d]: %s(%s)", round_num, tool_name, args)

                # Repeat-detection: same (tool, args) signature in a row
                call_sig = (tool_name, raw_args[:500])
                recent_calls.append(call_sig)
                if (
                    len(recent_calls) >= REPEAT_THRESHOLD
                    and len(set(recent_calls[-REPEAT_THRESHOLD:])) == 1
                ):
                    logger.warning(
                        "Tool call loop stuck: %s called %d times with "
                        "identical arguments — aborting worker loop",
                        tool_name, REPEAT_THRESHOLD,
                    )
                    abort_msg = {
                        "ok": False,
                        "status": 500,
                        "data": {},
                        "error": (
                            f"ABORTED: You called `{tool_name}` "
                            f"{REPEAT_THRESHOLD} times in a row with the "
                            f"same arguments. The previous error responses "
                            f"are above — read them, FIX the underlying "
                            f"issue (e.g. syntax error, wrong path), then "
                            f"either call the tool with DIFFERENT arguments "
                            f"or stop calling tools and return your final "
                            f"answer with `confidence` reflecting that the "
                            f"task could not be completed."
                        ),
                    }
                    current_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": json.dumps(abort_msg, default=str),
                        }
                    )
                    # Force one more LLM round so the model can produce a
                    # final answer with the abort context, then exit.
                    final = self.chat(
                        current_messages,
                        tools=tools,
                        tool_choice="none",  # NO more tool calls
                        **kwargs,
                    )
                    final_msg = final.get("choices", [{}])[0].get("message", {})
                    return final_msg or current_messages[-1]

                try:
                    result = tool_executor(tool_name, args)
                except Exception as exc:
                    result = {"ok": False, "status": 500, "data": {}, "error": str(exc)}

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result, default=str),
                    }
                )

        # Max rounds reached -- return last message
        logger.warning("Tool calling loop reached max rounds (%d)", max_rounds)
        return current_messages[-1] if current_messages else {}
