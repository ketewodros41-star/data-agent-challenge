"""
Shared typed models for the Oracle Forge runtime scaffold.

These dataclasses define stable contracts between:
- the execution engine
- the MCP client
- the sandbox client
- the self-correction loop

The goal here is interface clarity, not final product completeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepKind(str, Enum):
    """High-level category of work a plan step performs."""

    DATABASE = "database"
    EXTRACT = "extract"
    TRANSFORM = "transform"
    MERGE = "merge"
    VALIDATE = "validate"


class StepRoute(str, Enum):
    """Execution backends available to the runtime."""

    MCP_TOOLBOX = "mcp_toolbox"
    SANDBOX = "sandbox"
    SELF_CORRECTION = "self_correction"


class ExecutionStatus(str, Enum):
    """Normalized status values used across traces and results."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass(frozen=True)
class ExecutionStep:
    """One executable unit within a runtime plan."""

    step_id: str
    kind: StepKind
    route: Optional[StepRoute] = None
    tool_name: Optional[str] = None
    database_type: Optional[str] = None
    code: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    input_refs: List[str] = field(default_factory=list)
    output_key: Optional[str] = None


@dataclass(frozen=True)
class ExecutionPlan:
    """Ordered runtime plan consumed by the execution engine."""

    plan_id: str
    steps: List[ExecutionStep]
    final_output_key: Optional[str] = None
    max_retries: int = 3


@dataclass(frozen=True)
class MCPToolCall:
    """Request contract for the MCP tool caller."""

    tool_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    database_type: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPToolResult:
    """Normalized result for a single MCP tool invocation."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    tool_name: Optional[str] = None


@dataclass(frozen=True)
class SandboxExecutionRequest:
    """Request contract for sandbox execution or validation."""

    code_plan: str
    trace_id: str
    inputs_payload: Optional[Dict[str, Any]] = None
    db_type: str = "transform"
    context: Dict[str, Any] = field(default_factory=dict)
    step_id: Optional[str] = None


@dataclass(frozen=True)
class SandboxResult:
    """Normalized result returned by the sandbox client."""

    success: bool
    result: Any = None
    trace: List[Dict[str, Any]] = field(default_factory=list)
    validation_status: str = "TODO"
    error_if_any: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ExecutionTrace:
    """Trace entry emitted for every routed execution step."""

    step_id: str
    step_kind: StepKind
    route: StepRoute
    status: ExecutionStatus
    attempt: int
    execution_time: float
    output: Any = None
    output_key: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureRecord:
    """Structured failure payload passed into self-correction."""

    step_id: str
    route: StepRoute
    error: str
    attempt: int
    trace: List[ExecutionTrace] = field(default_factory=list)


@dataclass(frozen=True)
class CorrectionDecision:
    """Decision returned by the self-correction loop."""

    retryable: bool
    reason: str
    updated_plan: Optional[ExecutionPlan] = None


@dataclass(frozen=True)
class ExecutionResult:
    """Final engine result returned to higher-level runtime callers."""

    success: bool
    status: ExecutionStatus
    final_output: Any = None
    outputs: Dict[str, Any] = field(default_factory=dict)
    trace: List[ExecutionTrace] = field(default_factory=list)
    attempts: int = 0
    correction_applied: bool = False
    error: Optional[str] = None
