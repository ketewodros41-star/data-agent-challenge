"""
Shared dataclasses for Oracle Forge Agent.
All cross-component contracts are defined here.
Never duplicate these definitions in other modules.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ColumnSchema:
    """Rich metadata for a single database column."""
    name: str
    data_type: str = "unknown"
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: Optional[str] = None  # "table.column" format for FK targets


@dataclass
class TableSchema:
    """Rich metadata for a single table/collection."""
    name: str
    columns: List[ColumnSchema] = field(default_factory=list)
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, str]] = field(default_factory=list)
    # Each FK entry: {from_col, to_table, to_col}


@dataclass
class SchemaInfo:
    database: str
    db_type: str  # postgres | mongodb | sqlite | duckdb
    tables: Dict[str, List[str]]  # table_name -> [column_names] (backward compat)
    table_schemas: Dict[str, TableSchema] = field(default_factory=dict)  # rich schema
    foreign_keys: List[Dict[str, str]] = field(default_factory=list)  # cross-table FKs
    sample_values: Dict[str, Dict[str, List[Any]]] = field(default_factory=dict)
    indexes: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class Document:
    source: str       # file path or identifier
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CorrectionEntry:
    query: str
    failure_cause: str
    correction: str
    timestamp: datetime
    database: Optional[str] = None


@dataclass
class ContextBundle:
    schema: Dict[str, SchemaInfo]                 # Layer 1: {db_name: SchemaInfo}
    institutional_knowledge: List[Document]        # Layer 2: KB documents
    corrections: List[CorrectionEntry]             # Layer 3: corrections log


@dataclass
class SubQuery:
    database: str
    query: str
    query_type: str                                # sql | mongo | duckdb | python
    dependencies: List[int] = field(default_factory=list)
    description: str = ""


@dataclass
class JoinOp:
    left_db: str
    right_db: str
    left_key: str
    right_key: str
    left_table: str = ""
    right_table: str = ""
    join_type: str = "inner"   # inner | left | right | full
    strategy: str = "hash"     # hash | nested_loop | merge


@dataclass
class QueryPlan:
    sub_queries: List[SubQuery]
    execution_order: List[int]
    join_operations: List[JoinOp]
    requires_sandbox: bool = False
    rationale: str = ""


@dataclass
class QueryResult:
    database: str
    data: Any
    columns: List[str] = field(default_factory=list)
    error: Optional[str] = None
    success: bool = True
    rows_affected: int = 0


@dataclass
class FormatTransform:
    """Format transformation for join key resolution across databases."""
    source_format: str           # e.g., "integer"
    target_format: str           # e.g., "CUST-{:05d}" or "string"
    transformation_function: str # Python expression: "int(value)", "str(value)", etc.


@dataclass
class FailureInfo:
    """Detected failure information from query execution (task 8.1)."""
    failure_type: str            # syntax | join_key_mismatch | wrong_db_type | data_quality | extraction_failure
    error_message: str
    failed_query: str
    database: str
    execution_trace: List[str] = field(default_factory=list)


@dataclass
class Diagnosis:
    """Root cause diagnosis of a detected failure (task 8.2)."""
    root_cause: str
    confidence: float            # 0.0–1.0
    evidence: List[str] = field(default_factory=list)
    similar_past_failures: List[Any] = field(default_factory=list)  # List[CorrectionEntry]
    suggested_fix: str = ""


@dataclass
class CorrectionStrategy:
    """Strategy for recovering from a diagnosed failure (task 8.3)."""
    strategy_type: str           # regenerate_query | transform_join_key | reroute_database | apply_quality_rules | alternative_extraction
    modified_query: Optional[str] = None
    format_transformations: List[FormatTransform] = field(default_factory=list)
    database_rerouting: Optional[str] = None
    extraction_method: Optional[str] = None
    rationale: str = ""


@dataclass
class QueryEvent:
    """Unit of trace recorded by EvaluationHarness for every agent invocation."""
    event_id: str
    timestamp: datetime
    session_id: str
    query_text: str
    available_databases: List[str]
    tool_calls: List[str]
    answer: Any
    expected_answer: Any
    correct: bool
    confidence: float
    correction_applied: bool = False   # True if Layer 3 fix was applied proactively
    error: Optional[str] = None
