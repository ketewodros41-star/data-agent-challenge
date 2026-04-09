#!/usr/bin/env python3
"""
KB Injection Test Runner — Oracle Forge Data Agent
====================================================
Injects each KB document into a fresh LLM context (no other context)
and asks the question embedded at the bottom of each document.
PASS = LLM answers using only the document, hitting all required keywords.
FAIL = LLM says "NOT IN DOCUMENT", answers from pretraining, or misses keywords.

Usage:
  python run_all_tests.py                     # run all 4 documents
  python run_all_tests.py --doc memory_system
  python run_all_tests.py --doc tool_scoping
  python run_all_tests.py --doc openai_context
  python run_all_tests.py --doc execution_loop

Requirements:
  pip install openai python-dotenv
  OPENROUTER_API_KEY in .env (project root)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ── paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "kb" / "architecture"
RESULTS_FILE = Path(__file__).parent / "results.md"

load_dotenv(REPO_ROOT / ".env")

# ── model ──────────────────────────────────────────────────────────────────
MODEL = "anthropic/claude-haiku-4-5"   # cheap, fast — enough for retrieval tests

# ── test definitions ───────────────────────────────────────────────────────
# Each entry: doc_key → { file, question, required_keywords }
# required_keywords: ALL must appear in the answer (case-insensitive) for PASS.
TESTS = {
    "memory_system": {
        "file": KB_DIR / "memory_system.md",
        "doc_label": "memory_system.md",
        "cases": [
            {
                "id": "MS-1",
                "question": (
                    "What is MEMORY.md for, what is its word limit, "
                    "and what triggers a topic file to be loaded from memory?"
                ),
                "required_keywords": ["index", "200", "on-demand", "topic"],
            },
            {
                "id": "MS-2",
                "question": "What is the autoDream pattern and when does it run?",
                "required_keywords": ["session end", "corrections", "consolidat"],
            },
            {
                "id": "MS-3",
                "question": "Where are Layer 3 session transcripts stored and how are they accessed?",
                "required_keywords": ["jsonl", "search", "never load"],
            },
            {
                "id": "MS-4",
                "question": "What is the maximum word count for a topic file?",
                "required_keywords": ["400"],
            },
        ],
    },
    "tool_scoping": {
        "file": KB_DIR / "tool_scoping.md",
        "doc_label": "tool_scoping.md",
        "cases": [
            {
                "id": "TS-1",
                "question": (
                    "A DAB question asks: which customers had support complaints this week? "
                    "Which database tool do you use, what query language, "
                    "and why can't you use query_postgresql for this?"
                ),
                "required_keywords": [
                    "query_mongodb",
                    "aggregation",
                    "empty",
                ],
            },
            {
                "id": "TS-2",
                "question": (
                    "What happens if you send a SQL query to query_mongodb?"
                ),
                "required_keywords": ["empty", "silent"],
            },
            {
                "id": "TS-3",
                "question": (
                    "A question requires data from both PostgreSQL and MongoDB. "
                    "What is the correct procedure?"
                ),
                "required_keywords": [
                    "separately",
                    "sandbox",
                ],
            },
            {
                "id": "TS-4",
                "question": "What tool is used for analytical SQL queries against the data warehouse?",
                "required_keywords": ["query_duckdb"],
            },
        ],
    },
    "openai_context": {
        "file": KB_DIR / "context_layer.md",
        "doc_label": "context_layer.md",
        "cases": [
            {
                "id": "OC-1",
                "question": "What is Codex Enrichment and which of the six layers is it?",
                "required_keywords": ["layer 3", "pipeline", "join key"],
            },
            {
                "id": "OC-2",
                "question": "What does Layer 4 contain and what does it map to in this agent's KB?",
                "required_keywords": [
                    "institutional",
                    "business_terms",
                ],
            },
            {
                "id": "OC-3",
                "question": (
                    "According to the document's key finding from OpenAI, "
                    "what should the agent do before running analysis, "
                    "and what happens the more time it spends in that phase?"
                ),
                "required_keywords": ["discovery", "validate", "before"],
            },
            {
                "id": "OC-4",
                "question": "What is Layer 6 used for and when is it triggered?",
                "required_keywords": ["live", "stale", "real-time"],
            },
        ],
    },
    "execution_loop": {
        "file": KB_DIR / "self_correcting_execution.md",
        "doc_label": "self_correcting_execution.md",
        "cases": [
            {
                "id": "EL-1",
                "question": (
                    "The sandbox returns validation_status: failed, error: ID format mismatch. "
                    "What are the exact next steps and what happens after 3 retries all fail?"
                ),
                "required_keywords": [
                    "strip",
                    "convert",
                    "retry",
                    "honest",
                    "never",
                ],
            },
            {
                "id": "EL-2",
                "question": "What are the 6 steps of the execution loop in order?",
                "required_keywords": [
                    "plan",
                    "execute",
                    "check",
                    "diagnose",
                    "deliver",
                    "log",
                ],
            },
            {
                "id": "EL-3",
                "question": (
                    "A tool call returns an empty result set with no error. "
                    "What does the agent do next?"
                ),
                "required_keywords": ["verify", "table", "schemas", "retry"],
            },
            {
                "id": "EL-4",
                "question": "What confidence levels does the agent assign and when?",
                "required_keywords": ["high", "medium", "low"],
            },
        ],
    },
}

# ── LLM call ───────────────────────────────────────────────────────────────

def call_llm(document_text: str, question: str) -> str:
    """Inject document as system context; ask question with no other context."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY not set. Copy .env.example → .env and add your key."
        )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    system_prompt = (
        "You are answering questions using ONLY the document provided below. "
        "Do not use any other knowledge. "
        "If the answer is not in the document, say exactly: NOT IN DOCUMENT.\n\n"
        "=== DOCUMENT START ===\n"
        f"{document_text}\n"
        "=== DOCUMENT END ==="
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=512,
    )
    return response.choices[0].message.content.strip()


# ── verdict ────────────────────────────────────────────────────────────────

def evaluate(answer: str, required_keywords: list[str]) -> tuple[bool, list[str]]:
    """Return (passed, missing_keywords)."""
    answer_lower = answer.lower()
    if "not in document" in answer_lower:
        return False, required_keywords
    missing = [kw for kw in required_keywords if kw.lower() not in answer_lower]
    return len(missing) == 0, missing


# ── runner ─────────────────────────────────────────────────────────────────

def run_tests(doc_keys: list[str]) -> list[dict]:
    results = []
    for key in doc_keys:
        spec = TESTS[key]
        doc_path: Path = spec["file"]

        if not doc_path.exists():
            print(f"  [SKIP] {doc_path.name} — file not found")
            continue

        document_text = doc_path.read_text(encoding="utf-8")

        for case in spec["cases"]:
            print(f"  Running {case['id']} ({spec['doc_label']}) ...", end=" ", flush=True)
            try:
                answer = call_llm(document_text, case["question"])
                passed, missing = evaluate(answer, case["required_keywords"])
            except Exception as exc:
                answer = f"ERROR: {exc}"
                passed = False
                missing = case["required_keywords"]

            status = "PASS" if passed else "FAIL"
            print(status)

            results.append(
                {
                    "id": case["id"],
                    "doc": spec["doc_label"],
                    "question": case["question"],
                    "required_keywords": case["required_keywords"],
                    "answer": answer,
                    "missing_keywords": missing,
                    "passed": passed,
                }
            )
    return results


# ── results writer ─────────────────────────────────────────────────────────

def write_results(results: list[dict]) -> None:
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Injection Test Results",
        "",
        f"**Last run:** {timestamp}  ",
        f"**Status:** {passed}/{total} tests passing",
        "",
        "---",
        "",
    ]

    for r in results:
        verdict = "✅ PASS" if r["passed"] else "❌ FAIL"
        lines += [
            f"## {r['id']} — {r['doc']}",
            "",
            f"**Verdict:** {verdict}",
            "",
            f"**Question:**",
            f"> {r['question']}",
            "",
            f"**Required keywords:** {', '.join(f'`{k}`' for k in r['required_keywords'])}",
        ]
        if not r["passed"] and r["missing_keywords"]:
            lines.append(
                f"**Missing keywords:** {', '.join(f'`{k}`' for k in r['missing_keywords'])}"
            )
        lines += [
            "",
            "**Answer:**",
            "",
            r["answer"],
            "",
            "---",
            "",
        ]

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nResults written to {RESULTS_FILE.relative_to(REPO_ROOT)}")


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="KB injection test runner")
    parser.add_argument(
        "--doc",
        choices=list(TESTS.keys()),
        default=None,
        help="Run tests for one document only (omit to run all)",
    )
    args = parser.parse_args()

    doc_keys = [args.doc] if args.doc else list(TESTS.keys())

    print(f"Running injection tests for: {', '.join(doc_keys)}\n")
    results = run_tests(doc_keys)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    write_results(results)

    print(f"\n{'='*50}")
    print(f"  {passed}/{total} tests passed")
    print(f"{'='*50}")

    if passed < total:
        failed = [r["id"] for r in results if not r["passed"]]
        print(f"\nFAILED: {', '.join(failed)}")
        print("Rewrite the document. Do not commit until all tests pass.")
        sys.exit(1)
    else:
        print("\nAll tests passed. Safe to commit.")


if __name__ == "__main__":
    main()
