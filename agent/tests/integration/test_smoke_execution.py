from __future__ import annotations

from agent.execution_engine import ExecutionEngine, FormatTransform, JoinOp, QueryPlan, SubQuery
from agent.mcp_toolbox import ToolResult
from eval.harness import EvaluationHarness


class IntegrationToolbox:
    def call_tool(self, tool_name: str, parameters: dict) -> ToolResult:
        if tool_name == "run_query":
            return ToolResult(success=True, data=[{"customer_id": "CUST-7", "name": "Ada"}])
        if tool_name == "duckdb_query":
            return ToolResult(success=True, data=[{"customer_ref": 7, "total": 120.5}])
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
            SubQuery("select customer_id, name from customers", "customers", "postgres"),
            SubQuery("select customer_ref, total from orders", "orders", "duckdb"),
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

    session = harness.start_session()
    result = engine.execute_plan(plan, context={})

    tool_call_ids = []
    for entry in result.query_trace:
        if "tool" not in entry:
            continue
        tool_call_ids.append(
            harness.trace_tool_call(
                session_id=session,
                tool_name=entry["tool"],
                parameters={"subquery_idx": entry["subquery_idx"]},
                result={"rows": entry["rows"]},
                execution_time=entry["execution_time"],
                error=entry["error"],
            )
        )

    query_event = harness.record_query_outcome(
        session_id=session,
        query="Show the first customer and their total",
        answer=result.answer,
        expected=[{"customer_id": "CUST-7", "name": "Ada", "customer_ref": "CUST-7", "total": 120.5}],
        tool_call_ids=tool_call_ids,
        available_databases=["postgres", "duckdb"],
        confidence=result.confidence,
        correction_applied=result.correction_applied,
    )

    assert result.success is True
    assert query_event.correct is True
    assert harness.calculate_pass_at_1() == 100.0
    assert len(harness.parse_trace_log()) == 3
