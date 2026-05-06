#!/usr/bin/env python3
"""Run Oracle Forge against our local DAB mirror under `runs/<dataset>/<query>/`.

Folder layout (DAB-compatible):

    runs/<dataset>/<query_name>/
        query.json           (scaffolded from DAB)
        ground_truth.csv
        validate.py
        logs/data_agent/<root_name>/
            final_agent.json
            llm_calls.jsonl
            tool_calls.jsonl

Usage:
    # Run one query
    python run_agent.py --dataset agnews --query query1 --root_name run_0

    # Run every query in a dataset
    python run_agent.py --dataset agnews --all --root_name run_0

    # Override databases
    python run_agent.py --dataset bookreview --query query1 --root_name run_0 \\
        --databases books_database review_database
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))
from utils.dab_output import (
    next_query_dir,
    ensure_query_artifacts,
    ensure_run_dir,
    write_dab_style_run,
    write_summary,
)
from dotenv import load_dotenv

load_dotenv()

from agent.config_manager import ConfigManager
from agent.oracle_forge_agent import OracleForgeAgent

KB_DATASET_OVERVIEW = ROOT_DIR / "kb" / "domain" / "dataset_overview.md"
MCP_TOOLS_YAML = ROOT_DIR / "mcp" / "tools.yaml"
RUNS_ROOT = ROOT_DIR / "runs"

# Canonical DB type names as understood by the agent
_TYPE_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mongodb": "mongodb",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
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
        help="Prefix for per-run log files inside logs/ (default: run).",
    )
    parser.add_argument(
        "--output_dir",
        default="results",
        help="Root directory for result folders (default: results/).",
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

    dataset_root = RUNS_ROOT / args.dataset
    if not dataset_root.is_dir():
        raise SystemExit(
            f"Dataset not scaffolded: {dataset_root}\n"
            f"Run: python scripts/scaffold_bench.py --dataset {args.dataset}"
        )

    query_dirs = _select_query_dirs(dataset_root, args.query, args.all)

    config_mgr = ConfigManager(KB_DATASET_OVERVIEW, MCP_TOOLS_YAML)
    if args.databases:
        databases_info = [{"db_id": db_id, "db_type": ""} for db_id in args.databases]
        db_ids = args.databases
    else:
        registry = config_mgr.parse_kb_dataset_registry()
        key = args.dataset.lower()
        if key not in registry:
            raise SystemExit(
                f"Dataset '{args.dataset}' not in KB registry.\n"
                f"Known: {sorted(registry.keys())}\nUse --databases to override."
            )
        databases_info = registry[key]
        db_ids = [d["db_id"] for d in databases_info]

    db_configs = config_mgr.build_db_configs_from_env(
        databases_info, dataset_name=args.dataset.lower()
    )
    # validate_runtime_dependencies(databases_info, db_configs)  # TODO: Implement if needed

    print(f"Dataset      : {args.dataset}")
    print(f"Databases    : {db_ids}")
    print(
        f"DB configs   : {list(db_configs.keys()) or '(agent will auto-discover)'}"
    )
    print(f"Max iters    : {args.iterations}  (agentic loop LLM steps)")
    print(f"Output prefix: {args.root_name}")
    print(f"Batched runs : {len(queries)} queries found.")
    print(f"Iterations   : {args.iterations}")
    print(f"Log prefix    : {args.root_name}")
    print()

    # ------------------------------------------------------------------
    # 5. Prepare output directory using query-centered layout
    # ------------------------------------------------------------------
    # DAB-style output root
    dataset_dir = Path(args.output_dir) / f"query_{args.dataset}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    target_query_dir = next_query_dir(dataset_dir)

    # copy query.json + validate.py + ground_truth.csv if present
    if queries:
        ensure_query_artifacts(target_query_dir, queries[0])
    # ------------------------------------------------------------------
    # 6. Run logic in try/finally
    # ------------------------------------------------------------------
    agent = OracleForgeAgent(
        db_configs=db_configs or None,
        max_iterations=args.iterations,
    )
    
    try:
        for idx, qdir in enumerate(query_dirs, 1):
            print(f"--- ({idx}/{len(query_dirs)}) {args.dataset}/{qdir.name}")
            question = _load_question(qdir)

            log_dir = qdir / "logs" / "data_agent" / args.root_name
            if log_dir.exists():
                if not args.force:
                    print(f"  SKIP: {log_dir} already exists (use --force to overwrite)\n")
                    continue
                # Remove old logs; mirrors DAB's assert-not-exists contract once cleared
                for f in ("final_agent.json", "llm_calls.jsonl", "tool_calls.jsonl"):
                    (log_dir / f).unlink(missing_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)

            hints_text = ""
            if args.use_hints:
                for fname in ("db_description_with_hint.txt", "db_description_withhint.txt"):
                    hint_file = qdir / fname
                    if hint_file.exists():
                        hints_text = hint_file.read_text(encoding="utf-8")
                        break

            print(f"  question: {question!r}")
            run_start = time.time()
            result = agent.answer(
                {
                    "question": question,
                    "available_databases": db_ids,
                    "schema_info": {},
                    "hints": hints_text,
                    "log_dir": log_dir,
                }
            )
            run_name = args.root_name if len(queries) == 1 else f"{args.root_name}_{q_path.stem}"

            per_query_dir = target_query_dir if len(queries) == 1 else (target_query_dir / q_path.stem)
            per_query_dir.mkdir(parents=True, exist_ok=True)
            if len(queries) > 1:
                ensure_query_artifacts(per_query_dir, q_path)

            run_dir = ensure_run_dir(per_query_dir, run_name)

            # these stay empty until OracleForgeAgent exposes them
            llm_calls = getattr(agent, "llm_calls", [])
            tool_calls = getattr(agent, "tool_calls", [])

            write_dab_style_run(
                run_dir,
                result,
                llm_calls=llm_calls,
                tool_calls=tool_calls,
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
            # 8. Print final answer
            # ------------------------------------------------------------------
            print(f"Answer       : {result.get('answer')}")
            print(f"Confidence   : {result.get('confidence')}")
            print(f"Iterations   : {result.get('iterations')} / {args.iterations}")
            print(f"Stopped      : {result.get('terminate_reason')}\n")

        summary_path = write_summary(
            target_query_dir=target_query_dir,
            root_name=args.root_name,
            dataset=args.dataset,
            db_ids=db_ids,
            question=str(question),
            iterations=len(queries),
            all_results=[],
            output_root=Path(args.output_dir),
        )
        print(f"Summary written to {summary_path}")
        
        # ------------------------------------------------------------------
        # 7. Write summary file
        # ------------------------------------------------------------------
        all_results = []  # Initialize empty results list for single query run
        summary_path = per_query_dir / f"{args.root_name}_summary.json"
        summary = {
            "dataset": args.dataset,
            "databases": db_ids,
            "question": question,
            "query_file": str((per_query_dir / "query.json").relative_to(Path(args.output_dir))),
            "iterations": args.iterations,
            "results": all_results,
        }
        summary_path.write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nSummary written to {summary_path}")

    except Exception as e:
        print(f"Error during execution: {e}")
        raise
    finally:
        print("cleanup...")
        agent.end_session()


if __name__ == "__main__":
    main()
