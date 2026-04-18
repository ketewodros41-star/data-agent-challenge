"""
Build a baseline.json from existing results by running each dataset's validate.py.

Usage:
    python -m eval.build_baseline --datasets googlelocal crmarenapro
    python -m eval.build_baseline --datasets googlelocal crmarenapro --output eval/baseline.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

DAB_ROOT = Path("/home/estifanos/DataAgentBench")
RESULTS_ROOT = Path(__file__).resolve().parent.parent / "results"


def load_validate(dataset: str, query_dir: str):
    val_path = DAB_ROOT / f"query_{dataset}" / query_dir / "validate.py"
    if not val_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("validate", val_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.validate


def build(datasets: list[str], output: str) -> None:
    records = []

    for dataset in datasets:
        run_dir = RESULTS_ROOT / dataset
        dab_dir = DAB_ROOT / f"query_{dataset}"

        if not run_dir.exists():
            print(f"  [skip] No results for {dataset}")
            continue

        run_files = sorted(run_dir.glob("run_*.json"))
        def _query_num(d: Path) -> int:
            suffix = d.name.replace("query", "")
            return int(suffix) if suffix.isdigit() else 9999

        query_dirs = sorted(
            [d for d in dab_dir.iterdir() if d.is_dir() and d.name.startswith("query")],
            key=_query_num
        ) if dab_dir.exists() else []

        for run_file, query_dir in zip(run_files, query_dirs):
            data = json.loads(run_file.read_text())
            answer = str(data.get("answer", ""))
            question = data.get("_meta", {}).get("question", "")

            validate_fn = load_validate(dataset, query_dir.name)
            if validate_fn:
                ok, reason = validate_fn(answer)
            else:
                ok, reason = False, "no validate.py found"

            records.append({
                "dataset": dataset,
                "query": query_dir.name,
                "run_file": run_file.name,
                "question": question[:100],
                "answer": answer[:200],
                "correct": ok,
                "validation_reason": reason,
                "confidence": data.get("confidence", 0.0),
                "correction_applied": data.get("correction_applied", False),
                "iterations": data.get("iterations", 0),
                "query_trace": data.get("query_trace", []),
            })

            mark = "✅ PASS" if ok else "❌ FAIL"
            print(f"  {dataset}/{query_dir.name} ({run_file.name}): {mark} — {reason[:70]}")

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2))
    print(f"\nBaseline written → {out_path}  ({len(records)} queries)")

    correct = sum(1 for r in records if r["correct"])
    print(f"Quick score: {correct}/{len(records)} = {correct/max(len(records),1):.1%} Pass@1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="+", default=["googlelocal", "crmarenapro"])
    parser.add_argument("--output", default="eval/baseline.json")
    args = parser.parse_args()
    build(args.datasets, args.output)


if __name__ == "__main__":
    main()
