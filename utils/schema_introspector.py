"""
schema_introspector — Database-agnostic schema inspector.

Returns a normalised SchemaInfo for any supported database type
(PostgreSQL, MongoDB, SQLite, DuckDB). Used by ContextManager to
populate Layer 1 at session start.

Architecture rule: ALL database access goes through MCPToolbox.call_tool().
Never import psycopg2, sqlite3, duckdb, or pymongo here for production use.

Primary API (architecture-compliant):
  introspect_schema_via_mcp(db_name, config, call_tool)
    → uses MCP tool calls routed through MCPToolbox

Config keys used by the MCP path:
  postgres — mcp_tool (str, e.g. "run_query" or "run_query_googlelocal")
  sqlite   — mcp_tool (str, e.g. "sqlite_bookreview_query")
  duckdb   — mcp_tool (str, e.g. "duckdb_query")
  mongodb  — no extra keys; always samples "business" and "checkin" collections
"""

from __future__ import annotations

import json as _json
from typing import Any, Callable, Dict, List, Optional

from agent.models.models import ColumnSchema, SchemaInfo, TableSchema


# ---------------------------------------------------------------------------
# Primary API — MCP-based introspection (architecture-compliant)
# ---------------------------------------------------------------------------

def introspect_schema_via_mcp(
    db_name: str,
    config: dict,
    call_tool: Callable,
) -> SchemaInfo:
    """
    Introspect database schema via MCPToolbox.call_tool().

    No direct database connections are made. All queries are routed through
    the MCP toolbox binary (PostgreSQL/SQLite/MongoDB) or the DuckDB MCP
    service (DuckDB).

    Args:
        db_name:   Logical name of the database (used as SchemaInfo.database).
        config:    Connection config with at minimum a "type" key and a
                   "mcp_tool" key naming the MCP tool to use for queries.
        call_tool: Callable with signature (tool_name: str, params: dict) ->
                   ToolResult.  Typically MCPToolbox.call_tool.

    Returns:
        Populated SchemaInfo.  Returns an empty SchemaInfo on failure so the
        caller can decide whether that is fatal.
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
    return _empty_schema(db_name, db_type or "unknown")


def _mcp_rows(result: Any) -> List[Dict]:
    """Extract a flat list of row dicts from a ToolResult or raw data value.

    The MCP toolbox binary returns result in one of these shapes:
      A) ['[{"col": val}, ...]']     — result field was a JSON-encoded string;
                                       _normalize_mcp_content wraps it in a list
                                       but does NOT parse the string (because the
                                       result was not a dict, so the content path
                                       was bypassed).  This is the most common
                                       shape for postgres-execute-sql tools.
      B) [[row, row, ...], ...]      — result was {"content":[{"type":"text","text":"..."}]};
                                       _normalize_mcp_content parsed the text into
                                       a list and wrapped it again.
      C) [row, row, ...]             — DuckDB HTTP service returns direct list of dicts
      D) {"content": [...]}          — unnormalized MCP content block (rare)
    """
    data = result.data if hasattr(result, "data") else result
    if not data:
        return []
    if isinstance(data, list):
        # Format A: list with a single JSON-encoded string element
        if data and isinstance(data[0], str):
            try:
                parsed = _json.loads(data[0])
                if isinstance(parsed, str):
                    parsed = _json.loads(parsed)
                if isinstance(parsed, list):
                    return [r for r in parsed if isinstance(r, dict)]
            except Exception:
                pass
            return []
        # Format B: list-of-lists — unwrap one level
        if data and isinstance(data[0], list):
            return [r for r in data[0] if isinstance(r, dict)]
        # Format C: already a flat list of dicts
        if data and isinstance(data[0], dict):
            return data
        return []
    if isinstance(data, dict):
        # Format D: unnormalized MCP content block
        for item in data.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    parsed = _json.loads(item["text"])
                    if isinstance(parsed, str):
                        parsed = _json.loads(parsed)
                    if isinstance(parsed, list):
                        return [r for r in parsed if isinstance(r, dict)]
                except Exception:
                    pass
    return []


def _introspect_postgres_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    """Introspect a PostgreSQL database via the MCP run_query_* tool."""
    mcp_tool = config.get("mcp_tool", "run_query")

    # Single query: all tables + columns in one round-trip
    all_cols_sql = (
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' "
        "ORDER BY table_name, ordinal_position"
    )
    result = call_tool(mcp_tool, {"sql": all_cols_sql})
    if not result.success:
        # Retry with "query" key in case the tool needs it
        result = call_tool(mcp_tool, {"query": all_cols_sql})
    if not result.success:
        return _empty_schema(db_name, "postgres")

    col_rows = _mcp_rows(result)
    if not col_rows:
        return _empty_schema(db_name, "postgres")

    # Group by table
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    col_buf: Dict[str, List] = {}

    for row in col_rows:
        if not isinstance(row, dict):
            continue
        tname = row.get("table_name", "")
        cname = row.get("column_name", "")
        if not tname or not cname:
            continue
        col_buf.setdefault(tname, []).append(row)

    for tname, rows in col_buf.items():
        col_names = [r["column_name"] for r in rows]
        tables[tname] = col_names
        columns = [
            ColumnSchema(
                name=r["column_name"],
                data_type=r.get("data_type", "unknown"),
                nullable=(str(r.get("is_nullable", "YES")).upper() == "YES"),
            )
            for r in rows
        ]
        table_schemas[tname] = TableSchema(name=tname, columns=columns)

    return SchemaInfo(
        database=db_name,
        db_type="postgres",
        tables=tables,
        table_schemas=table_schemas,
    )


def _introspect_sqlite_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    """Introspect a SQLite database via the MCP sqlite_*_query tool."""
    mcp_tool = config.get("mcp_tool", "sqlite_query")

    # List tables
    tables_result = call_tool(
        mcp_tool,
        {"sql": "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"},
    )
    if not tables_result.success:
        return _empty_schema(db_name, "sqlite")

    table_rows = _mcp_rows(tables_result)
    table_names = [r.get("name", "") for r in table_rows if isinstance(r, dict) and r.get("name")]

    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}

    for tname in table_names:
        pragma_result = call_tool(mcp_tool, {"sql": f"PRAGMA table_info({tname})"})
        if not pragma_result.success:
            tables[tname] = []
            continue
        pragma_rows = _mcp_rows(pragma_result)
        col_names = [r.get("name", "") for r in pragma_rows if isinstance(r, dict)]
        tables[tname] = [c for c in col_names if c]
        columns = [
            ColumnSchema(
                name=r["name"],
                data_type=r.get("type", "unknown") or "unknown",
                nullable=not bool(r.get("notnull", 0)),
                is_primary_key=bool(r.get("pk", 0)),
            )
            for r in pragma_rows
            if isinstance(r, dict) and r.get("name")
        ]
        table_schemas[tname] = TableSchema(
            name=tname,
            columns=columns,
            primary_keys=[r["name"] for r in pragma_rows if isinstance(r, dict) and r.get("pk")],
        )

    return SchemaInfo(
        database=db_name,
        db_type="sqlite",
        tables=tables,
        table_schemas=table_schemas,
    )


def _introspect_duckdb_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    """Introspect a DuckDB database via the MCP duckdb_*_query tool."""
    mcp_tool = config.get("mcp_tool", "duckdb_query")

    all_cols_sql = (
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'main' "
        "ORDER BY table_name, ordinal_position"
    )
    result = call_tool(mcp_tool, {"sql": all_cols_sql})
    if not result.success:
        return _empty_schema(db_name, "duckdb")

    col_rows = _mcp_rows(result)
    if not col_rows:
        return _empty_schema(db_name, "duckdb")

    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    col_buf: Dict[str, List] = {}

    for row in col_rows:
        if not isinstance(row, dict):
            continue
        tname = row.get("table_name", "")
        cname = row.get("column_name", "")
        if tname and cname:
            col_buf.setdefault(tname, []).append(row)

    for tname, rows in col_buf.items():
        col_names = [r["column_name"] for r in rows]
        tables[tname] = col_names
        columns = [
            ColumnSchema(
                name=r["column_name"],
                data_type=r.get("data_type", "unknown"),
                nullable=(str(r.get("is_nullable", "YES")).upper() == "YES"),
            )
            for r in rows
        ]
        table_schemas[tname] = TableSchema(name=tname, columns=columns)

    return SchemaInfo(
        database=db_name,
        db_type="duckdb",
        tables=tables,
        table_schemas=table_schemas,
    )


def _introspect_mongodb_via_mcp(
    db_name: str, config: dict, call_tool: Callable
) -> SchemaInfo:
    """Infer MongoDB schema by sampling via MCP find tools."""
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}

    for cname, tool_name in [
        ("business", "find_yelp_businesses"),
        ("checkin", "find_yelp_checkins"),
    ]:
        result = call_tool(tool_name, {"filterPayload": "{}", "limit": 1})
        if not result.success:
            continue
        docs = _mcp_rows(result)
        if not docs or not isinstance(docs[0], dict):
            continue
        doc = docs[0]
        col_names = list(doc.keys())
        tables[cname] = col_names
        columns = [
            ColumnSchema(
                name=k,
                data_type=_mongo_type(v),
                is_primary_key=(k == "_id"),
            )
            for k, v in doc.items()
        ]
        table_schemas[cname] = TableSchema(
            name=cname,
            columns=columns,
            primary_keys=["_id"] if "_id" in doc else [],
        )

    return SchemaInfo(
        database=db_name,
        db_type="mongodb",
        tables=tables,
        table_schemas=table_schemas,
    )


# ---------------------------------------------------------------------------
# Legacy API — kept for offline testing only; NOT used in production
# Direct DB connections violate the architecture (all access via MCPToolbox).
# ---------------------------------------------------------------------------

def introspect_schema(db_name: str, config: dict) -> SchemaInfo:
    """
    Inspect the schema of the named database and return a SchemaInfo.

    Args:
        db_name: Logical name of the database (used as SchemaInfo.database).
        config:  Connection config dict with at minimum a "type" key.

    Returns:
        Populated SchemaInfo.  Returns an empty SchemaInfo (tables={}) when
        a connection cannot be established — caller decides if that is fatal.

    Raises:
        ValueError: if config["type"] is not a supported database type.
    """
    db_type = config.get("type", "")
    if db_type == "sqlite":
        return _introspect_sqlite(db_name, config)
    if db_type == "duckdb":
        return _introspect_duckdb(db_name, config)
    if db_type in ("postgres", "postgresql"):
        return _introspect_postgres(db_name, config)
    if db_type == "mongodb":
        return _introspect_mongodb(db_name, config)
    raise ValueError(f"Unsupported database type: {db_type!r}")


# ── SQLite ─────────────────────────────────────────────────────────────────────

def _introspect_sqlite(db_name: str, config: dict) -> SchemaInfo:
    import os as _os
    import sqlite3

    path = config.get("path", "")
    if not path:
        return _empty_schema(db_name, "sqlite")
    path = _os.path.expanduser(path)

    try:
        conn = sqlite3.connect(path)
        try:
            return _read_sqlite(db_name, conn)
        finally:
            conn.close()
    except Exception:
        return _empty_schema(db_name, "sqlite")


def _read_sqlite(db_name: str, conn) -> SchemaInfo:
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    table_names = [row[0] for row in cursor.fetchall()]

    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    all_fks: List[Dict[str, str]] = []
    indexes: Dict[str, List[str]] = {}

    for tname in table_names:
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        cursor.execute(f"PRAGMA table_info({tname})")
        col_rows = cursor.fetchall()
        col_names = [row[1] for row in col_rows]
        pk_names = [row[1] for row in col_rows if row[5] > 0]
        tables[tname] = col_names

        columns = [
            ColumnSchema(
                name=row[1],
                data_type=row[2] or "unknown",
                nullable=not bool(row[3]),
                is_primary_key=row[5] > 0,
            )
            for row in col_rows
        ]

        # PRAGMA foreign_key_list columns: id, seq, table, from, to, on_update, on_delete, match
        cursor.execute(f"PRAGMA foreign_key_list({tname})")
        fk_list: List[Dict[str, str]] = []
        for fk_row in cursor.fetchall():
            fk_entry: Dict[str, str] = {
                "from_col": fk_row[3],
                "to_table": fk_row[2],
                "to_col": fk_row[4],
            }
            fk_list.append(fk_entry)
            all_fks.append({"from_table": tname, **fk_entry})
            for col in columns:
                if col.name == fk_row[3]:
                    col.is_foreign_key = True
                    col.references = f"{fk_row[2]}.{fk_row[4]}"

        table_schemas[tname] = TableSchema(
            name=tname,
            columns=columns,
            primary_keys=pk_names,
            foreign_keys=fk_list,
        )

    cursor.execute(
        "SELECT name, tbl_name FROM sqlite_master "
        "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    for idx_name, tbl_name in cursor.fetchall():
        indexes.setdefault(tbl_name, []).append(idx_name)

    return SchemaInfo(
        database=db_name,
        db_type="sqlite",
        tables=tables,
        table_schemas=table_schemas,
        foreign_keys=all_fks,
        indexes=indexes,
    )


# ── DuckDB ─────────────────────────────────────────────────────────────────────

def _introspect_duckdb(db_name: str, config: dict) -> SchemaInfo:
    try:
        import duckdb
    except ImportError:
        return _empty_schema(db_name, "duckdb")

    path = config.get("path", ":memory:")
    try:
        # In-memory databases cannot be opened read-only
        if path in (":memory:", "", None):
            conn = duckdb.connect(":memory:")
        else:
            conn = duckdb.connect(path, read_only=True)
        try:
            return _read_duckdb(db_name, conn)
        finally:
            conn.close()
    except Exception:
        return _empty_schema(db_name, "duckdb")


def _read_duckdb(db_name: str, conn) -> SchemaInfo:
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}

    try:
        table_rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
        table_names = [row[0] for row in table_rows]
    except Exception:
        table_names = []

    for tname in table_names:
        try:
            col_rows = conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? "
                "ORDER BY ordinal_position",
                [tname],
            ).fetchall()
        except Exception:
            col_rows = []

        col_names = [row[0] for row in col_rows]
        tables[tname] = col_names
        columns = [
            ColumnSchema(
                name=row[0],
                data_type=row[1],
                nullable=(str(row[2]).upper() == "YES"),
            )
            for row in col_rows
        ]
        table_schemas[tname] = TableSchema(name=tname, columns=columns)

    return SchemaInfo(
        database=db_name,
        db_type="duckdb",
        tables=tables,
        table_schemas=table_schemas,
    )


# ── PostgreSQL ─────────────────────────────────────────────────────────────────

def _introspect_postgres(db_name: str, config: dict) -> SchemaInfo:
    connection_string = config.get("connection_string", "")
    if not connection_string:
        return _empty_schema(db_name, "postgres")

    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(connection_string)
        try:
            return _read_postgres(db_name, conn)
        finally:
            conn.close()
    except Exception:
        return _empty_schema(db_name, "postgres")


def _read_postgres(db_name: str, conn) -> SchemaInfo:
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}
    all_fks: List[Dict[str, str]] = []
    indexes: Dict[str, List[str]] = {}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        table_names = [row[0] for row in cur.fetchall()]

        for tname in table_names:
            cur.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "ORDER BY ordinal_position",
                (tname,),
            )
            col_rows = cur.fetchall()
            col_names = [row[0] for row in col_rows]
            tables[tname] = col_names

            cur.execute(
                "SELECT kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "  AND tc.table_schema = kcu.table_schema "
                "WHERE tc.table_schema = 'public' AND tc.table_name = %s "
                "  AND tc.constraint_type = 'PRIMARY KEY'",
                (tname,),
            )
            pk_names = [row[0] for row in cur.fetchall()]

            columns = [
                ColumnSchema(
                    name=row[0],
                    data_type=row[1],
                    nullable=(str(row[2]).upper() == "YES"),
                    is_primary_key=(row[0] in pk_names),
                )
                for row in col_rows
            ]

            cur.execute(
                "SELECT kcu.column_name, ccu.table_name, ccu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "  AND tc.table_schema = kcu.table_schema "
                "JOIN information_schema.constraint_column_usage ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %s",
                (tname,),
            )
            fk_list: List[Dict[str, str]] = []
            for fk_row in cur.fetchall():
                fk_entry: Dict[str, str] = {
                    "from_col": fk_row[0],
                    "to_table": fk_row[1],
                    "to_col": fk_row[2],
                }
                fk_list.append(fk_entry)
                all_fks.append({"from_table": tname, **fk_entry})
                for col in columns:
                    if col.name == fk_row[0]:
                        col.is_foreign_key = True
                        col.references = f"{fk_row[1]}.{fk_row[2]}"

            table_schemas[tname] = TableSchema(
                name=tname,
                columns=columns,
                primary_keys=pk_names,
                foreign_keys=fk_list,
            )

        cur.execute(
            "SELECT tablename, indexname FROM pg_indexes "
            "WHERE schemaname = 'public' ORDER BY tablename, indexname"
        )
        for tbl_name, idx_name in cur.fetchall():
            indexes.setdefault(tbl_name, []).append(idx_name)

    return SchemaInfo(
        database=db_name,
        db_type="postgres",
        tables=tables,
        table_schemas=table_schemas,
        foreign_keys=all_fks,
        indexes=indexes,
    )


# ── MongoDB ────────────────────────────────────────────────────────────────────

def _introspect_mongodb(db_name: str, config: dict) -> SchemaInfo:
    connection_string = config.get("connection_string", "")
    if not connection_string:
        return _empty_schema(db_name, "mongodb")

    try:
        import pymongo  # type: ignore
        client = pymongo.MongoClient(connection_string, serverSelectionTimeoutMS=3000)
        client.server_info()  # raises if unreachable
        # Prefer the database encoded in the URI; fall back to db_name
        uri_db = client.get_default_database(default=None)
        db = uri_db if uri_db is not None else client[db_name]
        try:
            return _read_mongodb(db_name, db)
        finally:
            client.close()
    except Exception:
        return _empty_schema(db_name, "mongodb")


def _read_mongodb(db_name: str, db) -> SchemaInfo:
    """Sample up to 100 documents per collection to infer field names and types."""
    tables: Dict[str, List[str]] = {}
    table_schemas: Dict[str, TableSchema] = {}

    try:
        collection_names = db.list_collection_names()
    except Exception:
        return _empty_schema(db_name, "mongodb")

    for cname in collection_names:
        try:
            sample_docs = list(db[cname].find().limit(100))
        except Exception:
            sample_docs = []

        # Union of all keys seen in sample; track inferred type from first occurrence
        seen_keys: Dict[str, str] = {}
        for doc in sample_docs:
            for key, val in doc.items():
                if key not in seen_keys:
                    seen_keys[key] = _mongo_type(val)

        col_names = list(seen_keys.keys())
        tables[cname] = col_names
        columns = [
            ColumnSchema(
                name=k,
                data_type=v,
                is_primary_key=(k == "_id"),
            )
            for k, v in seen_keys.items()
        ]
        table_schemas[cname] = TableSchema(
            name=cname,
            columns=columns,
            primary_keys=["_id"] if "_id" in seen_keys else [],
        )

    return SchemaInfo(
        database=db_name,
        db_type="mongodb",
        tables=tables,
        table_schemas=table_schemas,
    )


def _mongo_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_schema(db_name: str, db_type: str) -> SchemaInfo:
    return SchemaInfo(database=db_name, db_type=db_type, tables={})
