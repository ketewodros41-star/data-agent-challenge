from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def ensure_llm_api_key(monkeypatch, request):
    """Ensure LLM API key is available for tests. Use dummy key if not provided."""
    # Skip for tests that explicitly opt-out
    if "no_mock_llm" in request.keywords:
        return

    # Set dummy OpenRouter key if no real keys are available
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-for-ci-" + request.node.nodeid)


@pytest.fixture(autouse=True)
def mock_llm_client(monkeypatch, request):
    """Auto-mock LLMClient for all tests to avoid real API calls."""
    # Skip for tests that explicitly opt-out
    if "no_mock_llm" in request.keywords:
        return None

    # Create a mock that behaves like the real LLMClient
    def mock_llm_factory():
        mock = MagicMock()
        # Mock the messages interface (used as .messages.create())
        mock.messages = MagicMock()

        # Mock response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="SELECT * FROM test")]
        mock.messages.create = MagicMock(return_value=mock_response)

        return mock

    monkeypatch.setattr(
        "agent.llm_client.LLMClient",
        mock_llm_factory,
    )

    # Also mock at import sites to catch eager initialization
    monkeypatch.setattr(
        "agent.oracle_forge_agent.LLMClient",
        mock_llm_factory,
    )
    monkeypatch.setattr(
        "agent.query_router.LLMClient",
        mock_llm_factory,
    )
    monkeypatch.setattr(
        "agent.self_correction.LLMClient",
        mock_llm_factory,
    )

