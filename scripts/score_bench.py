#!/usr/bin/env python3
"""Score Oracle Forge runs using each query's DAB validate.py.

For each `runs/<dataset>/<query>/logs/data_agent/<root_name>/final_agent.json`,
imports the sibling `validate.py` (DAB convention) and calls
`validate(final_result)` — which returns `(is_valid: bool, reason: str)`.

Outputs (DAB-aligned):
  - `runs/<dataset>/<query>/logs/data_agent/<root_name>/score.json` per run.
  - Prints per-run pass/fail tables and overall Pass@1 aggregates.
  - `runs/submission.json` — single leaderboard-style flat array of
    {dataset, query, run, answer} entries, across all scored runs. Matches
    `DataAgentBench/leaderboard_submissions/*.json`.

Usage:
    # Score every run_* present (default)
    python scripts/score_bench.py

    # Specific runs (produces one submission.json covering all listed)
    python scripts/score_bench.py --root_name run_0 run_1 run_2 run_3 run_4

    # Limit to a dataset
    python scripts/score_bench.py --dataset agnews --root_name run_0
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = ROOT_DIR / "runs"


def _load_validator(validate_py: Path):
    spec = importlib.util.spec_from_file_location(
        f"validate_{validate_py.parent.parent.name}_{validate_py.parent.name}",
        str(validate_py),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.validate


def _read_ground_truth(query_dir: Path) -> str:
    gt_path = query_dir / "ground_truth.csv"
    if not gt_path.exists():
        return ""
    return "\n".join(
        line.strip() for line in gt_path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def _query_number(query_name: str) -> str:
    m = re.match(r"query(\d+)$", query_name)
    return m.group(1) if m else query_name


def _run_number(root_name: str) -> str:
    m = re.match(r"run_?(\d+)$", root_name)
    return m.group(1) if m else root_name


def _score_query(query_dir: Path, root_name: str) -> Dict[str, Any] | None:
    log_dir = query_dir / "logs" / "data_agent" / root_name
    final_path = log_dir / "final_agent.json"
    if not final_path.exists():
        return None

    payload = json.loads(final_path.read_text(encoding="utf-8"))
    llm_answer = payload.get("final_result", "") or ""
    terminate_reason = payload.get("terminate_reason")
    ground_truth = _read_ground_truth(query_dir)
    validate_py = query_dir / "validate.py"

    if not validate_py.exists():
        is_valid, reason = False, f"validate.py missing: {validate_py}"
    elif llm_answer.strip() == "":
        is_valid, reason = False, f"empty answer ({terminate_reason})"
    else:
        try:
            validate_fn = _load_validator(validate_py)
            is_valid, reason = validate_fn(llm_answer)
        except Exception as exc:
            is_valid, reason = False, f"validate.py raised {type(exc).__name__}: {exc}"

    score_record = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "dataset": query_dir.parent.name,
        "query": query_dir.name,
        "root_name": root_name,
        "is_valid": bool(is_valid),
        "reason": reason,
        "llm_answer": llm_answer.strip(),
        "ground_truth": ground_truth,
        "terminate_reason": terminate_reason,
        "duration": payload.get("duration"),
        "iterations": payload.get("llm_call_count"),
    }

    score_path = log_dir / "score.json"
    score_path.write_text(json.dumps(score_record, indent=2, default=str), encoding="utf-8")
    score_record["_score_path"] = str(score_path)
    return score_record


def _score_dataset(dataset_dir: Path, root_name: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for qdir in sorted(dataset_dir.iterdir()):
        if not qdir.is_dir() or not qdir.name.startswith("query"):
            continue
        row = _score_query(qdir, root_name)
        if row is not None:
            rows.append(row)
    return rows


def _clean_legacy_dataset_scores(dataset_dir: Path, root_name: str) -> None:
    """Remove the old `scores_<root>.json` at the dataset level (superseded by per-run score.json)."""
    legacy = dataset_dir / f"scores_{root_name}.json"
    if legacy.exists():
        legacy.unlink()


def _discover_root_names(dataset_dirs: List[Path]) -> List[str]:
    """Scan every `logs/data_agent/run_*` directory across datasets and queries."""
    seen: set[str] = set()
    for ds in dataset_dirs:
        for qdir in ds.iterdir():
            if not qdir.is_dir() or not qdir.name.startswith("query"):
                continue
            da_dir = qdir / "logs" / "data_agent"
            if not da_dir.is_dir():
                continue
            for run_dir in da_dir.iterdir():
                if run_dir.is_dir() and run_dir.name.startswith("run"):
                    seen.add(run_dir.name)
    return sorted(seen, key=lambda n: (len(n), n))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root_name",
        nargs="+",
        help="One or more run directory names (e.g. run_0 run_1). Default: all run_* present.",
    )
    parser.add_argument("--dataset", help="Limit to this dataset.")
    parser.add_argument(
        "--no_submission",
        action="store_true",
        help="Skip writing runs/submission.json.",
    )
    parser.add_argument(
        "--submission_path",
        default=None,
        help="Override submission output path (default: runs/submission.json).",
    )
    args = parser.parse_args()

    if not RUNS_ROOT.is_dir():
        sys.exit(f"runs/ not found: {RUNS_ROOT}")

    dataset_dirs = sorted(p for p in RUNS_ROOT.iterdir() if p.is_dir())
    if args.dataset:
        dataset_dirs = [p for p in dataset_dirs if p.name == args.dataset]
        if not dataset_dirs:
            sys.exit(f"Dataset not found under runs/: {args.dataset}")

    root_names = args.root_name or _discover_root_names(dataset_dirs)
    if not root_names:
        sys.exit("No runs found under runs/<dataset>/<query>/logs/data_agent/.")

    submission: List[Dict[str, Any]] = []
    overall_total = overall_pass = 0
    for root_name in root_names:
        run_total = run_pass = 0
        print(f"\n########## {root_name} ##########")
        run_id = _run_number(root_name)
        for ds_dir in dataset_dirs:
            rows = _score_dataset(ds_dir, root_name)
            if not rows:
                continue
            _clean_legacy_dataset_scores(ds_dir, root_name)

            passed = sum(1 for r in rows if r["is_valid"])
            total = len(rows)
            run_pass += passed
            run_total += total

            print(f"\n=== {ds_dir.name} ({passed}/{total}) ===")
            for r in rows:
                mark = "✓" if r["is_valid"] else "✗"
                print(f"  {mark} {r['query']:12s}  {r['llm_answer'][:60]!r}")
                if not r["is_valid"]:
                    print(f"      reason: {r['reason'][:120]}")
                submission.append({
                    "dataset": ds_dir.name,
                    "query": _query_number(r["query"]),
                    "run": run_id,
                    "answer": r["llm_answer"],
                })

        if run_total:
            print(f"\n{root_name}: {run_pass}/{run_total} (pass@1 = {run_pass/run_total:.3f})")
        else:
            print(f"{root_name}: no results found")
        overall_pass += run_pass
        overall_total += run_total

    if not args.no_submission and submission:
        sub_path = Path(args.submission_path) if args.submission_path else RUNS_ROOT / "submission.json"
        sub_path.write_text(json.dumps(submission, indent=2, default=str), encoding="utf-8")
        print(f"\nSubmission: {sub_path} ({len(submission)} rows across {len(root_names)} run(s))")

    if overall_total:
        print(f"\nOVERALL: {overall_pass}/{overall_total} (pass@1 = {overall_pass/overall_total:.3f})")
    else:
        print("No runs scored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
