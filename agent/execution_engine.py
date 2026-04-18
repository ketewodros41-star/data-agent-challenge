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
from typing import Any, Dict, List, Optional, Tuple
import json

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
    """Execute query plans, returning one QueryResult per sub-query.

    Supports two calling conventions:

    **Legacy** (``QueryPlan`` from ``agent.models.models``):
        ``engine = ExecutionEngine(toolbox=..., db_configs=...)``
        ``results: List[QueryResult] = engine.execute_plan(query_plan, context)``

    **Typed scaffold** (``ExecutionPlan`` from ``agent.types``):
        ``engine = ExecutionEngine(mcp_client=..., sandbox_client=..., self_correction=...)``
        ``result: ExecutionResult = engine.execute_plan(execution_plan, context)``
    """

    def __init__(
        self,
        toolbox: Optional[MCPToolbox] = None,
        db_configs: Optional[Dict[str, dict]] = None,
        mcp_client: Optional[MCPClient] = None,
        sandbox_client: Optional[SandboxClient] = None,
        self_correction: Optional[Any] = None,
    ):
        # Legacy interface
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
        # Typed scaffold interface
        self._mcp_client = mcp_client
        self._sandbox_client = sandbox_client
        if self_correction is None:
            from agent.self_correction import SelfCorrectionLoop
            self._self_correction: Any = SelfCorrectionLoop()
        else:
            self._self_correction = self_correction

    def execute_plan(
        self,
        plan: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a plan.  Dispatches to the typed or legacy path by plan type."""
        from agent.types import ExecutionPlan as _TypedPlan
        if isinstance(plan, _TypedPlan):
            return self._typed_execute_plan(plan, context or {})
        return self._legacy_execute_plan(plan, context if context is not None else {})

    # ── Typed scaffold execution ──────────────────────────────────────────────

    def _typed_execute_plan(
        self,
        plan: Any,
        context: Dict[str, Any],
    ) -> Any:
        """Execute a typed ``ExecutionPlan``, returning an ``ExecutionResult``."""
        from agent.types import (
            ExecutionResult,
            ExecutionStatus,
            ExecutionTrace,
            FailureRecord,
            MCPToolCall,
            SandboxExecutionRequest,
            StepKind,
            StepRoute,
        )

        trace: List[Any] = []
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
        while True:
            attempts += 1
            attempt_outputs: Dict[str, Any] = {}
            attempt_trace: List[Any] = []
            failed_step = None
            failed_error = ""

            for step in current_plan.steps:
                t0 = time.monotonic()

                if step.kind == StepKind.DATABASE:
                    tool_call = MCPToolCall(
                        tool_name=step.tool_name,
                        parameters=step.parameters or {},
                    )
                    tool_result = self._mcp_client.call_tool(tool_call)
                    elapsed = time.monotonic() - t0

                    if tool_result.success:
                        if step.output_key:
                            attempt_outputs[step.output_key] = tool_result.data
                        attempt_trace.append(ExecutionTrace(
                            step_id=step.step_id,
                            step_kind=step.kind,
                            route=StepRoute.MCP_TOOLBOX,
                            status=ExecutionStatus.SUCCEEDED,
                            attempt=attempts,
                            execution_time=elapsed,
                            output=tool_result.data,
                            output_key=step.output_key,
                        ))
                    else:
                        attempt_trace.append(ExecutionTrace(
                            step_id=step.step_id,
                            step_kind=step.kind,
                            route=StepRoute.MCP_TOOLBOX,
                            status=ExecutionStatus.FAILED,
                            attempt=attempts,
                            execution_time=elapsed,
                            error=tool_result.error,
                        ))
                        failed_step = step
                        failed_error = tool_result.error or "Tool call failed"
                        break

                else:  # TRANSFORM, MERGE, VALIDATE, EXTRACT → sandbox
                    inputs_payload = {
                        ref: attempt_outputs.get(ref)
                        for ref in (step.input_refs or [])
                    }
                    sandbox_request = SandboxExecutionRequest(
                        code_plan=step.code or "",
                        trace_id=f"{step.step_id}:attempt-{attempts}",
                        inputs_payload=inputs_payload,
                        step_id=step.step_id,
                        context={"shared_context": context},
                    )
                    sandbox_result = self._sandbox_client.execute(sandbox_request)
                    elapsed = time.monotonic() - t0

                    metadata: Dict[str, Any] = {
                        "validation_status": sandbox_result.validation_status
                    }
                    if sandbox_result.trace:
                        metadata["sandbox_trace"] = sandbox_result.trace

                    if sandbox_result.success:
                        if step.output_key:
                            attempt_outputs[step.output_key] = sandbox_result.result
                        attempt_trace.append(ExecutionTrace(
                            step_id=step.step_id,
                            step_kind=step.kind,
                            route=StepRoute.SANDBOX,
                            status=ExecutionStatus.SUCCEEDED,
                            attempt=attempts,
                            execution_time=elapsed,
                            output=sandbox_result.result,
                            output_key=step.output_key,
                            metadata=metadata,
                        ))
                    else:
                        error = sandbox_result.error_if_any or "Sandbox execution failed"
                        attempt_trace.append(ExecutionTrace(
                            step_id=step.step_id,
                            step_kind=step.kind,
                            route=StepRoute.SANDBOX,
                            status=ExecutionStatus.FAILED,
                            attempt=attempts,
                            execution_time=elapsed,
                            error=error,
                            metadata=metadata,
                        ))
                        failed_step = step
                        failed_error = error
                        break

            if failed_step is None:
                final_output = attempt_outputs.get(current_plan.final_output_key)
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
                    outputs=attempt_outputs,
                    trace=trace + attempt_trace,
                    attempts=attempts,
                    correction_applied=correction_applied,
                )

            # Consult self-correction loop
            failure = FailureRecord(
                step_id=failed_step.step_id,
                route=(
                    StepRoute.MCP_TOOLBOX
                    if failed_step.kind == StepKind.DATABASE
                    else StepRoute.SANDBOX
                ),
                error=failed_error,
                attempt=attempts,
                trace=trace + attempt_trace,
            )
            decision = self._self_correction.handle_failure(current_plan, failure)

            if not decision.retryable or attempts >= current_plan.max_retries:
                return ExecutionResult(
                    success=False,
                    status=ExecutionStatus.FAILED,
                    trace=trace + attempt_trace,
                    attempts=attempts,
                    correction_applied=correction_applied,
                    error=failed_error,
                )

            correction_trace = ExecutionTrace(
                step_id=failed_step.step_id,
                step_kind=failed_step.kind,
                route=StepRoute.SELF_CORRECTION,
                status=ExecutionStatus.RETRYING,
                attempt=attempts,
                execution_time=0.0,
                metadata={"reason": decision.reason},
            )
            trace = trace + attempt_trace + [correction_trace]
            correction_applied = True
            current_plan = decision.updated_plan or current_plan

    # ── Legacy execution ──────────────────────────────────────────────────────

    def _legacy_execute_plan(
        self,
        plan: QueryPlan,
        context: Dict[str, Any],
    ) -> List[QueryResult]:
        """Execute a legacy ``QueryPlan``, returning a list of ``QueryResult``."""
        results: List[QueryResult] = []

        for idx in plan.execution_order:
            sq = plan.sub_queries[idx]
            try:
                mongo_local_plan = self._maybe_prepare_local_mongo_aggregation(sq)
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
                    # The MCP toolbox sometimes returns a DB error as a 200 OK with
                    # {"error": "..."} embedded in the content.  Detect and surface it
                    # so the self-correction loop can react to the real failure.
                    embedded_error = self._extract_embedded_error(data)
                    if embedded_error:
                        results.append(
                            QueryResult(
                                database=sq.database,
                                data=None,
                                error=embedded_error,
                                success=False,
                            )
                        )
                    else:
                        if mongo_local_plan is not None:
                            data = self._apply_local_mongo_aggregation(data, mongo_local_plan)
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

    @staticmethod
    def _extract_embedded_error(data: Any) -> Optional[str]:
        """
        Detect DB errors embedded inside a nominally-successful MCP response.

        The Google MCP Toolbox returns HTTP 200 even for query errors, with the
        error message encoded as ``[{"error": "..."}]`` in the content payload.
        Return the error string so callers can surface it as a real failure.
        """
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and "error" in first and len(first) == 1:
                return str(first["error"])
            # String element that starts with the toolbox error prefix
            if isinstance(first, str) and first.startswith("error processing request"):
                return first
        if isinstance(data, str) and data.startswith("error processing request"):
            return data
        return None

    # Mapping: logical db_id → the postgres-execute-sql tool name in tools.yaml.
    # Each PostgreSQL database has its own tool so queries hit the right database.
    _PG_TOOL_MAP: Dict[str, str] = {
        "books_database":         "run_query",            # bookreview_db
        "business_database":      "run_query_googlelocal",
        "clinical_database":      "run_query_pancancer",
        "CPCDefinition_database": "run_query_patents",
        "support_database":       "run_query_crm_support",
    }

    def _build_tool_call(self, sq: SubQuery) -> tuple[str, Dict[str, Any]]:
        """Map a sub-query to the MCP tool and its parameters."""
        db_type = self._db_configs.get(sq.database, {}).get("type", sq.query_type).lower()
        normalized_query = self._normalize_query_text(sq.query)

        if db_type in ("postgresql", "postgres"):
            static_tool = self._match_static_pg_tool(normalized_query)
            if static_tool:
                return static_tool, {}
            # Route to the per-database tool; fall back to run_query (bookreview default)
            pg_tool = self._PG_TOOL_MAP.get(sq.database, "run_query")
            return pg_tool, {"query": normalized_query}

        if db_type == "sqlite":
            sqlite_tool = self._db_configs.get(sq.database, {}).get("mcp_tool", "sqlite_query")
            return sqlite_tool, {"sql": normalized_query}

        if db_type == "duckdb":
            duckdb_tool = self._db_configs.get(sq.database, {}).get("mcp_tool", "duckdb_query")
            return duckdb_tool, {"sql": normalized_query}

        if db_type == "mongodb":
            collection, pipeline = self._parse_mongo_query(sq.query)
            collection, pipeline = self._parse_mongo_query(normalized_query)
            tool_name = "find_yelp_checkins" if collection == "checkin" else "find_yelp_businesses"
            request_payload = self._build_mongo_find_payload(pipeline)
            return tool_name, request_payload

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
        """Extract collection hint and valid JSON pipeline from a MongoDB query string.

        The query string is what the LLM generated — typically a JSON aggregation
        pipeline ``[{...}, ...]`` or a find-filter ``{...}``.  The previous
        implementation always returned ``"{}"`` (empty filter), so every MongoDB
        call returned unfiltered data.  We now pass the actual query through.
        """
        q_lower = query.lower()

        # Detect the target collection from keywords.  Prefer explicit names;
        # fall back to "business" for anything else (most Yelp queries).
        if "checkin" in q_lower:
            collection = "checkin"
        else:
            collection = "business"

        stripped = query.strip()

        # Fast path: the entire string is valid JSON — use it as-is.
        try:
            json.loads(stripped)
            return collection, stripped
        except (json.JSONDecodeError, ValueError):
            pass

        # Slow path: the LLM may have wrapped the JSON in prose or code fences.
        # Extract the outermost JSON array or object.
        json_match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', stripped)
        if json_match:
            candidate = json_match.group(1)
            try:
                json.loads(candidate)
                return collection, candidate
            except (json.JSONDecodeError, ValueError):
                pass

        # Final fallback: empty filter (returns all documents).  This is the
        # pre-existing behaviour — better than crashing, but the LLM output
        # should almost always be parseable JSON.
        return collection, "{}"

    @staticmethod
    def _build_mongo_find_payload(pipeline: str) -> Dict[str, Any]:
        """
        Convert a Mongo query string into parameters for the toolbox `mongodb-find` tools.

        The toolbox only exposes `find` operations today, so if the query is an
        aggregation pipeline we extract the leading `$match` filter and fetch a
        larger document set for client-side post-processing.
        """
        default_payload: Dict[str, Any] = {"filterPayload": "{}", "limit": 20}
        try:
            parsed = json.loads(pipeline)
        except (json.JSONDecodeError, TypeError, ValueError):
            return default_payload

        if isinstance(parsed, dict):
            return {"filterPayload": json.dumps(parsed), "limit": 5000}

        if isinstance(parsed, list):
            for stage in parsed:
                if isinstance(stage, dict) and "$match" in stage and isinstance(stage["$match"], dict):
                    return {"filterPayload": json.dumps(stage["$match"]), "limit": 5000}
            return default_payload

        return default_payload

    def _maybe_prepare_local_mongo_aggregation(self, sq: SubQuery) -> Optional[Dict[str, Any]]:
        db_type = self._db_configs.get(sq.database, {}).get("type", sq.query_type).lower()
        if db_type != "mongodb":
            return None

        normalized_query = self._normalize_query_text(sq.query)
        _, pipeline = self._parse_mongo_query(normalized_query)
        try:
            parsed = json.loads(pipeline)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

        if not isinstance(parsed, list):
            return None

        group_stage = None
        for stage in parsed:
            if isinstance(stage, dict) and "$group" in stage and isinstance(stage["$group"], dict):
                group_stage = stage["$group"]
                break
        if group_stage is None:
            return None

        aggregate_spec = self._extract_supported_group_aggregation(group_stage)
        if aggregate_spec is None:
            return None

        return {"aggregate": aggregate_spec}

    @staticmethod
    def _extract_supported_group_aggregation(group_stage: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Support a narrow subset of Mongo aggregations locally.

        Today this is enough to unblock the Yelp baseline:
        - `{$group: {"_id": null, "average_rating": {"$avg": "$stars"}}}`
        """
        if group_stage.get("_id", object()) is not None:
            return None

        aggregate_fields = [(key, value) for key, value in group_stage.items() if key != "_id"]
        if len(aggregate_fields) != 1:
            return None

        output_field, expression = aggregate_fields[0]
        if not isinstance(expression, dict) or len(expression) != 1:
            return None

        operator, operand = next(iter(expression.items()))
        if operator not in {"$avg"}:
            return None
        if not isinstance(operand, str) or not operand.startswith("$"):
            return None

        return {
            "operator": operator,
            "source_field": operand[1:],
            "output_field": output_field,
        }

    @staticmethod
    def _apply_local_mongo_aggregation(data: Any, local_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = data if isinstance(data, list) else []
        aggregate = local_plan.get("aggregate") or {}
        operator = aggregate.get("operator")
        source_field = aggregate.get("source_field")
        output_field = aggregate.get("output_field")

        if operator != "$avg" or not source_field or not output_field:
            return rows

        numeric_values: List[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get(source_field)
            if isinstance(value, (int, float)):
                numeric_values.append(float(value))

        average = sum(numeric_values) / len(numeric_values) if numeric_values else None
        return [{output_field: average}]

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
