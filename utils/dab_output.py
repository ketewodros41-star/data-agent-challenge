from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def next_query_dir(dataset_dir: Path) -> Path:
    """
    Return the next numbered query directory under a dataset output folder.

    Example:
        results/query_yelp/query1
        results/query_yelp/query2
        ...
    """
    existing_numbers = []

    if dataset_dir.exists():
        for child in dataset_dir.iterdir():
            if not child.is_dir() or not child.name.startswith("query"):
                continue
            suffix = child.name.removeprefix("query").removeprefix("_")
            try:
                existing_numbers.append(int(suffix))
            except ValueError:
                continue

    next_num = max(existing_numbers, default=0) + 1
    return dataset_dir / f"query{next_num}"


def ensure_query_artifacts(
    target_query_dir: Path,
    source_query_file: Path,
) -> None:
    """
    Create a DAB-style query folder and copy the source query + optional
    validation artifacts into it.

    Writes:
      - query.json
      - validate.py         (if present next to source query)
      - ground_truth.csv    (if present next to source query)
    """
    target_query_dir.mkdir(parents=True, exist_ok=True)

    raw = source_query_file.read_text(encoding="utf-8")
    (target_query_dir / "query.json").write_text(raw, encoding="utf-8")

    source_dir = source_query_file.parent
    for name in ("validate.py", "ground_truth.csv"):
        src = source_dir / name
        if src.exists():
            shutil.copy2(src, target_query_dir / name)


def ensure_run_dir(target_query_dir: Path, run_name: str) -> Path:
    """
    Create and return:
      <target_query_dir>/logs/data_agent/<run_name>
    """
    run_dir = target_query_dir / "logs" / "data_agent" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "exec_tool_work_dir").mkdir(exist_ok=True)
    return run_dir


def _safe_jsonl_write(path: Path, records: Optional[Iterable[Dict[str, Any]]]) -> None:
    """
    Write JSONL records. If records is None or empty, create an empty file.
    """
    with path.open("w", encoding="utf-8") as f:
        if not records:
            return
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")


def write_dab_style_run(
    run_dir: Path,
    result: Dict[str, Any],
    *,
    llm_calls: Optional[Iterable[Dict[str, Any]]] = None,
    tool_calls: Optional[Iterable[Dict[str, Any]]] = None,
) -> None:
    """
    Write one run in a DAB-like layout.

    Produces:
      - final_agent.json
      - llm_calls.jsonl
      - tool_calls.jsonl
      - exec_tool_work_dir/
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "exec_tool_work_dir").mkdir(exist_ok=True)

    final_agent_payload = {
        "final_result": result.get("answer"),
        "confidence": result.get("confidence"),
        "terminate_reason": result.get("terminate_reason"),
        "correction_applied": result.get("correction_applied", False),
        "execution_time": result.get("_meta", {}).get("elapsed_seconds", 0.0),
        # keep raw query trace available for harness/debugging
        "tool_calls": result.get("query_trace", []),
        "raw_result": result,
    }

    (run_dir / "final_agent.json").write_text(
        json.dumps(final_agent_payload, indent=2, default=str),
        encoding="utf-8",
    )

    _safe_jsonl_write(run_dir / "llm_calls.jsonl", llm_calls)
    _safe_jsonl_write(run_dir / "tool_calls.jsonl", tool_calls)


def write_summary(
    target_query_dir: Path,
    root_name: str,
    dataset: str,
    db_ids: list[str],
    question: str,
    iterations: int,
    all_results: list[dict],
    *,
    output_root: Path,
) -> Path:
    """
    Write a DAB-friendly summary JSON at:
      <target_query_dir>/<root_name>_summary.json
    """
    summary_path = target_query_dir / f"{root_name}_summary.json"

    summary = {
        "dataset": dataset,
        "databases": db_ids,
        "question": question,
        "query_file": str((target_query_dir / "query.json").relative_to(output_root)),
        "iterations": iterations,
        "results": all_results,
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary_path