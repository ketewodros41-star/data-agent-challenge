"""
MCP client. All database calls go through HTTP to an MCP server:
- PostgreSQL, MongoDB, SQLite -> Google MCP Toolbox binary (single instance)
- DuckDB                      -> local DuckDB MCP service

No direct database drivers are used here.
"""

from __future__ import annotations

import json
import itertools
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv() -> bool:
        return False


load_dotenv()

TOOLBOX_URL = os.getenv("MCP_TOOLBOX_URL", os.getenv("TOOLBOX_URL", "http://localhost:5001"))
DUCKDB_MCP_URL = os.getenv("DUCKDB_MCP_URL", "http://127.0.0.1:8001")

HTTP_SOURCE_TYPES = {"postgres", "mongodb", "sqlite"}
DUCKDB_SOURCE_TYPES = {"duckdb"}
SQLITE_SOURCE_TYPES = {"sqlite"}

# Cap HTTP response size to prevent the agent from loading huge blobs (e.g.
# SELECT * on a 3M-row table) into memory. The server still runs the query;
# we just refuse to download past this limit and nudge the LLM to use LIMIT.
MAX_HTTP_RESPONSE_BYTES = int(os.getenv("MCP_MAX_RESPONSE_BYTES", "2000000"))
_OVERSIZE_HINT = (
    "Response too large (>{limit} bytes). Re-issue the query with a tighter "
    "WHERE, add LIMIT, or aggregate (COUNT/SUM/AVG/GROUP BY)."
)


@dataclass
class ToolResult:
    """Result from any tool call."""

    success: bool
    data: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    source_type: str = ""
    tool_name: str = ""


class MCPToolbox:
    """
    Hybrid MCP client routing to the configured MCP backends.

    Routing:
      postgres / mongodb / sqlite → HTTP Google MCP Toolbox (team-dab-toolbox)
      duckdb                      → HTTP custom DuckDB MCP service
    """

    def __init__(
        self,
        toolbox_url: str = TOOLBOX_URL,
        duckdb_mcp_url: str = DUCKDB_MCP_URL,
        db_configs: Optional[Dict[str, dict]] = None,
    ):
        self.toolbox_url = toolbox_url
        self.duckdb_mcp_url = duckdb_mcp_url
        self._db_configs: Dict[str, dict] = db_configs or {}
        self._request_ids = itertools.count(1)
        self._tool_source_map: Dict[str, str] = {}
        self._default_source_map = {
            "run_query": "postgres",
            "list_tables": "postgres",
            "describe_books_info": "postgres",
            "preview_books_info": "postgres",
            "mongodb_query": "mongodb",
            "mongodb_query_yelp_business": "mongodb",
            "mongodb_query_yelp_checkin": "mongodb",
            "sqlite_query": "sqlite",
            "sqlite_bookreview_query": "sqlite",
            "sqlite_googlelocal_query": "sqlite",
            "sqlite_agnews_query": "sqlite",
            "sqlite_crm_core_query": "sqlite",
            "sqlite_crm_products_query": "sqlite",
            "sqlite_crm_territory_query": "sqlite",
            "sqlite_stockinfo_query": "sqlite",
            "sqlite_music_brainz_tracks_query": "sqlite",
            "sqlite_stockindex_info_query": "sqlite",
            "sqlite_patents_publication_query": "sqlite",
            "sqlite_deps_dev_package_query": "sqlite",
            "duckdb_query": "duckdb",
            "duckdb_crm_activities_query": "duckdb",
            "duckdb_crm_sales_pipeline_query": "duckdb",
            "duckdb_deps_dev_v1_query": "duckdb",
            "duckdb_github_repos_query": "duckdb",
            "duckdb_music_brainz_query": "duckdb",
            "duckdb_music_brainz_20k_query": "duckdb",
            "duckdb_pancancer_query": "duckdb",
            "duckdb_pancancer_atlas_query": "duckdb",
            "duckdb_stockindex_query": "duckdb",
            "duckdb_stockmarket_query": "duckdb",
            "duckdb_yelp_query": "duckdb",
        }

    def call_tool(self, tool_name: str, parameters: Dict[str, Any]) -> ToolResult:
        """
        Invoke a named tool. DuckDB uses its own HTTP MCP service; every other
        source (postgres, mongodb, sqlite) is dispatched to the Google MCP
        Toolbox via HTTP.
        """
        parameters = self._normalize_parameters(tool_name, parameters)
        source_type = self._resolve_source_type(tool_name)
        start = time.time()

        if source_type in DUCKDB_SOURCE_TYPES:
            result = self._call_duckdb_http(tool_name, parameters)
        else:
            result = self._call_http(tool_name, parameters)

        result.execution_time = round(time.time() - start, 3)
        result.tool_name = tool_name
        result.source_type = source_type
        return result

    def verify_connections(self) -> Dict[str, bool]:
        """
        Verify all database sources are reachable.
        """
        results: Dict[str, bool] = {}

        try:
            self.list_tools()
            results["toolbox_http"] = True
        except Exception as exc:
            results["toolbox_http"] = False
            results["toolbox_error"] = str(exc)

        try:
            payload = self._post_mcp("tools/list", {}, base_url=self.duckdb_mcp_url)
            results["duckdb"] = bool(payload.get("result", {}).get("tools"))
        except Exception as exc:
            results["duckdb"] = False
            results["duckdb_error"] = str(exc)

        return results

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        List all tools registered in the running toolbox binary and duckdb mcp server.
        """
        data = []
        try:
            payload = self._post_mcp("tools/list", {})
            data.extend(payload.get("result", {}).get("tools", []))
        except Exception as exc:
            pass

        try:
            duckdb_payload = self._post_mcp("tools/list", {}, base_url=self.duckdb_mcp_url)
            data.extend(duckdb_payload.get("result", {}).get("tools", []))
        except Exception as exc:
            pass

        if not data:
            return [{"error": "Both toolboxes failed to respond."}]

        for tool in data:
            name = tool.get("name", "")
            if name:
                self._tool_source_map[name] = self._default_source_map.get(name, "")
        return data

    def _call_http(self, tool_name: str, parameters: Dict[str, Any]) -> ToolResult:
        """Send tool invocation to MCP Toolbox HTTP server."""
        url = f"{self.toolbox_url}/api/tool/{tool_name}/invoke"
        payload = json.dumps(parameters).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read(MAX_HTTP_RESPONSE_BYTES + 1)
                if len(body) > MAX_HTTP_RESPONSE_BYTES:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=_OVERSIZE_HINT.format(limit=MAX_HTTP_RESPONSE_BYTES),
                    )
                raw = json.loads(body.decode())

                result = raw.get("result", raw)

                # NORMALIZATION LAYER
                normalized = self._normalize_mcp_content(result)

                return ToolResult(
                    success=True,
                    data=normalized,
                )

        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if exc.fp else str(exc)
            return ToolResult(success=False, data=None, error=f"HTTP {exc.code}: {body}")
        except Exception as exc:
            return ToolResult(success=False, data=None, error=str(exc))


    def _normalize_mcp_content(self, result: Any) -> List[Any]:
        """
        Convert MCP responses (which often triple-encode JSON in strings) into flat lists of dictionaries.
        """
        if result is None:
            return []
            
        def _deep_unpack(val: Any) -> Any:
            if isinstance(val, str):
                stripped = val.strip()
                if (stripped.startswith('[') and stripped.endswith(']')) or (stripped.startswith('{') and stripped.endswith('}')):
                    try:
                        parsed = json.loads(val)
                        return _deep_unpack(parsed)
                    except json.JSONDecodeError:
                        return val
                return val
            if isinstance(val, list):
                unpacked = []
                for item in val:
                    res = _deep_unpack(item)
                    if isinstance(res, list):
                        unpacked.extend(res)
                    else:
                        unpacked.append(res)
                return unpacked
            if isinstance(val, dict):
                # If it's an MCP 'content' dict, look inside 'text'
                if val.get("type") == "text" and "text" in val:
                    return _deep_unpack(val["text"])
                # If it's a JSON-RPC 'result' dict, look inside 'content'
                if "content" in val:
                    return _deep_unpack(val["content"])
                return {k: _deep_unpack(v) for k, v in val.items()}
            return val

        unpacked = _deep_unpack(result)
        return unpacked if isinstance(unpacked, list) else [unpacked]

    def _post_mcp(self, method: str, params: Dict[str, Any], base_url: Optional[str] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request to the toolbox MCP HTTP endpoint."""
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": next(self._request_ids),
                "method": method,
                "params": params,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{(base_url or self.toolbox_url).rstrip('/')}/mcp",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def _call_duckdb_http(self, tool_name: str, parameters: Dict[str, Any]) -> ToolResult:
        """Send DuckDB tool invocation to the local DuckDB MCP service."""
        try:
            url = f"{self.duckdb_mcp_url.rstrip('/')}/api/tool/{tool_name}/invoke"
            payload = json.dumps(parameters).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read(MAX_HTTP_RESPONSE_BYTES + 1)
                if len(body) > MAX_HTTP_RESPONSE_BYTES:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=_OVERSIZE_HINT.format(limit=MAX_HTTP_RESPONSE_BYTES),
                    )
                data = json.loads(body.decode())
                result = data.get("result", data)
                normalized = self._normalize_mcp_content(result)
                return ToolResult(success=True, data=normalized)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if exc.fp else str(exc)
            return ToolResult(success=False, data=None, error=f"HTTP {exc.code}: {body}")
        except Exception as exc:
            return ToolResult(success=False, data=None, error=str(exc))

    def _resolve_source_type(self, tool_name: str) -> str:
        """Determine source type for a tool name."""
        if tool_name in self._tool_source_map:
            return self._tool_source_map[tool_name]
        return self._default_source_map.get(tool_name, "postgres")

    @staticmethod
    def _normalize_parameters(tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Translate agent-side parameter names to the names each tool expects."""
        normalized = dict(parameters)

        if tool_name in {"run_query", "postgres-sql", "postgres-execute-sql"}:
            if "sql" not in normalized and "query" in normalized:
                normalized["sql"] = normalized.pop("query")
        if tool_name.startswith("sqlite") and "sql" not in normalized and "query" in normalized:
            normalized["sql"] = normalized.pop("query")
        if tool_name.startswith("duckdb") and "sql" not in normalized and "query" in normalized:
            normalized["sql"] = normalized.pop("query")

        if tool_name.startswith("mongodb_query"):
            if "pipeline" not in normalized and "query" in normalized:
                normalized["pipeline"] = normalized.pop("query")
            pipeline = normalized.get("pipeline")
            if pipeline is not None and not isinstance(pipeline, str):
                normalized["pipeline"] = json.dumps(pipeline)
            # mongodb-aggregate accepts only `pipeline`; drop callers' extras.
            for extra in ("database", "query_type", "sql"):
                normalized.pop(extra, None)

        return normalized
