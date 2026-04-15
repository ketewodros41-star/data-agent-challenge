"""
Typed sandbox client for Oracle Forge execution support.

This module normalizes sandbox execution responses into a stable internal
format so the execution engine can treat backend, HTTP, and mocked responses
the same way.

Expected sandbox contract:
- input: ``code_plan``, ``trace_id``, optional ``inputs_payload``
- output: ``result``, ``trace``, ``validation_status``, ``error_if_any``

TODO:
- Add authentication headers once the deployed sandbox contract is finalized
- Expand timeout policy per endpoint when production SLOs are known
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from .types import SandboxExecutionRequest, SandboxResult


class SandboxClient:
    """Minimal adapter around a sandbox backend or transport stub."""

    def __init__(
        self,
        backend: Optional[Any] = None,
        base_url: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.backend = backend
        resolved_base_url = base_url or os.getenv("SANDBOX_URL")
        self.base_url = resolved_base_url.rstrip("/") if resolved_base_url else None
        self.timeout_seconds = timeout_seconds

    def execute(self, request: SandboxExecutionRequest) -> SandboxResult:
        """
        Execute one sandbox request.

        If a backend is injected and exposes ``execute(request)``, this adapter
        delegates to it. Otherwise it tries the configured HTTP sandbox URL.
        """
        if self.backend is not None:
            return self._normalize_response(self.backend.execute(request))

        if not self.base_url:
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="TODO",
                error_if_any="TODO: wire SandboxClient to the sandbox service",
                raw_response=None,
            )

        payload = {
            "code_plan": request.code_plan,
            "trace_id": request.trace_id,
            "inputs_payload": request.inputs_payload,
        }
        if request.context:
            payload["context"] = request.context
        if request.db_type:
            payload["db_type"] = request.db_type
        if request.step_id:
            payload["step_id"] = request.step_id

        return self._post_json("/execute", payload)

    def validate(self, request: SandboxExecutionRequest) -> SandboxResult:
        """
        Validate sandbox input without executing it.

        TODO: route this to a dedicated sandbox validation endpoint.
        """
        if self.backend is not None and hasattr(self.backend, "validate"):
            return self._normalize_response(self.backend.validate(request))

        if not self.base_url:
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="TODO",
                error_if_any="TODO: wire SandboxClient.validate to sandbox validation",
                raw_response=None,
            )

        payload = {
            "code_plan": request.code_plan,
            "trace_id": request.trace_id,
            "inputs_payload": request.inputs_payload,
        }
        if request.context:
            payload["context"] = request.context
        if request.db_type:
            payload["db_type"] = request.db_type
        if request.step_id:
            payload["step_id"] = request.step_id

        return self._post_json("/validate", payload)

    def _post_json(self, path: str, payload: Dict[str, Any]) -> SandboxResult:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            return self._normalize_response(body)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8") if exc.fp else ""
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="HTTP_ERROR",
                error_if_any=f"HTTP {exc.code}: {body_text or exc.reason}",
                raw_response=None,
            )
        except urllib.error.URLError as exc:
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="TRANSPORT_ERROR",
                error_if_any=f"Sandbox unreachable: {exc.reason}",
                raw_response=None,
            )
        except (TimeoutError, socket.timeout):
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="TIMEOUT",
                error_if_any=f"Sandbox request timed out after {self.timeout_seconds}s",
                raw_response=None,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            return SandboxResult(
                success=False,
                result=None,
                trace=[],
                validation_status="CLIENT_ERROR",
                error_if_any=str(exc),
                raw_response=None,
            )

    @staticmethod
    def _normalize_response(response: Any) -> SandboxResult:
        if isinstance(response, SandboxResult):
            return response

        if isinstance(response, dict):
            validation_status = str(response.get("validation_status", "UNKNOWN"))
            error_if_any = response.get("error_if_any")
            return SandboxResult(
                success=not error_if_any and validation_status not in {"FAILED", "ERROR", "TIMEOUT"},
                result=response.get("result"),
                trace=response.get("trace", []) or [],
                validation_status=validation_status,
                error_if_any=error_if_any,
                raw_response=response,
            )

        return SandboxResult(
            success=getattr(response, "success", False),
            result=getattr(response, "result", None),
            trace=getattr(response, "trace", []) or [],
            validation_status=getattr(response, "validation_status", "UNKNOWN"),
            error_if_any=getattr(response, "error_if_any", None),
            raw_response=None,
        )
