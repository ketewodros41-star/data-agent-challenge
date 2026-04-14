"""
Property-based tests for QueryRouter.

Task 5.4 — validates:
  Property 1: Query Routing Correctness    (Requirements 1.1)
  Property 2: Multi-Database Query Decomposition  (Requirements 1.2)

Uses Hypothesis to generate adversarial inputs and verify invariants hold
across all inputs, not just hand-crafted examples.

LLM calls are always mocked so tests run fast and deterministically.
"""

from __future__ import annotations

import json
from typing import Dict, List, Set
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from agent.models.models import ContextBundle, Document, SchemaInfo, SubQuery
from agent.query_router import QueryDialect, QueryRouter, QueryType


# ── Hypothesis strategies ──────────────────────────────────────────────────────

# Realistic database names used in the DAB benchmark
_DB_NAMES = ["postgres", "mongodb", "sqlite", "duckdb"]

# Entity types across DAB domains
_ENTITY_TYPES = [
    "customers", "orders", "transactions", "reviews", "comments",
    "businesses", "products", "categories", "users", "payments",
]

# Natural-language question templates
_QUESTION_TEMPLATES = [
    "How many {entity} are there?",
    "What is the average {metric} for {entity}?",
    "List all {entity} with {condition}",
    "Find {entity} that mention {keyword}",
    "Show monthly trend of {entity} over time",
    "Compare {entity} across different regions",
    "Which {entity} have the highest ratings?",
]

db_name_strategy = st.sampled_from(_DB_NAMES)
entity_strategy = st.sampled_from(_ENTITY_TYPES)

available_dbs_strategy = st.lists(
    db_name_strategy,
    min_size=1,
    max_size=4,
    unique=True,
)

table_names_strategy = st.lists(
    entity_strategy,
    min_size=1,
    max_size=5,
    unique=True,
)

column_names_strategy = st.lists(
    st.sampled_from(["id", "name", "value", "status", "created_at", "text", "stars"]),
    min_size=1,
    max_size=6,
    unique=True,
)

question_strategy = st.sampled_from([
    "How many customers placed orders last month?",
    "What is the average star rating for businesses?",
    "Find reviews mentioning parking",
    "List all products in the electronics category",
    "Show total transactions per user",
    "Which businesses have the most reviews?",
])


def _make_schema_for_dbs(db_names: List[str], tables_per_db: Dict[str, List[str]]) -> Dict[str, SchemaInfo]:
    schema = {}
    for db in db_names:
        tables = tables_per_db.get(db, ["default_table"])
        schema[db] = SchemaInfo(
            database=db,
            db_type=db,
            tables={t: ["id", "name"] for t in tables},
        )
    return schema


def _mock_router_with_entities(entities: List[str]) -> QueryRouter:
    """Build a router whose entity-extraction LLM call returns the given entities."""
    mock_client = MagicMock()
    call_count = {"n": 0}

    def side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Entity extraction call
            return MagicMock(content=[MagicMock(text=json.dumps(entities))])
        # Query generation call(s) — return a simple SQL stub
        return MagicMock(content=[MagicMock(text="SELECT 1")])

    mock_client.messages.create.side_effect = side_effect
    return QueryRouter(client=mock_client)


# ── Property 1: Query Routing Correctness (Requirement 1.1) ──────────────────
#
# Invariant: for any valid question and available_databases, every sub-query in
# the produced QueryPlan is assigned to a database that appears in
# available_databases.  The router must NEVER route to a database that was not
# listed as available.

@given(
    question=question_strategy,
    available_dbs=available_dbs_strategy,
    entities=st.lists(entity_strategy, min_size=1, max_size=4, unique=True),
)
@settings(
    max_examples=80,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_property1_routing_stays_within_available_databases(
    question: str,
    available_dbs: List[str],
    entities: List[str],
):
    """
    Property 1 — Query Routing Correctness.

    For any question and any subset of available databases, every sub-query
    produced by route() must target a database that is listed in
    available_databases.
    """
    router = _mock_router_with_entities(entities)
    schema = _make_schema_for_dbs(available_dbs, {})
    bundle = ContextBundle(
        schema=schema,
        institutional_knowledge=[],
        corrections=[],
    )

    plan = router.route(question=question, context=bundle, available_databases=available_dbs)

    for sq in plan.sub_queries:
        assert sq.database in available_dbs, (
            f"Sub-query assigned to '{sq.database}' but available_databases={available_dbs}"
        )


# ── Property 2: Multi-Database Query Decomposition (Requirement 1.2) ─────────
#
# Invariant: when the entity list contains entities from at least two different
# databases (as determined by the hint map), the plan must produce at least two
# sub-queries targeting distinct databases.

_HINT_PAIRS = [
    (["reviews"], ["mongodb"]),          # review → mongodb
    (["customers"], ["postgres"]),       # customer → postgres
    (["products"], ["sqlite"]),          # product → sqlite
    (["orders"], ["postgres"]),          # order → postgres
]

@given(
    left_entities=st.sampled_from([p[0] for p in _HINT_PAIRS]),
    right_entities=st.sampled_from([p[0] for p in _HINT_PAIRS]),
)
@settings(
    max_examples=40,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_property2_multi_db_decomposition(
    left_entities: List[str],
    right_entities: List[str],
):
    """
    Property 2 — Multi-Database Query Decomposition.

    When entities span at least two distinct databases (determined by the hint
    map), the produced QueryPlan must contain at least two sub-queries from
    different databases.
    """
    from agent.query_router import _ENTITY_DB_HINTS

    combined_entities = left_entities + right_entities
    expected_dbs: Set[str] = {
        _ENTITY_DB_HINTS[e] for e in combined_entities if e in _ENTITY_DB_HINTS
    }

    # Only meaningful if entities map to 2+ distinct databases
    assume(len(expected_dbs) >= 2)

    router = _mock_router_with_entities(combined_entities)
    schema = _make_schema_for_dbs(list(expected_dbs), {})
    bundle = ContextBundle(
        schema=schema,
        institutional_knowledge=[],
        corrections=[],
    )

    plan = router.route(
        question="Show me data spanning multiple databases",
        context=bundle,
        available_databases=list(expected_dbs),
    )

    unique_dbs = {sq.database for sq in plan.sub_queries}
    assert len(unique_dbs) >= 2, (
        f"Expected sub-queries targeting ≥2 databases, got: {unique_dbs} "
        f"(entities={combined_entities}, expected_dbs={expected_dbs})"
    )


# ── Property: Execution order is a valid permutation ─────────────────────────
#
# Invariant: execution_order contains exactly the indices [0..n-1] with no
# duplicates, regardless of how many sub-queries the plan has.

@given(
    n_queries=st.integers(min_value=1, max_value=6),
)
@settings(max_examples=50, deadline=None)
def test_property_execution_order_is_valid_permutation(n_queries: int):
    """
    For any plan with n sub-queries, execution_order must be a permutation of
    [0, 1, …, n-1] — every index appears exactly once.
    """
    router = QueryRouter(client=MagicMock())
    sub_queries = [
        SubQuery(database="postgres", query="SELECT 1", query_type="sql")
        for _ in range(n_queries)
    ]
    order = router._determine_execution_order(sub_queries)

    assert sorted(order) == list(range(n_queries)), (
        f"execution_order {order} is not a permutation of 0..{n_queries - 1}"
    )
    assert len(set(order)) == n_queries, "execution_order contains duplicates"


# ── Property: Topological order respects declared dependencies ────────────────

@given(
    n=st.integers(min_value=2, max_value=6),
    dep_pairs=st.lists(
        st.tuples(st.integers(min_value=0, max_value=5), st.integers(min_value=0, max_value=5)),
        min_size=1,
        max_size=6,
    ),
)
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_property_topological_order_respects_dependencies(n: int, dep_pairs):
    """
    For any acyclic dependency graph, every dependency must appear before the
    sub-query that depends on it in execution_order.
    """
    # Build a DAG: only keep edges i → j where i < j (ensures acyclicity)
    acyclic_pairs = [(i % n, j % n) for i, j in dep_pairs if (i % n) < (j % n)]

    from collections import defaultdict
    dep_map = defaultdict(list)
    for dep, target in acyclic_pairs:
        dep_map[target].append(dep)

    router = QueryRouter(client=MagicMock())
    sub_queries = [
        SubQuery(
            database="postgres",
            query="SELECT 1",
            query_type="sql",
            dependencies=dep_map[i],
        )
        for i in range(n)
    ]

    order = router._determine_execution_order(sub_queries)

    # Verify all declared dependencies appear before their dependents
    pos = {idx: rank for rank, idx in enumerate(order)}
    for i, sq in enumerate(sub_queries):
        for dep in sq.dependencies:
            if 0 <= dep < n:
                assert pos[dep] < pos[i], (
                    f"Dependency violation: sq[{dep}] must run before sq[{i}], "
                    f"but order was {order}"
                )


# ── Property: dialect_templates cover all QueryType values ───────────────────

@given(
    db_name=st.sampled_from(["postgres", "mongodb", "sqlite", "duckdb"]),
    query_type=st.sampled_from(list(QueryType)),
)
@settings(max_examples=24, deadline=None)
def test_property_dialect_hint_always_returns_string(db_name: str, query_type: QueryType):
    """
    _get_dialect_hint must return a string (possibly empty) for any
    valid db_name × query_type combination — never raise an exception.
    """
    router = QueryRouter(client=MagicMock())
    result = router._get_dialect_hint(db_name, query_type)
    assert isinstance(result, str)


# ── Property: classify_query_type always returns a valid QueryType ────────────

@given(question=st.text(min_size=1, max_size=200))
@settings(max_examples=100, deadline=None)
def test_property_classify_query_type_always_valid(question: str):
    """
    _classify_query_type must always return a member of QueryType and never raise,
    regardless of question content.
    """
    router = QueryRouter(client=MagicMock())
    result = router._classify_query_type(question)
    assert isinstance(result, QueryType)
    assert result in list(QueryType)
