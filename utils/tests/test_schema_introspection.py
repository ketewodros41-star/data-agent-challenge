"""Tests for schema_introspector utilities (MCP version)."""

import pytest
from unittest.mock import MagicMock
from utils.schema_introspector import introspect_schema
from agent.models import SchemaInfo


@pytest.fixture
def mock_call_tool():
    """Returns a mock call_tool function that returns a failed ToolResult by default."""
    m = MagicMock()
    # Mock return value to have a 'success' attribute set to False
    m.return_value.success = False
    m.return_value.data = None
    return m


def test_introspect_schema_unsupported_type(mock_call_tool):
    with pytest.raises(ValueError, match="Unsupported"):
        introspect_schema("mydb", {"type": "oracle"}, mock_call_tool)


def test_introspect_schema_sqlite_missing_path(mock_call_tool):
    # In MCP mode, it tries to call the tool. Since mock returns success=False, it returns empty.
    result = introspect_schema("sqlite", {"type": "sqlite", "path": ""}, mock_call_tool)
    assert isinstance(result, SchemaInfo)
    assert result.tables == {}


def test_introspect_schema_duckdb_in_memory(mock_call_tool):
    result = introspect_schema("duckdb", {"type": "duckdb", "path": ":memory:"}, mock_call_tool)
    assert isinstance(result, SchemaInfo)
    assert result.db_type == "duckdb"


def test_introspect_schema_postgres_no_connection(mock_call_tool):
    result = introspect_schema("postgres", {"type": "postgres", "connection_string": ""}, mock_call_tool)
    assert isinstance(result, SchemaInfo)
    assert result.tables == {}


def test_introspect_schema_mongodb_no_connection(mock_call_tool):
    result = introspect_schema("mongodb", {"type": "mongodb", "connection_string": ""}, mock_call_tool)
    assert isinstance(result, SchemaInfo)
    assert result.tables == {}
