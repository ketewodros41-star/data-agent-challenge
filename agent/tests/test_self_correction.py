"""
Unit tests for SelfCorrectionLoop — task 8.6.

Tests cover:
  - Failure detection for each of the five error categories (8.1)
  - Diagnosis logic using Layer 2 and Layer 3 (8.2)
  - Correction strategy generation for each failure type (8.3)
  - Retry logic: success first try, retry on failure, retry exhaustion (8.4)
  - Correction logging to Layer 3 (8.4)
  - Proactive Layer 3 correction (self-learning loop, 8.4)
  - Edge cases: max retries exceeded, ambiguous errors
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.models import (
    ContextBundle,
    CorrectionEntry,
    CorrectionStrategy,
    Diagnosis,
    Document,
    FailureInfo,
    FormatTransform,
    QueryPlan,
    QueryResult,
    SchemaInfo,
    SubQuery,
)
from agent.self_correction import MAX_RETRIES, SelfCorrectionLoop


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_plan(queries=None):
    queries = queries or [
        SubQuery(database="postgres", query="SELECT 1", query_type="sql")
    ]
    return QueryPlan(
        sub_queries=queries,
        execution_order=list(range(len(queries))),
        join_operations=[],
    )


def _make_result(success=True, database="postgres", error=None):
    return QueryResult(
        database=database,
        data=[[1]] if success else None,
        success=success,
        error=error,
        rows_affected=1 if success else 0,
    )


def _make_loop(engine=None, ctx=None, client=None, similar_corrections=None):
    """Helper that wires up a SelfCorrectionLoop with sensible defaults."""
    if engine is None:
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]
    if ctx is None:
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = similar_corrections or []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
    if client is None:
        client = MagicMock()
    return SelfCorrectionLoop(engine, ctx, client=client)


# ── 8.1  Failure detection ────────────────────────────────────────────────────

class TestDetectFailure:
    def test_returns_none_on_success(self):
        loop = _make_loop()
        assert loop.detect_failure(_make_result(success=True)) is None

    def test_detects_syntax_error(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="syntax error near 'FROM'")
        )
        assert info is not None
        assert info.failure_type == "syntax"

    def test_detects_no_such_table(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="no such table: orders")
        )
        assert info is not None
        assert info.failure_type == "syntax"

    def test_detects_join_key_mismatch(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(
                success=False, error="operator does not exist: integer = text"
            )
        )
        assert info is not None
        assert info.failure_type == "join_key_mismatch"

    def test_detects_incompatible_types(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="incompatible types in join expression")
        )
        assert info is not None
        assert info.failure_type == "join_key_mismatch"

    def test_detects_wrong_db_type(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(
                success=False, error="unsupported operation: SQL not supported on MongoDB"
            )
        )
        assert info is not None
        assert info.failure_type == "wrong_db_type"

    def test_detects_invalid_aggregation(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="invalid aggregation pipeline stage")
        )
        assert info is not None
        assert info.failure_type == "wrong_db_type"

    def test_detects_data_quality(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="violates unique constraint 'users_pkey'")
        )
        assert info is not None
        assert info.failure_type == "data_quality"

    def test_detects_null_constraint(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="null constraint violated on column id")
        )
        assert info is not None
        assert info.failure_type == "data_quality"

    def test_detects_extraction_failure(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="extraction failed: invalid json returned")
        )
        assert info is not None
        assert info.failure_type == "extraction_failure"

    def test_unknown_error_defaults_to_syntax(self):
        """Ambiguous errors fall back to 'syntax' so LLM regeneration is attempted."""
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, error="something went terribly wrong")
        )
        assert info is not None
        assert info.failure_type == "syntax"

    def test_failure_info_captures_database(self):
        loop = _make_loop()
        info = loop.detect_failure(
            _make_result(success=False, database="mongodb", error="syntax error")
        )
        assert info.database == "mongodb"


# ── 8.2  Failure diagnosis ────────────────────────────────────────────────────

class TestDiagnoseRootCause:
    def _make_failure(self, failure_type="syntax", error="syntax error near FROM"):
        return FailureInfo(
            failure_type=failure_type,
            error_message=error,
            failed_query="SELECT * FROM orders",
            database="postgres",
        )

    def test_returns_diagnosis_with_matching_root_cause(self):
        loop = _make_loop()
        failure = self._make_failure()
        diag = loop.diagnose_root_cause(failure)
        assert diag.root_cause == "syntax"
        assert isinstance(diag.confidence, float)
        assert 0.0 <= diag.confidence <= 1.0

    def test_similar_past_failures_increase_confidence(self):
        past = CorrectionEntry(
            query="SELECT * FROM orders",
            failure_cause="syntax: missing alias",
            correction="Add alias to subquery",
            timestamp=datetime.utcnow(),
            database="postgres",
        )
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = [past]
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[past]
        )
        loop = SelfCorrectionLoop(MagicMock(), ctx, client=MagicMock())

        failure = self._make_failure()
        diag = loop.diagnose_root_cause(failure)

        assert diag.confidence >= 0.6
        assert len(diag.similar_past_failures) == 1
        assert "Add alias to subquery" in diag.suggested_fix

    def test_join_key_mismatch_consults_glossary(self):
        glossary_doc = Document(
            source="kb/domain/join_key_glossary.md",
            content="| customer_id | id | customer_id | INT in PostgreSQL, string in MongoDB — cast Mongo value to int |",
        )
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={},
            institutional_knowledge=[glossary_doc],
            corrections=[],
        )
        loop = SelfCorrectionLoop(MagicMock(), ctx, client=MagicMock())
        failure = self._make_failure(
            failure_type="join_key_mismatch",
            error="operator does not exist: integer = text on customer_id",
        )
        failure.failed_query = "SELECT * FROM orders JOIN users ON orders.customer_id = users.id"

        diag = loop.diagnose_root_cause(failure)
        assert diag.confidence >= 0.8
        assert any("customer_id" in e for e in diag.evidence)

    def test_evidence_list_is_non_empty(self):
        loop = _make_loop()
        diag = loop.diagnose_root_cause(self._make_failure())
        assert len(diag.evidence) >= 1

    def test_no_past_failures_gives_base_confidence(self):
        loop = _make_loop()
        diag = loop.diagnose_root_cause(self._make_failure())
        assert diag.confidence == 0.5


# ── 8.3  Correction strategy generation ──────────────────────────────────────

class TestGenerateCorrection:
    def _diag(self, root_cause="syntax", suggested_fix=""):
        return Diagnosis(
            root_cause=root_cause,
            confidence=0.7,
            evidence=[],
            suggested_fix=suggested_fix,
        )

    def test_syntax_produces_regenerate_query(self):
        loop = _make_loop()
        strategy = loop.generate_correction(self._diag("syntax"), "SELECT * FORM t")
        assert strategy.strategy_type == "regenerate_query"

    def test_join_key_mismatch_produces_transform_join_key(self):
        loop = _make_loop()
        strategy = loop.generate_correction(
            self._diag("join_key_mismatch"), "SELECT * FROM a JOIN b ON a.id = b.id"
        )
        assert strategy.strategy_type == "transform_join_key"

    def test_wrong_db_produces_reroute(self):
        loop = _make_loop()
        strategy = loop.generate_correction(self._diag("wrong_db_type"), "SELECT 1")
        assert strategy.strategy_type == "reroute_database"

    def test_data_quality_produces_quality_rules(self):
        loop = _make_loop()
        strategy = loop.generate_correction(self._diag("data_quality"), "SELECT * FROM t")
        assert strategy.strategy_type == "apply_quality_rules"

    def test_extraction_failure_produces_alternative_extraction(self):
        loop = _make_loop()
        strategy = loop.generate_correction(
            self._diag("extraction_failure"), "db.reviews.find({})"
        )
        assert strategy.strategy_type == "alternative_extraction"
        assert strategy.extraction_method is not None

    def test_unknown_type_defaults_to_regenerate(self):
        loop = _make_loop()
        strategy = loop.generate_correction(
            self._diag("totally_unknown_type"), "SELECT 1"
        )
        assert strategy.strategy_type == "regenerate_query"

    def test_join_key_mismatch_builds_format_transform_when_evidence_present(self):
        loop = _make_loop()
        diag = Diagnosis(
            root_cause="join_key_mismatch",
            confidence=0.85,
            evidence=["INT in PostgreSQL, string in MongoDB — cast Mongo value to int"],
            suggested_fix="Cast to int",
        )
        strategy = loop.generate_correction(diag, "SELECT * FROM t")
        assert strategy.strategy_type == "transform_join_key"
        assert len(strategy.format_transformations) == 1
        ft = strategy.format_transformations[0]
        assert ft.transformation_function == "int(value)"

    def test_strategy_has_rationale(self):
        loop = _make_loop()
        strategy = loop.generate_correction(self._diag("syntax"), "SELECT 1")
        assert isinstance(strategy.rationale, str)
        assert len(strategy.rationale) > 0


# ── 8.4  Retry logic ─────────────────────────────────────────────────────────

class TestExecuteWithCorrection:
    def test_success_first_try(self):
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]
        loop = _make_loop(engine=engine)

        result = loop.execute_with_correction(_make_plan(), "test question")

        assert result["success"] is True
        assert result["retries_used"] == 0
        assert result["correction_applied"] is False
        engine.execute_plan.assert_called_once()

    def test_retries_on_failure_and_succeeds(self):
        engine = MagicMock()
        engine.execute_plan.side_effect = [
            [_make_result(success=False, error="syntax error near FROM")],
            [_make_result(success=False, error="syntax error near FROM")],
            [_make_result(success=True)],
        ]
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(text="SELECT id FROM orders")
        ]
        loop = _make_loop(engine=engine, client=client)

        result = loop.execute_with_correction(_make_plan(), "test question")

        assert result["success"] is True
        assert result["retries_used"] == 2
        assert result["correction_applied"] is True

    def test_exhausts_retries_returns_failure(self):
        engine = MagicMock()
        engine.execute_plan.return_value = [
            _make_result(success=False, error="persistent syntax error")
        ]
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(text="SELECT id FROM orders")
        ]
        loop = _make_loop(engine=engine, client=client)

        result = loop.execute_with_correction(_make_plan(), "test question")

        assert result["success"] is False
        assert engine.execute_plan.call_count == MAX_RETRIES

    def test_correction_is_logged_on_failure(self):
        engine = MagicMock()
        engine.execute_plan.return_value = [
            _make_result(success=False, error="syntax error: no such column")
        ]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(text="SELECT id FROM orders")
        ]
        loop = SelfCorrectionLoop(engine, ctx, client=client)

        loop.execute_with_correction(_make_plan(), "what are orders?")

        ctx.log_correction.assert_called()

    def test_correction_logged_with_correct_database(self):
        engine = MagicMock()
        # Use a syntax error so the strategy produces a corrected query and logs it
        engine.execute_plan.return_value = [
            _make_result(success=False, database="mongodb", error="syntax error near '{'")
        ]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(text="db.orders.find({})")
        ]
        plan = _make_plan([
            SubQuery(database="mongodb", query="db.orders.find({)", query_type="mongo")
        ])
        loop = SelfCorrectionLoop(engine, ctx, client=client)
        loop.execute_with_correction(plan, "find all orders")

        ctx.log_correction.assert_called()
        call_kwargs = ctx.log_correction.call_args
        # database kwarg must match the failing sub-query
        assert call_kwargs.kwargs.get("database") == "mongodb" or (
            call_kwargs.args and "mongodb" in str(call_kwargs.args)
        )

    def test_no_retry_on_immediate_success(self):
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        loop = SelfCorrectionLoop(engine, ctx, client=MagicMock())

        loop.execute_with_correction(_make_plan(), "q")

        assert engine.execute_plan.call_count == 1


# ── Proactive Layer 3 correction (self-learning loop) ─────────────────────────

class TestProactiveCorrections:
    def test_proactive_correction_applied_when_similar_exists(self):
        """
        When Layer 3 has a matching correction, the plan is rewritten BEFORE
        the first execution attempt and correction_applied is set True.
        """
        past = CorrectionEntry(
            query="SELECT * FROM orders WHERE customer_id = 1",
            failure_cause="syntax: missing alias",
            correction="SELECT * FROM orders o WHERE o.customer_id = 1",
            timestamp=datetime.utcnow(),
            database="postgres",
        )
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]

        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = [past]
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[past]
        )

        # LLM returns a corrected query different from the original
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(
                text="SELECT * FROM orders o WHERE o.customer_id = 1"
            )
        ]

        plan = _make_plan([
            SubQuery(
                database="postgres",
                query="SELECT * FROM orders WHERE customer_id = 1",
                query_type="sql",
            )
        ])
        loop = SelfCorrectionLoop(engine, ctx, client=client)
        result = loop.execute_with_correction(plan, "find orders for customer 1")

        assert result["correction_applied"] is True
        assert result["success"] is True

    def test_no_proactive_correction_when_no_similar_exists(self):
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        loop = SelfCorrectionLoop(engine, ctx, client=MagicMock())

        result = loop.execute_with_correction(_make_plan(), "test")

        assert result["correction_applied"] is False

    def test_proactive_correction_not_applied_when_llm_returns_same_query(self):
        """If the LLM returns the exact same query, no correction is recorded."""
        past = CorrectionEntry(
            query="SELECT 1",
            failure_cause="syntax",
            correction="SELECT 1",
            timestamp=datetime.utcnow(),
            database="postgres",
        )
        engine = MagicMock()
        engine.execute_plan.return_value = [_make_result(success=True)]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = [past]
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[past]
        )
        client = MagicMock()
        # LLM returns the same text as the original query
        client.messages.create.return_value.content = [MagicMock(text="SELECT 1")]

        loop = SelfCorrectionLoop(engine, ctx, client=client)
        result = loop.execute_with_correction(_make_plan(), "test")

        assert result["correction_applied"] is False


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_max_retries_constant_is_three(self):
        assert MAX_RETRIES == 3

    def test_multiple_failing_subqueries_both_corrected(self):
        """When two sub-queries fail, both should be corrected and logged."""
        engine = MagicMock()
        engine.execute_plan.side_effect = [
            [
                _make_result(success=False, database="postgres", error="syntax error"),
                # Use syntax error for mongodb too so the LLM path runs and logs
                _make_result(success=False, database="mongodb", error="syntax error near '{'"),
            ],
            [
                _make_result(success=True, database="postgres"),
                _make_result(success=True, database="mongodb"),
            ],
        ]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        client = MagicMock()
        client.messages.create.return_value.content = [
            MagicMock(text="SELECT id FROM t")
        ]
        plan = _make_plan([
            SubQuery(database="postgres", query="SELECT * FORM t", query_type="sql"),
            SubQuery(database="mongodb", query="db.find({})", query_type="mongo"),
        ])
        loop = SelfCorrectionLoop(engine, ctx, client=client)
        result = loop.execute_with_correction(plan, "q")

        assert result["success"] is True
        assert ctx.log_correction.call_count >= 2

    def test_llm_failure_during_correction_does_not_crash(self):
        """If the LLM throws during correction, the loop should not crash."""
        engine = MagicMock()
        engine.execute_plan.return_value = [
            _make_result(success=False, error="syntax error")
        ]
        ctx = MagicMock()
        ctx.get_similar_corrections.return_value = []
        ctx.get_bundle.return_value = ContextBundle(
            schema={}, institutional_knowledge=[], corrections=[]
        )
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API timeout")

        loop = SelfCorrectionLoop(engine, ctx, client=client)
        result = loop.execute_with_correction(_make_plan(), "q")

        # Should not raise; returns failure after exhausting retries
        assert result["success"] is False

    def test_empty_error_message_classified_as_syntax(self):
        loop = _make_loop()
        info = loop.detect_failure(_make_result(success=False, error=""))
        assert info is not None
        assert info.failure_type == "syntax"

    def test_classify_error_all_five_types(self):
        """Direct test of _classify_error for completeness."""
        loop = _make_loop()
        cases = [
            ("syntax error near FROM", "syntax"),
            ("operator does not exist: integer = text", "join_key_mismatch"),
            ("unsupported operation for this database", "wrong_db_type"),
            ("null constraint violated", "data_quality"),
            ("extraction failed: invalid json", "extraction_failure"),
        ]
        for error_msg, expected_type in cases:
            assert loop._classify_error(error_msg) == expected_type, (
                f"Expected '{expected_type}' for error: {error_msg!r}"
            )
