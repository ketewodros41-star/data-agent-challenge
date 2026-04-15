"""
schema_introspector — Unified Database Schema Inspector (MCP Only).
──────────────────────────────────────────────────────────────
Standardised tool for listing tables and columns via the MCP Toolbox.
Direct database connections are expressly forbidden by the architecture.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.models.models import ColumnSchema, SchemaInfo, TableSchema


# ==============================================================================
# SECTION 1: PUBLIC API
# ==============================================================================

def introspect_schema(
    db_name: str,
    config: dict,
    call_tool: Callable
) -> SchemaInfo:
    """
    Primary entry point for runtime introspection.
    Must always be called with a valid 'call_tool' function from MCPToolbox.
    """
    db_type = config.get("type", "")
    if db_type in ("postgres", "postgresql"):
        return _introspect_postgres_via_mcp(db_name, config, call_tool)
    if db_type == "sqlite":
        return _introspect_sqlite_via_mcp(db_name, config, call_tool)
    if db_type == "duckdb":
        return _introspect_duckdb_via_mcp(db_name, config, call_tool)
    if db_type == "mongodb":
        return _introspect_mongodb_via_mcp(db_name, config, call_tool)

    raise ValueError(f"Unsupported database type: {db_type!r}")


def introspect_to_markdown(
    db_name: str,
    config: dict,
    call_tool: Callable
) -> str:
    """Generate markdown schema documentation using the architecture-compliant MCP path."""
    info = introspect_schema(db_name, config, call_tool)
    lines = [f"## Schema: {info.database} (`{info.db_type}`)\n"]

    if not info.table_schemas:
        lines.append("> No tables discovered via MCP.\n")
        return "\n".join(lines)

    for tname, ts in sorted(info.table_schemas.items()):
        lines.append(f"#### Table: `{tname}`")
        lines.append("| Column | Type | PK? |")
        lines.append("|--------|------|-----|")
        for col in sorted(ts.columns, key=lambda x: x.name):
            pk = "★" if col.name in ts.primary_keys else ""
            lines.append(f"| {col.name} | {col.data_type} | {pk} |")
        lines.append("")

    return "\n".join(lines)


# ==============================================================================
# SECTION 2: MCP DRIVERS
# ==============================================================================

def _mcp_rows(result: Any) -> List[Dict]:
    """Extracts a flat list of row dicts from ToolResult content blocks."""
    data = result.data if hasattr(result, "data") else result
    if not data:
        return []

    # Handle list-wrapped results (e.g., DuckDB service or local MCP)
    if isinstance(data, list):
        if data and isinstance(data[0], str):
            try:
                p = _json.loads(data[0])
                if isinstance(p, str): p = _json.loads(p)
                return [r for r in p if isinstance(r, dict)]
            except: pass
            return []
        if data and isinstance(data[0], list):
            return [r for r in data[0] if isinstance(r, dict)]
        if data and isinstance(data[0], dict):
            return data
        return []

    # Handle standard MCP content blocks
    if isinstance(data, dict):
        for item in data.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    p = _json.loads(item["text"])
                    if isinstance(p, str): p = _json.loads(p)
                    if isinstance(p, list):
                        return [r for r in p if isinstance(r, dict)]
                except:
                    pass
    return []


def _introspect_postgres_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    mcp_tool = config.get("mcp_tool", "run_query")
    sql = (
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    result = call_tool(mcp_tool, {"sql": sql})
    # Fallback for toolbox-specific param names if first fail
    if not result.success:
        result = call_tool(mcp_tool, {"query": sql})
    if not result.success:
        return _empty_schema(db_name, "postgres")

    col_rows = _mcp_rows(result)
    if not col_rows:
        return _empty_schema(db_name, "postgres")

    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    col_buf: Dict[str, List] = {}

    for row in col_rows:
        if isinstance(row, dict) and (tname := row.get("table_name")):
            col_buf.setdefault(tname, []).append(row)

    for tname, rows in col_buf.items():
        columns = [
            ColumnSchema(
                name=r["column_name"],
                data_type=r.get("data_type", "unknown"),
                nullable=(str(r.get("is_nullable", "YES")).upper() == "YES"),
            )
            for r in rows
        ]
        tables[tname] = [c.name for c in columns]
        table_schemas[tname] = TableSchema(name=tname, columns=columns)

    return SchemaInfo(database=db_name, db_type="postgres", tables=tables, table_schemas=table_schemas)


def _introspect_sqlite_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    mcp_tool = config.get("mcp_tool", "sqlite_query")
    res = call_tool(mcp_tool, {"sql": "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"})
    if not res.success:
        return _empty_schema(db_name, "sqlite")

    table_names = [r.get("name") for r in _mcp_rows(res) if isinstance(r, dict) and r.get("name")]
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}

    for tname in table_names:
        p_res = call_tool(mcp_tool, {"sql": f"PRAGMA table_info({tname})"})
        if not p_res.success:
            continue
        p_rows = _mcp_rows(p_res)
        columns = [
            ColumnSchema(
                name=r["name"],
                data_type=r.get("type", "unknown") or "unknown",
                nullable=not bool(r.get("notnull", 0)),
                is_primary_key=bool(r.get("pk", 0)),
            )
            for r in p_rows if isinstance(r, dict) and r.get("name")
        ]
        tables[tname] = [c.name for c in columns]
        table_schemas[tname] = TableSchema(name=tname, columns=columns, primary_keys=[c.name for c in columns if c.is_primary_key])

    return SchemaInfo(database=db_name, db_type="sqlite", tables=tables, table_schemas=table_schemas)


def _introspect_duckdb_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    mcp_tool = config.get("mcp_tool", "duckdb_query")
    sql = "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'main'"
    result = call_tool(mcp_tool, {"sql": sql})
    if not result.success:
        return _empty_schema(db_name, "duckdb")

    rows = _mcp_rows(result)
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    col_buf: Dict[str, List] = {}

    for row in rows:
        if isinstance(row, dict) and (tname := row.get("table_name")):
            col_buf.setdefault(tname, []).append(row)

    for tname, trows in col_buf.items():
        columns = [ColumnSchema(name=r["column_name"], data_type=r["data_type"]) for r in trows]
        tables[tname] = [c.name for c in columns]
        table_schemas[tname] = TableSchema(name=tname, columns=columns)

    return SchemaInfo(database=db_name, db_type="duckdb", tables=tables, table_schemas=table_schemas)


def _introspect_mongodb_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    # Sampling for Yelp dataset (standard discovery targets)
    for cname, tool_name in [("business", "find_yelp_businesses"), ("checkin", "find_yelp_checkins")]:
        result = call_tool(tool_name, {"filterPayload": "{}", "limit": 1})
        if not result.success:
            continue
        docs = _mcp_rows(result)
        if not docs or not isinstance(docs[0], dict):
            continue
        doc = docs[0]
        columns = [ColumnSchema(name=k, data_type=type(v).__name__, is_primary_key=(k == "_id")) for k, v in doc.items()]
        tables[cname] = [c.name for c in columns]
        table_schemas[cname] = TableSchema(name=cname, columns=columns, primary_keys=["_id"] if "_id" in doc else [])

    return SchemaInfo(database=db_name, db_type="mongodb", tables=tables, table_schemas=table_schemas)


def _empty_schema(db_name: str, db_type: str) -> SchemaInfo:
    return SchemaInfo(database=db_name, db_type=db_type, tables={})
