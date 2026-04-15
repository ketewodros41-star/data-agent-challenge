from __future__ import annotations

from agent.execution_engine import ExecutionEngine, JoinOp, QueryPlan, SubQuery
from agent.mcp_toolbox import ToolResult
from eval.harness import EvaluationHarness


class IntegrationToolbox:
    def call_tool(self, tool_name: str, parameters: dict) -> ToolResult:
        if tool_name == "run_query":
            return ToolResult(success=True, data=[{"customer_id": "CUST-7", "name": "Ada"}])
        if tool_name == "duckdb_query":
            return ToolResult(success=True, data=[{"customer_ref": "CUST-7", "total": 120.5}])
        return ToolResult(success=False, data=None, error=f"unexpected tool {tool_name}")


def test_execution_and_harness_smoke_flow(tmp_path):
    engine = ExecutionEngine(toolbox=IntegrationToolbox())
    harness = EvaluationHarness(
        eval_dir=tmp_path,
        score_log_path=tmp_path / "score_log.json",
        trace_log_path=tmp_path / "trace_log.jsonl",
    )
    plan = QueryPlan(
        sub_queries=[
            SubQuery(database="customers", query="select customer_id, name from customers", query_type="postgres"),
            SubQuery(database="orders", query="select customer_ref, total from orders", query_type="duckdb"),
        ],
        execution_order=[0, 1],
        join_operations=[
            JoinOp(
                left_db="customers",
                right_db="orders",
                left_key="customer_id",
                right_key="customer_ref",
            )
        ],
    )

    session = harness.start_session()
    results = engine.execute_plan(plan, context={})

    # execute_plan returns a list; with a join operation it returns one merged result
    assert results, "Expected at least one result from execute_plan"
    result = results[0]

    tool_call_ids = []
    for i, sq in enumerate(plan.sub_queries):
        tool_name = "run_query" if sq.query_type == "postgres" else "duckdb_query"
        tool_call_ids.append(
            harness.trace_tool_call(
                session_id=session,
                tool_name=tool_name,
                parameters={"subquery_idx": i},
                result={"rows": result.rows_affected},
                execution_time=0.0,
                error=None,
            )
        )

    query_event = harness.record_query_outcome(
        session_id=session,
        query="Show the first customer and their total",
        answer=result.data,
        expected=[{"customer_id": "CUST-7", "name": "Ada", "customer_ref": "CUST-7", "total": 120.5}],
        tool_call_ids=tool_call_ids,
        available_databases=["postgres", "duckdb"],
        confidence=0.9,
        correction_applied=False,
    )

    assert result.success is True
    assert query_event.correct is True
    assert harness.calculate_pass_at_1() == 100.0
    assert len(harness.parse_trace_log()) == 3
