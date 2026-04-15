"""
Evaluation harness entry point.

Usage:
    python -m eval.run_benchmark --agent agent.oracle_forge_agent --trials 1 --output eval/baseline.json
    python -m eval.run_benchmark --agent agent.oracle_forge_agent --trials 5 --output results/final.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).parent.parent
_SCORE_LOG = _REPO_ROOT / "eval" / "score_log.jsonl"

# Sample DAB questions for development/testing
# Replace with actual DAB benchmark loader when datasets are available
_SAMPLE_QUESTIONS = [
    {
        "question": "What is the average star rating for businesses in Las Vegas?",
        "available_databases": ["postgres"],
        "schema_info": {},
        "expected_answer": None,
    },
    {
        "question": "How many reviews mention the word 'excellent'?",
        "available_databases": ["mongodb"],
        "schema_info": {},
        "expected_answer": None,
    },
    {
        "question": "Which business has the most reviews across all databases?",
        "available_databases": ["postgres", "mongodb"],
        "schema_info": {},
        "expected_answer": None,
    },
]


def load_agent(agent_module_path: str):
    """Dynamically import and instantiate the agent class."""
    module_path, _, class_name = agent_module_path.rpartition(".")
    if not module_path:
        module_path = agent_module_path
        class_name = "OracleForgeAgent"
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    if cls is None:
        # Try default class name
        cls = getattr(module, "OracleForgeAgent")
    return cls()


def run_benchmark(
    agent,
    questions: List[Dict[str, Any]],
    trials: int = 1,
) -> List[Dict[str, Any]]:
    results = []

    for q in questions:
        trial_answers = []
        for t in range(trials):
            start = time.time()
            try:
                output = agent.answer(q)
                elapsed = time.time() - start
                trial_answers.append({
                    "trial": t + 1,
                    "answer": output.get("answer"),
                    "confidence": output.get("confidence", 0.0),
                    "query_trace": output.get("query_trace", []),
                    "elapsed_s": round(elapsed, 3),
                    "error": None,
                })
            except Exception as exc:
                elapsed = time.time() - start
                trial_answers.append({
                    "trial": t + 1,
                    "answer": None,
                    "confidence": 0.0,
                    "query_trace": [],
                    "elapsed_s": round(elapsed, 3),
                    "error": str(exc),
                })

        # Use first trial as primary answer (Pass@1)
        primary = trial_answers[0] if trial_answers else {}
        results.append({
            "question": q["question"],
            "available_databases": q.get("available_databases", []),
            "expected_answer": q.get("expected_answer"),
            "answer": primary.get("answer"),
            "confidence": primary.get("confidence", 0.0),
            "correct": _check_correct(primary.get("answer"), q.get("expected_answer")),
            "correction_applied": any(
                step.get("correction_applied")
                for step in primary.get("query_trace", [])
            ),
            "trials": trial_answers,
            "timestamp": datetime.utcnow().isoformat(),
        })

    return results


def _check_correct(answer: Any, expected: Any) -> bool:
    if expected is None:
        return False  # Cannot evaluate without expected answer
    if isinstance(expected, float) and isinstance(answer, (int, float)):
        return abs(float(answer) - expected) / max(abs(expected), 1e-9) <= 0.05
    if isinstance(expected, list) and isinstance(answer, list):
        return set(str(e) for e in expected) == set(str(a) for a in answer)
    return str(answer).strip().lower() == str(expected).strip().lower()


def compute_pass_at_1(results: List[Dict]) -> Dict[str, Any]:
    total = len(results)
    correct = sum(1 for r in results if r.get("correct", False))
    return {
        "pass_at_1": correct / total if total > 0 else 0.0,
        "total": total,
        "correct": correct,
        "timestamp": datetime.utcnow().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle Forge benchmark runner")
    parser.add_argument(
        "--agent",
        default="agent.oracle_forge_agent",
        help="Dotted module path to agent (default: agent.oracle_forge_agent)",
    )
    parser.add_argument("--trials", type=int, default=1, help="Number of trials per question")
    parser.add_argument("--output", default="eval/baseline.json", help="Output results file")
    parser.add_argument(
        "--questions",
        default=None,
        help="Path to JSON file with questions (defaults to built-in sample set)",
    )
    args = parser.parse_args()

    # Load questions
    if args.questions:
        with open(args.questions) as f:
            questions = json.load(f)
    else:
        print("[benchmark] No --questions file provided. Using built-in sample set.")
        questions = _SAMPLE_QUESTIONS

    # Load agent
    print(f"[benchmark] Loading agent: {args.agent}")
    agent = load_agent(args.agent)

    # Run
    print(f"[benchmark] Running {len(questions)} questions × {args.trials} trials")
    results = run_benchmark(agent, questions, trials=args.trials)

    # Score
    score = compute_pass_at_1(results)
    print(f"[benchmark] Pass@1 = {score['pass_at_1']:.3f} ({score['correct']}/{score['total']})")

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"score": score, "results": results}, f, indent=2, default=str)
    print(f"[benchmark] Results written to {output_path}")


if __name__ == "__main__":
    main()
