"""
DAB Evaluation Harness

Runs the complete Oracle Forge evaluation:
1. Reads run logs produced by run_agent.py
2. Calls DAB's validate.py for each query
3. Computes pass@1
4. Appends to score_log.json
5. Generates trace log with tool call links

Usage:
  python eval/run_evaluation.py --dataset bookreview --run run_0 --note "baseline"
  python eval/run_evaluation.py --all --note "after KB v2"
  python eval/run_evaluation.py --progress
"""
import json
import importlib.util
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

DAB_ROOT  = Path(".")
EVAL_DIR  = Path("eval")
SCORE_LOG = EVAL_DIR / "score_log.json"
TRACE_LOG = EVAL_DIR / "trace_log.jsonl"

ALL_DATASETS = [
    "bookreview", "agnews", "crmarenapro", "googlelocal",
    "yelp", "stockmarket", "stockindex", "github_repos",
    "music_brainz_20k", "pancancer_atlas", "deps_dev_v1", "PATENTS"
]


def validate_one(dataset: str, qid: int, run: str = "run_0") -> dict:
    """Validate one run against DAB ground truth. Returns per-query record."""
    query_dir = DAB_ROOT / "results" / f"query_{dataset}" / f"query{qid}"
    run_dir   = query_dir / "logs" / "data_agent" / run

    # Read ground truth
    gt_path = query_dir / "ground_truth.csv"
    gt      = gt_path.read_text().strip() if gt_path.exists() else ""

    # Check run exists
    final_path = run_dir / "final_agent.json"
    if not final_path.exists():
        return make_record(dataset, qid, run, "", gt, False, "run_not_found", [], 0)

    with open(final_path) as f:
        agent_json = json.load(f)

    answer      = agent_json.get("final_result", "")
    term_reason = agent_json.get("terminate_reason", "")
    n_iters     = agent_json.get("num_iterations", 0)

    # Extract tool calls from trajectory for traceability
    tool_calls = []
    for step in agent_json.get("trajectory", []):
        if isinstance(step, dict) and step.get("role") == "assistant":
            for tc in step.get("tool_calls", []):
                tool_calls.append({
                    "id":        tc.get("id", ""),
                    "tool":      tc.get("name", tc.get("function", {}).get("name", "")),
                    "arguments": tc.get("arguments", {})
                })

    # Automatic fail
    if term_reason in ("no_tool_call", "max_iterations") or not answer:
        return make_record(dataset, qid, run, answer, gt, False, term_reason, tool_calls, n_iters)

    # DAB's per-query validate.py
    validate_path = query_dir / "validate.py"
    if not validate_path.exists():
        return make_record(dataset, qid, run, answer, gt, False, "validate_missing", tool_calls, n_iters)

    spec = importlib.util.spec_from_file_location("validate", validate_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Handle different validate function signatures
    try:
        # Try with just llm_answer
        result = mod.validate(llm_answer=answer)
    except TypeError as e:
        try:
            # Try with llm_answer and empty query_df
            result = mod.validate(llm_answer=answer, query_df=None)
        except TypeError:
            try:
                # Try with llm_answer and empty dict for query_df
                result = mod.validate(llm_answer=answer, query_df={})
            except TypeError:
                # Last resort: try positional argument
                result = mod.validate(answer)
    passed   = result[0] if isinstance(result, tuple) else bool(result)
    reason   = result[1] if isinstance(result, tuple) and len(result) > 1 else ""

    return make_record(dataset, qid, run, answer, gt, passed, reason, tool_calls, n_iters)


def make_record(dataset, qid, run, answer, gt, passed, reason, tool_calls, n_iters):
    """Build a structured per-query record satisfying all 6 rubric criteria."""
    return {
        "query_id":        f"{dataset}/query{qid}",   # Criterion 6: identifier
        "dataset":         dataset,
        "query_num":       qid,
        "run":             run,
        "passed":          passed,                     # Criterion 6: pass/fail
        "tool_call_trace": tool_calls,                 # Criterion 6: trace
        "tool_call_count": len(tool_calls),
        "agent_answer":    str(answer),
        "ground_truth":    str(gt),
        "failure_reason":  reason if not passed else "",
        "iterations_used": n_iters,
        "timestamp":       datetime.now(timezone.utc).isoformat()
    }


def score_dataset(dataset: str, run: str = "run_0", note: str = "") -> dict:
    """Score all queries for one dataset. Returns summary + appends to logs."""
    dataset_dir = DAB_ROOT / "results" / f"query_{dataset}"
    if not dataset_dir.exists():
        print(f"  SKIP: {dataset} not found")
        return None

    query_dirs = sorted(
        [d for d in dataset_dir.iterdir() if d.is_dir() and d.name.startswith("query")],
        key=lambda p: int(p.name.replace("query",""))
    )

    records = []
    print(f"\n{'='*55}")
    print(f"  {dataset}  |  {run}")
    print(f"{'='*55}")

    for qdir in query_dirs:
        qid    = int(qdir.name.replace("query",""))
        record = validate_one(dataset, qid, run)
        records.append(record)

        icon   = "Ã¯Â¿Â½" if record["passed"] else "Ã¯Â¿Â½"
        tools  = record["tool_call_count"]
        reason = record["failure_reason"][:35] if not record["passed"] else "OK"
        print(f"  {icon} query{qid:2d} | tools:{tools:2d} | {reason}")

    passed   = sum(1 for r in records if r["passed"])
    total    = len(records)
    pass_at_1 = round(passed / total * 100, 2) if total else 0.0

    print(f"\n  pass@1: {pass_at_1}% ({passed}/{total})")

    # Append to score_log.json
    EVAL_DIR.mkdir(exist_ok=True)
    log = []
    if SCORE_LOG.exists():
        try: log = json.loads(SCORE_LOG.read_text())
        except: pass

    entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "dataset":    dataset,
        "run":        run,
        "pass_at_1":  pass_at_1,
        "passed":     passed,
        "total":      total,
        "note":       note,
        "per_query":  records              # full detail Ã¢â¬â Criterion 3
    }
    log.append(entry)
    SCORE_LOG.write_text(json.dumps(log, indent=2))

    # Append to trace_log.jsonl
    with open(TRACE_LOG, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"  Logged to: {SCORE_LOG}")
    return entry


def show_progression(dataset=None):
    if not SCORE_LOG.exists():
        print("No score log yet.")
        return
    try:
        log = json.loads(SCORE_LOG.read_text())
        if not log:
            print("No score log entries yet.")
            return
    except:
        print("Score log is empty or corrupted.")
        return
    
    if dataset:
        log = [e for e in log if e.get("dataset") == dataset]
    print(f"\n{'='*58}")
    print(f"  Score Progression")
    print(f"{'='*58}")
    for i, e in enumerate(log):
        date  = e["timestamp"][:16].replace("T"," ")
        mark  = " Ã¢â¬Â baseline" if i==0 else (" Ã¢â¬Â latest" if i==len(log)-1 else "")
        print(f"  {date}  {e['dataset']:14}  {e['pass_at_1']:6.1f}%  {e.get('note','')[:20]}{mark}")
    if len(log) >= 2:
        delta = log[-1]["pass_at_1"] - log[0]["pass_at_1"]
        print(f"\n  Ãâ° improvement: {'+' if delta>=0 else ''}{delta:.1f}%")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset",  help="e.g. bookreview")
    p.add_argument("--run",      default="run_0")
    p.add_argument("--note",     default="")
    p.add_argument("--all",      action="store_true", help="Score all datasets")
    p.add_argument("--progress", action="store_true", help="Show score log")
    args = p.parse_args()

    if args.progress:
        show_progression(args.dataset)
        return
    if args.all:
        for ds in ALL_DATASETS:
            score_dataset(ds, args.run, args.note)
        show_progression()
        return
    if args.dataset:
        score_dataset(args.dataset, args.run, args.note)
        show_progression(args.dataset)
        return
    p.print_help()

if __name__ == "__main__":
    main()
