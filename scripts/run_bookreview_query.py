#!/usr/bin/env python3
"""Run one natural language query against the BookReview database."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# Ensure repo root is on sys.path so `from agent...` works when the script is run from scripts/
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv()

from agent.oracle_forge_agent import OracleForgeAgent


def build_db_configs(database_id: str, db_type: str, connection: str) -> Dict[str, dict]:
    db_type = db_type.lower()
    if db_type in {"postgres", "mongodb"}:
        return {
            database_id: {
                "type": db_type,
                "connection_string": connection,
            }
        }
    if db_type in {"sqlite", "duckdb"}:
        return {
            database_id: {
                "type": db_type,
                "path": connection,
            }
        }
    raise ValueError(f"Unsupported db type: {db_type}")


def next_query_dir(dataset_dir: Path) -> Path:
    existing_numbers: List[int] = []
    for child in dataset_dir.iterdir() if dataset_dir.exists() else []:
        if not child.is_dir() or not child.name.startswith("query"):
            continue
        try:
            suffix = child.name.removeprefix("query").removeprefix("_")
            existing_numbers.append(int(suffix))
        except ValueError:
            continue
    next_number = max(existing_numbers, default=0) + 1
    return dataset_dir / f"query{next_number}"


def render_db_config_yaml(db_configs: Dict[str, dict]) -> str:
    lines = ["databases:"]
    for db_id, config in db_configs.items():
        lines.append(f"  {db_id}:")
        for key, value in config.items():
            rendered = json.dumps(value)
            lines.append(f"    {key}: {rendered}")
    return "\n".join(lines) + "\n"


def _load_description_text(path: Path, title: str) -> str:
    if not path.exists():
        return f"{title}\n\nSource file missing: {path}\n"
    return f"{title}\n\nSource: {path.relative_to(ROOT_DIR)}\n\n{path.read_text(encoding='utf-8')}"


def export_eval_bundle(
    dataset_dir: Path,
    question: str,
    result: Dict[str, object],
    db_configs: Dict[str, dict],
    trace_events: List[Dict[str, object]],
) -> Path:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "query_dataset").mkdir(exist_ok=True)

    query_dir = next_query_dir(dataset_dir)
    query_dir.mkdir(parents=True, exist_ok=False)

    (dataset_dir / "db_config.yaml").write_text(
        render_db_config_yaml(db_configs),
        encoding="utf-8",
    )
    (dataset_dir / "db_description.txt").write_text(
        _load_description_text(ROOT_DIR / "kb" / "domain" / "schema.md", "Database description"),
        encoding="utf-8",
    )
    (dataset_dir / "db_description_with_hint.txt").write_text(
        _load_description_text(
            ROOT_DIR / "kb" / "domain" / "dataset_overview.md",
            "Database description with hints",
        ),
        encoding="utf-8",
    )

    (query_dir / "query.json").write_text(json.dumps(question), encoding="utf-8")
    (query_dir / "ground_truth.csv").write_text("", encoding="utf-8")
    (query_dir / "validate.py").write_text(
        """#!/usr/bin/env python3
\"\"\"Validation placeholder for a single DAB benchmark query.\"\"\"

from __future__ import annotations

from typing import Any


def validate(query_df: Any, llm_answer: str, team_name: str = "Team PaLM", team_reason: str = "") -> dict:
    return {
        "timestamp": "",
        "query_name": __file__.split("/")[-2],
        "is_valid": False,
        "reason": team_reason or "Validation logic not implemented yet.",
        "ground_truth": "",
        "llm_answer": llm_answer,
    }


if __name__ == "__main__":
    raise SystemExit("Import validate() from this module to run benchmark validation.")
""",
        encoding="utf-8",
    )
    (query_dir / "run_result.json").write_text(
        json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
                "trace_events": trace_events,
                "db_configs": db_configs,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return query_dir


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Run a single natural language query against the BookReview database."
    )
    parser.add_argument("--question", required=True, help="Natural language question to answer.")
    parser.add_argument(
        "--db-type",
        default=os.getenv("BOOKREVIEW_DB_TYPE", "postgres"),
        choices=["postgres", "mongodb", "sqlite", "duckdb"],
        help="Database type for the BookReview database.",
    )
    parser.add_argument(
        "--connection",
        default=os.getenv("BOOKREVIEW_DB_CONN", ""),
        help=(
            "Connection string for postgres/mongodb or file path for sqlite/duckdb. "
            "Optional for postgres/mongodb — query execution is routed through the "
            "MCP Toolbox (MCP_TOOLBOX_URL). If omitted, schema introspection falls "
            "back to KB Layer 2 knowledge. Can also be set via BOOKREVIEW_DB_CONN."
        ),
    )
    parser.add_argument(
        "--db-id",
        default=os.getenv("BOOKREVIEW_DB_ID", "books_database"),
        help="Logical database identifier used by the agent (default: books_database).",
    )
    parser.add_argument(
        "--eval-dir",
        default=str(ROOT_DIR / "query_bookreview"),
        help="Directory where the DAB-style query export should be written.",
    )
    parser.add_argument("--output", default=None, help="Write JSON result to this file.")
    args = parser.parse_args()

    if not args.connection and args.db_type in {"sqlite", "duckdb"}:
        raise SystemExit(
            f"Error: --connection (file path) is required for --db-type {args.db_type}."
        )

    db_configs = build_db_configs(args.db_id, args.db_type, args.connection)
    agent = OracleForgeAgent(db_configs=db_configs)
    result = agent.answer(
        {
            "question": args.question,
            "available_databases": [args.db_id],
            "schema_info": {},
        }
    )
    harness = agent.get_harness()
    session_id = agent.get_harness_session_id()
    trace_events = [
        event
        for event in harness.parse_trace_log()
        if event.get("session_id") == session_id
    ]
    exported_query_dir = export_eval_bundle(
        dataset_dir=Path(args.eval_dir),
        question=args.question,
        result=result,
        db_configs=db_configs,
        trace_events=trace_events,
    )

    output_text = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Wrote result to {args.output}")
    else:
        print(output_text)
    print(f"Exported DAB-style eval bundle to {exported_query_dir}")


if __name__ == "__main__":
    main()
