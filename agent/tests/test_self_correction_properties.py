"""
Property-based tests for SelfCorrectionLoop — task 8.5.

Validates:
  Property 10: Error Capture Completeness        (Requirements 3.1)
  Property 11: Failure Diagnosis Coverage        (Requirements 3.2)
  Property 12: Join Key Format Resolution        (Requirements 3.3, 4.3)
  Property 13: Query Regeneration on Syntax Error (Requirements 3.4)
  Property 14: Transparent Error Recovery        (Requirements 3.5)
  Property 15: Structured Error After Retry Exhaustion (Requirements 3.7)
  Property 18: Join Failure Learning             (Requirements 4.5)

LLM calls are always mocked so tests run fast and deterministically.
Uses Hypothesis to generate adversarial inputs.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from agent.models.models import (
    ContextBundle,
    CorrectionEntry,
    Document,
    FailureInfo,
    QueryPlan,
    QueryResult,
    SubQuery,
)
from agent.self_correction import MAX_RETRIES, SelfCorrectionLoop

# ── Hypothesis strategies ─────────────────────────────────────────────────────

_DB_NAMES = ["postgres", "mongodb", "sqlite", "duckdb"]
_FAILURE_TYPES = [
    "syntax",
    "join_key_mismatch",
    "wrong_db_type",
    "data_quality",
    "extraction_failure",
]

# Error messages representative of each failure category
_TYPED_ERRORS = {
    "syntax": [
        "syntax error near 'FROM'",
        "invalid syntax at position 12",
        "no such table: orders",
        "unexpected token: SELECT",
        "does not exist: column revenue",
    ],
    "join_key_mismatch": [
        "operator does not exist: integer = text",
        "incompatible types in join expression",
        "cannot cast integer to text",
        "type mismatch in join predicate",
    ],
    "wrong_db_type": [
        "unsupported operation for this engine",
        "SQL not supported on MongoDB",
        "invalid aggregation pipeline stage",
        "command not found: aggregate",
    ],
    "data_quality": [
        "null constraint violated on column id",
        "duplicate key value violates unique constraint",
        "violates check constraint: positive_amount",
        "referential integrity violation",
    ],
    "extraction_failure": [
        "extraction failed: invalid json returned",
        "json parse error in sandbox",
        "no data extracted from document",
        "unstructured field extraction error",
    ],
}

db_name_strategy = st.sampled_from(_DB_NAMES)

error_by_type_strategy = st.one_of(
    *[
        # Use ft=ft default arg to capture the current loop value, avoiding closure bug
        st.sampled_from(errors).map(lambda e, ft=ft: (ft, e))
        for ft, errors in _TYPED_ERRORS.items()
    ]
)

failure_type_strategy = st.sampled_from(_FAILURE_TYPES)

query_strategy = st.sampled_from([
    "SELECT * FROM orders WHERE customer_id = 1",
    "db.reviews.find({'stars': {'$gte': 4}})",
    "SELECT AVG(amount) FROM transactions",
    "SELECT u.name, COUNT(o.id) FROM users u JOIN orders o ON u.id = o.user_id",
    "SELECT * FROM products WHERE category IS NOT NULL",
])

question_strategy = st.sampled_from([
    "How many orders were placed last month?",
    "What is the average review rating?",
    "List all customers with overdue payments",
    "Which products have the highest sales?",
])


def _make_ctx(similar_corrections=None, institutional_knowledge=None):
    ctx = MagicMock()
    ctx.get_similar_corrections.return_value = similar_corrections or []
    ctx.get_bundle.return_value = ContextBundle(
        schema={},
        institutional_knowledge=institutional_knowledge or [],
        corrections=similar_corrections or [],
    )
    return ctx


def _make_loop(engine=None, similar_corrections=None, institutional_knowledge=None):
    if engine is None:
        engine = MagicMock()
        engine.execute.return_value = [
            QueryResult(database="postgres", data=[[1]], success=True)
        ]
    ctx = _make_ctx(
        similar_corrections=similar_corrections,
        institutional_knowledge=institutional_knowledge,
    )
    client = MagicMock()
    client.messages.create.return_value.content = [
        MagicMock(text="SELECT corrected FROM t")
    ]
    return SelfCorrectionLoop(engine, ctx, client=client)


# ── Property 10: Error Capture Completeness ───────────────────────────────────
#
# For any failed QueryResult, detect_failure() must return a FailureInfo
# (not None) and must correctly identify one of the five canonical categories.

@given(error_info=error_by_type_strategy, db=db_name_strategy)
@settings(max_examples=100, deadline=None)
def test_property10_error_capture_completeness(error_info, db):
    """
    Property 10 — Error Capture Completeness.

    For any execution result with success=False, detect_failure() must
    return a non-None FailureInfo.  Every known error message from each
    failure category must be classified as one of the five canonical types.
    """
    expected_type, error_msg = error_info
    loop = _make_loop()
    result = QueryResult(
        database=db, data=None, success=False, error=error_msg
    )
    info = loop.detect_failure(result)

    assert info is not None, (
        f"detect_failure() returned None for error: {error_msg!r}"
    )
    assert info.failure_type in _FAILURE_TYPES, (
        f"Unknown failure type '{info.failure_type}' for error: {error_msg!r}"
    )
    assert info.failure_type == expected_type, (
        f"Expected '{expected_type}' but got '{info.failure_type}' "
        f"for error: {error_msg!r}"
    )


@given(db=db_name_strategy)
@settings(max_examples=20, deadline=None)
def test_property10_successful_result_returns_none(db):
    """detect_failure() must return None when the result is successful."""
    loop = _make_loop()
    result = QueryResult(database=db, data=[[1]], success=True)
    assert loop.detect_failure(result) is None


# ── Property 11: Failure Diagnosis Coverage ───────────────────────────────────
#
# For any FailureInfo, diagnose_root_cause() must return a Diagnosis whose
# root_cause matches the failure_type and whose confidence is in [0, 1].

@given(
    failure_type=failure_type_strategy,
    query=query_strategy,
    db=db_name_strategy,
)
@settings(max_examples=80, deadline=None)
def test_property11_diagnosis_covers_all_failure_types(failure_type, query, db):
    """
    Property 11 — Failure Diagnosis Coverage.

    diagnose_root_cause() must return a Diagnosis with root_cause matching
    the input failure_type, and confidence in [0.0, 1.0], for every possible
    failure category.
    """
    loop = _make_loop()
    failure = FailureInfo(
        failure_type=failure_type,
        error_message="some error",
        failed_query=query,
        database=db,
    )
    diag = loop.diagnose_root_cause(failure, question="test question")

    assert diag.root_cause == failure_type, (
        f"Diagnosis root_cause '{diag.root_cause}' != failure_type '{failure_type}'"
    )
    assert 0.0 <= diag.confidence <= 1.0, (
        f"Confidence {diag.confidence} out of [0, 1] range"
    )
    assert isinstance(diag.evidence, list)
    assert len(diag.evidence) >= 1


@given(
    failure_type=failure_type_strategy,
    n_past=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=40, deadline=None)
def test_property11_past_failures_increase_confidence(failure_type, n_past):
    """
    When Layer 3 has similar past failures, confidence must be > 0.5.
    """
    past_corrections = [
        CorrectionEntry(
            query=f"SELECT * FROM t{i}",
            failure_cause=f"{failure_type}: example error",
            correction="Apply type cast",
            timestamp=datetime.utcnow(),
            database="postgres",
        )
        for i in range(n_past)
    ]
    loop = _make_loop(similar_corrections=past_corrections)
    failure = FailureInfo(
        failure_type=failure_type,
        error_message="example error",
        failed_query="SELECT * FROM t0",
        database="postgres",
    )
    diag = loop.diagnose_root_cause(failure)

    assert diag.confidence > 0.5, (
        f"Expected confidence > 0.5 with {n_past} past failures, got {diag.confidence}"
    )


# ── Property 12: Join Key Format Resolution ───────────────────────────────────
#
# For a join_key_mismatch failure, generate_correction() must return a
# CorrectionStrategy with strategy_type == "transform_join_key".

@given(query=query_strategy, suggested_fix=st.text(min_size=0, max_size=100))
@settings(max_examples=60, deadline=None)
def test_property12_join_key_mismatch_produces_transform_strategy(
    query, suggested_fix
):
    """
    Property 12 — Join Key Format Resolution.

    For any join_key_mismatch failure, generate_correction() must produce
    a CorrectionStrategy with strategy_type == "transform_join_key".
    """
    from agent.models.models import Diagnosis

    loop = _make_loop()
    diag = Diagnosis(
        root_cause="join_key_mismatch",
        confidence=0.75,
        evidence=["operator does not exist: integer = text"],
        suggested_fix=suggested_fix,
    )
    strategy = loop.generate_correction(diag, query)

    assert strategy.strategy_type == "transform_join_key", (
        f"Expected 'transform_join_key', got '{strategy.strategy_type}'"
    )
    assert isinstance(strategy.format_transformations, list)


@given(query=query_strategy)
@settings(max_examples=30, deadline=None)
def test_property12_int_string_evidence_builds_format_transform(query):
    """
    When evidence contains 'int' and 'string', a FormatTransform must be built.
    """
    from agent.models.models import Diagnosis

    loop = _make_loop()
    diag = Diagnosis(
        root_cause="join_key_mismatch",
        confidence=0.85,
        evidence=["INT in PostgreSQL, string in MongoDB — cast Mongo value to int"],
        suggested_fix="Cast to int",
    )
    strategy = loop.generate_correction(diag, query)
    assert len(strategy.format_transformations) == 1
    ft = strategy.format_transformations[0]
    assert ft.transformation_function in ("int(value)", "str(value)")


# ── Property 13: Query Regeneration on Syntax Error ──────────────────────────
#
# For a syntax failure, generate_correction() must return a CorrectionStrategy
# with strategy_type == "regenerate_query".

@given(query=query_strategy, suggested_fix=st.text(min_size=0, max_size=50))
@settings(max_examples=60, deadline=None)
def test_property13_syntax_error_produces_regenerate_strategy(query, suggested_fix):
    """
    Property 13 — Query Regeneration on Syntax Error.

    For any syntax failure, generate_correction() must produce a
    CorrectionStrategy with strategy_type == 'regenerate_query'.
    """
    from agent.models.models import Diagnosis

    loop = _make_loop()
    diag = Diagnosis(
        root_cause="syntax",
        confidence=0.6,
        evidence=["Failure type classified as: syntax"],
        suggested_fix=suggested_fix,
    )
    strategy = loop.generate_correction(diag, query)

    assert strategy.strategy_type == "regenerate_query", (
        f"Expected 'regenerate_query', got '{strategy.strategy_type}'"
    )


# ── Property 14: Transparent Error Recovery ───────────────────────────────────
#
# When execution eventually succeeds (within MAX_RETRIES), success=True and
# the user sees no error — only the final results list.

@given(
    success_on_attempt=st.integers(min_value=0, max_value=MAX_RETRIES - 1),
)
@settings(max_examples=30, deadline=None)
def test_property14_transparent_error_recovery(success_on_attempt):
    """
    Property 14 — Transparent Error Recovery.

    When execution succeeds on attempt N (0-indexed, N < MAX_RETRIES),
    the returned dict must have success=True and 'results' must contain
    at least one successful QueryResult. The user sees no error.
    """
    failure = QueryResult(
        database="postgres", data=None, success=False,
        error="syntax error near FROM"
    )
    success = QueryResult(database="postgres", data=[[1]], success=True)

    side_effects = [
        [failure] for _ in range(success_on_attempt)
    ] + [[success]]

    engine = MagicMock()
    engine.execute_plan.side_effect = side_effects

    ctx = _make_ctx()
    client = MagicMock()
    client.messages.create.return_value.content = [
        MagicMock(text="SELECT corrected FROM t")
    ]
    loop = SelfCorrectionLoop(engine, ctx, client=client)

    result = loop.execute_with_correction(
        QueryPlan(
            sub_queries=[SubQuery(database="postgres", query="SELECT * FORM t", query_type="sql")],
            execution_order=[0],
            join_operations=[],
        ),
        question="how many rows?",
    )

    assert result["success"] is True, (
        f"Expected success=True when execution succeeds on attempt {success_on_attempt}"
    )
    assert any(r.success for r in result["results"]), (
        "results list should contain at least one successful QueryResult"
    )


# ── Property 15: Structured Error After Retry Exhaustion ─────────────────────
#
# When all MAX_RETRIES attempts fail, success=False and retries_used==MAX_RETRIES-1.

@given(db=db_name_strategy)
@settings(max_examples=30, deadline=None)
def test_property15_structured_error_after_retry_exhaustion(db):
    """
    Property 15 — Structured Error After Retry Exhaustion.

    When all MAX_RETRIES attempts fail, the return dict must have:
      success=False, retries_used == MAX_RETRIES - 1.
    """
    engine = MagicMock()
    engine.execute_plan.return_value = [
        QueryResult(database=db, data=None, success=False, error="persistent error")
    ]
    ctx = _make_ctx()
    client = MagicMock()
    client.messages.create.return_value.content = [
        MagicMock(text="SELECT still_broken FROM t")
    ]
    loop = SelfCorrectionLoop(engine, ctx, client=client)

    result = loop.execute_with_correction(
        QueryPlan(
            sub_queries=[SubQuery(database=db, query="SELECT broken", query_type="sql")],
            execution_order=[0],
            join_operations=[],
        ),
        question="anything",
    )

    assert result["success"] is False, "Expected success=False after retry exhaustion"
    assert result["retries_used"] == MAX_RETRIES - 1, (
        f"Expected retries_used={MAX_RETRIES - 1}, got {result['retries_used']}"
    )
    assert engine.execute_plan.call_count == MAX_RETRIES


# ── Property 18: Join Failure Learning ───────────────────────────────────────
#
# After a join failure is corrected and logged to Layer 3, a subsequent run
# of a similar query must have correction_applied=True (proactive correction).

@given(db=db_name_strategy)
@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_property18_join_failure_learning(db):
    """
    Property 18 — Join Failure Learning.

    After a join_key_mismatch failure is corrected and logged to Layer 3,
    a subsequent call with a similar query must have correction_applied=True,
    demonstrating that the agent learned from the failure.
    """
    join_query = (
        f"SELECT * FROM orders o JOIN users u ON o.{db}_id = u.id"
    )

    # Simulate: Layer 3 already has a recorded correction for this pattern
    past = CorrectionEntry(
        query=join_query,
        failure_cause="join_key_mismatch: operator does not exist: integer = text",
        correction="transform_join_key: SELECT * FROM orders o JOIN users u ON CAST(o.id AS TEXT) = u.id LIMIT 200",
        timestamp=datetime.utcnow(),
        database=db,
    )

    engine = MagicMock()
    engine.execute.return_value = [
        QueryResult(database=db, data=[[1, 2]], success=True)
    ]

    ctx = _make_ctx(similar_corrections=[past])
    client = MagicMock()
    # LLM returns a corrected query (different from original)
    client.messages.create.return_value.content = [
        MagicMock(
            text=f"SELECT * FROM orders o JOIN users u ON CAST(o.id AS TEXT) = u.id"
        )
    ]

    loop = SelfCorrectionLoop(engine, ctx, client=client)
    result = loop.execute_with_correction(
        QueryPlan(
            sub_queries=[SubQuery(database=db, query=join_query, query_type="sql")],
            execution_order=[0],
            join_operations=[],
        ),
        question="list orders with user names",
    )

    assert result["correction_applied"] is True, (
        "Expected correction_applied=True when Layer 3 has a matching past correction "
        f"(db={db})"
    )
    assert result["success"] is True


# ── Cross-cutting: strategy_type is always one of the five valid values ───────

@given(failure_type=failure_type_strategy, query=query_strategy)
@settings(max_examples=50, deadline=None)
def test_generate_correction_always_returns_valid_strategy_type(failure_type, query):
    """
    generate_correction() must always return one of the five canonical
    strategy types, regardless of failure_type input.
    """
    from agent.models.models import Diagnosis

    _VALID_STRATEGY_TYPES = {
        "regenerate_query",
        "transform_join_key",
        "reroute_database",
        "apply_quality_rules",
        "alternative_extraction",
    }

    loop = _make_loop()
    diag = Diagnosis(
        root_cause=failure_type,
        confidence=0.6,
        evidence=[],
    )
    strategy = loop.generate_correction(diag, query)

    assert strategy.strategy_type in _VALID_STRATEGY_TYPES, (
        f"Unexpected strategy_type '{strategy.strategy_type}' "
        f"for failure_type='{failure_type}'"
    )
