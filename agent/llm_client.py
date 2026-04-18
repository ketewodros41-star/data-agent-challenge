"""LLM client wrapper that supports OpenRouter and Anthropic backends."""

from __future__ import annotations

import json as _json
import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

try:
    import anthropic  # type: ignore
except ImportError:  # pragma: no cover
    anthropic = None

OPENROUTER_URL_DEFAULT = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_DEFAULT = "google/gemini-3.1-pro-preview"


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

    def __init__(self, tool_calls: List[LLMToolCall], stop_reason: str, text: str):
        self.tool_calls = tool_calls
        self.stop_reason = stop_reason
        self.text = text

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    def __repr__(self) -> str:
        return (
            f"LLMToolCallResponse(tool_calls={self.tool_calls!r}, "
            f"stop_reason={self.stop_reason!r}, text={self.text!r})"
        )


# ── LLM Client ────────────────────────────────────────────────────────────────


class LLMClient:
    """Unified interface for Anthropic or OpenRouter chat completions."""

    def __init__(self):
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self._openrouter_url = os.getenv("OPENROUTER_URL", OPENROUTER_URL_DEFAULT)
        self._openrouter_model = os.getenv("OPENROUTER_MODEL", OPENROUTER_MODEL_DEFAULT)

        if openrouter_api_key:
            self._backend = "openrouter"
            self._openrouter_api_key = openrouter_api_key
            self._session = httpx.Client(timeout=30.0)
            self.messages = self
        elif anthropic is not None:
            self._backend = "anthropic"
            self._client = anthropic.Anthropic()
            self.messages = self._client.messages
        else:
            raise RuntimeError(
                "No LLM backend is available. Set OPENROUTER_API_KEY or install anthropic."
            )

    # ── Standard text completion ───────────────────────────────────────────

    def create(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        resolved_model = model or os.getenv("OPENROUTER_MODEL", self._openrouter_model)
        if self._backend == "anthropic":
            return self._client.messages.create(
                model=resolved_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        return self._create_openrouter_response(
            model=resolved_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

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
            )
        return self._create_with_tools_openrouter(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
        )

    def _create_with_tools_anthropic(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        system: Optional[str],
    ) -> LLMToolCallResponse:
        """Anthropic native tool-calling via the `tools=` parameter."""
        converted = _convert_messages_to_anthropic(messages)

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
        )

    def _create_with_tools_openrouter(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        system: Optional[str],
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
        payload: Dict[str, Any] = {
            "model": final_model,
            "messages": all_messages,
            "tools": openai_tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

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
            raise RuntimeError("OpenRouter returned no choices for tool call")

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
        return LLMToolCallResponse(
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            text=str(text).strip() if text else "",
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
