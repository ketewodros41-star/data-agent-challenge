"""
Execution Engine.

Supports two execution contracts:
1. Legacy query-plan execution used by the current Oracle Forge agent
2. Typed runtime execution used for sandbox-aware transform / extract / merge / validate steps

Routing:
  PostgreSQL / SQLite / MongoDB  -> HTTP Google MCP Toolbox
  DuckDB                         -> HTTP custom DuckDB MCP service
  Extract / Transform / Merge / Validate -> Sandbox
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from agent.mcp_client import MCPClient
from agent.sandbox_client import SandboxClient
from agent.types import (
    CorrectionDecision,
    ExecutionPlan as TypedExecutionPlan,
    ExecutionResult,
    ExecutionStatus,
    ExecutionStep,
    ExecutionTrace,
    FailureRecord,
    MCPToolCall,
    StepKind,
    StepRoute,
)
from agent.models.models import (
    FormatTransform,
    JoinOp,
    QueryPlan,
    QueryResult,
    SubQuery,
)
from .mcp_toolbox import MCPToolbox


class ExecutionEngine:
    """Execute legacy query plans and typed runtime plans."""

    def __init__(
        self,
        toolbox: Optional[MCPToolbox] = None,
        db_configs: Optional[Dict[str, dict]] = None,
        mcp_client: Optional[MCPClient] = None,
        sandbox_client: Optional[SandboxClient] = None,
        self_correction: Optional[Any] = None,
    ):
        self._db_configs: Dict[str, dict] = db_configs or {}
        self.toolbox = toolbox or MCPToolbox(db_configs=self._db_configs)
        self.mcp_client = mcp_client or MCPClient(backend=self.toolbox)
        self.sandbox_client = sandbox_client or SandboxClient()
        self.self_correction = self_correction

    def execute_plan(
        self,
        plan: QueryPlan | TypedExecutionPlan,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[QueryResult] | ExecutionResult:
        """Dispatch to the legacy or typed runtime path."""
        if hasattr(plan, "steps"):
            return self._execute_typed_plan(plan, context or {})
        return self._execute_legacy_plan(plan, context or {})

    def _execute_typed_plan(
        self,
        plan: TypedExecutionPlan,
        context: Dict[str, Any],
    ) -> ExecutionResult:
        trace: List[ExecutionTrace] = []
        attempts = 0
        correction_applied = False
        current_plan = plan

        while attempts < current_plan.max_retries:
            attempts += 1
            outputs: Dict[str, Any] = {}
            failure: Optional[FailureRecord] = None

            for step in current_plan.steps:
                step_result = self._execute_typed_step(
                    step=step,
                    attempt=attempts,
                    context=context,
                    outputs=outputs,
                )
                trace.append(step_result["trace"])

                if not step_result["success"]:
                    failure = FailureRecord(
                        step_id=step.step_id,
                        route=step_result["trace"].route,
                        error=step_result["error"] or "Unknown execution error",
                        attempt=attempts,
                        trace=trace.copy(),
                    )
                    break

                if step.output_key:
                    outputs[step.output_key] = step_result["output"]

            if failure is None:
                final_output = self._resolve_final_output(current_plan, outputs)
                return ExecutionResult(
                    success=True,
                    status=ExecutionStatus.SUCCEEDED,
                    final_output=final_output,
                    outputs=outputs,
                    trace=trace,
                    attempts=attempts,
                    correction_applied=correction_applied,
                    error=None,
                )

            decision = self._handle_failure(current_plan, failure)
            if not decision.retryable:
                return ExecutionResult(
                    success=False,
                    status=ExecutionStatus.FAILED,
                    final_output=None,
                    outputs=outputs,
                    trace=trace,
                    attempts=attempts,
                    correction_applied=correction_applied,
                    error=failure.error,
                )

            correction_applied = True
            trace.append(
                ExecutionTrace(
                    step_id=failure.step_id,
                    step_kind=self._lookup_step(current_plan, failure.step_id).kind,
                    route=StepRoute.SELF_CORRECTION,
                    status=ExecutionStatus.RETRYING,
                    attempt=attempts,
                    execution_time=0.0,
                    error=failure.error,
                    metadata={"reason": decision.reason},
                )
            )
            current_plan = decision.updated_plan or current_plan

        return ExecutionResult(
            success=False,
            status=ExecutionStatus.FAILED,
            final_output=None,
            outputs={},
            trace=trace,
            attempts=attempts,
            correction_applied=correction_applied,
            error="Retry budget exhausted",
        )

    def _execute_typed_step(
        self,
        step: ExecutionStep,
        attempt: int,
        context: Dict[str, Any],
        outputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        route = self._resolve_route(step)
        started_at = time.perf_counter()

        if route is StepRoute.MCP_TOOLBOX:
            request = MCPToolCall(
                tool_name=step.tool_name or "",
                parameters=dict(step.parameters),
                database_type=step.database_type,
                context=context,
            )
            result = self.mcp_client.call_tool(request)
            elapsed = time.perf_counter() - started_at
            if not result.success:
                return {
                    "success": False,
                    "output": None,
                    "error": result.error,
                    "trace": ExecutionTrace(
                        step_id=step.step_id,
                        step_kind=step.kind,
                        route=route,
                        status=ExecutionStatus.FAILED,
                        attempt=attempt,
                        execution_time=elapsed,
                        error=result.error,
                        metadata={"tool_name": request.tool_name},
                    ),
                }

            return {
                "success": True,
                "output": result.data,
                "error": None,
                "trace": ExecutionTrace(
                    step_id=step.step_id,
                    step_kind=step.kind,
                    route=route,
                    status=ExecutionStatus.SUCCEEDED,
                    attempt=attempt,
                    execution_time=elapsed,
                    output=result.data,
                    output_key=step.output_key,
                    metadata={"tool_name": request.tool_name},
                ),
            }

        sandbox_request = self._build_sandbox_request(step, attempt, context, outputs)
        sandbox_result = (
            self.sandbox_client.validate(sandbox_request)
            if step.kind is StepKind.VALIDATE
            else self.sandbox_client.execute(sandbox_request)
        )
        elapsed = time.perf_counter() - started_at
        metadata = {
            "validation_status": sandbox_result.validation_status,
            "sandbox_trace": sandbox_result.trace,
            "trace_id": sandbox_request.trace_id,
        }

        if not sandbox_result.success:
            return {
                "success": False,
                "output": None,
                "error": sandbox_result.error_if_any or "Sandbox execution failed",
                "trace": ExecutionTrace(
                    step_id=step.step_id,
                    step_kind=step.kind,
                    route=route,
                    status=ExecutionStatus.FAILED,
                    attempt=attempt,
                    execution_time=elapsed,
                    error=sandbox_result.error_if_any,
                    metadata=metadata,
                ),
            }

        return {
            "success": True,
            "output": sandbox_result.result,
            "error": None,
            "trace": ExecutionTrace(
                step_id=step.step_id,
                step_kind=step.kind,
                route=route,
                status=ExecutionStatus.SUCCEEDED,
                attempt=attempt,
                execution_time=elapsed,
                output=sandbox_result.result,
                output_key=step.output_key,
                metadata=metadata,
            ),
        }

    def _handle_failure(
        self,
        plan: TypedExecutionPlan,
        failure: FailureRecord,
    ) -> CorrectionDecision:
        if self.self_correction is not None and hasattr(self.self_correction, "handle_failure"):
            return self.self_correction.handle_failure(plan, failure)

        if failure.attempt >= plan.max_retries:
            return CorrectionDecision(
                retryable=False,
                reason="Retry budget exhausted",
                updated_plan=None,
            )

        return CorrectionDecision(
            retryable=True,
            reason="generic retry after execution failure",
            updated_plan=plan,
        )

    def _build_sandbox_request(
        self,
        step: ExecutionStep,
        attempt: int,
        context: Dict[str, Any],
        outputs: Dict[str, Any],
    ):
        from agent.types import SandboxExecutionRequest

        inputs_payload = {ref: outputs.get(ref) for ref in step.input_refs}
        return SandboxExecutionRequest(
            code_plan=step.code or "",
            trace_id=f"{step.step_id}:attempt-{attempt}",
            inputs_payload=inputs_payload,
            db_type=step.database_type or step.kind.value,
            context={
                "shared_context": context,
                "step_parameters": dict(step.parameters),
                "available_outputs": outputs,
            },
            step_id=step.step_id,
        )

    def _resolve_route(self, step: ExecutionStep) -> StepRoute:
        if step.route is not None:
            return step.route
        if step.kind is StepKind.DATABASE:
            return StepRoute.MCP_TOOLBOX
        return StepRoute.SANDBOX

    def _lookup_step(self, plan: TypedExecutionPlan, step_id: str) -> ExecutionStep:
        for step in plan.steps:
            if step.step_id == step_id:
                return step
        return plan.steps[-1]

    def _resolve_final_output(
        self,
        plan: TypedExecutionPlan,
        outputs: Dict[str, Any],
    ) -> Any:
        if plan.final_output_key:
            return outputs.get(plan.final_output_key)
        if not outputs:
            return None
        last_key = next(reversed(outputs))
        return outputs[last_key]

    def _execute_legacy_plan(
        self,
        plan: QueryPlan,
        context: Dict[str, Any],
    ) -> List[QueryResult]:
        """Execute each sub-query in plan order and return per-DB results."""
        results: List[QueryResult] = []

        for idx in plan.execution_order:
            sq = plan.sub_queries[idx]
            try:
                tool_name, params = self._build_tool_call(sq)
                tool_result = self.toolbox.call_tool(tool_name, params)

                if not tool_result.success:
                    results.append(
                        QueryResult(
                            database=sq.database,
                            data=None,
                            error=tool_result.error,
                            success=False,
                        )
                    )
                else:
                    data = tool_result.data
                    rows = len(data) if isinstance(data, list) else 1
                    results.append(
                        QueryResult(
                            database=sq.database,
                            data=data,
                            success=True,
                            rows_affected=rows,
                        )
                    )
            except Exception as exc:
                results.append(
                    QueryResult(
                        database=sq.database,
                        data=None,
                        error=str(exc),
                        success=False,
                    )
                )

        if plan.join_operations and len(results) > 1:
            try:
                results_by_db = {
                    r.database: r.data
                    for r in results
                    if r.success and isinstance(r.data, list)
                }
                merged = self._merge_by_db(results_by_db, plan.join_operations)
                if merged is not None:
                    first_db = plan.sub_queries[plan.execution_order[0]].database
                    return [
                        QueryResult(
                            database=first_db,
                            data=merged,
                            success=True,
                            rows_affected=len(merged) if isinstance(merged, list) else 0,
                        )
                    ]
            except Exception:
                pass

        return results

    def _build_tool_call(self, sq: SubQuery) -> tuple[str, Dict[str, Any]]:
        """Map a sub-query to the MCP tool and its parameters."""
        db_type = self._db_configs.get(sq.database, {}).get("type", sq.query_type).lower()
        normalized_query = self._normalize_query_text(sq.query)

        if db_type in ("postgresql", "postgres"):
            static_tool = self._match_static_pg_tool(normalized_query)
            if static_tool:
                return static_tool, {}
            return "run_query", {"query": normalized_query}

        if db_type == "sqlite":
            sqlite_tool = self._db_configs.get(sq.database, {}).get("mcp_tool", "sqlite_query")
            return sqlite_tool, {"sql": normalized_query}

        if db_type == "duckdb":
            duckdb_tool = self._db_configs.get(sq.database, {}).get("mcp_tool", "duckdb_query")
            return duckdb_tool, {"sql": normalized_query}

        if db_type == "mongodb":
            collection, pipeline = self._parse_mongo_query(normalized_query)
            tool_name = "find_yelp_checkins" if collection == "checkin" else "find_yelp_businesses"
            return tool_name, {"filterPayload": pipeline, "limit": 20}

        return "run_query", {"query": normalized_query}

    @staticmethod
    def _normalize_query_text(query: str) -> str:
        """Strip common markdown wrappers that LLMs add around query text."""
        cleaned = query.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            if lines:
                first = lines[0].strip()
                last = lines[-1].strip()
                if first.startswith("```") and last == "```":
                    inner_lines = lines[1:-1]
                    cleaned = "\n".join(inner_lines).strip()
        if cleaned.lower().startswith("sql\n"):
            cleaned = cleaned[4:].lstrip()
        cleaned = re.sub(r"\\+'", "''", cleaned)
        return cleaned

    def _match_static_pg_tool(self, query: str) -> Optional[str]:
        q = query.lower().strip()
        if "information_schema.columns" in q and "books_info" in q:
            return "describe_books_info"
        if "information_schema.tables" in q:
            return "list_tables"
        if (
            "books_info" in q
            and q.lstrip().startswith("select")
            and "where" not in q
            and "group by" not in q
            and "having" not in q
            and "order by" not in q
            and "max(" not in q
            and "min(" not in q
            and "count(" not in q
            and "sum(" not in q
            and "avg(" not in q
        ):
            return "preview_books_info"
        return None

    def _parse_mongo_query(self, query: str) -> tuple[str, str]:
        collection = "checkin" if "checkin" in query.lower() else "business"
        return collection, "{}"

    def _merge_by_db(
        self,
        results_by_db: Dict[str, List[Dict[str, Any]]],
        join_ops: List[JoinOp],
    ) -> Optional[List[Dict[str, Any]]]:
        if not results_by_db or not join_ops:
            return None
        op = join_ops[0]
        left = results_by_db.get(op.left_db, [])
        right = results_by_db.get(op.right_db, [])
        if not left and not right:
            return None
        return self._join_datasets(left, right, op.left_key, op.right_key, op.join_type)

    def merge_results(
        self,
        results_by_index: Dict[int, List[Dict[str, Any]]],
        join_ops: List[JoinOp],
    ) -> List[Dict[str, Any]]:
        if not results_by_index:
            return []
        if not join_ops:
            return next(iter(results_by_index.values()))
        return next(iter(results_by_index.values()))

    def _join_datasets(
        self,
        left: List[Dict[str, Any]],
        right: List[Dict[str, Any]],
        key_left: str,
        key_right: str,
        join_type: str = "inner",
        transform: Optional[FormatTransform] = None,
    ) -> List[Dict[str, Any]]:
        normalized_right: List[Dict[str, Any]] = []
        for row in right:
            updated_row = dict(row)
            if transform and key_right in updated_row:
                updated_row[key_right] = self.apply_format_transformation(
                    updated_row[key_right],
                    transform.source_format,
                    transform.target_format,
                )
            normalized_right.append(updated_row)

        right_index: Dict[Any, List[Dict[str, Any]]] = {}
        for row in normalized_right:
            right_index.setdefault(row.get(key_right), []).append(row)

        result: List[Dict[str, Any]] = []
        matched_right_keys: set = set()
        for left_row in left:
            left_value = left_row.get(key_left)
            matches = right_index.get(left_value, [])
            if matches:
                matched_right_keys.add(left_value)
                for right_row in matches:
                    result.append({**left_row, **right_row})
            elif join_type in ("left", "full"):
                result.append(dict(left_row))

        if join_type in ("right", "full"):
            for right_key, right_rows in right_index.items():
                if right_key in matched_right_keys:
                    continue
                result.extend(dict(row) for row in right_rows)

        return result

    def apply_format_transformation(
        self,
        value: Any,
        source_format: str,
        target_format: str,
    ) -> Any:
        if value is None:
            return value
        try:
            if source_format == "integer" and "{" in target_format:
                return target_format.format(int(value))
            if source_format.startswith("prefix:"):
                prefix = source_format.split(":", 1)[1]
                return int(str(value).replace(prefix, "", 1))
            if source_format == "zero_padded":
                return int(str(value).lstrip("0") or "0")
            if target_format == "uppercase":
                return str(value).upper()
            if target_format == "lowercase":
                return str(value).lower()
        except (TypeError, ValueError):
            return value
        return value

    def validate_result(
        self, result: Any, expected_schema: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        issues: List[str] = []

        if result is None:
            return {"valid": False, "issues": ["Result is None"]}

        if isinstance(result, list):
            if result and isinstance(result[0], dict):
                for key, value in result[0].items():
                    if value is None and expected_schema.get(key, {}).get("nullable") is False:
                        issues.append(f"Unexpected null in column: {key}")

            seen: set = set()
            for row in result:
                marker = repr(sorted(row.items())) if isinstance(row, dict) else repr(row)
                if marker in seen:
                    issues.append("Duplicate rows detected")
                    break
                seen.add(marker)

        return {"valid": not issues, "issues": issues}
