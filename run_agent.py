#!/usr/bin/env python3
"""Run any DAB dataset query through the Oracle Forge agent.

Reads the KB (kb/domain/dataset_overview.md) to discover database names and
types for the requested dataset, then drives the agent for N iterations.

Usage:
    python run_agent.py \\
        --dataset googlelocal \\
        --query query/googlelocal/query.json \\
        --iterations 10 \\
        --root_name run_0

    # Override databases discovered from KB
    python run_agent.py \\
        --dataset bookreview \\
        --query query/bookreview/query.json \\
        --databases books_database review_database \\
        --root_name run_0

Connection strings are read from env vars using the pattern:
    {DB_ID_UPPER}_DB_TYPE   — sqlite | duckdb | postgres | mongodb
    {DB_ID_UPPER}_DB_CONN   — connection string (postgres/mongodb) or file path
    {DB_ID_UPPER}_DB_PATH   — file path (sqlite/duckdb, preferred over _DB_CONN)

Unset databases fall back to OracleForgeAgent's auto-discovery (DAB directory
structure + known dataset defaults).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv()

from agent.oracle_forge_agent import OracleForgeAgent

KB_DATASET_OVERVIEW = ROOT_DIR / "kb" / "domain" / "dataset_overview.md"
MCP_TOOLS_YAML = ROOT_DIR / "mcp" / "tools.yaml"

# Canonical DB type names as understood by the agent
_TYPE_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mongodb": "mongodb",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
}


# ---------------------------------------------------------------------------
# mcp/tools.yaml reader
# ---------------------------------------------------------------------------


def _parse_yaml_simple(text: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for mcp/tools.yaml (used when pyyaml is unavailable).
    Handles 2-space-indented nested mappings with scalar values only.
    """
    result: Dict[str, Any] = {}
    stack: list = [(-1, result)]

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        content = line.strip()
        if ":" not in content:
            continue
        key, sep, value = content.partition(":")
        key = key.strip()
        value = value.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else result
        if value:
            parent[key] = value
        else:
            new_dict: Dict[str, Any] = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
    return result


def _load_toolbox_yaml() -> Dict[str, Any]:
    """Parse mcp/tools.yaml; try pyyaml first, fall back to built-in parser."""
    if not MCP_TOOLS_YAML.exists():
        return {}
    text = MCP_TOOLS_YAML.read_text(encoding="utf-8")
    try:
        import yaml
        raw = yaml.safe_load(text)
        return raw if isinstance(raw, dict) else {}
    except ImportError:
        return _parse_yaml_simple(text)
    except Exception:
        return {}


def _load_toolbox_sources() -> Dict[str, Dict[str, Any]]:
    """Parse mcp/tools.yaml and return {source_name: source_config}."""
    raw = _load_toolbox_yaml()
    return raw.get("sources", {}) if raw else {}


def _load_toolbox_tools() -> Dict[str, Dict[str, Any]]:
    """Parse mcp/tools.yaml and return {tool_name: tool_config}."""
    raw = _load_toolbox_yaml()
    return raw.get("tools", {}) if raw else {}


def _toolbox_mcp_tool_for_source(source_name: str) -> str:
    """Return the MCP tool name whose `source:` matches *source_name*, or ''."""
    for tool_name, tool_cfg in _load_toolbox_tools().items():
        if isinstance(tool_cfg, dict) and tool_cfg.get("source") == source_name:
            return tool_name
    return ""


def _toolbox_postgres_mcp_tool(dataset_name: str) -> str:
    """
    Return the postgres-execute-sql MCP tool name for the given dataset.

    Looks up mcp/tools.yaml: finds the postgres source whose `database` field
    contains the dataset name, then returns the dynamic execute-sql tool that
    uses that source (e.g. 'run_query' for bookreview, 'run_query_googlelocal'
    for googlelocal).  Static postgres-sql tools (list_tables, describe_*,
    preview_*) are skipped — only 'kind: postgres-execute-sql' tools qualify.
    Falls back to 'run_query' when no specific tool is found.
    """
    sources = _load_toolbox_sources()
    tools = _load_toolbox_tools()

    pg_sources = {
        name: cfg for name, cfg in sources.items() if cfg.get("kind") == "postgres"
    }
    if not pg_sources:
        return "run_query"

    d = dataset_name.lower()

    # Best-match: source name or database field contains the dataset name (or vice versa).
    # Also check word-level matching: any significant word from the source name
    # appears in the dataset name (e.g. "crm" from "postgres_crm_support" in "crmarenapro").
    def _source_matches(src_name: str, src_cfg: dict) -> bool:
        sname = src_name.lower()
        pg_db = src_cfg.get("database", "").lower()
        if d in sname or d in pg_db or sname in d or pg_db.replace("_", "") in d:
            return True
        # Word-level: any meaningful word (>2 chars) in source/db name found in dataset
        words = [w for w in sname.split("_") + pg_db.split("_") if len(w) > 2 and w != "postgres"]
        return any(w in d for w in words)

    chosen_source_name = next(
        (name for name, cfg in pg_sources.items() if _source_matches(name, cfg)),
        next(iter(pg_sources.keys())),  # fallback: first postgres source
    )

    # Find the execute-sql tool (not static sql tools like list_tables)
    for tool_name, tool_cfg in tools.items():
        if not isinstance(tool_cfg, dict):
            continue
        if tool_cfg.get("source") == chosen_source_name and tool_cfg.get("kind") == "postgres-execute-sql":
            return tool_name
    return "run_query"


def _toolbox_sqlite_config(dataset_name: str) -> Optional[Tuple[str, str]]:
    """
    Find the SQLite source for a dataset in mcp/tools.yaml.

    Returns (host_path, mcp_tool_name) or None.

    The toolbox stores container-internal paths (e.g. /datasets/query_bookreview/…).
    We translate those to host paths via the SQLITE_{DATASET_UPPER} env var.
    """
    sources = _load_toolbox_sources()
    for source_name, cfg in sources.items():
        if cfg.get("kind") != "sqlite":
            continue
        container_path = cfg.get("database", "")
        # Match by dataset name appearing in the container path
        if f"query_{dataset_name.lower()}" not in container_path:
            continue
        # Host-side path: SQLITE_{DATASET_UPPER} env var, or None
        host_path = os.getenv(f"SQLITE_{dataset_name.upper()}", "")
        if not host_path:
            # Fall back to the container path (works when running inside Docker)
            host_path = container_path
        host_path = os.path.expanduser(host_path)
        mcp_tool = _toolbox_mcp_tool_for_source(source_name)
        return host_path, mcp_tool
    return None


# ---------------------------------------------------------------------------
# KB parser
# ---------------------------------------------------------------------------


def parse_kb_dataset_registry(kb_path: Path) -> Dict[str, List[Dict[str, str]]]:
    """
    Parse kb/domain/dataset_overview.md and return a mapping of
    dataset_name → list of {db_id, db_type} dicts.

    Dataset names are lowercased so look-ups are case-insensitive.
    db_type is empty-string when the MD entry is ambiguous (e.g.
    "see full db_description").  The agent handles those via auto-discovery.
    """
    text = kb_path.read_text(encoding="utf-8")

    # Split text at dataset-level headings: ## N. datasetname
    section_pat = re.compile(r"^##\s+\d+\.\s+(\S+)", re.MULTILINE)
    splits = list(section_pat.finditer(text))

    registry: Dict[str, List[Dict[str, str]]] = {}

    for idx, match in enumerate(splits):
        dataset_name = match.group(1).lower()
        section_start = match.start()
        section_end = splits[idx + 1].start() if idx + 1 < len(splits) else len(text)
        section_text = text[section_start:section_end]

        # Each section opens with a markdown table listing databases.
        # There may be additional tables later (e.g. exchange-to-index maps) —
        # restrict parsing to the FIRST contiguous table block only.
        first_table_pat = re.compile(r"(?:^\|[^\n]*\n)+", re.MULTILINE)
        first_table_match = first_table_pat.search(section_text)
        table_text = first_table_match.group(0) if first_table_match else ""

        row_pat = re.compile(r"^\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|", re.MULTILINE)
        databases: List[Dict[str, str]] = []

        for row_match in row_pat.finditer(table_text):
            col1 = row_match.group(1).strip()
            col2 = row_match.group(2).strip()

            # Skip separator rows (---|---) and header rows
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", col1):
                continue
            if col1.lower() in ("database", "db", "databases"):
                continue

            # Extract DB type from the first word of col2
            first_word = col2.lower().split()[0] if col2 else ""
            db_type = _TYPE_MAP.get(first_word, "")

            databases.append({"db_id": col1, "db_type": db_type})

        if databases:
            registry[dataset_name] = databases

    return registry


# ---------------------------------------------------------------------------
# DB config builder — env vars with mcp/tools.yaml fallback
# ---------------------------------------------------------------------------


def build_db_configs_from_env(
    databases_info: List[Dict[str, str]],
    dataset_name: str = "",
) -> Dict[str, dict]:
    """
    Build db_configs for OracleForgeAgent.

    Resolution order per database:
      1. Explicit env vars  — {DB_ID_UPPER}_DB_TYPE / _DB_CONN / _DB_PATH / _MCP_TOOL
      2. mcp/tools.yaml     — find the execute-sql MCP tool for PostgreSQL sources;
                              translate SQLite container paths via SQLITE_{DATASET_UPPER}.

    All database access goes through the MCP toolbox (never direct connections).
    For PostgreSQL, the config carries only the mcp_tool name (e.g. "run_query_bookreview").
    For SQLite, the config carries the host-side path and mcp_tool name.
    For DuckDB, agent auto-discovers via DAB directory structure.

    The `dataset_name` argument enables the tools.yaml lookup to pick the right
    source when there are multiple databases of the same type (e.g. several
    postgres databases across different datasets).
    """
    configs: Dict[str, dict] = {}

    for entry in databases_info:
        db_id = entry["db_id"]
        kb_type = entry["db_type"]  # may be ""
        prefix = db_id.upper()

        db_type = os.getenv(f"{prefix}_DB_TYPE", kb_type).lower()

        if db_type in ("sqlite", "duckdb"):
            # 1. Explicit env vars
            path = (
                os.getenv(f"{prefix}_DB_PATH", "")
                or os.getenv(f"{prefix}_DB_CONN", "")
            )
            mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "")

            # 3. tools.yaml fallback for sqlite (duckdb has its own service, skip)
            if not path and db_type == "sqlite" and dataset_name:
                result = _toolbox_sqlite_config(dataset_name)
                if result:
                    path, mcp_tool = result

            if path:
                path = os.path.expanduser(path)
                cfg: dict = {"type": db_type, "path": path}
                if mcp_tool:
                    cfg["mcp_tool"] = mcp_tool
                configs[db_id] = cfg
            # else: agent auto-discovers (e.g. DAB directory scan)

        elif db_type in ("postgres", "postgresql"):
            # All postgres access goes through the MCP toolbox (never direct connections).
            # Resolve the per-database execute-sql tool from tools.yaml.
            mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "") or _toolbox_postgres_mcp_tool(dataset_name or db_id)
            cfg: dict = {"type": "postgres"}
            if mcp_tool:
                cfg["mcp_tool"] = mcp_tool
            configs[db_id] = cfg

        elif db_type == "mongodb":
            conn = os.getenv(f"{prefix}_DB_CONN", "") or os.getenv("MONGODB_URL", "")
            configs[db_id] = {"type": "mongodb", "connection_string": conn}

        # db_type == "" → nothing to add; agent auto-discovers

    return configs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a natural-language query against any DAB dataset via the "
            "Oracle Forge agent.  Database names and types are looked up "
            "automatically from kb/domain/dataset_overview.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="DAB dataset name (e.g. googlelocal, bookreview, yelp).",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Path to a JSON file containing the natural-language question string.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        metavar="N",
        help="Number of times to run the query (default: 1).",
    )
    parser.add_argument(
        "--root_name",
        default="run",
        help="Prefix for output files (default: run).",
    )
    parser.add_argument(
        "--output_dir",
        default="results",
        help="Directory for result files (default: results/).",
    )
    parser.add_argument(
        "--databases",
        nargs="+",
        metavar="DB_ID",
        default=None,
        help=(
            "Override the KB-derived database list.  "
            "Specify logical DB IDs, e.g. --databases review_database business_database"
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Create a new agent instance for every iteration (isolated runs).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Load the question
    # ------------------------------------------------------------------
    query_path = Path(args.query)
    if not query_path.exists():
        raise SystemExit(f"Error: query file not found: {query_path}")
    raw = query_path.read_text(encoding="utf-8").strip()
    try:
        question = json.loads(raw)
    except json.JSONDecodeError:
        question = raw  # treat as a plain string if not valid JSON
    if not isinstance(question, str):
        raise SystemExit(
            f"Error: query file must contain a JSON string. "
            f"Got {type(question).__name__}."
        )

    # ------------------------------------------------------------------
    # 2. Resolve databases from KB (or CLI override)
    # ------------------------------------------------------------------
    if args.databases:
        # User explicitly listed the database IDs — no type info from KB
        databases_info = [{"db_id": db_id, "db_type": ""} for db_id in args.databases]
        db_ids = args.databases
    else:
        if not KB_DATASET_OVERVIEW.exists():
            raise SystemExit(
                f"Error: KB file not found: {KB_DATASET_OVERVIEW}\n"
                "Use --databases to specify database IDs explicitly."
            )
        registry = parse_kb_dataset_registry(KB_DATASET_OVERVIEW)
        dataset_key = args.dataset.lower()
        if dataset_key not in registry:
            raise SystemExit(
                f"Error: dataset '{args.dataset}' not found in KB.\n"
                f"Known datasets: {', '.join(sorted(registry.keys()))}\n"
                "Use --databases to override."
            )
        databases_info = registry[dataset_key]
        db_ids = [d["db_id"] for d in databases_info]

    # ------------------------------------------------------------------
    # 3. Build explicit db_configs from env vars / mcp/tools.yaml
    # ------------------------------------------------------------------
    db_configs = build_db_configs_from_env(
        databases_info, dataset_name=args.dataset.lower()
    )

    # ------------------------------------------------------------------
    # 4. Print run summary header
    # ------------------------------------------------------------------
    print(f"Dataset      : {args.dataset}")
    print(f"Databases    : {db_ids}")
    print(
        f"DB configs   : {list(db_configs.keys()) or '(agent will auto-discover)'}"
    )
    print(f"Question     : {question}")
    print(f"Iterations   : {args.iterations}")
    print(f"Output prefix: {args.root_name}")
    print()

    # ------------------------------------------------------------------
    # 5. Prepare output directory (nested under dataset name)
    # ------------------------------------------------------------------
    output_dir = Path(args.output_dir) / args.dataset
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 6. Run iterations
    # ------------------------------------------------------------------
    agent: Optional[OracleForgeAgent] = None
    all_results: List[dict] = []

    for i in range(1, args.iterations + 1):
        if args.fresh or agent is None:
            agent = OracleForgeAgent(db_configs=db_configs or None)

        print(f"[{i}/{args.iterations}] Running...", end=" ", flush=True)
        t0 = time.perf_counter()

        result = agent.answer(
            {
                "question": question,
                "available_databases": db_ids,
                "schema_info": {},
            }
        )

        elapsed = round(time.perf_counter() - t0, 3)

        # Attach metadata
        result["_meta"] = {
            "iteration": i,
            "dataset": args.dataset,
            "databases": db_ids,
            "question": question,
            "elapsed_seconds": elapsed,
        }
        all_results.append(result)

        # Write per-iteration file
        out_file = output_dir / f"{args.root_name}_iter_{i}.json"
        out_file.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        print(f"done ({elapsed}s)  →  {out_file}")

    # End the agent session (triggers Layer-3 autoDream consolidation)
    if agent is not None:
        agent.end_session()

    # ------------------------------------------------------------------
    # 7. Write summary file
    # ------------------------------------------------------------------
    summary_path = output_dir / f"{args.root_name}_summary.json"
    summary = {
        "dataset": args.dataset,
        "databases": db_ids,
        "question": question,
        "iterations": args.iterations,
        "results": all_results,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nSummary written to {summary_path}")

    # ------------------------------------------------------------------
    # 8. Print final answer from the last iteration
    # ------------------------------------------------------------------
    last = all_results[-1]
    print(f"\nFinal answer : {last.get('answer')}")
    print(f"Confidence   : {last.get('confidence')}")
    if last.get("correction_applied"):
        print("(correction was applied)")


if __name__ == "__main__":
    main()
