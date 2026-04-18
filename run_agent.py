#!/usr/bin/env python3
"""Run any DAB dataset query through the Oracle Forge agent (agentic mode).

Reads the KB (kb/domain/dataset_overview.md) to discover database names and
types for the requested dataset, then runs one agentic query with up to
--iterations LLM tool-call steps.

Usage:
    python run_agent.py \\
        --dataset googlelocal \\
        --query query/googlelocal/query.json \\
        --iterations 20 \\
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

Unset databases fall back to OracleForgeAgent’s auto-discovery (DAB directory
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


from agent.config_manager import ConfigManager

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
        required=False,
        help="Path to a JSON file containing the natural-language question string.",
    )
    parser.add_argument(
        "--query_dir",
        required=False,
        help="Path to a directory containing natural-language question string JSON files (e.g. query/bookreview/). Will execute all JSON files inside.",
    )
    parser.add_argument(
        "--use_hints",
        action="store_true",
        help="Search for db_description_with_hint.txt next to query files and use it as domain hints.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=20,
        metavar="N",
        help=(
            "Maximum number of LLM tool-call iterations the agentic loop "
            "is allowed to make per question (default: 20). "
            "Higher values allow more exploration for complex questions."
        ),
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
    args = parser.parse_args()

    queries = []
    if args.query:
        queries.append(Path(args.query))
    if args.query_dir:
        queries.extend(sorted(Path(args.query_dir).rglob("*.json")))
        
    if not queries:
        raise SystemExit("Error: either --query or --query_dir must be provided.")

    config_mgr = ConfigManager(KB_DATASET_OVERVIEW, MCP_TOOLS_YAML)

    # ------------------------------------------------------------------
    # 2. Resolve databases from KB (or CLI override)
    # ------------------------------------------------------------------
    if args.databases:
        databases_info = [{"db_id": db_id, "db_type": ""} for db_id in args.databases]
        db_ids = args.databases
    else:
        if not KB_DATASET_OVERVIEW.exists():
            raise SystemExit(
                f"Error: KB file not found: {KB_DATASET_OVERVIEW}\n"
                "Use --databases to specify database IDs explicitly."
            )
        registry = config_mgr.parse_kb_dataset_registry()
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
    db_configs = config_mgr.build_db_configs_from_env(
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
    print(f"Max iters    : {args.iterations}  (agentic loop LLM steps)")
    print(f"Output prefix: {args.root_name}")
    print(f"Batched runs : {len(queries)} queries found.")
    print()

    # ------------------------------------------------------------------
    # 5. Prepare output directory (nested under dataset name)
    # ------------------------------------------------------------------
    output_dir = Path(args.output_dir) / args.dataset
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 6. Run logic in try/finally
    # ------------------------------------------------------------------
    agent = OracleForgeAgent(
        db_configs=db_configs or None,
        max_iterations=args.iterations,
    )
    
    try:
        for idx, q_path in enumerate(queries, 1):
            print(f"--- Running Query {idx}/{len(queries)}: {q_path.name}")
            
            raw = q_path.read_text(encoding="utf-8").strip()
            try:
                question = json.loads(raw)
            except json.JSONDecodeError:
                question = raw

            hints_text = ""
            if args.use_hints:
                # Look for hint file next to query.json or in the parent dirs if we are batching
                hint_file = q_path.parent / "db_description_with_hint.txt"
                if hint_file.exists():
                    hints_text = hint_file.read_text(encoding="utf-8")
                else:
                    hint_file2 = q_path.parent / "db_description_withhint.txt"
                    if hint_file2.exists():
                        hints_text = hint_file2.read_text(encoding="utf-8")
            
            print(f"Question     : {question}")
            if hints_text:
                print("Hints matched: YES")

            t0 = time.perf_counter()

            result = agent.answer(
                {
                    "question": question,
                    "available_databases": db_ids,
                    "schema_info": {},
                    "hints": hints_text,
                }
            )

            elapsed = round(time.perf_counter() - t0, 3)
            print(f"Finished in {elapsed}s")

            # Attach metadata
            result["_meta"] = {
                "dataset": args.dataset,
                "databases": db_ids,
                "question": question,
                "elapsed_seconds": elapsed,
                "max_iterations": args.iterations,
                "iterations_used": result.get("iterations"),
                "terminate_reason": result.get("terminate_reason"),
            }

            # ------------------------------------------------------------------
            # 7. Write result file
            # ------------------------------------------------------------------
            out_name = args.root_name if len(queries) == 1 else f"{args.root_name}_{q_path.stem}"
            out_file = output_dir / f"{out_name}.json"
            out_file.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
            print(f"Result written to {out_file}")

            # ------------------------------------------------------------------
            # 8. Print final answer
            # ------------------------------------------------------------------
            print(f"Answer       : {result.get('answer')}")
            print(f"Confidence   : {result.get('confidence')}")
            print(f"Iterations   : {result.get('iterations')} / {args.iterations}")
            print(f"Stopped      : {result.get('terminate_reason')}\n")

    finally:
        print("Executing cleanup operations...")
        agent.end_session()


if __name__ == "__main__":
    main()
