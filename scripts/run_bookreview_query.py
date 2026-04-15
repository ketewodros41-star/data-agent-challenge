#!/usr/bin/env python3
"""Run one or more natural language queries against the BookReview database."""

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


BOOKREVIEW_BENCHMARK_QUESTIONS = [
    "Which decade of publication (e.g., 1980s) has the highest average rating among decades with at least 10 distinct books that have been rated? Return the decade with the highest average rating.",
    "Which English-language books in the 'Literature & Fiction' category have a perfect average rating of 5.0? Return all matching books.",
    "Which books categorized as 'Children's Books' have received an average rating of at least 4.5 based on reviews from 2020 onwards?",
]


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
\"\"\"Validation helper for a single DAB benchmark query.\"\"\"

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return _normalize(parsed)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def _load_ground_truth() -> str:
    ground_truth_path = Path(__file__).with_name("ground_truth.csv")
    if not ground_truth_path.exists():
        return ""
    return ground_truth_path.read_text(encoding="utf-8").strip()


def _coerce_query_df(query_df: Any) -> Any:
    if hasattr(query_df, "to_dict"):
        try:
            return query_df.to_dict(orient="records")
        except TypeError:
            return query_df.to_dict()
    return query_df


def validate(query_df: Any, llm_answer: str, team_name: str = "Team PaLM", team_reason: str = "") -> dict:
    ground_truth_raw = _load_ground_truth()
    normalized_ground_truth = _normalize(ground_truth_raw) if ground_truth_raw else ""
    normalized_answer = _normalize(llm_answer)
    normalized_query_df = _normalize(_coerce_query_df(query_df))

    is_valid = False
    reason = team_reason or "Ground truth missing."

    if ground_truth_raw:
        is_valid = normalized_answer == normalized_ground_truth or normalized_query_df == normalized_ground_truth
        reason = team_reason or ("Answer matches ground truth." if is_valid else "Answer does not match ground truth.")

    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "query_name": Path(__file__).parent.name,
        "is_valid": is_valid,
        "reason": reason,
        "ground_truth": ground_truth_raw,
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


def load_questions(question: str | None, questions_file: str | None, bookreview_benchmark: bool) -> List[str]:
    selected_inputs = [bool(question), bool(questions_file), bookreview_benchmark]
    if sum(selected_inputs) != 1:
        raise SystemExit(
            "Exactly one of --question, --questions-file, or --bookreview-benchmark must be provided."
        )

    if question:
        return [question]

    if bookreview_benchmark:
        return list(BOOKREVIEW_BENCHMARK_QUESTIONS)

    file_path = Path(questions_file or "")
    if not file_path.exists():
        raise SystemExit(f"Questions file not found: {file_path}")

    raw_text = file_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise SystemExit(f"Questions file is empty: {file_path}")

    if file_path.suffix.lower() == ".json":
        payload = json.loads(raw_text)
        if isinstance(payload, list) and all(isinstance(item, str) for item in payload):
            return payload
        raise SystemExit("JSON questions file must contain a list of question strings.")

    questions = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not questions:
        raise SystemExit(f"Questions file is empty: {file_path}")
    return questions


def run_single_question(
    question: str,
    db_configs: Dict[str, dict],
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    agent = OracleForgeAgent(db_configs=db_configs)
    result = agent.answer(
        {
            "question": question,
            "available_databases": list(db_configs.keys()),
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
    return result, trace_events


def main() -> None:

    parser = argparse.ArgumentParser(
        description="Run one or more natural language queries against the BookReview database."
    )
    parser.add_argument("--question", help="Natural language question to answer.")
    parser.add_argument(
        "--questions-file",
        default=None,
        help="Path to a text or JSON file containing multiple questions.",
    )
    parser.add_argument(
        "--bookreview-benchmark",
        action="store_true",
        help="Run the three built-in BookReview benchmark queries.",
    )
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
    questions = load_questions(args.question, args.questions_file, args.bookreview_benchmark)
    dataset_dir = Path(args.eval_dir)
    run_summaries = []

    for question in questions:
        result, trace_events = run_single_question(question, db_configs)
        exported_query_dir = export_eval_bundle(
            dataset_dir=dataset_dir,
            question=question,
            result=result,
            db_configs=db_configs,
            trace_events=trace_events,
        )
        run_summaries.append(
            {
                "question": question,
                "result": result,
                "exported_query_dir": str(exported_query_dir),
            }
        )
        print(json.dumps(result, indent=2, default=str))
        print(f"Exported DAB-style eval bundle to {exported_query_dir}")

    if args.output:
        output_payload: Dict[str, object]
        if len(run_summaries) == 1:
            output_payload = run_summaries[0]["result"]  # type: ignore[assignment]
        else:
            output_payload = {
                "dataset": "bookreview",
                "queries_run": len(run_summaries),
                "runs": run_summaries,
            }
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json.dumps(output_payload, indent=2, default=str))
        print(f"Wrote result to {args.output}")


if __name__ == "__main__":
    main()
