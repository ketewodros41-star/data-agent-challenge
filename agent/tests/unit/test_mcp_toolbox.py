import json
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from agent.mcp_toolbox import MCPToolbox


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class MCPToolboxTests(unittest.TestCase):
    def test_list_tools_reads_mcp_tools_list(self) -> None:
        client = MCPToolbox("http://127.0.0.1:5000")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "list_tables", "description": "List tables"}]},
        }

        with patch("agent.mcp_toolbox.urllib.request.urlopen", return_value=FakeResponse(payload)) as urlopen_mock:
            result = client.list_tools()

        self.assertEqual(result, payload["result"]["tools"])
        self.assertEqual(client._tool_source_map["list_tables"], "postgres")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:5000/mcp")
        self.assertEqual(request.get_method(), "POST")

    def test_call_tool_uses_http_for_non_duckdb_sources(self) -> None:
        client = MCPToolbox("http://127.0.0.1:5000")
        payload = {"result": [{"table_name": "books_info"}]}

        with patch("agent.mcp_toolbox.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.call_tool("list_tables", {})

        self.assertTrue(result.success)
        self.assertEqual(result.data, [{"table_name": "books_info"}])
        self.assertEqual(result.source_type, "postgres")
        self.assertEqual(result.tool_name, "list_tables")

    def test_call_tool_routes_duckdb_queries_directly(self) -> None:
        client = MCPToolbox()

        connection = MagicMock()
        connection.execute.return_value.fetchall.return_value = [(1, "book")]
        connection.description = [("id",), ("name",)]

        duckdb_module = ModuleType("duckdb")
        duckdb_module.connect = MagicMock(return_value=connection)

        with patch.dict("sys.modules", {"duckdb": duckdb_module}):
            result = client.call_tool("duckdb_query", {"query": "select 1 as id, 'book' as name"})

        self.assertTrue(result.success)
        self.assertEqual(result.data, [{"id": 1, "name": "book"}])
        self.assertEqual(result.source_type, "duckdb")

    def test_verify_connections_reports_http_and_duckdb(self) -> None:
        client = MCPToolbox("http://127.0.0.1:5000")

        duckdb_connection = MagicMock()
        duckdb_connection.execute.return_value.fetchone.return_value = (1,)
        duckdb_module = ModuleType("duckdb")
        duckdb_module.connect = MagicMock(return_value=duckdb_connection)

        mcp_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "list_tables"}]},
        }

        with patch("agent.mcp_toolbox.urllib.request.urlopen", return_value=FakeResponse(mcp_payload)):
            with patch.dict("sys.modules", {"duckdb": duckdb_module}):
                result = client.verify_connections()

        self.assertTrue(result["toolbox_http"])
        self.assertTrue(result["duckdb"])

    def test_list_tools_returns_error_payload_on_failure(self) -> None:
        client = MCPToolbox("http://127.0.0.1:5000")

        with patch("agent.mcp_toolbox.urllib.request.urlopen", side_effect=RuntimeError("boom")):
            result = client.list_tools()

        self.assertEqual(result, [{"error": "boom"}])


if __name__ == "__main__":
    unittest.main()
