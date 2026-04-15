"""Focused scaffold tests for the typed execution engine runtime."""

from __future__ import annotations

import unittest

from agent.execution_engine import ExecutionEngine
from agent.mcp_client import MCPClient
from agent.sandbox_client import SandboxClient
from agent.self_correction import SelfCorrectionLoop
from agent.types import (
    CorrectionDecision,
    ExecutionPlan,
    ExecutionStatus,
    ExecutionStep,
    FailureRecord,
    MCPToolResult,
    SandboxResult,
    StepKind,
    StepRoute,
)


class FakeMCPBackend:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def call_tool(self, tool_name, parameters):
        self.calls.append((tool_name, parameters))
        return self.results.pop(0)


class FakeSandboxBackend:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        return self.results.pop(0)


class NeverRetry(SelfCorrectionLoop):
    def handle_failure(self, plan: ExecutionPlan, failure: FailureRecord) -> CorrectionDecision:
        return CorrectionDecision(retryable=False, reason="stop", updated_plan=None)


class RepairingCorrection(SelfCorrectionLoop):
    def handle_failure(self, plan: ExecutionPlan, failure: FailureRecord) -> CorrectionDecision:
        if failure.attempt >= plan.max_retries:
            return CorrectionDecision(retryable=False, reason="stop", updated_plan=None)

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
                        code="return { repaired: true, rows: inputs.rows ?? [] };",
                        parameters=step.parameters,
                        input_refs=step.input_refs,
                        output_key=step.output_key,
                    )
                )
            else:
                repaired_steps.append(step)

        return CorrectionDecision(
            retryable=True,
            reason="repair sandbox step",
            updated_plan=ExecutionPlan(
                plan_id=plan.plan_id,
                steps=repaired_steps,
                final_output_key=plan.final_output_key,
                max_retries=plan.max_retries,
            ),
        )


class ExecutionEngineScaffoldTests(unittest.TestCase):
    def test_database_step_routes_to_mcp_client(self) -> None:
        backend = FakeMCPBackend(
            [MCPToolResult(success=True, data=[{"id": 1}], tool_name="list_tables")]
        )
        engine = ExecutionEngine(mcp_client=MCPClient(backend=backend))
        plan = ExecutionPlan(
            plan_id="plan-1",
            steps=[
                ExecutionStep(
                    step_id="step-db",
                    kind=StepKind.DATABASE,
                    tool_name="list_tables",
                    output_key="tables",
                )
            ],
            final_output_key="tables",
        )

        result = engine.execute_plan(plan, context={"request_id": "abc"})

        self.assertTrue(result.success)
        self.assertEqual(result.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(result.final_output, [{"id": 1}])
        self.assertEqual(result.outputs["tables"], [{"id": 1}])
        self.assertEqual(backend.calls, [("list_tables", {})])
        self.assertEqual(result.trace[0].route, StepRoute.MCP_TOOLBOX)

    def test_transform_step_routes_to_sandbox_client(self) -> None:
        sandbox_backend = FakeSandboxBackend(
            [SandboxResult(success=True, result={"rows": 1}, validation_status="PASSED")]
        )
        engine = ExecutionEngine(
            sandbox_client=SandboxClient(backend=sandbox_backend),
        )
        plan = ExecutionPlan(
            plan_id="plan-2",
            steps=[
                ExecutionStep(
                    step_id="step-transform",
                    kind=StepKind.TRANSFORM,
                    code="return data;",
                    input_refs=["raw_rows"],
                    output_key="summary",
                )
            ],
            final_output_key="summary",
        )

        result = engine.execute_plan(plan, context={"raw_rows": [{"id": 1}]})

        self.assertTrue(result.success)
        self.assertEqual(result.outputs["summary"], {"rows": 1})
        self.assertEqual(result.trace[0].route, StepRoute.SANDBOX)
        request = sandbox_backend.calls[0]
        self.assertEqual(request.step_id, "step-transform")
        self.assertEqual(request.trace_id, "step-transform:attempt-1")
        self.assertEqual(request.inputs_payload["raw_rows"], None)
        self.assertEqual(request.context["shared_context"]["raw_rows"], [{"id": 1}])
        self.assertEqual(result.trace[0].metadata["validation_status"], "PASSED")

    def test_engine_retries_after_failure_when_self_correction_allows_it(self) -> None:
        backend = FakeMCPBackend(
            [
                MCPToolResult(success=False, error="temporary failure", tool_name="list_tables"),
                MCPToolResult(success=True, data=[{"id": 2}], tool_name="list_tables"),
            ]
        )
        engine = ExecutionEngine(mcp_client=MCPClient(backend=backend))
        plan = ExecutionPlan(
            plan_id="plan-3",
            steps=[
                ExecutionStep(
                    step_id="step-db",
                    kind=StepKind.DATABASE,
                    tool_name="list_tables",
                    output_key="tables",
                )
            ],
            final_output_key="tables",
            max_retries=2,
        )

        result = engine.execute_plan(plan)

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertTrue(result.correction_applied)
        self.assertEqual(len(backend.calls), 2)
        self.assertTrue(
            any(trace.route is StepRoute.SELF_CORRECTION for trace in result.trace)
        )

    def test_engine_stops_when_failure_is_not_retryable(self) -> None:
        backend = FakeMCPBackend(
            [MCPToolResult(success=False, error="fatal failure", tool_name="list_tables")]
        )
        engine = ExecutionEngine(
            mcp_client=MCPClient(backend=backend),
            self_correction=NeverRetry(),
        )
        plan = ExecutionPlan(
            plan_id="plan-4",
            steps=[
                ExecutionStep(
                    step_id="step-db",
                    kind=StepKind.DATABASE,
                    tool_name="list_tables",
                    output_key="tables",
                )
            ],
            final_output_key="tables",
        )

        result = engine.execute_plan(plan)

        self.assertFalse(result.success)
        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.error, "fatal failure")

    def test_example_postgres_and_mongo_rows_are_sent_to_sandbox_merge(self) -> None:
        mcp_backend = FakeMCPBackend(
            [
                MCPToolResult(
                    success=True,
                    data=[{"business_id": "b1", "name": "Cafe Blue"}],
                    tool_name="preview_books_info",
                ),
                MCPToolResult(
                    success=True,
                    data=[{"business_id": "b1", "checkins": 14}],
                    tool_name="find_yelp_checkins",
                ),
            ]
        )
        sandbox_backend = FakeSandboxBackend(
            [
                SandboxResult(
                    success=True,
                    result=[{"business_id": "b1", "name": "Cafe Blue", "checkins": 14}],
                    trace=[{"step": "normalize"}, {"step": "join"}],
                    validation_status="PASSED",
                )
            ]
        )
        engine = ExecutionEngine(
            mcp_client=MCPClient(backend=mcp_backend),
            sandbox_client=SandboxClient(backend=sandbox_backend),
        )
        plan = ExecutionPlan(
            plan_id="plan-5",
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
                    tool_name="find_yelp_checkins",
                    output_key="mongo_docs",
                ),
                ExecutionStep(
                    step_id="normalize-join",
                    kind=StepKind.MERGE,
                    code=(
                        "Normalize Postgres rows and Mongo docs by business_id, "
                        "then join into a single payload."
                    ),
                    input_refs=["postgres_rows", "mongo_docs"],
                    output_key="joined_rows",
                ),
            ],
            final_output_key="joined_rows",
        )

        result = engine.execute_plan(plan)

        self.assertTrue(result.success)
        self.assertEqual(
            result.final_output,
            [{"business_id": "b1", "name": "Cafe Blue", "checkins": 14}],
        )
        sandbox_request = sandbox_backend.calls[0]
        self.assertEqual(sandbox_request.trace_id, "normalize-join:attempt-1")
        self.assertEqual(
            sandbox_request.inputs_payload,
            {
                "postgres_rows": [{"business_id": "b1", "name": "Cafe Blue"}],
                "mongo_docs": [{"business_id": "b1", "checkins": 14}],
            },
        )
        self.assertEqual(result.trace[2].metadata["sandbox_trace"], [{"step": "normalize"}, {"step": "join"}])

    def test_validation_failure_from_sandbox_fails_when_not_retryable(self) -> None:
        sandbox_backend = FakeSandboxBackend(
            [
                SandboxResult(
                    success=False,
                    result=None,
                    trace=[{"step": "validate"}, {"step": "reject"}],
                    validation_status="FAILED",
                    error_if_any="join key mismatch",
                )
            ]
        )
        engine = ExecutionEngine(
            sandbox_client=SandboxClient(backend=sandbox_backend),
            self_correction=NeverRetry(),
        )
        plan = ExecutionPlan(
            plan_id="plan-6",
            steps=[
                ExecutionStep(
                    step_id="validate-join",
                    kind=StepKind.VALIDATE,
                    code="return { ok: false };",
                    input_refs=["rows"],
                    output_key="validated",
                )
            ],
            final_output_key="validated",
        )

        result = engine.execute_plan(plan, context={"rows": [{"id": 1}]})

        self.assertFalse(result.success)
        self.assertEqual(result.error, "join key mismatch")
        self.assertEqual(result.trace[0].metadata["validation_status"], "FAILED")

    def test_retry_after_repair_succeeds_for_sandbox_step(self) -> None:
        sandbox_backend = FakeSandboxBackend(
            [
                SandboxResult(
                    success=False,
                    result=None,
                    trace=[{"step": "execute"}, {"step": "validation_failed"}],
                    validation_status="FAILED",
                    error_if_any="normalization failed",
                ),
                SandboxResult(
                    success=True,
                    result={"repaired": True},
                    trace=[{"step": "execute"}, {"step": "done"}],
                    validation_status="PASSED",
                )
            ]
        )
        engine = ExecutionEngine(
            sandbox_client=SandboxClient(backend=sandbox_backend),
            self_correction=RepairingCorrection(),
        )
        plan = ExecutionPlan(
            plan_id="plan-7",
            steps=[
                ExecutionStep(
                    step_id="repairable-transform",
                    kind=StepKind.TRANSFORM,
                    code="return { repaired: false };",
                    input_refs=["rows"],
                    output_key="transformed",
                )
            ],
            final_output_key="transformed",
            max_retries=2,
        )

        result = engine.execute_plan(plan, context={"rows": [{"id": 1}]})

        self.assertTrue(result.success)
        self.assertTrue(result.correction_applied)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.final_output, {"repaired": True})
        self.assertEqual(sandbox_backend.calls[0].code_plan, "return { repaired: false };")
        self.assertEqual(sandbox_backend.calls[1].code_plan, "return { repaired: true, rows: inputs.rows ?? [] };")
        self.assertTrue(any(trace.route is StepRoute.SELF_CORRECTION for trace in result.trace))


if __name__ == "__main__":
    unittest.main()
