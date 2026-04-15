"""
Typed MCP client scaffold for Oracle Forge.

This wrapper gives the execution engine a narrow interface for database-tool
calls without forcing the engine to know about transport details.

TODO:
- Replace the default fallback with the real MCP Toolbox transport
- Add tool discovery and connection verification methods as needed
"""

from __future__ import annotations

from typing import Any, Optional

from .types import MCPToolCall, MCPToolResult


class MCPClient:
    """Small adapter around an MCP-capable backend."""

    def __init__(self, backend: Optional[Any] = None) -> None:
        self.backend = backend

    def call_tool(self, request: MCPToolCall) -> MCPToolResult:
        """
        Execute one MCP tool call.

        If a backend is injected and exposes ``call_tool(tool_name, parameters)``,
        this adapter delegates to it. Otherwise a typed TODO response is returned.
        """
        if self.backend is None:
            return MCPToolResult(
                success=False,
                data=None,
                error="TODO: wire MCPClient to the real Toolbox backend",
                tool_name=request.tool_name,
            )

        result = self.backend.call_tool(request.tool_name, request.parameters)
        return MCPToolResult(
            success=getattr(result, "success", False),
            data=getattr(result, "data", None),
            error=getattr(result, "error", None),
            tool_name=request.tool_name,
        )
