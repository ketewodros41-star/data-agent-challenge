"""
schema_introspector.py
─────────────────────
Connects to any of the four DAB database types and returns a
standardised schema dict — same output format regardless of source.

Supported:  PostgreSQL · MongoDB · SQLite · DuckDB

Usage:
    from utils.schema_introspector import introspect

    schema = introspect("bookreview", db_type="postgresql")
    # → {"tables": [{"name": "...", "columns": [...], "row_count": ...}]}

Drivers inject the returned dict into KB v2 at session start.
Intelligence Officers use it to populate dab_database_schemas.md.
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import psycopg2
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ── connection defaults (mirror common_scaffold/tools/db_utils) ──────────
PG_HOST     = os.getenv("PG_HOST",     "127.0.0.1")
PG_PORT     = int(os.getenv("PG_PORT", "5432"))
PG_USER     = os.getenv("PG_USER",     "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DB       = os.getenv("PG_DB",       "test")
MONGO_URI   = os.getenv("MONGO_URI",   "mongodb://localhost:27017/")

# Datasets present on your server and their db_type per database
# Extend this as more datasets are loaded
DATASET_DB_MAP: dict[str, list[dict]] = {
    "agnews":           [{"type": "mongodb",    "name": "agnews"},
                         {"type": "sqlite",     "path": "query_agnews/query_dataset/agnews.db"}],
    "bookreview":       [{"type": "postgresql", "name": "bookreview"},
                         {"type": "sqlite",     "path": "query_bookreview/query_dataset/review_query.db"}],
    "crmarenapro":      [{"type": "duckdb",     "path": "query_crmarenapro/query_dataset/crm.duckdb"},
                         {"type": "postgresql", "name": "crmarenapro"},
                         {"type": "sqlite",     "path": "query_crmarenapro/query_dataset/crm.db"}],
    "deps_dev_v1":      [{"type": "duckdb",     "path": "query_DEPS_DEV_V1/query_dataset/deps.duckdb"},
                         {"type": "sqlite",     "path": "query_DEPS_DEV_V1/query_dataset/deps.db"}],
    "github_repos":     [{"type": "duckdb",     "path": "query_GITHUB_REPOS/query_dataset/github.duckdb"},
                         {"type": "sqlite",     "path": "query_GITHUB_REPOS/query_dataset/github.db"}],
    "googlelocal":      [{"type": "postgresql", "name": "googlelocal"},
                         {"type": "sqlite",     "path": "query_googlelocal/query_dataset/googlelocal.db"}],
    "music_brainz_20k": [{"type": "duckdb",     "path": "query_music_brainz_20k/query_dataset/mb.duckdb"},
                         {"type": "sqlite",     "path": "query_music_brainz_20k/query_dataset/mb.db"}],
    "pancancer_atlas":  [{"type": "duckdb",     "path": "query_PANCANCER_ATLAS/query_dataset/pancancer.duckdb"},
                         {"type": "postgresql", "name": "pancancer_atlas"}],
    "patents":          [{"type": "postgresql", "name": "patents"},
                         {"type": "sqlite",     "path": "query_PATENTS/query_dataset/patent_publication.db"}],
    "stockindex":       [{"type": "duckdb",     "path": "query_stockindex/query_dataset/stockindex.duckdb"},
                         {"type": "sqlite",     "path": "query_stockindex/query_dataset/stockindex.db"}],
    "stockmarket":      [{"type": "duckdb",     "path": "query_stockmarket/query_dataset/stockmarket.duckdb"},
                         {"type": "sqlite",     "path": "query_stockmarket/query_dataset/stockmarket.db"}],
    "yelp":             [{"type": "duckdb",     "path": "query_yelp/query_dataset/yelp.duckdb"},
                         {"type": "mongodb",    "name": "yelp"}],
}


# ── public API ────────────────────────────────────────────────────────────

def introspect(dataset: str, db_type: str | None = None) -> dict[str, Any]:
    """
    Return standardised schema for a DAB dataset.

    Args:
        dataset:  dataset name, e.g. "bookreview"
        db_type:  "postgresql" | "mongodb" | "sqlite" | "duckdb"
                  If None, introspects ALL databases for that dataset.

    Returns:
        {
          "dataset":   str,
          "databases": [
            {
              "type":   str,
              "tables": [
                {
                  "name":      str,
                  "columns":   [{"name": str, "type": str}],
                  "row_count": int | None
                }
              ]
            }
          ]
        }
    """
    dataset = dataset.lower()
    if dataset not in DATASET_DB_MAP:
        raise ValueError(f"Unknown dataset '{dataset}'. Known: {list(DATASET_DB_MAP)}")

    dbs = DATASET_DB_MAP[dataset]
    if db_type:
        dbs = [d for d in dbs if d["type"] == db_type]
        if not dbs:
            raise ValueError(f"No {db_type!r} database found for dataset '{dataset}'")

    result: dict[str, Any] = {"dataset": dataset, "databases": []}
    for db_cfg in dbs:
        t = db_cfg["type"]
        try:
            if t == "postgresql":
                tables = _introspect_pg(db_cfg.get("name", PG_DB))
            elif t == "mongodb":
                tables = _introspect_mongo(db_cfg.get("name", dataset))
            elif t == "sqlite":
                tables = _introspect_sqlite(db_cfg["path"])
            elif t == "duckdb":
                tables = _introspect_duckdb(db_cfg["path"])
            else:
                raise ValueError(f"Unsupported db type: {t}")
            result["databases"].append({"type": t, "tables": tables})
        except Exception as exc:
            result["databases"].append({"type": t, "error": str(exc)})

    return result


def introspect_to_markdown(dataset: str, db_type: str | None = None) -> str:
    """Return schema as a markdown table — ready to paste into KB v2."""
    data = introspect(dataset, db_type)
    lines = [f"## Schema: {data['dataset']}\n"]
    for db in data["databases"]:
        lines.append(f"### Database type: `{db['type']}`")
        if "error" in db:
            lines.append(f"> Error: {db['error']}\n")
            continue
        for tbl in db["tables"]:
            lines.append(f"\n#### Table: `{tbl['name']}`")
            if tbl.get("row_count") is not None:
                lines.append(f"Row count: {tbl['row_count']:,}")
            lines.append("| Column | Type |")
            lines.append("|--------|------|")
            for col in tbl["columns"]:
                lines.append(f"| {col['name']} | {col['type']} |")
    return "\n".join(lines)


# ── private helpers ───────────────────────────────────────────────────────

def _introspect_pg(db_name: str) -> list[dict]:
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=db_name
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = []
    for (tbl,) in cur.fetchall():
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            ORDER BY ordinal_position
        """, (tbl,))
        cols = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
        cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
        row_count = cur.fetchone()[0]
        tables.append({"name": tbl, "columns": cols, "row_count": row_count})
    conn.close()
    return tables


def _introspect_mongo(db_name: str) -> list[dict]:
    client = MongoClient(MONGO_URI)
    db = client[db_name]
    tables = []
    for coll_name in db.list_collection_names():
        sample = db[coll_name].find_one() or {}
        cols = [{"name": k, "type": type(v).__name__} for k, v in sample.items()]
        row_count = db[coll_name].estimated_document_count()
        tables.append({"name": coll_name, "columns": cols, "row_count": row_count})
    client.close()
    return tables


def _introspect_sqlite(path: str) -> list[dict]:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = []
    for (tbl,) in cur.fetchall():
        cur.execute(f"PRAGMA table_info('{tbl}')")
        cols = [{"name": r[1], "type": r[2]} for r in cur.fetchall()]
        cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
        row_count = cur.fetchone()[0]
        tables.append({"name": tbl, "columns": cols, "row_count": row_count})
    conn.close()
    return tables


def _introspect_duckdb(path: str) -> list[dict]:
    conn = duckdb.connect(path, read_only=True)
    tables = []
    for (tbl,) in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
    ).fetchall():
        cols_raw = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name='{tbl}' ORDER BY ordinal_position"
        ).fetchall()
        cols = [{"name": r[0], "type": r[1]} for r in cols_raw]
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
        tables.append({"name": tbl, "columns": cols, "row_count": row_count})
    conn.close()
    return tables
