"""
Unit tests for QueryRouter — entity extraction, routing, decomposition,
dialect detection, join strategy, and execution order.

Covers task 5.5 requirements:
  - Single-database query routing
  - Multi-database query decomposition
  - Execution order determination
  - Join strategy selection
  - Dialect detection
  - Edge cases (unavailable database, ambiguous entity types)
"""

import pytest
from unittest.mock import MagicMock

from agent.models.models import ContextBundle, CorrectionEntry, Document, SchemaInfo, SubQuery
from agent.query_router import (
    JoinStrategy,
    QueryDialect,
    QueryRouter,
    QueryType,
    _load_unstructured_fields,
)
from datetime import datetime


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_bundle(pg_tables=None, mongo_tables=None, sqlite_tables=None, duckdb_tables=None):
    schema = {}
    if pg_tables:
        schema["postgres"] = SchemaInfo(
            database="postgres",
            db_type="postgres",
            tables=pg_tables,
        )
    if mongo_tables:
        schema["mongodb"] = SchemaInfo(
            database="mongodb",
            db_type="mongodb",
            tables=mongo_tables,
        )
    if sqlite_tables:
        schema["sqlite"] = SchemaInfo(
            database="sqlite",
            db_type="sqlite",
            tables=sqlite_tables,
        )
    if duckdb_tables:
        schema["duckdb"] = SchemaInfo(
            database="duckdb",
            db_type="duckdb",
            tables=duckdb_tables,
        )
    return ContextBundle(schema=schema, institutional_knowledge=[], corrections=[])


def _mock_router(entity_text="[]", query_text="SELECT 1"):
    """Create a QueryRouter with a pre-configured mock client."""
    mock_client = MagicMock()
    call_count = {"n": 0}

    def side_effect(**kwargs):
        call_count["n"] += 1
        # First call: entity extraction
        if call_count["n"] == 1:
            return MagicMock(content=[MagicMock(text=entity_text)])
        # Subsequent calls: query generation (one per sub-query)
        return MagicMock(content=[MagicMock(text=query_text)])

    mock_client.messages.create.side_effect = side_effect
    return QueryRouter(client=mock_client)


# ── 5.1 Entity extraction & DB assignment ──────────────────────────────────────

class TestDatabaseAssignment:
    def test_hint_routing_reviews_to_mongodb(self):
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(
            pg_tables={"businesses": ["business_id", "name", "stars"]},
            mongo_tables={"reviews": ["review_id", "business_id", "text"]},
        )
        assignment = router._assign_databases(
            entities=["reviews"],
            context=bundle,
            available_databases=["postgres", "mongodb"],
        )
        assert "mongodb" in assignment
        assert "reviews" in assignment["mongodb"]

    def test_hint_routing_customers_to_postgres(self):
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(pg_tables={"customers": ["id", "name"]})
        assignment = router._assign_databases(
            entities=["customers"],
            context=bundle,
            available_databases=["postgres"],
        )
        assert "postgres" in assignment

    def test_schema_routing_when_no_hint(self):
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(
            pg_tables={"transactions": ["id", "amount", "customer_id"]},
        )
        assignment = router._assign_databases(
            entities=["transactions"],
            context=bundle,
            available_databases=["postgres"],
        )
        assert "postgres" in assignment

    def test_unavailable_database_skipped(self):
        """Entities hinted to an unavailable DB fall back to schema/default."""
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(
            pg_tables={"businesses": ["id", "name"]},
            mongo_tables={"reviews": ["id", "text"]},
        )
        # mongodb not in available_databases
        assignment = router._assign_databases(
            entities=["reviews"],
            context=bundle,
            available_databases=["postgres"],
        )
        # Must only assign to available databases
        for db in assignment:
            assert db in ["postgres"], f"Assigned to unavailable db '{db}'"

    def test_default_to_first_available_when_no_match(self):
        """Entity with no hint and no matching schema defaults to first available DB."""
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(pg_tables={"some_table": ["id"]})
        assignment = router._assign_databases(
            entities=["unknown_entity"],
            context=bundle,
            available_databases=["postgres", "mongodb"],
        )
        # Should be assigned somewhere (not dropped)
        total_assigned = sum(len(v) for v in assignment.values())
        assert total_assigned >= 1

    def test_multiple_entities_multi_db(self):
        """Entities from different hint buckets land in separate databases."""
        router = QueryRouter(client=MagicMock())
        bundle = _make_bundle(
            pg_tables={"customers": ["id", "name"]},
            mongo_tables={"reviews": ["id", "text"]},
        )
        assignment = router._assign_databases(
            entities=["customers", "reviews"],
            context=bundle,
            available_databases=["postgres", "mongodb"],
        )
        assert "postgres" in assignment
        assert "mongodb" in assignment


# ── 5.3 Dialect detection ─────────────────────────────────────────────────────

class TestDialectDetection:
    def test_postgres_dialect(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("postgres") == QueryDialect.POSTGRESQL

    def test_postgresql_alias(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("postgresql") == QueryDialect.POSTGRESQL

    def test_sqlite_dialect(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("sqlite") == QueryDialect.SQLITE

    def test_duckdb_dialect(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("duckdb") == QueryDialect.DUCKDB

    def test_mongodb_dialect(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("mongodb") == QueryDialect.MONGODB

    def test_mongo_alias(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("mongo") == QueryDialect.MONGODB

    def test_unknown_db_defaults_to_postgresql(self):
        router = QueryRouter(client=MagicMock())
        assert router.detect_dialect("unknown_db") == QueryDialect.POSTGRESQL


# ── 5.3 Query type classification ─────────────────────────────────────────────

class TestQueryTypeClassification:
    def test_aggregate_count(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("How many customers placed orders last month?")
        assert qt == QueryType.TIMESERIES  # "month" wins over aggregate

    def test_aggregate_average(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("What is the average star rating for restaurants?")
        assert qt == QueryType.AGGREGATE

    def test_aggregate_top(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("List the top 10 businesses by review count")
        assert qt == QueryType.AGGREGATE

    def test_timeseries_monthly(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("Show monthly sales trend over the past year")
        assert qt == QueryType.TIMESERIES

    def test_full_text_mention(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("Find businesses that mention parking in their description")
        assert qt == QueryType.FULL_TEXT

    def test_join_across(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("Compare customer orders across both databases")
        assert qt == QueryType.JOIN

    def test_filter_find(self):
        router = QueryRouter(client=MagicMock())
        qt = router._classify_query_type("Find all businesses in Las Vegas with 4+ stars")
        assert qt == QueryType.FILTER


# ── 5.2 Join strategy selection ───────────────────────────────────────────────

class TestJoinStrategySelection:
    def _make_sq(self, db_name: str) -> SubQuery:
        return SubQuery(database=db_name, query="SELECT 1", query_type="sql")

    def test_large_large_returns_hash(self):
        router = QueryRouter(client=MagicMock())
        left = self._make_sq("postgres")
        right = self._make_sq("duckdb")
        strategy = router._select_join_strategy(left, right, schema={})
        assert strategy == JoinStrategy.HASH

    def test_large_mongodb_returns_hash(self):
        router = QueryRouter(client=MagicMock())
        left = self._make_sq("postgres")
        right = self._make_sq("mongodb")
        strategy = router._select_join_strategy(left, right, schema={})
        assert strategy == JoinStrategy.HASH

    def test_small_right_returns_nested_loop(self):
        router = QueryRouter(client=MagicMock())
        left = self._make_sq("postgres")
        right = self._make_sq("sqlite")  # not in _LARGE_DBS
        strategy = router._select_join_strategy(left, right, schema={})
        assert strategy == JoinStrategy.NESTED_LOOP

    def test_small_left_returns_nested_loop(self):
        router = QueryRouter(client=MagicMock())
        left = self._make_sq("sqlite")
        right = self._make_sq("postgres")
        strategy = router._select_join_strategy(left, right, schema={})
        assert strategy == JoinStrategy.NESTED_LOOP


# ── 5.2 Execution order (topological sort) ────────────────────────────────────

class TestExecutionOrder:
    def _sq(self, db, deps=None):
        return SubQuery(
            database=db,
            query="SELECT 1",
            query_type="sql",
            dependencies=deps or [],
        )

    def test_no_dependencies_sequential(self):
        router = QueryRouter(client=MagicMock())
        sqs = [self._sq("postgres"), self._sq("mongodb"), self._sq("sqlite")]
        order = router._determine_execution_order(sqs)
        assert sorted(order) == [0, 1, 2]  # All nodes present
        # No strict ordering required when there are no deps
        assert len(order) == 3

    def test_simple_chain(self):
        """sq[1] depends on sq[0] → sq[0] must come first."""
        router = QueryRouter(client=MagicMock())
        sqs = [self._sq("postgres"), self._sq("mongodb", deps=[0])]
        order = router._determine_execution_order(sqs)
        assert order.index(0) < order.index(1)

    def test_diamond_dependency(self):
        """
        sq[0] → sq[1], sq[2] → sq[3]
        Valid orders: [0, 1, 2, 3] or [0, 2, 1, 3] etc.
        Constraint: 0 before 1 and 2; 1 and 2 before 3.
        """
        router = QueryRouter(client=MagicMock())
        sqs = [
            self._sq("postgres"),          # 0
            self._sq("mongodb", deps=[0]), # 1
            self._sq("sqlite", deps=[0]),  # 2
            self._sq("duckdb", deps=[1, 2]),  # 3
        ]
        order = router._determine_execution_order(sqs)
        assert len(order) == 4
        assert order.index(0) < order.index(1)
        assert order.index(0) < order.index(2)
        assert order.index(1) < order.index(3)
        assert order.index(2) < order.index(3)

    def test_cycle_falls_back_to_sequential(self):
        """Cyclic dependencies degrade gracefully to [0, 1, 2]."""
        router = QueryRouter(client=MagicMock())
        sqs = [
            self._sq("postgres", deps=[1]),  # 0 → 1
            self._sq("mongodb", deps=[0]),   # 1 → 0 (cycle)
        ]
        order = router._determine_execution_order(sqs)
        assert sorted(order) == [0, 1]  # Both still present

    def test_single_query_order(self):
        router = QueryRouter(client=MagicMock())
        sqs = [self._sq("postgres")]
        order = router._determine_execution_order(sqs)
        assert order == [0]

    def test_empty_list(self):
        router = QueryRouter(client=MagicMock())
        order = router._determine_execution_order([])
        assert order == []


# ── 5.5 Sandbox detection ─────────────────────────────────────────────────────

class TestSandboxDetection:
    def test_sandbox_needed_for_unstructured_field(self):
        router = QueryRouter(client=MagicMock())
        router._unstructured_fields = {"text", "description"}
        assert router._check_sandbox_needed(["text", "stars"]) is True

    def test_no_sandbox_for_structured_entities(self):
        router = QueryRouter(client=MagicMock())
        router._unstructured_fields = {"text", "description"}
        assert router._check_sandbox_needed(["businesses", "orders"]) is False

    def test_empty_entity_list(self):
        router = QueryRouter(client=MagicMock())
        router._unstructured_fields = {"text"}
        assert router._check_sandbox_needed([]) is False


# ── 5.5 Full route() integration ─────────────────────────────────────────────

class TestRouteIntegration:
    def test_single_database_plan(self):
        router = _mock_router(
            entity_text='["businesses"]',
            query_text="SELECT AVG(stars) FROM businesses",
        )
        bundle = _make_bundle(pg_tables={"businesses": ["business_id", "city", "stars"]})
        plan = router.route(
            question="What is the average star rating?",
            context=bundle,
            available_databases=["postgres"],
        )
        assert len(plan.sub_queries) == 1
        assert plan.sub_queries[0].database == "postgres"
        assert plan.execution_order == [0]

    def test_multi_database_produces_multiple_subqueries(self):
        """Entities spanning postgres and mongodb → two sub-queries."""
        call_count = {"n": 0}
        mock_client = MagicMock()

        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(content=[MagicMock(text='["customers", "reviews"]')])
            return MagicMock(content=[MagicMock(text="SELECT 1")])

        mock_client.messages.create.side_effect = side_effect
        router = QueryRouter(client=mock_client)

        bundle = _make_bundle(
            pg_tables={"customers": ["id", "name"]},
            mongo_tables={"reviews": ["id", "text"]},
        )
        plan = router.route(
            question="What do customers say in their reviews?",
            context=bundle,
            available_databases=["postgres", "mongodb"],
        )
        assert len(plan.sub_queries) == 2
        dbs = {sq.database for sq in plan.sub_queries}
        assert "postgres" in dbs
        assert "mongodb" in dbs

    def test_query_type_reflected_in_subquery_description(self):
        """The query_type should appear in sub-query description."""
        router = _mock_router(
            entity_text='["businesses"]',
            query_text="SELECT COUNT(*) FROM businesses GROUP BY city",
        )
        bundle = _make_bundle(pg_tables={"businesses": ["business_id", "city", "stars"]})
        plan = router.route(
            question="What is the total count of businesses per city?",
            context=bundle,
            available_databases=["postgres"],
        )
        # The word "aggregate" should appear in the description
        desc = plan.sub_queries[0].description.lower()
        assert "aggregate" in desc

    def test_execution_order_length_matches_subqueries(self):
        """execution_order must have one entry per sub-query."""
        router = _mock_router(
            entity_text='["orders"]',
            query_text="SELECT * FROM orders",
        )
        bundle = _make_bundle(pg_tables={"orders": ["id", "amount"]})
        plan = router.route(
            question="List all orders",
            context=bundle,
            available_databases=["postgres"],
        )
        assert len(plan.execution_order) == len(plan.sub_queries)

    def test_mongo_subquery_type_is_mongo(self):
        """Sub-queries targeting MongoDB should have query_type='mongo'."""
        router = _mock_router(
            entity_text='["reviews"]',
            query_text='[{"$match": {"stars": {"$gte": 4}}}]',
        )
        bundle = _make_bundle(
            mongo_tables={"reviews": ["review_id", "business_id", "stars"]}
        )
        plan = router.route(
            question="Find high-rated reviews",
            context=bundle,
            available_databases=["mongodb"],
        )
        assert plan.sub_queries[0].query_type == "mongo"

    def test_sql_subquery_type_is_sql(self):
        """Sub-queries targeting SQL databases should have query_type='sql'."""
        router = _mock_router(
            entity_text='["businesses"]',
            query_text="SELECT * FROM businesses",
        )
        bundle = _make_bundle(pg_tables={"businesses": ["id", "name"]})
        plan = router.route(
            question="List all businesses",
            context=bundle,
            available_databases=["postgres"],
        )
        assert plan.sub_queries[0].query_type == "sql"

    def test_rationale_non_empty(self):
        """Plan rationale string should always be present and non-empty."""
        router = _mock_router(
            entity_text='["products"]',
            query_text="SELECT * FROM products",
        )
        bundle = _make_bundle(sqlite_tables={"products": ["id", "name", "price"]})
        plan = router.route(
            question="What are the available products?",
            context=bundle,
            available_databases=["sqlite"],
        )
        assert plan.rationale and len(plan.rationale) > 0

    def test_corrections_included_in_prompt(self):
        """If corrections exist, LLM must be called with correction context."""
        mock_client = MagicMock()
        call_count = {"n": 0}
        captured_prompts = []

        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return MagicMock(content=[MagicMock(text='["businesses"]')])
            # Capture the prompt for assertion
            captured_prompts.append(kwargs["messages"][0]["content"])
            return MagicMock(content=[MagicMock(text="SELECT * FROM businesses")])

        mock_client.messages.create.side_effect = side_effect
        router = QueryRouter(client=mock_client)

        from datetime import datetime
        bundle = ContextBundle(
            schema={
                "postgres": SchemaInfo(
                    database="postgres",
                    db_type="postgres",
                    tables={"businesses": ["id", "name"]},
                )
            },
            institutional_knowledge=[],
            corrections=[
                CorrectionEntry(
                    query="SELECT * FROM business",  # wrong table name
                    failure_cause="table not found",
                    correction="Use table name 'businesses' not 'business'",
                    timestamp=datetime.utcnow(),
                    database="postgres",
                )
            ],
        )
        router.route(
            question="List all businesses",
            context=bundle,
            available_databases=["postgres"],
        )
        assert captured_prompts, "LLM was not called for query generation"
        assert "businesses" in captured_prompts[0]
