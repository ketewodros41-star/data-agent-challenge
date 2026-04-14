"""Tests for sandbox response normalization and transport error handling."""

from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import patch

from agent.sandbox_client import SandboxClient
from agent.types import SandboxExecutionRequest


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class SandboxClientTests(unittest.TestCase):
    def test_execute_normalizes_http_sandbox_response(self) -> None:
        client = SandboxClient(base_url="http://sandbox.local", timeout_seconds=3)
        request = SandboxExecutionRequest(
            code_plan="normalize and join",
            trace_id="trace-1",
            inputs_payload={"postgres_rows": [{"id": 1}], "mongo_docs": [{"id": 1}]},
        )
        payload = {
            "result": [{"id": 1, "joined": True}],
            "trace": [{"step": "normalize"}, {"step": "join"}],
            "validation_status": "PASSED",
            "error_if_any": None,
        }

        with patch("agent.sandbox_client.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.execute(request)

        self.assertTrue(result.success)
        self.assertEqual(result.result, [{"id": 1, "joined": True}])
        self.assertEqual(result.trace, [{"step": "normalize"}, {"step": "join"}])
        self.assertEqual(result.validation_status, "PASSED")
        self.assertIsNone(result.error_if_any)

    def test_execute_returns_timeout_result(self) -> None:
        client = SandboxClient(base_url="http://sandbox.local", timeout_seconds=2)
        request = SandboxExecutionRequest(code_plan="normalize", trace_id="trace-2")

        with patch("agent.sandbox_client.urllib.request.urlopen", side_effect=socket.timeout()):
            result = client.execute(request)

        self.assertFalse(result.success)
        self.assertEqual(result.validation_status, "TIMEOUT")
        self.assertIn("timed out", result.error_if_any or "")


if __name__ == "__main__":
    unittest.main()
