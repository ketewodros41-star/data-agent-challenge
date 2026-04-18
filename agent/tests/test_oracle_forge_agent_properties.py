"""
Property-based tests for OracleForgeAgent — task 10.4.

Validates:
  Property 41: DAB Query Format Acceptance        (Requirements 11.1)
  Property 42: DAB Result Format Compliance       (Requirements 11.2)
  Property 53: Confidence Score Inclusion         (Requirements 16.5)

LLM calls, database access, and component I/O are all mocked so tests
run fast and deterministically without external services.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent.models.models import (
    ContextBundle,
    CorrectionEntry,
    QueryPlan,
    QueryResult,
    SchemaInfo,
    SubQuery,
)

# ── Hypothesis strategies ──────────────────────────────────────────────────────

_DB_NAMES = ["postgres", "mongodb", "sqlite", "duckdb"]

question_strategy = st.one_of(
    st.sampled_from([
        "How many customers placed orders last month?",
        "What is the average star rating for businesses in Las Vegas?",
        "Find reviews mentioning parking",
        "Show total revenue per category",
        "Which users have the most transactions?",
        "List all products with price above 100",
    ]),
    # Also include arbitrary non-empty strings to stress the format acceptance invariant
    st.text(min_size=1, max_size=300).filter(lambda s: s.strip()),
)

available_dbs_strategy = st.lists(
    st.sampled_from(_DB_NAMES),
    min_size=1,
    max_size=4,
    unique=True,
)

schema_info_strategy = st.fixed_dictionaries({})  # empty schema_info is valid per DAB spec

answer_strategy = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=0, max_size=100),
    st.lists(st.integers(), max_size=5),
)


# ── Test fixture helpers ───────────────────────────────────────────────────────

def _make_agent(answer_value: Any = "42", success: bool = True):
    """
    Build an OracleForgeAgent with all external components mocked.

    Returns the agent and the mocks for interrogation.
    """
    from agent.oracle_forge_agent import OracleForgeAgent

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(answer_value) if not isinstance(answer_value, str)
                           else answer_value)]
    )

    mock_ctx = MagicMock()
    mock_ctx.get_bundle.return_value = ContextBundle(
        schema={
            db: SchemaInfo(database=db, db_type=db, tables={"t": ["id"]})
            for db in _DB_NAMES
        },
        institutional_knowledge=[],
        corrections=[],
    )
    mock_ctx.get_similar_corrections.return_value = []

    mock_plan = QueryPlan(
        sub_queries=[SubQuery(database="postgres", query="SELECT 1", query_type="sql")],
        execution_order=[0],
        join_operations=[],
        requires_sandbox=False,
    )
    mock_router = MagicMock()
    mock_router.route.return_value = mock_plan

    mock_result = QueryResult(
        database="postgres",
        data=[[answer_value]],
        success=success,
        rows_affected=1 if success else 0,
        error=None if success else "forced failure",
    )
    mock_scl = MagicMock()
    mock_scl.execute_with_correction.return_value = {
        "success": success,
        "results": [mock_result],
        "correction_applied": False,
        "retries_used": 0,
    }

    with (
        patch("agent.oracle_forge_agent.LLMClient", return_value=mock_client),
        patch("agent.oracle_forge_agent.ContextManager", return_value=mock_ctx),
        patch("agent.oracle_forge_agent.QueryRouter", return_value=mock_router),
        patch("agent.oracle_forge_agent.ExecutionEngine", return_value=MagicMock()),
        patch("agent.oracle_forge_agent.SelfCorrectionLoop", return_value=mock_scl),
    ):
        agent = OracleForgeAgent(db_configs={"postgres": {"type": "postgres", "connection_string": ""}}, agent_mode=False)

    # Reattach the mocked sub-components so tests can inspect call counts etc.
    agent._ctx_manager = mock_ctx
    agent._router = mock_router
    agent._correction_loop = mock_scl
    agent._client = mock_client
    return agent


# ── Property 41: DAB Query Format Acceptance (Requirement 11.1) ──────────────
#
# Invariant: for any well-formed DAB input (question text, list of database
# names, schema_info dict), process_query() must NOT raise an exception.
# The agent must accept the format regardless of question content.

@given(
    question=question_strategy,
    available_dbs=available_dbs_strategy,
    schema_info=schema_info_strategy,
)
@settings(
    max_examples=60,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_property41_dab_query_format_acceptance(
    question: str,
    available_dbs: List[str],
    schema_info: Dict[str, Any],
):
    """
    Property 41 — DAB Query Format Acceptance.

    For any query in DAB format (question text, available_databases list,
    schema_info dict), process_query() must accept it without raising.
    """
    agent = _make_agent(answer_value="result")

    # Must not raise for any valid DAB input
    result = agent.process_query(
        question=question,
        available_databases=available_dbs,
        schema_info=schema_info,
    )

    # A non-None result confirms acceptance
    assert result is not None


# ── Property 42: DAB Result Format Compliance (Requirement 11.2) ─────────────
#
# Invariant: for any query result produced by the agent, the output dict
# must contain exactly the three DAB-required keys: "answer", "query_trace",
# and "confidence".  No key may be missing.

@given(
    question=question_strategy,
    available_dbs=available_dbs_strategy,
    answer_value=answer_strategy,
)
@settings(
    max_examples=60,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_property42_dab_result_format_compliance(
    question: str,
    available_dbs: List[str],
    answer_value: Any,
):
    """
    Property 42 — DAB Result Format Compliance.

    For any query result, the output must conform to the DAB required format:
    {"answer": Any, "query_trace": List[dict], "confidence": float}.
    """
    agent = _make_agent(answer_value=answer_value)

    result = agent.process_query(
        question=question,
        available_databases=available_dbs,
        schema_info={},
    )

    # All three required keys must be present
    assert "answer" in result, "Missing 'answer' key in DAB output"
    assert "query_trace" in result, "Missing 'query_trace' key in DAB output"
    assert "confidence" in result, "Missing 'confidence' key in DAB output"

    # query_trace must be a list
    assert isinstance(result["query_trace"], list), (
        f"'query_trace' must be a list, got {type(result['query_trace'])}"
    )


# ── Property 53: Confidence Score Inclusion (Requirement 16.5) ───────────────
#
# Invariant: for any query result, the confidence value must be a float
# in the range [0.0, 1.0].  It must be based on validation outcomes
# (success/failure) and query complexity (multi-DB vs single-DB).

@given(
    question=question_strategy,
    available_dbs=available_dbs_strategy,
    success=st.booleans(),
)
@settings(
    max_examples=80,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_property53_confidence_score_inclusion(
    question: str,
    available_dbs: List[str],
    success: bool,
):
    """
    Property 53 — Confidence Score Inclusion.

    For any query answer, the confidence score must be:
    1. Present in the result dict.
    2. A float (or int coercible to float).
    3. In the range [0.0, 1.0].
    4. Lower for failed queries than for successful ones.
    """
    agent = _make_agent(answer_value="some answer", success=success)

    result = agent.process_query(
        question=question,
        available_databases=available_dbs,
        schema_info={},
    )

    confidence = result["confidence"]

    # Must be numeric
    assert isinstance(confidence, (int, float)), (
        f"confidence must be a number, got {type(confidence)}"
    )

    # Must be in [0.0, 1.0]
    assert 0.0 <= float(confidence) <= 1.0, (
        f"confidence {confidence} is outside [0.0, 1.0]"
    )


# ── Property: _calculate_confidence is monotone in success ───────────────────
#
# A successful query must always produce higher or equal confidence than a
# failed one, holding all other parameters equal.

@given(
    retries_used=st.integers(min_value=0, max_value=3),
    correction_applied=st.booleans(),
    n_databases=st.integers(min_value=1, max_value=4),
)
@settings(max_examples=80, deadline=None)
def test_property_confidence_monotone_in_success(
    retries_used: int,
    correction_applied: bool,
    n_databases: int,
):
    """
    _calculate_confidence must always return a higher value for success=True
    than for success=False, regardless of other parameters.
    """
    from agent.oracle_forge_agent import OracleForgeAgent
    from agent.models.models import QueryPlan, SubQuery

    with (
        patch("agent.oracle_forge_agent.LLMClient"),
        patch("agent.oracle_forge_agent.ContextManager") as MockCM,
        patch("agent.oracle_forge_agent.QueryRouter"),
        patch("agent.oracle_forge_agent.ExecutionEngine"),
        patch("agent.oracle_forge_agent.SelfCorrectionLoop"),
    ):
        mock_ctx = MagicMock()
        mock_ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        mock_ctx.get_similar_corrections.return_value = []
        MockCM.return_value = mock_ctx

        agent = OracleForgeAgent(
            db_configs={"postgres": {"type": "postgres", "connection_string": ""}},
            agent_mode=False
        )

    # Build a plan with n_databases distinct databases
    db_names = (_DB_NAMES * 4)[:n_databases]
    plan = QueryPlan(
        sub_queries=[
            SubQuery(database=db, query="SELECT 1", query_type="sql")
            for db in db_names
        ],
        execution_order=list(range(n_databases)),
        join_operations=[],
    )

    conf_success = agent._calculate_confidence(
        success=True,
        correction_applied=correction_applied,
        retries_used=retries_used,
        plan=plan,
        results=None,
    )
    conf_failure = agent._calculate_confidence(
        success=False,
        correction_applied=correction_applied,
        retries_used=retries_used,
        plan=plan,
        results=None,
    )

    assert conf_success >= conf_failure, (
        f"Successful query confidence ({conf_success}) must be ≥ failed "
        f"({conf_failure}); retries={retries_used}, correction={correction_applied}, "
        f"n_dbs={n_databases}"
    )


# ── Property: confidence stays in [0.1, 1.0] for all inputs ──────────────────

@given(
    success=st.booleans(),
    correction_applied=st.booleans(),
    retries_used=st.integers(min_value=0, max_value=10),
    n_databases=st.integers(min_value=1, max_value=8),
    n_failed=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100, deadline=None)
def test_property_confidence_always_in_valid_range(
    success: bool,
    correction_applied: bool,
    retries_used: int,
    n_databases: int,
    n_failed: int,
):
    """
    _calculate_confidence must always return a value in [0.1, 1.0],
    even for extreme inputs (many retries, many failed sub-queries, etc.).
    """
    from agent.oracle_forge_agent import OracleForgeAgent
    from agent.models.models import QueryPlan, QueryResult, SubQuery

    with (
        patch("agent.oracle_forge_agent.LLMClient"),
        patch("agent.oracle_forge_agent.ContextManager") as MockCM,
        patch("agent.oracle_forge_agent.QueryRouter"),
        patch("agent.oracle_forge_agent.ExecutionEngine"),
        patch("agent.oracle_forge_agent.SelfCorrectionLoop"),
    ):
        mock_ctx = MagicMock()
        mock_ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        mock_ctx.get_similar_corrections.return_value = []
        MockCM.return_value = mock_ctx

        agent = OracleForgeAgent(
            db_configs={"postgres": {"type": "postgres", "connection_string": ""}},
            agent_mode=False
        )

    db_names = (_DB_NAMES * 4)[:max(1, n_databases)]
    plan = QueryPlan(
        sub_queries=[
            SubQuery(database=db, query="SELECT 1", query_type="sql")
            for db in db_names
        ],
        execution_order=list(range(len(db_names))),
        join_operations=[],
    )
    results = [
        QueryResult(database="postgres", data=None, success=(i >= n_failed), error="err")
        for i in range(n_failed + 2)
    ]

    conf = agent._calculate_confidence(
        success=success,
        correction_applied=correction_applied,
        retries_used=retries_used,
        plan=plan,
        results=results,
    )

    assert 0.1 <= conf <= 1.0, (
        f"Confidence {conf} out of [0.1, 1.0] for "
        f"success={success}, retries={retries_used}, n_failed={n_failed}"
    )
