"""LLM client wrapper that supports OpenRouter and Anthropic backends."""

from __future__ import annotations

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
OPENROUTER_MODEL_DEFAULT = "google/gemini-2.5-flash-lite"


class LLMResponseContent:
    def __init__(self, text: str):
        self.text = text


class LLMResponse:
    def __init__(self, text: str):
        self.content = [LLMResponseContent(text)]


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

    def create(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> LLMResponse:
        if self._backend == "anthropic":
            return self._client.messages.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        return self._create_openrouter_response(
            model=model,
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
