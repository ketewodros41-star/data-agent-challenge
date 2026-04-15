from types import SimpleNamespace

from agent.execution_engine import ExecutionEngine
from agent.models.models import (
    FormatTransform,
    JoinOp,
    QueryPlan,
    QueryResult,
    SubQuery,
)


class StubToolbox:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call_tool(self, tool_name, params):
        self.calls.append((tool_name, params))
        response = self.responses.pop(0)
        if callable(response):
            response = response(tool_name, params)
        return response


def make_result(success=True, data=None, error=None, execution_time=0.01):
    return SimpleNamespace(
        success=success,
        data=[] if data is None else data,
        error=error,
        execution_time=execution_time,
    )


def test_build_tool_call_routes_sqlite_and_mongodb():
    engine = ExecutionEngine(toolbox=StubToolbox([]))

    # SubQuery field order: database, query, query_type
    sqlite_tool, sqlite_params = engine._build_tool_call(
        SubQuery(database="local", query="select 1", query_type="sqlite")
    )
    mongo_tool, mongo_params = engine._build_tool_call(
        SubQuery(database="mongo", query="db.checkin.aggregate([])", query_type="mongodb")
    )

    assert sqlite_tool == "sqlite_query"
    assert sqlite_params == {"sql": "select 1"}
    assert mongo_tool == "find_yelp_checkins"
    assert mongo_params["limit"] == 20


def test_build_tool_call_uses_sqlite_mcp_tool_override():
    engine = ExecutionEngine(
        toolbox=StubToolbox([]),
        db_configs={
            "bookreview_sqlite": {
                "type": "sqlite",
                "mcp_tool": "sqlite_bookreview_query",
            }
        },
    )

    sqlite_tool, sqlite_params = engine._build_tool_call(
        SubQuery(database="bookreview_sqlite", query="select 1", query_type="sqlite")
    )

    assert sqlite_tool == "sqlite_bookreview_query"
    assert sqlite_params == {"sql": "select 1"}


def test_build_tool_call_uses_duckdb_mcp_tool_override():
    engine = ExecutionEngine(
        toolbox=StubToolbox([]),
        db_configs={
            "stockmarket_duckdb": {
                "type": "duckdb",
                "mcp_tool": "duckdb_stockmarket_query",
            }
        },
    )

    duckdb_tool, duckdb_params = engine._build_tool_call(
        SubQuery(database="stockmarket_duckdb", query="select 1", query_type="duckdb")
    )

    assert duckdb_tool == "duckdb_stockmarket_query"
    assert duckdb_params == {"sql": "select 1"}


def test_join_datasets_applies_format_transformation():
    """_join_datasets transforms right-side join keys via FormatTransform before matching."""
    engine = ExecutionEngine(toolbox=StubToolbox([]))
    transform = FormatTransform(
        source_format="integer",
        target_format="CUST-{}",
        transformation_function="prefix customer ids",
    )

    merged = engine._join_datasets(
        left=[{"customer_id": "CUST-7", "amount": 10}],
        right=[{"customer_ref": 7, "name": "Ada"}],
        key_left="customer_id",
        key_right="customer_ref",
        transform=transform,
    )

    assert merged == [{"customer_id": "CUST-7", "amount": 10, "customer_ref": "CUST-7", "name": "Ada"}]


def test_validate_result_rejects_duplicates():
    engine = ExecutionEngine(toolbox=StubToolbox([]))

    validation = engine.validate_result([{"id": 1}, {"id": 1}], {})

    assert validation["valid"] is False
    assert "Duplicate rows detected" in validation["issues"]


def test_execute_plan_returns_failure_result_on_tool_error():
    """A failed tool call propagates as a QueryResult with success=False."""
    toolbox = StubToolbox(
        [
            make_result(success=False, error="syntax error near FROM"),
        ]
    )
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[SubQuery(database="catalog", query="select * from books", query_type="postgres")],
        execution_order=[0],
        join_operations=[],
    )

    results = engine.execute_plan(plan, {})

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error == "syntax error near FROM"


def test_execute_plan_returns_success_result():
    """A successful tool call returns a QueryResult with the data."""
    toolbox = StubToolbox(
        [
            make_result(success=True, data=[{"id": 1}]),
        ]
    )
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[SubQuery(database="catalog", query="select * from books", query_type="postgres")],
        execution_order=[0],
        join_operations=[],
    )

    results = engine.execute_plan(plan, {})

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].data == [{"id": 1}]


def test_execute_plan_merges_joined_subqueries():
    """execute_plan joins results from two databases using JoinOp left_db/right_db/left_key/right_key."""
    toolbox = StubToolbox(
        [
            make_result(success=True, data=[{"customer_id": 9}]),
            make_result(success=True, data=[{"customer_ref": 9, "status": "active"}]),
        ]
    )
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[
            SubQuery(database="db1", query="select customer_id from customers", query_type="postgres"),
            SubQuery(database="db2", query="select customer_ref, status from orders", query_type="duckdb"),
        ],
        execution_order=[0, 1],
        join_operations=[
            JoinOp(
                left_db="db1",
                right_db="db2",
                left_key="customer_id",
                right_key="customer_ref",
            )
        ],
    )

    results = engine.execute_plan(plan, {})

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].data == [{"customer_id": 9, "customer_ref": 9, "status": "active"}]
