from types import SimpleNamespace

from agent.execution_engine import (
    ExecutionEngine,
    FormatTransform,
    JoinOp,
    QueryPlan,
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

    sqlite_tool, sqlite_params = engine._build_tool_call(
        SubQuery("select 1", "local", "sqlite")
    )
    mongo_tool, mongo_params = engine._build_tool_call(
        SubQuery("db.checkin.aggregate([])", "mongo", "mongodb")
    )

    assert sqlite_tool == "sqlite_query"
    assert sqlite_params == {"query": "select 1"}
    assert mongo_tool == "find_yelp_checkins"
    assert mongo_params["limit"] == 20


def test_merge_results_applies_format_transformation():
    engine = ExecutionEngine(toolbox=StubToolbox([]))
    join_op = JoinOp(
        left_subquery_idx=0,
        right_subquery_idx=1,
        join_key_left="customer_id",
        join_key_right="customer_ref",
        format_transformation=FormatTransform(
            source_format="integer",
            target_format="CUST-{}",
            transformation_function="prefix customer ids",
        ),
    )

    merged = engine.merge_results(
        {
            0: [{"customer_id": "CUST-7", "amount": 10}],
            1: [{"customer_ref": 7, "name": "Ada"}],
        },
        [join_op],
    )

    assert merged == [{"customer_id": "CUST-7", "amount": 10, "customer_ref": "CUST-7", "name": "Ada"}]


def test_validate_result_rejects_duplicates():
    engine = ExecutionEngine(toolbox=StubToolbox([]))

    validation = engine.validate_result([{"id": 1}, {"id": 1}], {})

    assert validation["valid"] is False
    assert "Duplicate rows detected" in validation["issues"]


def test_execute_plan_retries_after_syntax_failure_and_succeeds():
    toolbox = StubToolbox(
        [
            make_result(success=False, error="syntax error near FROM"),
            make_result(success=True, data=[{"id": 1}]),
        ]
    )
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[SubQuery("select * from books", "catalog", "postgres")],
        execution_order=[0],
        join_operations=[],
    )

    result = engine.execute_plan(plan, {})

    assert result.success is True
    assert result.correction_applied is True
    assert result.answer == [{"id": 1}]
    assert toolbox.calls[1][1]["query"].endswith("LIMIT 100;")


def test_execute_plan_merges_joined_subqueries():
    toolbox = StubToolbox(
        [
            make_result(success=True, data=[{"customer_id": "CUST-9"}]),
            make_result(success=True, data=[{"customer_ref": 9, "status": "active"}]),
        ]
    )
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[
            SubQuery("select customer_id from customers", "db1", "postgres"),
            SubQuery("select customer_ref, status from orders", "db2", "duckdb"),
        ],
        execution_order=[0, 1],
        join_operations=[
            JoinOp(
                left_subquery_idx=0,
                right_subquery_idx=1,
                join_key_left="customer_id",
                join_key_right="customer_ref",
                format_transformation=FormatTransform(
                    source_format="integer",
                    target_format="CUST-{}",
                    transformation_function="prefix customer ids",
                ),
            )
        ],
    )

    result = engine.execute_plan(plan, {})

    assert result.success is True
    assert result.answer == [{"customer_id": "CUST-9", "customer_ref": "CUST-9", "status": "active"}]
