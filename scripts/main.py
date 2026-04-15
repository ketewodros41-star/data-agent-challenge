from __future__ import annotations

import json
from pathlib import Path

from agent.execution_engine import ExecutionEngine
from agent.mcp_client import MCPClient
from agent.mcp_toolbox import MCPToolbox, ToolResult
from agent.sandbox_client import SandboxClient
from agent.self_correction import SelfCorrectionLoop
from agent.types import (
    CorrectionDecision,
    ExecutionPlan,
    ExecutionStep,
    FailureRecord,
    MCPToolResult,
    SandboxResult,
    StepKind,
)
from eval.harness import EVAL_DIR, EvaluationHarness


class DemoToolbox:
    """Deterministic toolbox used for local smoke runs."""

    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, parameters: dict) -> ToolResult:
        self.calls.append({"tool_name": tool_name, "parameters": parameters})

        if tool_name == "run_query":
            return ToolResult(
                success=True,
                data=[{"customer_id": "CUST-7", "customer_name": "Ada"}],
            )
        if tool_name == "duckdb_query":
            return ToolResult(
                success=True,
                data=[{"customer_ref": 7, "order_total": 120.5}],
            )
        return ToolResult(success=False, data=None, error=f"Unsupported demo tool: {tool_name}")


class RuntimeDemoMCPBackend:
    """Deterministic MCP backend for the typed runtime smoke flow."""

    def __init__(self) -> None:
        self.calls = []

    def call_tool(self, tool_name: str, parameters: dict) -> MCPToolResult:
        self.calls.append({"tool_name": tool_name, "parameters": parameters})

        if tool_name == "preview_books_info":
            return MCPToolResult(
                success=True,
                data=[{"business_id": "b1", "title": "Cafe Blue"}],
                tool_name=tool_name,
            )
        if tool_name == "find_yelp_businesses":
            return MCPToolResult(
                success=True,
                data=[{"business_id": "b1", "category": "Cafe"}],
                tool_name=tool_name,
            )

        return MCPToolResult(success=False, data=None, error=f"Unsupported tool: {tool_name}", tool_name=tool_name)


class RuntimeDemoSandboxBackend:
    """Sandbox stub that fails validation once, then succeeds after repair."""

    def __init__(self) -> None:
        self.calls = []

    def execute(self, request) -> SandboxResult:
        self.calls.append(request)

        operation = json.loads(request.code_plan)
        if not operation.get("repaired"):
            return SandboxResult(
                success=False,
                result=None,
                trace=[{"step": "normalize"}, {"step": "validation_failed"}],
                validation_status="FAILED",
                error_if_any="normalization failed",
            )

        postgres_rows = (request.inputs_payload or {}).get("postgres_rows") or []
        mongo_docs = (request.inputs_payload or {}).get("mongo_docs") or []
        merged = []
        for left in postgres_rows:
            for right in mongo_docs:
                if left.get("business_id") == right.get("business_id"):
                    merged.append({**left, **right})

        return SandboxResult(
            success=True,
            result=merged,
            trace=[{"step": "normalize"}, {"step": "join"}, {"step": "done"}],
            validation_status="PASSED",
            error_if_any=None,
        )


class RuntimeDemoCorrection(SelfCorrectionLoop):
    """Repair the sandbox merge step after a validation failure."""

    def handle_failure(
        self,
        plan: ExecutionPlan,
        failure: FailureRecord,
    ) -> CorrectionDecision:
        if failure.attempt >= plan.max_retries:
            return CorrectionDecision(retryable=False, reason="Retry budget exhausted", updated_plan=None)

        repaired_steps = []
        for step in plan.steps:
            if step.step_id == failure.step_id:
                repaired_steps.append(
                    ExecutionStep(
                        step_id=step.step_id,
                        kind=step.kind,
                        route=step.route,
                        tool_name=step.tool_name,
                        database_type=step.database_type,
                        code=json.dumps(
                            {
                                "operation": "merge_on_key",
                                "left_input": "postgres_rows",
                                "right_input": "mongo_docs",
                                "left_key": "business_id",
                                "right_key": "business_id",
                                "join_type": "inner",
                                "require_repaired": True,
                                "repaired": True,
                            }
                        ),
                        parameters=step.parameters,
                        input_refs=step.input_refs,
                        output_key=step.output_key,
                    )
                )
            else:
                repaired_steps.append(step)

        return CorrectionDecision(
            retryable=True,
            reason="repair sandbox merge step",
            updated_plan=ExecutionPlan(
                plan_id=plan.plan_id,
                steps=repaired_steps,
                final_output_key=plan.final_output_key,
                max_retries=plan.max_retries,
            ),
        )


class RealToolboxBackend:
    """Adapter that lets the typed runtime use the real MCPToolbox client."""

    def __init__(self) -> None:
        self.toolbox = MCPToolbox()
        self.calls = []

    def call_tool(self, tool_name: str, parameters: dict) -> MCPToolResult:
        self.calls.append({"tool_name": tool_name, "parameters": parameters})
        result = self.toolbox.call_tool(tool_name, parameters)
        return MCPToolResult(
            success=result.success,
            data=result.data,
            error=result.error,
            tool_name=tool_name,
        )


def run_smoke_demo() -> int:
    """Run a complete execution-engine + evaluation-harness demo."""
    from agent.execution_engine import FormatTransform, JoinOp, QueryPlan, SubQuery

    toolbox = DemoToolbox()
    engine = ExecutionEngine(toolbox=toolbox)
    plan = QueryPlan(
        sub_queries=[
            SubQuery(
                query_text="SELECT customer_id, customer_name FROM customers LIMIT 1",
                target_database="customers_db",
                database_type="postgres",
            ),
            SubQuery(
                query_text="SELECT customer_ref, order_total FROM orders LIMIT 1",
                target_database="analytics_db",
                database_type="duckdb",
            ),
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

    harness = EvaluationHarness()
    session_id = harness.start_session()

    result = engine.execute_plan(plan, context={})
    tool_call_ids = []
    for entry in result.query_trace:
        if "tool" not in entry:
            continue
        tool_call_ids.append(
            harness.trace_tool_call(
                session_id=session_id,
                tool_name=entry["tool"],
                parameters={"subquery_idx": entry["subquery_idx"]},
                result={"rows": entry["rows"]},
                execution_time=entry["execution_time"],
                error=entry["error"],
            )
        )

    query_event = harness.record_query_outcome(
        session_id=session_id,
        query="Show the first customer and order total",
        answer=result.answer,
        expected=[{"customer_id": "CUST-7", "customer_name": "Ada", "customer_ref": "CUST-7", "order_total": 120.5}],
        tool_call_ids=tool_call_ids,
        available_databases=["postgres", "duckdb"],
        confidence=result.confidence,
        correction_applied=result.correction_applied,
    )
    harness.log_score(
        pass_at_1=harness.calculate_pass_at_1(),
        total_queries=1,
        correct=1 if query_event.correct and not query_event.correction_applied else 0,
        corrections=1 if query_event.correction_applied else 0,
        avg_time=0.0,
        changes="smoke demo run",
    )

    print("Smoke run summary")
    print(json.dumps(
        {
            "execution_success": result.success,
            "rows_returned": len(result.answer or []),
            "tool_calls": len(toolbox.calls),
            "query_scored_correct": query_event.correct,
            "pass_at_1": harness.calculate_pass_at_1(),
            "trace_log_path": str(harness.trace_log_path),
            "score_log_path": str(harness.score_log_path),
        },
        indent=2,
    ))
    print("\nTrace")
    print(harness.pretty_print_trace())
    return 0 if result.success and query_event.correct else 1


def verify_connections() -> int:
    """Check whether the real toolbox HTTP server and DuckDB are reachable."""
    toolbox = MCPToolbox()
    status = toolbox.verify_connections()
    print(json.dumps(status, indent=2))
    return 0 if all(value is True for key, value in status.items() if not key.endswith("_error")) else 1


def run_real_toolbox_smoke() -> int:
    """
    Run a smoke check against the actual configured toolbox tools.

    This verifies real connectivity and trace logging, but it does not use the
    execution engine because the current toolbox config exposes fixed tools like
    preview_books_info rather than the engine's generic run_query tool.
    """
    toolbox = MCPToolbox()
    connection_status = toolbox.verify_connections()
    tools = toolbox.list_tools()

    harness = EvaluationHarness()
    session_id = harness.start_session()

    tool_call_ids = []
    sampled_results = {}
    smoke_tools = [
        ("preview_books_info", {}),
        ("find_yelp_businesses", {"filterPayload": "{}", "limit": 2}),
    ]

    for tool_name, params in smoke_tools:
        started_at = __import__("time").time()
        result = toolbox.call_tool(tool_name, params)
        elapsed = round(__import__("time").time() - started_at, 3)
        sampled_results[tool_name] = {
            "success": result.success,
            "rows": len(result.data) if isinstance(result.data, list) else None,
            "error": result.error,
        }
        tool_call_ids.append(
            harness.trace_tool_call(
                session_id=session_id,
                tool_name=tool_name,
                parameters=params,
                result=result.data,
                execution_time=elapsed,
                error=result.error,
            )
        )

    overall_success = all(item["success"] for item in sampled_results.values())
    query_event = harness.record_query_outcome(
        session_id=session_id,
        query="Real toolbox smoke check",
        answer="success" if overall_success else "failure",
        expected="success",
        tool_call_ids=tool_call_ids,
        available_databases=["postgres", "mongodb"],
        confidence=1.0 if overall_success else 0.0,
        correction_applied=False,
    )
    harness.log_score(
        pass_at_1=harness.calculate_pass_at_1(),
        total_queries=1,
        correct=1 if query_event.correct else 0,
        corrections=0,
        avg_time=0.0,
        changes="real toolbox smoke run",
    )

    print("Real toolbox smoke summary")
    print(
        json.dumps(
            {
                "connection_status": connection_status,
                "discovered_tools": [tool.get("name") for tool in tools if isinstance(tool, dict)],
                "sampled_results": sampled_results,
                "query_scored_correct": query_event.correct,
                "trace_log_path": str(harness.trace_log_path),
                "score_log_path": str(harness.score_log_path),
            },
            indent=2,
        )
    )
    print("\nTrace")
    print(harness.pretty_print_trace())

    return 0 if overall_success else 1


def run_real_engine_smoke() -> int:
    """
    Run the actual execution engine against live MCP-compatible tools.

    This currently uses MongoDB because the engine already maps mongodb
    subqueries to the live toolbox tool names in mcp/tools.yaml.
    """
    from agent.execution_engine import QueryPlan, SubQuery

    engine = ExecutionEngine(toolbox=MCPToolbox())
    plan = QueryPlan(
        sub_queries=[
            SubQuery(
                query_text="db.business.find({})",
                target_database="yelp_db",
                database_type="mongodb",
            )
        ],
        execution_order=[0],
        join_operations=[],
    )

    harness = EvaluationHarness()
    session_id = harness.start_session()

    result = engine.execute_plan(plan, context={})
    tool_call_ids = []
    for entry in result.query_trace:
        if "tool" not in entry:
            continue
        tool_call_ids.append(
            harness.trace_tool_call(
                session_id=session_id,
                tool_name=entry["tool"],
                parameters={"subquery_idx": entry["subquery_idx"]},
                result={"rows": entry["rows"]},
                execution_time=entry["execution_time"],
                error=entry["error"],
            )
        )

    query_event = harness.record_query_outcome(
        session_id=session_id,
        query="Real engine smoke check",
        answer="success" if result.success else "failure",
        expected="success",
        tool_call_ids=tool_call_ids,
        available_databases=["mongodb"],
        confidence=result.confidence,
        correction_applied=result.correction_applied,
    )
    harness.log_score(
        pass_at_1=harness.calculate_pass_at_1(),
        total_queries=1,
        correct=1 if query_event.correct and not query_event.correction_applied else 0,
        corrections=1 if query_event.correction_applied else 0,
        avg_time=0.0,
        changes="real execution engine smoke run",
    )

    print("Real execution engine smoke summary")
    print(
        json.dumps(
            {
                "execution_success": result.success,
                "error": result.error,
                "rows_returned": len(result.answer) if isinstance(result.answer, list) else None,
                "query_scored_correct": query_event.correct,
                "trace_log_path": str(harness.trace_log_path),
                "score_log_path": str(harness.score_log_path),
            },
            indent=2,
        )
    )
    print("\nTrace")
    print(harness.pretty_print_trace())

    return 0 if result.success else 1


def run_runtime_sandbox_demo() -> int:
    """Run a typed runtime demo: MCP fetches, sandbox merge, retry after repair."""
    mcp_backend = RuntimeDemoMCPBackend()
    sandbox_backend = RuntimeDemoSandboxBackend()
    engine = ExecutionEngine(
        mcp_client=MCPClient(backend=mcp_backend),
        sandbox_client=SandboxClient(backend=sandbox_backend),
        self_correction=RuntimeDemoCorrection(),
    )
    plan = ExecutionPlan(
        plan_id="runtime-sandbox-demo",
        steps=[
            ExecutionStep(
                step_id="postgres-fetch",
                kind=StepKind.DATABASE,
                tool_name="preview_books_info",
                output_key="postgres_rows",
            ),
            ExecutionStep(
                step_id="mongo-fetch",
                kind=StepKind.DATABASE,
                tool_name="find_yelp_businesses",
                output_key="mongo_docs",
            ),
            ExecutionStep(
                step_id="merge-results",
                kind=StepKind.MERGE,
                code=json.dumps(
                    {
                        "operation": "merge_on_key",
                        "left_input": "postgres_rows",
                        "right_input": "mongo_docs",
                        "left_key": "business_id",
                        "right_key": "business_id",
                        "join_type": "inner",
                        "require_repaired": True,
                        "repaired": False,
                    }
                ),
                input_refs=["postgres_rows", "mongo_docs"],
                output_key="joined_rows",
            ),
        ],
        final_output_key="joined_rows",
        max_retries=2,
    )

    result = engine.execute_plan(plan, context={})
    print("Runtime sandbox demo summary")
    print(
        json.dumps(
            {
                "success": result.success,
                "attempts": result.attempts,
                "correction_applied": result.correction_applied,
                "final_output": result.final_output,
                "mcp_calls": mcp_backend.calls,
                "sandbox_calls": [
                    {
                        "trace_id": call.trace_id,
                        "code_plan": call.code_plan,
                        "inputs_payload": call.inputs_payload,
                    }
                    for call in sandbox_backend.calls
                ],
                "trace": [
                    {
                        "step_id": entry.step_id,
                        "route": entry.route.value,
                        "status": entry.status.value,
                        "metadata": entry.metadata,
                        "error": entry.error,
                    }
                    for entry in result.trace
                ],
            },
            indent=2,
        )
    )
    return 0 if result.success else 1


def run_real_runtime_sandbox_demo() -> int:
    """
    Run the typed runtime against the real MCP toolbox and the configured sandbox.

    Architecture:
    - DB reads use MCP
    - merge logic uses the sandbox
    - self-correction retries the sandbox step after a validation failure
    """
    mcp_backend = RealToolboxBackend()
    sandbox_client = SandboxClient()
    engine = ExecutionEngine(
        mcp_client=MCPClient(backend=mcp_backend),
        sandbox_client=sandbox_client,
        self_correction=RuntimeDemoCorrection(),
    )
    plan = ExecutionPlan(
        plan_id="real-runtime-sandbox-demo",
        steps=[
            ExecutionStep(
                step_id="postgres-fetch",
                kind=StepKind.DATABASE,
                tool_name="preview_books_info",
                output_key="postgres_rows",
            ),
            ExecutionStep(
                step_id="mongo-fetch",
                kind=StepKind.DATABASE,
                tool_name="find_yelp_businesses",
                output_key="mongo_docs",
            ),
            ExecutionStep(
                step_id="merge-results",
                kind=StepKind.MERGE,
                code=json.dumps(
                    {
                        "operation": "merge_on_key",
                        "left_input": "postgres_rows",
                        "right_input": "mongo_docs",
                        "left_key": "business_id",
                        "right_key": "business_id",
                        "join_type": "inner",
                        "require_repaired": True,
                        "repaired": False,
                    }
                ),
                input_refs=["postgres_rows", "mongo_docs"],
                output_key="joined_rows",
            ),
        ],
        final_output_key="joined_rows",
        max_retries=2,
    )

    result = engine.execute_plan(plan, context={})
    print("Real runtime sandbox demo summary")
    print(
        json.dumps(
            {
                "success": result.success,
                "attempts": result.attempts,
                "correction_applied": result.correction_applied,
                "final_output_preview": (
                    result.final_output[:2] if isinstance(result.final_output, list) else result.final_output
                ),
                "mcp_calls": mcp_backend.calls,
                "trace": [
                    {
                        "step_id": entry.step_id,
                        "route": entry.route.value,
                        "status": entry.status.value,
                        "metadata": entry.metadata,
                        "error": entry.error,
                    }
                    for entry in result.trace
                ],
            },
            indent=2,
        )
    )
    return 0 if result.success else 1


def run_query_cli(sql: str) -> int:
    """Execute a SQL query through the MCP toolbox and print the result."""
    toolbox = MCPToolbox()
    result = toolbox.call_tool("run_query", {"sql": sql})
    print(
        json.dumps(
            {
                "tool_name": "run_query",
                "success": result.success,
                "source_type": result.source_type,
                "execution_time": result.execution_time,
                "error": result.error,
                "data": result.data,
            },
            indent=2,
        )
    )
    return 0 if result.success else 1


def list_mcp_tools_cli() -> int:
    """Print the currently available MCP tool names."""
    toolbox = MCPToolbox()
    tools = toolbox.list_tools()
    print(json.dumps([tool.get("name", tool) for tool in tools], indent=2))
    return 0


def main():
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if command == "smoke":
        raise SystemExit(run_smoke_demo())
    if command == "verify-connections":
        raise SystemExit(verify_connections())
    if command == "real-toolbox-smoke":
        raise SystemExit(run_real_toolbox_smoke())
    if command == "real-engine-smoke":
        raise SystemExit(run_real_engine_smoke())
    if command == "runtime-sandbox-demo":
        raise SystemExit(run_runtime_sandbox_demo())
    if command == "real-runtime-sandbox-demo":
        raise SystemExit(run_real_runtime_sandbox_demo())
    if command == "run-query":
        if len(sys.argv) < 3:
            raise SystemExit('Usage: python3 main.py run-query "<SQL>"')
        raise SystemExit(run_query_cli(sys.argv[2]))
    if command == "list-mcp-tools":
        raise SystemExit(list_mcp_tools_cli())
    raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
