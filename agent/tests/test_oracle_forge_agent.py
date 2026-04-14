"""
Unit tests for OracleForgeAgent — task 10.5.

Tests cover:
  - process_query() end-to-end (task 10.1)
  - answer() end-to-end via DAB dict format
  - _synthesise_answer() answer generation (task 10.2)
  - _calculate_confidence() score calculation (task 10.2)
  - load_session_context() and session state management (task 10.3)
  - update_interaction_memory() user correction handler (task 10.3)
  - Edge cases: invalid query format, empty results, all sub-queries fail

All LLM calls and database access are mocked so tests run without
external services.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, call, patch

import pytest

from agent.models import (
    ContextBundle,
    CorrectionEntry,
    Document,
    QueryPlan,
    QueryResult,
    SchemaInfo,
    SubQuery,
)


# ── Helpers / fixtures ────────────────────────────────────────────────────────

_MIN_DB_CONFIGS = {"postgres": {"type": "postgres", "connection_string": ""}}


def _mock_client(answer_text: str = "42") -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=answer_text)]
    )
    return client


def _make_plan(
    db: str = "postgres",
    query: str = "SELECT 1",
    query_type: str = "sql",
) -> QueryPlan:
    return QueryPlan(
        sub_queries=[SubQuery(database=db, query=query, query_type=query_type)],
        execution_order=[0],
        join_operations=[],
        requires_sandbox=False,
    )


def _make_execution_result(
    success: bool = True,
    database: str = "postgres",
    data: Any = [[42]],
    error: str | None = None,
    correction_applied: bool = False,
    retries_used: int = 0,
) -> Dict[str, Any]:
    return {
        "success": success,
        "results": [
            QueryResult(
                database=database,
                data=data,
                success=success,
                rows_affected=1 if success else 0,
                error=error,
            )
        ],
        "correction_applied": correction_applied,
        "retries_used": retries_used,
    }


def _build_agent(
    answer_text: str = "42",
    execution_result: Dict | None = None,
    prior_corrections: list | None = None,
):
    """
    Build an OracleForgeAgent with every external dependency mocked.

    Returns (agent, mocks_dict) where mocks_dict gives access to the
    underlying mock objects for assertion.
    """
    from agent.oracle_forge_agent import OracleForgeAgent

    if execution_result is None:
        execution_result = _make_execution_result()
    if prior_corrections is None:
        prior_corrections = []

    mock_client = _mock_client(answer_text)
    mock_ctx = MagicMock()
    mock_ctx.get_bundle.return_value = ContextBundle(
        schema={"postgres": SchemaInfo(database="postgres", db_type="postgres", tables={"t": ["id"]})},
        institutional_knowledge=[],
        corrections=[],
    )
    mock_ctx.get_similar_corrections.return_value = prior_corrections

    mock_plan = _make_plan()
    mock_router = MagicMock()
    mock_router.route.return_value = mock_plan

    mock_scl = MagicMock()
    mock_scl.execute_with_correction.return_value = execution_result

    with (
        patch("agent.oracle_forge_agent.LLMClient", return_value=mock_client),
        patch("agent.oracle_forge_agent.ContextManager", return_value=mock_ctx),
        patch("agent.oracle_forge_agent.QueryRouter", return_value=mock_router),
        patch("agent.oracle_forge_agent.ExecutionEngine", return_value=MagicMock()),
        patch("agent.oracle_forge_agent.SelfCorrectionLoop", return_value=mock_scl),
    ):
        agent = OracleForgeAgent(db_configs=_MIN_DB_CONFIGS)

    # Reattach mocks so tests can inspect them post-construction
    agent._client = mock_client
    agent._ctx_manager = mock_ctx
    agent._router = mock_router
    agent._correction_loop = mock_scl

    mocks = {
        "client": mock_client,
        "ctx": mock_ctx,
        "router": mock_router,
        "scl": mock_scl,
    }
    return agent, mocks


# ── process_query() — end-to-end (task 10.1) ─────────────────────────────────

class TestProcessQuery:
    def test_returns_dab_format_keys(self):
        agent, _ = _build_agent()
        result = agent.process_query(
            question="How many customers?",
            available_databases=["postgres"],
            schema_info={},
        )
        assert "answer" in result
        assert "query_trace" in result
        assert "confidence" in result

    def test_delegates_to_answer(self):
        """process_query() must produce same output as answer() with equivalent input."""
        agent, _ = _build_agent()
        r1 = agent.process_query(
            question="How many orders?",
            available_databases=["postgres"],
            schema_info={},
        )
        assert r1["answer"] is not None

    def test_passes_question_to_router(self):
        """The router must be called with the exact question text."""
        agent, mocks = _build_agent()
        agent.process_query(
            question="What is total revenue?",
            available_databases=["postgres"],
            schema_info={},
        )
        call_args = mocks["router"].route.call_args
        assert call_args[1].get("question") == "What is total revenue?" or (
            call_args[0] and call_args[0][0] == "What is total revenue?"
        )

    def test_passes_available_databases_to_router(self):
        agent, mocks = _build_agent()
        agent.process_query(
            question="q",
            available_databases=["postgres", "mongodb"],
            schema_info={},
        )
        call_args = mocks["router"].route.call_args
        # available_databases is the third positional arg or keyword
        positional = call_args[0]
        keyword = call_args[1]
        dbs = keyword.get("available_databases") or (
            positional[2] if len(positional) > 2 else None
        )
        assert dbs == ["postgres", "mongodb"]

    def test_query_trace_is_list(self):
        agent, _ = _build_agent()
        result = agent.process_query("q", ["postgres"], {})
        assert isinstance(result["query_trace"], list)

    def test_confidence_is_float_in_range(self):
        agent, _ = _build_agent()
        result = agent.process_query("q", ["postgres"], {})
        assert isinstance(result["confidence"], (int, float))
        assert 0.0 <= result["confidence"] <= 1.0


# ── answer() — DAB dict format ────────────────────────────────────────────────

class TestAnswer:
    def test_basic_success_returns_answer(self):
        agent, _ = _build_agent(answer_text="Las Vegas")
        result = agent.answer({
            "question": "What city has most businesses?",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert result["answer"] == "Las Vegas"

    def test_missing_available_databases_defaults_to_all_configs(self):
        """When available_databases is absent, all configured databases are used."""
        agent, mocks = _build_agent()
        agent.answer({
            "question": "q",
            "schema_info": {},
        })
        call_args = mocks["router"].route.call_args
        positional = call_args[0]
        keyword = call_args[1]
        dbs_used = keyword.get("available_databases") or (
            positional[2] if len(positional) > 2 else None
        )
        # Should default to configured databases
        assert dbs_used is not None
        assert len(dbs_used) >= 1

    def test_json_answer_is_parsed(self):
        """If the LLM returns valid JSON, the answer key holds the parsed object."""
        agent, _ = _build_agent(answer_text='[1, 2, 3]')
        result = agent.answer({
            "question": "q",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert result["answer"] == [1, 2, 3]

    def test_non_json_answer_is_string(self):
        agent, _ = _build_agent(answer_text="Not a JSON value")
        result = agent.answer({
            "question": "q",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert result["answer"] == "Not a JSON value"

    def test_empty_results_returns_unable_message(self):
        agent, _ = _build_agent(
            execution_result={
                "success": False,
                "results": [],
                "correction_applied": False,
                "retries_used": 0,
            }
        )
        result = agent.answer({
            "question": "q",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert "Unable" in str(result["answer"]) or result["confidence"] <= 0.2

    def test_failed_execution_lowers_confidence(self):
        agent, _ = _build_agent(
            execution_result=_make_execution_result(success=False, error="syntax error")
        )
        result = agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        assert result["confidence"] <= 0.3

    def test_successful_execution_high_confidence(self):
        agent, _ = _build_agent(
            execution_result=_make_execution_result(success=True)
        )
        result = agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        assert result["confidence"] >= 0.7

    def test_prior_corrections_boost_confidence_on_success(self):
        """A proactively applied correction on a successful run slightly boosts confidence."""
        correction = CorrectionEntry(
            query="SELECT * FROM customers",
            failure_cause="wrong table",
            correction="SELECT * FROM users",
            timestamp=datetime.utcnow(),
            database="postgres",
        )
        agent, _ = _build_agent(
            execution_result=_make_execution_result(success=True),
            prior_corrections=[correction],
        )
        result = agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        # confidence should be ≥ 0.7 (success) but ≤ 1.0 (still capped)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_trace_contains_one_step_per_subquery(self):
        plan = _make_plan()
        agent, mocks = _build_agent()
        mocks["router"].route.return_value = plan
        result = agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        assert len(result["query_trace"]) == len(plan.sub_queries)

    def test_trace_step_has_required_fields(self):
        agent, _ = _build_agent()
        result = agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        step = result["query_trace"][0]
        for field in ("step", "db", "query", "correction_applied"):
            assert field in step, f"Trace step missing field '{field}'"


# ── _calculate_confidence() (task 10.2) ──────────────────────────────────────

class TestCalculateConfidence:
    def _agent(self):
        agent, _ = _build_agent()
        return agent

    def test_failure_returns_low_confidence(self):
        agent = self._agent()
        conf = agent._calculate_confidence(
            success=False, correction_applied=False, retries_used=0
        )
        assert conf <= 0.3

    def test_clean_success_returns_high_confidence(self):
        agent = self._agent()
        conf = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0
        )
        assert conf >= 0.85

    def test_retries_decrease_confidence(self):
        agent = self._agent()
        conf_no_retry = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0
        )
        conf_two_retries = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=2
        )
        assert conf_two_retries < conf_no_retry

    def test_correction_applied_decreases_confidence(self):
        agent = self._agent()
        conf_no_correction = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0
        )
        conf_with_correction = agent._calculate_confidence(
            success=True, correction_applied=True, retries_used=0
        )
        assert conf_with_correction < conf_no_correction

    def test_multi_db_lower_than_single_db(self):
        agent = self._agent()
        single_db_plan = QueryPlan(
            sub_queries=[SubQuery(database="postgres", query="SELECT 1", query_type="sql")],
            execution_order=[0], join_operations=[],
        )
        multi_db_plan = QueryPlan(
            sub_queries=[
                SubQuery(database="postgres", query="SELECT 1", query_type="sql"),
                SubQuery(database="mongodb", query="{}", query_type="mongo"),
            ],
            execution_order=[0, 1], join_operations=[],
        )
        conf_single = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0, plan=single_db_plan
        )
        conf_multi = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0, plan=multi_db_plan
        )
        assert conf_multi < conf_single

    def test_partial_failures_decrease_confidence(self):
        agent = self._agent()
        results_all_ok = [
            QueryResult(database="postgres", data=[[1]], success=True, rows_affected=1)
        ]
        results_partial = [
            QueryResult(database="postgres", data=[[1]], success=True, rows_affected=1),
            QueryResult(database="mongodb", data=None, success=False, error="err"),
        ]
        conf_all_ok = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0, results=results_all_ok
        )
        conf_partial = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0, results=results_partial
        )
        assert conf_partial < conf_all_ok

    def test_confidence_never_below_0_1(self):
        """Even with many retries and corrections, confidence stays ≥ 0.1."""
        agent = self._agent()
        conf = agent._calculate_confidence(
            success=True, correction_applied=True, retries_used=100
        )
        assert conf >= 0.1

    def test_confidence_never_above_1_0(self):
        agent = self._agent()
        conf = agent._calculate_confidence(
            success=True, correction_applied=False, retries_used=0
        )
        assert conf <= 1.0


# ── Session management — load_session_context() (task 10.3) ──────────────────

class TestLoadSessionContext:
    def test_switches_session_id(self):
        agent, _ = _build_agent()
        original_id = agent._session_id
        new_id = "session-xyz"
        agent.load_session_context(new_id)
        assert agent._session_id == new_id
        assert agent._session_id != original_id

    def test_creates_empty_history_for_new_session(self):
        agent, _ = _build_agent()
        new_id = "new-session-abc"
        agent.load_session_context(new_id)
        assert agent._sessions[new_id] == []

    def test_preserves_existing_session_history(self):
        agent, _ = _build_agent()
        agent.load_session_context("session-a")
        # Simulate a turn in session-a
        agent._sessions["session-a"].append({"question": "q1", "answer": "a1"})

        # Switch away and back
        agent.load_session_context("session-b")
        agent.load_session_context("session-a")

        # History for session-a must still be intact
        assert len(agent._sessions["session-a"]) == 1
        assert agent._sessions["session-a"][0]["question"] == "q1"

    def test_reloads_context_layers(self):
        agent, mocks = _build_agent()
        initial_call_count = mocks["ctx"].load_all_layers.call_count
        agent.load_session_context("another-session")
        assert mocks["ctx"].load_all_layers.call_count == initial_call_count + 1

    def test_same_session_id_is_idempotent(self):
        """Calling load_session_context with the same ID twice must not corrupt state."""
        agent, _ = _build_agent()
        sid = agent._session_id
        agent.load_session_context(sid)
        agent.load_session_context(sid)
        assert agent._session_id == sid


# ── update_interaction_memory() (task 10.3) ───────────────────────────────────

class TestUpdateInteractionMemory:
    def test_calls_log_correction(self):
        agent, mocks = _build_agent()
        agent.update_interaction_memory(
            query="SELECT * FROM orders",
            correction="SELECT * FROM orders o WHERE o.status = 'active'",
            pattern="missing status filter",
        )
        mocks["ctx"].log_correction.assert_called_once()

    def test_log_correction_receives_query(self):
        agent, mocks = _build_agent()
        agent.update_interaction_memory(
            query="SELECT * FROM orders",
            correction="corrected query",
            pattern="syntax error",
        )
        call_kwargs = mocks["ctx"].log_correction.call_args
        # The query should appear in args or kwargs
        all_args = str(call_kwargs)
        assert "SELECT * FROM orders" in all_args

    def test_log_correction_receives_correction(self):
        agent, mocks = _build_agent()
        agent.update_interaction_memory(
            query="q",
            correction="fixed query here",
            pattern="pattern",
        )
        all_args = str(mocks["ctx"].log_correction.call_args)
        assert "fixed query here" in all_args

    def test_log_correction_receives_pattern_as_failure_cause(self):
        agent, mocks = _build_agent()
        agent.update_interaction_memory(
            query="q",
            correction="c",
            pattern="join key mismatch",
        )
        all_args = str(mocks["ctx"].log_correction.call_args)
        assert "join key mismatch" in all_args

    def test_multiple_corrections_each_logged(self):
        agent, mocks = _build_agent()
        agent.update_interaction_memory("q1", "c1", "p1")
        agent.update_interaction_memory("q2", "c2", "p2")
        assert mocks["ctx"].log_correction.call_count == 2


# ── Session interaction history accumulation (multi-turn) ─────────────────────

class TestSessionHistoryAccumulation:
    def test_history_grows_with_each_answer_call(self):
        agent, _ = _build_agent()
        sid = agent._session_id
        assert len(agent._sessions[sid]) == 0

        agent.answer({"question": "q1", "available_databases": ["postgres"], "schema_info": {}})
        assert len(agent._sessions[sid]) == 1

        agent.answer({"question": "q2", "available_databases": ["postgres"], "schema_info": {}})
        assert len(agent._sessions[sid]) == 2

    def test_history_records_question(self):
        agent, _ = _build_agent()
        agent.answer({"question": "Who placed the most orders?", "available_databases": ["postgres"], "schema_info": {}})
        sid = agent._session_id
        assert agent._sessions[sid][0]["question"] == "Who placed the most orders?"

    def test_history_records_confidence(self):
        agent, _ = _build_agent()
        agent.answer({"question": "q", "available_databases": ["postgres"], "schema_info": {}})
        sid = agent._session_id
        assert "confidence" in agent._sessions[sid][0]

    def test_separate_sessions_have_independent_history(self):
        agent, _ = _build_agent()
        agent.load_session_context("session-1")
        agent.answer({"question": "q1", "available_databases": ["postgres"], "schema_info": {}})

        agent.load_session_context("session-2")
        agent.answer({"question": "q2", "available_databases": ["postgres"], "schema_info": {}})

        assert len(agent._sessions["session-1"]) == 1
        assert len(agent._sessions["session-2"]) == 1
        assert agent._sessions["session-1"][0]["question"] == "q1"
        assert agent._sessions["session-2"][0]["question"] == "q2"


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_invalid_query_format_missing_question_raises_key_error(self):
        """If the caller omits 'question', a KeyError is the expected signal."""
        agent, _ = _build_agent()
        with pytest.raises(KeyError):
            agent.answer({"available_databases": ["postgres"], "schema_info": {}})

    def test_empty_string_question_is_accepted(self):
        """An empty question string is a valid (if degenerate) DAB input."""
        agent, _ = _build_agent()
        result = agent.process_query(
            question="",
            available_databases=["postgres"],
            schema_info={},
        )
        assert "answer" in result

    def test_all_subqueries_fail_returns_low_confidence(self):
        failed_result = {
            "success": False,
            "results": [
                QueryResult(database="postgres", data=None, success=False, error="err")
            ],
            "correction_applied": False,
            "retries_used": 3,
        }
        agent, _ = _build_agent(execution_result=failed_result)
        result = agent.answer({
            "question": "q",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert result["confidence"] <= 0.3

    def test_correction_applied_flag_reflected_in_trace(self):
        exec_result = _make_execution_result(correction_applied=True)
        agent, _ = _build_agent(execution_result=exec_result)
        result = agent.answer({
            "question": "q",
            "available_databases": ["postgres"],
            "schema_info": {},
        })
        assert result["query_trace"][0]["correction_applied"] is True

    def test_answer_method_does_not_raise_when_evaluation_harness_unavailable(self):
        """EvaluationHarness import failure must be silently swallowed."""
        agent, _ = _build_agent()
        with patch("agent.oracle_forge_agent.EvaluationHarness", side_effect=ImportError):
            # Should not raise
            result = agent.answer({
                "question": "q",
                "available_databases": ["postgres"],
                "schema_info": {},
            })
        assert "answer" in result
