#!/usr/bin/env python3
"""
KB Injection Test Runner — Oracle Forge Data Agent
====================================================
Protocol (strictly followed for every test):
  1. Take the document text.
  2. Start a fresh LLM session with ONLY that document as context.
  3. Ask a question the document should answer.
  4. PASS = LLM answers using only the document, hitting all required keywords.
     FAIL = LLM says "NOT IN DOCUMENT", answers from pretraining, or misses keywords.

Usage:
  python run_all_tests.py                          # run all documents
  python run_all_tests.py --doc memory_system
  python run_all_tests.py --doc tool_scoping
  python run_all_tests.py --doc openai_context
  python run_all_tests.py --doc execution_loop
  python run_all_tests.py --doc schema
  python run_all_tests.py --doc join_keys
  python run_all_tests.py --doc domain_terms
  python run_all_tests.py --doc dataset_overview
  python run_all_tests.py --doc unstructured_fields

Requirements:
  pip install openai python-dotenv
  OPENROUTER_API_KEY in .env (project root)
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ── paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR    = REPO_ROOT / "kb" / "architecture"
DOMAIN_DIR = REPO_ROOT / "kb" / "domain"
RESULTS_FILE = Path(__file__).parent / "results.md"

load_dotenv(REPO_ROOT / ".env")

# ── model ──────────────────────────────────────────────────────────────────
MODEL = "anthropic/claude-haiku-4-5"   # cheap, fast — enough for retrieval tests

# ── test definitions ───────────────────────────────────────────────────────
# Injection test protocol: every question must be answerable from the
# document alone. required_keywords are specific strings a correct,
# document-grounded answer will contain.
TESTS = {

    # ── ARCHITECTURE DOCUMENTS ────────────────────────────────────────────

    "memory_system": {
        "file": KB_DIR / "memory_system.md",
        "doc_label": "memory_system.md",
        "cases": [
            {
                "id": "MS-1",
                # Embedded Q1 in the document
                "question": (
                    "What is MEMORY.md for, what is its word limit, "
                    "and what triggers a topic file to be loaded from memory?"
                ),
                "required_keywords": ["index", "200", "on-demand", "topic"],
            },
            {
                "id": "MS-2",
                # Embedded Q2 in the document
                "question": (
                    "What fields must every corrections log entry contain, "
                    "and which field is most often missing?"
                ),
                "required_keywords": ["query", "failure", "root cause", "fix", "outcome"],
            },
            {
                "id": "MS-3",
                # Embedded Q3 in the document
                "question": "What is the consolidation rule for the corrections log?",
                "required_keywords": ["recurring", "one-off", "noise"],
            },
            {
                "id": "MS-4",
                # Embedded Q4 in the document
                "question": (
                    "Why is Claude memory architecture alone not enough "
                    "for this data agent project?"
                ),
                "required_keywords": ["schema", "domain", "openai"],
            },
        ],
    },

    "tool_scoping": {
        "file": KB_DIR / "tool_scoping.md",
        "doc_label": "tool_scoping.md",
        "cases": [
            {
                "id": "TS-1",
                # Embedded injection question in the document
                "question": (
                    "A DAB question asks: which customers had support complaints this week? "
                    "Which database tool do you use, what query language, "
                    "and why can't you use query_postgresql for this?"
                ),
                "required_keywords": ["query_mongodb", "aggregation", "empty"],
            },
            {
                "id": "TS-2",
                # Grounded in: "SQL → query_mongodb → empty result, no error, agent unaware"
                "question": "What happens if you send a SQL query to query_mongodb?",
                "required_keywords": ["empty", "silent"],
            },
            {
                "id": "TS-3",
                # Grounded in: cross-database join procedure section
                "question": (
                    "A question requires data from both PostgreSQL and MongoDB. "
                    "What is the correct procedure?"
                ),
                "required_keywords": ["separately", "sandbox"],
            },
            {
                "id": "TS-4",
                # Grounded in: tool table — query_duckdb → Warehouse, analytics
                "question": (
                    "What tool is used for analytical SQL queries "
                    "against the data warehouse?"
                ),
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
                # Embedded injection question in the document
                "question": "What is Codex Enrichment and which of the six layers is it?",
                "required_keywords": ["layer 3", "pipeline", "join key"],
            },
            {
                "id": "OC-2",
                # Grounded in: Layer 4 section — institutional knowledge → business_terms.md
                "question": (
                    "What does Layer 4 contain and what does it map to "
                    "in this agent's KB?"
                ),
                "required_keywords": ["institutional", "business_terms"],
            },
            {
                "id": "OC-3",
                # Grounded in: "Key finding from OpenAI: discovery phase" section
                "question": (
                    "According to the document's key finding from OpenAI, "
                    "what should the agent do before running analysis, "
                    "and what happens the more time it spends in that phase?"
                ),
                "required_keywords": ["discovery", "validate", "before"],
            },
            {
                "id": "OC-4",
                # Grounded in: Layer 6 — "Live runtime queries [OPTIONAL — only if schema is stale]"
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
                # Embedded injection question in the document
                "question": (
                    "The sandbox returns validation_status: failed, error: ID format mismatch. "
                    "What are the exact next steps and what happens after 3 retries all fail?"
                ),
                "required_keywords": ["strip", "convert", "retry", "honest", "never"],
            },
            {
                "id": "EL-2",
                # Grounded in: "Execution loop for this agent" — 6 named steps
                "question": "What are the 6 steps of the execution loop in order?",
                "required_keywords": ["plan", "execute", "check", "diagnose", "deliver", "log"],
            },
            {
                "id": "EL-3",
                # Grounded in: Step 4 — "empty result" → "verify table name in schemas, retry"
                "question": (
                    "A tool call returns an empty result set with no error. "
                    "What does the agent do next?"
                ),
                "required_keywords": ["verify", "table", "schemas", "retry"],
            },
            {
                "id": "EL-4",
                # Grounded in: Step 5 DELIVER — "high (direct result), medium (inferred), low (partial)"
                "question": "What confidence levels does the agent assign and when?",
                "required_keywords": ["high", "medium", "low"],
            },
        ],
    },

    # ── DOMAIN DOCUMENTS ─────────────────────────────────────────────────

    "schema": {
        "file": DOMAIN_DIR / "schema.md",
        "doc_label": "schema.md",
        "cases": [
            {
                "id": "SC-1",
                # Grounded in: yelp section — business_id format in MongoDB, business_ref in DuckDB
                "question": (
                    "What format is business_id in the Yelp MongoDB collection, "
                    "and what format is business_ref in the Yelp DuckDB user_database?"
                ),
                "required_keywords": ["businessid_", "businessref_"],
            },
            {
                "id": "SC-2",
                # Grounded in: googlelocal — "state: str — Operating status: OPEN, CLOSED, TEMPORARILY_CLOSED — NOT a US geographic state"
                "question": (
                    "What does the `state` column in the googlelocal "
                    "business_description table represent?"
                ),
                "required_keywords": ["open", "closed", "operating"],
            },
            {
                "id": "SC-3",
                # Grounded in: crmarenapro — "CRITICAL: All ID fields may have leading # and trailing whitespace"
                "question": (
                    "What data quality issue affects all ID fields in the "
                    "crmarenapro databases, and what must you do before any join?"
                ),
                "required_keywords": ["#", "before any join"],
            },
            {
                "id": "SC-4",
                # Grounded in: stocktrade_database — "One table per ticker symbol. Table name = ticker symbol"
                "question": (
                    "How is stock price history organised in the stocktrade_database, "
                    "and how do you find which tables exist?"
                ),
                "required_keywords": ["ticker", "show tables"],
            },
        ],
    },

    "join_keys": {
        "file": DOMAIN_DIR / "join_key_glossary.md",
        "doc_label": "join_key_glossary.md",
        "cases": [
            {
                "id": "JK-1",
                # Grounded in: yelp section — businessid_N vs businessref_N, strip prefix
                "question": (
                    "How is the Yelp business identifier formatted in MongoDB "
                    "versus DuckDB, and what is the correct join procedure?"
                ),
                "required_keywords": ["businessid_", "businessref_", "strip", "integer"],
            },
            {
                "id": "JK-2",
                # Grounded in: crmarenapro — "leading # ... TRIM(REPLACE(field, '#', ''))"
                "question": (
                    "What transformation must be applied to every ID field "
                    "in crmarenapro before joining, and what SQL expression does this?"
                ),
                "required_keywords": ["#", "trim", "replace"],
            },
            {
                "id": "JK-3",
                # Grounded in: stockmarket — "Each stock's price history is its own DuckDB table. Must enumerate tables first."
                "question": (
                    "In the stockmarket dataset, how do you join stockinfo "
                    "to a specific ticker's price history in stocktrade_database?"
                ),
                "required_keywords": ["show tables", "symbol"],
            },
            {
                "id": "JK-4",
                # Grounded in: "Datasets with clean joins" table — googlelocal gmap_id, agnews article_id
                "question": (
                    "Which datasets have clean joins requiring no key transformation, "
                    "and what are their join fields?"
                ),
                "required_keywords": ["googlelocal", "gmap_id", "agnews", "article_id"],
            },
        ],
    },

    "domain_terms": {
        "file": DOMAIN_DIR / "domain_term_definitions.md",
        "doc_label": "domain_term_definitions.md",
        "cases": [
            {
                "id": "DT-1",
                # Grounded in: crmarenapro — "won deal = StageName = 'Closed Won'"
                "question": (
                    "In crmarenapro, what does 'won deal' mean and "
                    "which column and value identify it?"
                ),
                "required_keywords": ["closed won", "stagename"],
            },
            {
                "id": "DT-2",
                # Grounded in: yelp — attributes.WiFi values: "free", "paid", "no"
                "question": (
                    "In the yelp dataset, how do you determine if a business "
                    "has WiFi available, and what are the possible values?"
                ),
                "required_keywords": ["attributes.wifi", "free", "paid", "no"],
            },
            {
                "id": "DT-3",
                # Grounded in: googlelocal — "state column is operating status (OPEN/CLOSED), NOT a US state"
                "question": (
                    "In the googlelocal dataset, what does the `state` column "
                    "actually contain, and how do you find the real US state?"
                ),
                "required_keywords": ["operating status", "description"],
            },
            {
                "id": "DT-4",
                # Grounded in: music_brainz_20k — "'unique track' = deduplicated entity, NOT unique track_id. Group by title, artist, album"
                "question": (
                    "What does 'unique track' mean in music_brainz_20k, "
                    "and why should you not use track_id directly?"
                ),
                "required_keywords": ["title", "artist", "album", "fuzzy"],
            },
        ],
    },

    "dataset_overview": {
        "file": DOMAIN_DIR / "dataset_overview.md",
        "doc_label": "dataset_overview.md",
        "cases": [
            {
                "id": "DO-1",
                # Grounded in: yelp join key section — "businessid_N ... businessref_N. Strip prefix and match integer suffix."
                "question": (
                    "What is the join key issue between the yelp "
                    "businessinfo_database and user_database, "
                    "and how is it resolved?"
                ),
                "required_keywords": ["businessid_", "businessref_", "strip", "integer"],
            },
            {
                "id": "DO-2",
                # Grounded in: googlelocal — "state in business_description is business operating status ... NOT a US state abbreviation"
                "question": (
                    "In the googlelocal dataset, what does the `state` column "
                    "in business_description contain, and where is the US state found?"
                ),
                "required_keywords": ["operating status", "description"],
            },
            {
                "id": "DO-3",
                # Grounded in: music_brainz_20k — "tracks table contains duplicates ... Dedup by comparing title, artist, album"
                "question": (
                    "What is the primary data quality challenge with the "
                    "music_brainz_20k tracks table, and how should it be resolved?"
                ),
                "required_keywords": ["duplicate", "title", "artist", "fuzzy"],
            },
            {
                "id": "DO-4",
                # Grounded in: DAB Overview — "Total queries: 54 across 12 datasets"
                "question": (
                    "How many total queries exist in the DAB benchmark "
                    "and across how many datasets?"
                ),
                "required_keywords": ["54", "12"],
            },
        ],
    },

    "unstructured_fields": {
        "file": DOMAIN_DIR / "unstructured_field_inventory.md",
        "doc_label": "unstructured_field_inventory.md",
        "cases": [
            {
                "id": "UF-1",
                # Grounded in: yelp — attributes field: "Python dict serialised as string ... ast.literal_eval()"
                "question": (
                    "How should the `attributes` field in the Yelp MongoDB "
                    "business collection be parsed before use?"
                ),
                "required_keywords": ["ast.literal_eval"],
            },
            {
                "id": "UF-2",
                # Grounded in: googlelocal — "state column is operating status (OPEN/CLOSED), NOT a US state. US state must come from description text"
                "question": (
                    "For the googlelocal dataset, how do you find a business's "
                    "US state, and why can't you use the `state` column?"
                ),
                "required_keywords": ["description", "operating status"],
            },
            {
                "id": "UF-3",
                # Grounded in: agnews — "category must be inferred from title + description ... LLM classification into: World / Sports / Business / Science/Technology"
                "question": (
                    "How are agnews article categories determined, "
                    "and what are the four possible categories?"
                ),
                "required_keywords": ["title", "description", "world", "sports"],
            },
            {
                "id": "UF-4",
                # Grounded in: PATENTS — publication_date is "NL date string, e.g. 'March 15th, 2020'" → dateparser.parse()
                "question": (
                    "What format are PATENTS date fields stored in, "
                    "and what parsing approach is recommended?"
                ),
                "required_keywords": ["natural language", "dateparser"],
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
            "**Question:**",
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
