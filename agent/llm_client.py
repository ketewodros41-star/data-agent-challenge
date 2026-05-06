"""LLM client wrapper that supports OpenRouter and Anthropic backends."""

from __future__ import annotations

import json as _json
import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

try:
    import anthropic  # type: ignore
except ImportError:  # pragma: no cover
    anthropic = None

OPENROUTER_URL_DEFAULT = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_DEFAULT = "gemini-3.1-pro-preview"

GROQ_URL_DEFAULT = "https://api.groq.com/openai/v1"
GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"


class LLMResponseContent:
    def __init__(self, text: str):
        self.text = text


class LLMResponse:
    def __init__(self, text: str):
        self.content = [LLMResponseContent(text)]


# ── Tool-calling data classes ──────────────────────────────────────────────────


class LLMToolCall:
    """Represents a single tool call made by the LLM in a tool-calling response."""

    def __init__(self, id: str, name: str, input: Dict[str, Any]):
        self.id = id
        self.name = name
        self.input = input  # parsed dict of arguments

    def __repr__(self) -> str:
        return f"LLMToolCall(id={self.id!r}, name={self.name!r}, input={self.input!r})"


class LLMToolCallResponse:
    """
    Response from LLMClient.create_with_tools().

    Attributes:
        tool_calls: List of LLMToolCall objects. Empty when LLM returned text only.
        stop_reason: The LLM stop reason ("tool_use", "end_turn", "stop", etc.)
        text: Any text content returned alongside or instead of tool calls.
    """

    def __init__(self, tool_calls: List[LLMToolCall], stop_reason: str, text: str, usage: Optional[Dict[str, Any]] = None):
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.text = text
        self.usage = usage or {}

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def __repr__(self) -> str:
        return (
            f"LLMToolCallResponse(tool_calls={self.tool_calls!r}, "
            f"stop_reason={self.stop_reason!r}, text={self.text!r}, usage={self.usage!r})"
        )


# ── LLM Client ────────────────────────────────────────────────────────────────


class LLMClient:
    """Unified interface for Anthropic or OpenRouter chat completions."""

    def __init__(self):
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self._openrouter_url = os.getenv("OPENROUTER_URL", OPENROUTER_URL_DEFAULT)
        self._openrouter_model = os.getenv("OPENROUTER_MODEL", OPENROUTER_MODEL_DEFAULT)

        groq_api_key = os.getenv("GROQ_API_KEY", os.getenv("GR0Q_API_KEY", ""))
        self._groq_url = os.getenv("GROQ_URL", GROQ_URL_DEFAULT)
        self._groq_model = os.getenv("GROQ_MODEL", GROQ_MODEL_DEFAULT)

        if groq_api_key: groq_api_key = groq_api_key.strip(' "\'')
        if openrouter_api_key: openrouter_api_key = openrouter_api_key.strip(' "\'')

        backend_override = os.getenv("LLM_BACKEND", "").lower()

        if backend_override == "groq" or (not backend_override and groq_api_key):
            self._backend = "groq"
            self._groq_api_key = groq_api_key
            self._session = httpx.Client(timeout=30.0)
            self.messages = self
        elif backend_override == "openrouter" or (not backend_override and openrouter_api_key):
            self._backend = "openrouter"
            self._openrouter_api_key = openrouter_api_key
            self._session = httpx.Client(timeout=30.0)
            self.messages = self
        elif anthropic is not None and backend_override in ("anthropic", ""):
            self._backend = "anthropic"
            self._client = anthropic.Anthropic()
            self.messages = self._client.messages
        else:
            raise RuntimeError(
                "No LLM backend is available. Set LLM_BACKEND to groq/openrouter/anthropic with respective keys."
            )

    # ── Standard text completion ───────────────────────────────────────────

    def create(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        model: Optional[str] = None,
        system: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self._backend == "anthropic":
            resolved_model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            response = self._client.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
                **kwargs,
            )
            return LLMResponse(response.content[0].text)
        elif self._backend == "groq":
            resolved_model = model or os.getenv("GROQ_MODEL", self._groq_model)
            all_messages = []
            if system:
                all_messages.append({"role": "system", "content": system})
            all_messages.extend(messages)
            return self._create_groq_response(
                model=resolved_model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

        resolved_model = model or os.getenv("OPENROUTER_MODEL", self._openrouter_model)
        return self._create_openrouter_response(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    def _create_groq_response(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int],
        temperature: float,
        **kwargs: Any,
    ) -> LLMResponse:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        headers = {
            "Authorization": f"Bearer {self._groq_api_key}",
            "Content-Type": "application/json",
        }
        url = self._groq_url.rstrip("/") + "/chat/completions"
        response = self._session.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip()
            details = body or str(exc)
            raise RuntimeError(
                f"Groq request failed for model '{model}' at '{url}': {details}"
            ) from exc
        data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("Groq returned no choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, dict):
            text = content.get("text") or content.get("type") or ""
        else:
            text = str(content)

        return LLMResponse(text)

    def _create_openrouter_response(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int],
        temperature: float,
        **kwargs: Any,
    ) -> LLMResponse:
        final_model = os.getenv("OPENROUTER_MODEL", self._openrouter_model)
        payload: Dict[str, Any] = {
            "model": final_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kwargs)

        headers = {
            "Authorization": f"Bearer {self._openrouter_api_key}",
            "Content-Type": "application/json",
        }
        url = self._openrouter_url.rstrip("/") + "/chat/completions"
        response = self._session.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip()
            details = body or str(exc)
            raise RuntimeError(
                f"OpenRouter request failed for model '{final_model}' at '{url}': {details}"
            ) from exc
        data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, dict):
            text = content.get("text") or content.get("type") or ""
        else:
            text = str(content)

        return LLMResponse(text)

    # ── Tool-calling (agentic loop) ────────────────────────────────────────

    def create_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        system: Optional[str] = None,
        enable_caching: bool = True,
    ) -> LLMToolCallResponse:
        """
        Call the LLM with tool definitions available and return a structured response.

        This is used exclusively by AgenticLoop — it allows the LLM to emit structured
        tool calls (query_db, list_db, return_answer) that the loop then dispatches to
        MCPToolbox. No direct DB connections are made here.

        Args:
            messages: Conversation history. For Anthropic backend, role="tool" messages
                      are automatically converted to the Anthropic content block format
                      by _convert_messages_to_anthropic().
            tools: Tool definitions. Each dict must have:
                   {"name": str, "description": str, "input_schema": dict}
                   (Anthropic-style — OpenRouter path auto-converts to OpenAI format.)
            max_tokens: Max response tokens.
            temperature: Sampling temperature (0 = deterministic).
            system: Optional system prompt string.
            enable_caching: When True (default), place an ephemeral cache
                breakpoint on the first user message so that [tools + system +
                first user] becomes a cached prefix on Anthropic-compatible
                backends.  Harmless on providers that ignore cache_control.

        Returns:
            LLMToolCallResponse with:
              .tool_calls  — list of LLMToolCall (empty if LLM returned plain text)
              .stop_reason — raw stop reason from the backend
              .text        — any text content in the response
        """
        if self._backend == "anthropic":
            return self._create_with_tools_anthropic(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                enable_caching=enable_caching,
            )
        elif self._backend == "groq":
            return self._create_with_tools_groq(
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
            )
        return self._create_with_tools_openrouter(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            enable_caching=enable_caching,
        )

    def _create_with_tools_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        system: Optional[str],
        enable_caching: bool = True,
    ) -> LLMToolCallResponse:
        """Anthropic native tool-calling via the `tools=` parameter."""
        converted = _convert_messages_to_anthropic(messages)
        if enable_caching:
            converted = _with_cache_control(converted)

        kwargs: Dict[str, Any] = {
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "messages": converted,
            "tools": tools,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)

        tool_calls: List[LLMToolCall] = []
        text_parts: List[str] = []

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(
                    LLMToolCall(id=block.id, name=block.name, input=block.input)
                )
            elif block.type == "text":
                text_parts.append(block.text)

        return LLMToolCallResponse(
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            text=" ".join(text_parts).strip(),
            usage=_normalize_usage(getattr(response, "usage", None)),
        )

    def _create_with_tools_groq(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        system: Optional[str],
    ) -> LLMToolCallResponse:
        """Groq native tool-calling via the `tools=` JSON field."""
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

        all_messages: List[Dict[str, Any]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        final_model = os.getenv("GROQ_MODEL", self._groq_model)
        payload: Dict[str, Any] = {
            "model": final_model,
            "messages": all_messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self._groq_api_key}",
            "Content-Type": "application/json",
        }
        url = self._groq_url.rstrip("/") + "/chat/completions"
        response = self._session.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip()
            raise RuntimeError(
                f"Groq tool-call request failed: {body or str(exc)}"
            ) from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            err = data.get("error") or data
            raise RuntimeError(
                f"Groq returned no choices for tool call "
                f"(max_tokens={max_tokens}, model={final_model}): {err}"
            )

        message = choices[0].get("message", {})
        raw_tool_calls = message.get("tool_calls") or []
        text = message.get("content") or ""

        tool_calls: List[LLMToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except _json.JSONDecodeError:
                args = {}
            tool_calls.append(
                LLMToolCall(id=tc.get("id", ""), name=fn.get("name", ""), input=args)
            )

        stop_reason = choices[0].get("finish_reason", "")
        usage = _normalize_usage(data.get("usage"))

        return LLMToolCallResponse(
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            text=str(text).strip() if text else "",
            usage=usage,
        )

    def _create_with_tools_openrouter(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        system: Optional[str],
        enable_caching: bool = True,
    ) -> LLMToolCallResponse:
        """OpenRouter OpenAI-compatible tool-calling via the `tools=` JSON field."""
        # Convert Anthropic-style input_schema to OpenAI function schema format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

        all_messages: List[Dict[str, Any]] = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        final_model = os.getenv("OPENROUTER_MODEL", self._openrouter_model)
        # cache_control markers are honoured only by Anthropic models.  For
        # Gemini / OpenAI via OpenRouter, the resulting content-as-list format
        # with unknown `cache_control` fields has been observed to occasionally
        # cause the model to return an empty response (no text, no tool call)
        # on long tool-call histories.  Gemini already does implicit caching
        # automatically, so we gain nothing by sending the markers.  Only apply
        # them when we know the underlying model is Anthropic.
        if enable_caching and _model_supports_cache_control(final_model):
            all_messages = _with_cache_control(all_messages)
        payload: Dict[str, Any] = {
            "model": final_model,
            "messages": all_messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Thinking-model control. Gemini 3 Pro / GPT-5 / Claude-thinking can
        # spend the entire completion budget on hidden reasoning, returning
        # empty text with stop_reason=length. OpenRouter exposes a unified
        # `reasoning` field that caps or disables this behavior.
        # Env-configurable:
        #   OPENROUTER_REASONING_MAX_TOKENS=0 → disable reasoning
        #   OPENROUTER_REASONING_MAX_TOKENS=N → cap at N (default 2048)
        reasoning_cap_env = os.getenv("OPENROUTER_REASONING_MAX_TOKENS", "2048")
        try:
            reasoning_cap = int(reasoning_cap_env)
        except ValueError:
            reasoning_cap = 2048
        if reasoning_cap <= 0:
            payload["reasoning"] = {"enabled": False}
        else:
            payload["reasoning"] = {"max_tokens": reasoning_cap}

        headers = {
            "Authorization": f"Bearer {self._openrouter_api_key}",
            "Content-Type": "application/json",
        }
        url = self._openrouter_url.rstrip("/") + "/chat/completions"
        response = self._session.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip()
            raise RuntimeError(
                f"OpenRouter tool-call request failed: {body or str(exc)}"
            ) from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            err = data.get("error") or data
            raise RuntimeError(
                f"OpenRouter returned no choices for tool call "
                f"(max_tokens={max_tokens}, model={final_model}): {err}"
            )

        message = choices[0].get("message", {})
        raw_tool_calls = message.get("tool_calls") or []
        text = message.get("content") or ""

        tool_calls: List[LLMToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                args = _json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except _json.JSONDecodeError:
                args = {}
            tool_calls.append(
                LLMToolCall(id=tc.get("id", ""), name=fn.get("name", ""), input=args)
            )

        stop_reason = choices[0].get("finish_reason", "")
        usage = _normalize_usage(data.get("usage"))

        return LLMToolCallResponse(
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            text=str(text).strip() if text else "",
            usage=usage,
        )


# ── Message format helpers ─────────────────────────────────────────────────────


def _convert_messages_to_anthropic(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert OpenAI-style messages (including role="tool") to Anthropic format.

    The AgenticLoop uses a unified message format. This function translates it
    so both Anthropic and OpenRouter backends work transparently:

      role="tool" messages  →  user-role content blocks with type="tool_result"
      role="assistant" with tool_calls  →  assistant content blocks with type="tool_use"
    """
    converted: List[Dict[str, Any]] = []
    pending_tool_results: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "tool":
            # Accumulate tool results to bundle into a user message
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            })
            continue

        # Flush accumulated tool results as a user message before any non-tool message
        if pending_tool_results:
            converted.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

        if role == "assistant":
            content_blocks: List[Dict[str, Any]] = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", tc)
                raw_args = fn.get("arguments") or fn.get("input", {})
                if isinstance(raw_args, str):
                    try:
                        raw_args = _json.loads(raw_args)
                    except _json.JSONDecodeError:
                        raw_args = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": raw_args,
                })
            converted.append({
                "role": "assistant",
                "content": content_blocks if content_blocks else msg.get("content", ""),
            })
        else:
            converted.append(msg)

    # Flush any trailing tool results
    if pending_tool_results:
        converted.append({"role": "user", "content": pending_tool_results})

    return converted


# ── Prompt caching helpers ────────────────────────────────────────────────────

# Minimum user-message size before we bother adding a cache breakpoint.
# Anthropic requires ~1024 input tokens (~4000 chars) before caching engages;
# smaller prefixes would pay the cache-write cost without ever being reused.
_CACHE_MIN_CHARS = 4000


def _model_supports_cache_control(model: str) -> bool:
    """Return True when the given OpenRouter model id routes to Anthropic.

    Only Anthropic honours `cache_control: {"type": "ephemeral"}`.  Sending
    the marker to other providers (Gemini, OpenAI, Mistral, …) forces the
    first user message into content-as-list form with an unknown field, which
    has been observed to destabilise some providers' tool-calling on long
    histories.  Gemini, DeepSeek, and GPT-4o-mini already have their own
    implicit caching, so no explicit marker is needed there.
    """
    if not model:
        return False
    m = model.lower()
    return m.startswith("anthropic/") or m.startswith("claude-") or "claude" in m or "gemini-" in m


def _with_cache_control(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return a shallow copy of `messages` with a single ephemeral cache_control
    breakpoint on the last text block of the first user message.

    Effect for supported backends:
      - Anthropic native (claude-*): caches [tools + system + first user] prefix.
        Subsequent calls within 5 min pay ~10% of normal input token cost for
        this prefix.
      - OpenRouter → Anthropic: forwarded transparently, same behaviour.
      - OpenRouter → Gemini / others: cache_control markers are ignored by
        providers that don't support them (Gemini does implicit caching
        automatically).  The request still succeeds.

    Idempotent: calling it twice on the same list does not add two markers.
    Safe: never mutates the input; returns a new list with new top-level dicts.
    """
    if not messages:
        return messages

    user_idx = next(
        (i for i, m in enumerate(messages) if m.get("role") == "user"),
        -1,
    )
    if user_idx < 0:
        return messages

    first_user = messages[user_idx]
    content = first_user.get("content", "")

    if isinstance(content, str):
        if len(content) < _CACHE_MIN_CHARS:
            return messages
        new_content = [{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    elif isinstance(content, list) and content:
        total_chars = sum(
            len(b.get("text", "")) for b in content if isinstance(b, dict)
        )
        if total_chars < _CACHE_MIN_CHARS:
            return messages
        # Idempotency — skip if any block already has cache_control
        if any(
            isinstance(b, dict) and "cache_control" in b for b in content
        ):
            return messages
        new_blocks = list(content)
        for i in range(len(new_blocks) - 1, -1, -1):
            b = new_blocks[i]
            if isinstance(b, dict) and b.get("type") == "text":
                new_blocks[i] = {**b, "cache_control": {"type": "ephemeral"}}
                break
        else:
            return messages  # no text block found to mark
        new_content = new_blocks
    else:
        return messages

    new_first = {**first_user, "content": new_content}
    return list(messages[:user_idx]) + [new_first] + list(messages[user_idx + 1:])


def _normalize_usage(raw: Any) -> Dict[str, Any]:
    """
    Convert backend usage payload to a uniform dict with cache fields.

    Handled shapes:
      - Anthropic SDK: `response.usage` object with attributes
        `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
        `cache_creation_input_tokens`.
      - OpenRouter (OpenAI-compat) dict with top-level
        `prompt_tokens`, `completion_tokens`, `total_tokens`,
        and optional `prompt_tokens_details.cached_tokens` (OpenAI) or
        `cache_read_input_tokens` / `cache_creation_input_tokens`
        (when routed to Anthropic).
    """
    if raw is None:
        return {}
    # Duck-type attribute access (SDK object) vs dict access
    def _get(obj: Any, key: str, default: int = 0) -> int:
        if isinstance(obj, dict):
            return int(obj.get(key, default) or default)
        return int(getattr(obj, key, default) or default)

    prompt_tokens = _get(raw, "prompt_tokens") or _get(raw, "input_tokens")
    completion_tokens = _get(raw, "completion_tokens") or _get(raw, "output_tokens")
    total_tokens = _get(raw, "total_tokens") or (prompt_tokens + completion_tokens)

    cache_read = _get(raw, "cache_read_input_tokens")
    cache_creation = _get(raw, "cache_creation_input_tokens")
    # OpenAI-style nested path (OpenRouter for non-Anthropic providers)
    if isinstance(raw, dict) and not cache_read:
        details = raw.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cache_read = int(details.get("cached_tokens", 0) or 0)

    out: Dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
    }
    if isinstance(raw, dict) and "cost" in raw:
        out["cost"] = float(raw.get("cost") or 0.0)
    return out
