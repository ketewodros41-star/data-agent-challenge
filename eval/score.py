"""
Score a benchmark results file and print the summary.

Usage:
    python -m eval.score --results eval/baseline.json
"""

import argparse
import json
from pathlib import Path


def score(results_path: str) -> None:
    path = Path(results_path)
    if not path.exists():
        print(f"[score] File not found: {results_path}")
        return

    with open(path) as f:
        data = json.load(f)

    # Support both flat list and {score, results} format
    results = data.get("results", data) if isinstance(data, dict) else data

    total = len(results)
    correct = sum(1 for r in results if r.get("correct", False))
    correction_applied = sum(1 for r in results if r.get("correction_applied", False))
    avg_confidence = sum(r.get("confidence", 0.0) for r in results) / max(total, 1)

    print(f"=== Score Report: {results_path} ===")
    print(f"  Total questions : {total}")
    print(f"  Correct (Pass@1): {correct}  ({correct/max(total,1):.1%})")
    print(f"  Corrections used: {correction_applied}")
    print(f"  Avg confidence  : {avg_confidence:.3f}")

    # Correction effectiveness
    with_correction = [r for r in results if r.get("correction_applied")]
    without_correction = [r for r in results if not r.get("correction_applied")]
    if with_correction:
        acc_with = sum(r.get("correct", False) for r in with_correction) / len(with_correction)
        print(f"  Accuracy w/ correction  : {acc_with:.1%} ({len(with_correction)} questions)")
    if without_correction:
        acc_without = sum(r.get("correct", False) for r in without_correction) / len(without_correction)
        print(f"  Accuracy w/o correction : {acc_without:.1%} ({len(without_correction)} questions)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score benchmark results")
    parser.add_argument("--results", required=True, help="Path to results JSON file")
    args = parser.parse_args()
    score(args.results)


if __name__ == "__main__":
    main()
