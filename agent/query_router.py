"""
QueryRouter — Entity extraction, multi-DB routing, and query plan generation.

Converts a natural language question + ContextBundle into a QueryPlan
(list of SubQueries with execution order and join operations).

Sub-tasks implemented here:
  5.1 - Query analysis: entity extraction, DB matching, join detection
  5.2 - Query decomposition: QueryPlan assembly, topological execution order,
         join strategy selection
  5.3 - Dialect detection: QueryDialect/QueryType enums, dialect templates,
         query type classifier
"""

from __future__ import annotations

import json
import re
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent.llm_client import LLMClient

from agent.models.models import (
    ContextBundle,
    JoinOp,
    QueryPlan,
    SchemaInfo,
    SubQuery,
)
from utils.join_key_resolver import resolve_join_keys

_REPO_ROOT = Path(__file__).parent.parent
_UNSTRUCTURED_FIELDS_FILE = _REPO_ROOT / "kb" / "domain" / "unstructured_fields.md"

# ── Enums ─────────────────────────────────────────────────────────────────────

class QueryDialect(str, Enum):
    """Database-specific query language dialect."""
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"
    DUCKDB = "duckdb"
    MONGODB = "mongodb"


class QueryType(str, Enum):
    """Semantic classification of what the query is trying to do."""
    SELECT = "select"           # Simple row fetch
    AGGREGATE = "aggregate"     # COUNT, SUM, AVG, GROUP BY
    FILTER = "filter"           # WHERE-focused retrieval
    JOIN = "join"               # Cross-table / cross-database
    TIMESERIES = "timeseries"   # Date-grouped or trending data
    FULL_TEXT = "full_text"     # Text search / keyword match


class JoinStrategy(str, Enum):
    """Physical join algorithm hint for the ExecutionEngine."""
    HASH = "hash"               # Best for large-to-large joins
    NESTED_LOOP = "nested_loop" # Best when one side is small
    MERGE = "merge"             # Best when both sides are pre-sorted on key


# ── Dialect-specific query templates ─────────────────────────────────────────
# These are illustrative examples injected into the LLM prompt so the model
# generates queries in the correct syntax for each database + query type.

_DIALECT_TEMPLATES: Dict[QueryDialect, Dict[QueryType, str]] = {
    QueryDialect.POSTGRESQL: {
        QueryType.SELECT:     "SELECT col1, col2 FROM table WHERE condition LIMIT 100",
        QueryType.AGGREGATE:  "SELECT group_col, COUNT(*), AVG(num_col) FROM table GROUP BY group_col ORDER BY COUNT(*) DESC",
        QueryType.FILTER:     "SELECT * FROM table WHERE col = 'value' AND num_col > 0",
        QueryType.JOIN:       "SELECT a.col, b.col FROM table_a a JOIN table_b b ON a.key = b.key",
        QueryType.TIMESERIES: "SELECT DATE_TRUNC('month', date_col) AS period, COUNT(*) FROM table GROUP BY 1 ORDER BY 1",
        QueryType.FULL_TEXT:  "SELECT * FROM table WHERE text_col ILIKE '%keyword%'",
    },
    QueryDialect.SQLITE: {
        QueryType.SELECT:     "SELECT col1, col2 FROM table WHERE condition LIMIT 100",
        QueryType.AGGREGATE:  "SELECT group_col, COUNT(*), AVG(num_col) FROM table GROUP BY group_col",
        QueryType.FILTER:     "SELECT * FROM table WHERE col = 'value'",
        QueryType.JOIN:       "SELECT a.col, b.col FROM table_a a JOIN table_b b ON a.key = b.key",
        QueryType.TIMESERIES: "SELECT strftime('%Y-%m', date_col) AS period, COUNT(*) FROM table GROUP BY 1",
        QueryType.FULL_TEXT:  "SELECT * FROM table WHERE text_col LIKE '%keyword%'",
    },
    QueryDialect.DUCKDB: {
        QueryType.SELECT:     "SELECT col1, col2 FROM table WHERE condition LIMIT 100",
        QueryType.AGGREGATE:  "SELECT group_col, COUNT(*), AVG(num_col) FROM table GROUP BY group_col",
        QueryType.FILTER:     "SELECT * FROM table WHERE col = 'value'",
        QueryType.JOIN:       "SELECT a.col, b.col FROM table_a a JOIN table_b b ON a.key = b.key",
        QueryType.TIMESERIES: "SELECT DATE_TRUNC('month', date_col) AS period, COUNT(*) FROM table GROUP BY 1",
        QueryType.FULL_TEXT:  "SELECT * FROM table WHERE text_col ILIKE '%keyword%'",
    },
    QueryDialect.MONGODB: {
        QueryType.SELECT:     '[{"$match": {"field": "value"}}, {"$project": {"_id": 0, "field1": 1, "field2": 1}}]',
        QueryType.AGGREGATE:  '[{"$group": {"_id": "$group_field", "count": {"$sum": 1}, "avg_val": {"$avg": "$num_field"}}}]',
        QueryType.FILTER:     '[{"$match": {"field": {"$gt": 0}, "other_field": "value"}}]',
        QueryType.JOIN:       '[{"$lookup": {"from": "other_collection", "localField": "key", "foreignField": "key", "as": "joined"}}, {"$unwind": "$joined"}]',
        QueryType.TIMESERIES: '[{"$group": {"_id": {"year": {"$year": "$date_field"}, "month": {"$month": "$date_field"}}, "count": {"$sum": 1}}}]',
        QueryType.FULL_TEXT:  '[{"$match": {"text_field": {"$regex": "keyword", "$options": "i"}}}]',
    },
}

# ── Query type classification keywords ────────────────────────────────────────

_AGGREGATE_KEYWORDS: Set[str] = {
    "average", "avg", "count", "how many", "sum", "total", "maximum", "minimum",
    "max", "min", "mean", "median", "top", "most", "least", "rank", "percentage",
    "proportion", "distribution",
}
_TIMESERIES_KEYWORDS: Set[str] = {
    "month", "year", "day", "trend", "over time", "weekly", "monthly", "yearly",
    "date", "period", "quarter", "daily", "history", "growth", "change over",
}
_FULL_TEXT_KEYWORDS: Set[str] = {
    "mention", "contain", "description", "about",
    "keyword", "phrase", "written", "says", "talk about", "refers to",
}
_JOIN_KEYWORDS: Set[str] = {
    "across", "between", "both", "combined", "join", "together", "correlation",
    "match", "relate", "compare",
}

# Databases that support standard SQL
_SQL_DBS: Set[str] = {"postgres", "sqlite", "duckdb"}

# Databases considered "large" for join strategy selection
_LARGE_DBS: Set[str] = {"postgres", "duckdb", "mongodb"}

# Entity-to-database hints (supplements schema-based routing)
_ENTITY_DB_HINTS: Dict[str, str] = {
    "review": "mongodb",
    "reviews": "mongodb",
    "comment": "mongodb",
    "text": "mongodb",
    "customer": "postgres",
    "customers": "postgres",
    "order": "postgres",
    "orders": "postgres",
    "transaction": "postgres",
    "transactions": "postgres",
    "product": "sqlite",
    "products": "sqlite",
    "category": "sqlite",
    "categories": "sqlite",
}


class QueryRouter:
    """
    Produces a QueryPlan from a natural language question and a ContextBundle.
    All LLM calls use temperature=0 for deterministic output.
    """

    def __init__(self, client: Optional[LLMClient] = None):
        self._client = client or LLMClient()
        self._unstructured_fields = _load_unstructured_fields()

    # ── Public API ────────────────────────────────────────────────────────────

    def route(
        self,
        question: str,
        context: ContextBundle,
        available_databases: List[str],
    ) -> QueryPlan:
        """
        Main entry point.  Returns a QueryPlan ready for ExecutionEngine.
        """
        entities = self._extract_entities(question)
        db_assignments = self._assign_databases(entities, context, available_databases)
        query_type = self._classify_query_type(question)

        # Discovery phase: validate table selections against live schema before
        # generating any SQL.  Compares entity names to every table in the assigned
        # database and returns the confirmed subset so the query-generation prompt
        # targets the right tables instead of the entire schema dump.
        table_selections = self._discover_relevant_tables(db_assignments, context)

        sub_queries = self._build_sub_queries(
            question, db_assignments, context, query_type, table_selections
        )
        join_ops = self._detect_join_ops(sub_queries, context)
        execution_order = self._determine_execution_order(sub_queries)
        requires_sandbox = self._check_sandbox_needed(entities)

        return QueryPlan(
            sub_queries=sub_queries,
            execution_order=execution_order,
            join_operations=join_ops,
            requires_sandbox=requires_sandbox,
            rationale=(
                f"Entities={entities} → DBs={list(db_assignments.keys())} "
                f"| type={query_type.value} | tables={table_selections} "
                f"| order={execution_order}"
            ),
        )

    # ── 5.3 Dialect detection ─────────────────────────────────────────────────

    def detect_dialect(self, db_name: str) -> QueryDialect:
        """Map a database name to its QueryDialect."""
        mapping: Dict[str, QueryDialect] = {
            "postgres": QueryDialect.POSTGRESQL,
            "postgresql": QueryDialect.POSTGRESQL,
            "sqlite": QueryDialect.SQLITE,
            "duckdb": QueryDialect.DUCKDB,
            "mongodb": QueryDialect.MONGODB,
            "mongo": QueryDialect.MONGODB,
        }
        return mapping.get(db_name.lower(), QueryDialect.POSTGRESQL)

    def _classify_query_type(self, question: str) -> QueryType:
        """
        Classify the semantic intent of the question without an LLM call.
        Returns the most specific matching QueryType.
        """
        q = question.lower()

        # Check from most-specific to least-specific
        if any(kw in q for kw in _TIMESERIES_KEYWORDS):
            return QueryType.TIMESERIES
        if any(kw in q for kw in _FULL_TEXT_KEYWORDS):
            return QueryType.FULL_TEXT
        if any(kw in q for kw in _JOIN_KEYWORDS):
            return QueryType.JOIN
        if any(kw in q for kw in _AGGREGATE_KEYWORDS):
            return QueryType.AGGREGATE
        return QueryType.FILTER

    def _get_dialect_hint(self, db_name: str, query_type: QueryType) -> str:
        """Return a dialect-specific example query string to guide the LLM."""
        dialect = self.detect_dialect(db_name)
        template = _DIALECT_TEMPLATES.get(dialect, {}).get(query_type, "")
        if template:
            return f"Example {dialect.value} {query_type.value} query:\n{template}"
        return ""

    # ── 5.2 Join strategy selection ───────────────────────────────────────────

    def _select_join_strategy(
        self,
        left_sq: SubQuery,
        right_sq: SubQuery,
        schema: Dict[str, SchemaInfo],
    ) -> JoinStrategy:
        """
        Choose a physical join algorithm based on the data source sizes.

        - Both large databases  → HASH (handles big-to-big efficiently)
        - One small database    → NESTED_LOOP (index-friendly for small right side)
        - Fall-through default  → HASH
        """
        left_large = left_sq.database.lower() in _LARGE_DBS
        right_large = right_sq.database.lower() in _LARGE_DBS

        if left_large and right_large:
            return JoinStrategy.HASH
        if not right_large:
            return JoinStrategy.NESTED_LOOP
        # left small, right large — still prefer nested loop (iterate small left)
        return JoinStrategy.NESTED_LOOP

    # ── 5.2 Execution order (topological sort) ────────────────────────────────

    def _determine_execution_order(self, sub_queries: List[SubQuery]) -> List[int]:
        """
        Return a valid topological execution order for the sub-queries.

        Uses Kahn's algorithm over SubQuery.dependencies (list of indices that
        must complete before this sub-query can start).  Falls back to
        sequential order [0, 1, …] if a dependency cycle is detected.
        """
        n = len(sub_queries)
        in_degree = [0] * n
        adj: Dict[int, List[int]] = {i: [] for i in range(n)}

        for i, sq in enumerate(sub_queries):
            for dep in sq.dependencies:
                if 0 <= dep < n:
                    adj[dep].append(i)
                    in_degree[i] += 1

        queue: deque[int] = deque(i for i in range(n) if in_degree[i] == 0)
        order: List[int] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Cycle detected — fall back to sequential
        if len(order) != n:
            return list(range(n))

        return order

    # ── 5.1 Entity extraction ─────────────────────────────────────────────────

    def _extract_entities(self, question: str) -> List[str]:
        """Use LLM to extract entity types from the question."""
        prompt = (
            "Extract the business entity types (e.g. customers, orders, reviews, products) "
            "mentioned in this question. Return a JSON array of strings only.\n\n"
            f"Question: {question}"
        )
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Extract JSON array from response
            match = re.search(r"\[.*?\]", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass
            parsed = [e.strip().strip('"') for e in text.strip("[]").split(",") if e.strip()]
            if parsed:
                return parsed
        except Exception:
            pass
        return self._extract_entities_locally(question)

    def _extract_entities_locally(self, question: str) -> List[str]:
        """Best-effort local entity extraction when the LLM is unavailable."""
        lowered = question.lower()
        candidates: List[str] = []

        # Prefer explicit SQL-style identifiers first.
        for match in re.findall(r"\b[a-z_][a-z0-9_]*\b", lowered):
            if "_" in match:
                candidates.append(match)

        # Capture identifiers that appear near "table"/"collection".
        for pattern in (
            r"\b(?:table|collection)\s+([a-z_][a-z0-9_]*)\b",
            r"\b([a-z_][a-z0-9_]*)\s+(?:table|collection)\b",
        ):
            for match in re.findall(pattern, lowered):
                candidates.append(match)

        # Final fallback: keep meaningful keywords rather than returning nothing.
        if not candidates:
            stopwords = {
                "a", "an", "and", "are", "does", "for", "from", "have", "how",
                "in", "is", "me", "of", "show", "table", "the", "what", "which",
                "with",
            }
            for token in re.findall(r"\b[a-z][a-z0-9_]*\b", lowered):
                if token not in stopwords and len(token) > 2:
                    candidates.append(token)

        deduped: List[str] = []
        seen = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                deduped.append(candidate)
        return deduped

    # ── 5.1 Database assignment ───────────────────────────────────────────────

    def _assign_databases(
        self,
        entities: List[str],
        context: ContextBundle,
        available_databases: List[str],
    ) -> Dict[str, Set[str]]:
        """
        Map entity types to database names.
        Returns {db_name: {entity, ...}}.
        Only assigns to databases in available_databases.
        """
        assignment: Dict[str, Set[str]] = {}
        schema = context.schema

        for entity in entities:
            entity_lower = entity.lower()

            # 1. Hint-based routing (fast path)
            hint_db = _ENTITY_DB_HINTS.get(entity_lower)
            if hint_db and hint_db in available_databases:
                assignment.setdefault(hint_db, set()).add(entity)
                continue

            # 2. Schema-based routing: find which DB has a table matching the entity
            matched_db = None
            for db_name, schema_info in schema.items():
                if db_name not in available_databases:
                    continue
                for table_name in schema_info.tables:
                    if entity_lower in table_name.lower():
                        matched_db = db_name
                        break
                if matched_db:
                    break

            if matched_db:
                assignment.setdefault(matched_db, set()).add(entity)
            elif available_databases:
                # Default to first available DB
                assignment.setdefault(available_databases[0], set()).add(entity)

        return assignment

    # ── Discovery phase ───────────────────────────────────────────────────────

    def _discover_relevant_tables(
        self,
        db_assignments: Dict[str, Set[str]],
        context: ContextBundle,
    ) -> Dict[str, List[str]]:
        """
        Discovery phase: compare entity names against every table in each assigned
        database and return only the confirmed matches.

        This runs before query generation so _build_sub_queries() can focus its
        prompt on the right tables rather than dumping the entire schema.  No LLM
        call is made — matching is purely name-overlap so it is fast and free.

        Returns {db_name: [confirmed_table_names]}.
        Falls back to all tables in the database when no entity matches any table
        (prevents silent omission of schema context).
        """
        confirmed: Dict[str, List[str]] = {}
        for db_name, entities in db_assignments.items():
            schema_info = context.schema.get(db_name)
            if not schema_info:
                confirmed[db_name] = []
                continue

            relevant: List[str] = []
            for table_name in schema_info.tables:
                table_lower = table_name.lower()
                for entity in entities:
                    entity_lower = entity.lower()
                    if entity_lower in table_lower or table_lower in entity_lower:
                        if table_name not in relevant:
                            relevant.append(table_name)

            # Fall back to all tables so the prompt always has something to work with
            confirmed[db_name] = relevant or list(schema_info.tables.keys())

        return confirmed

    # ── 5.2 Sub-query generation ──────────────────────────────────────────────

    def _build_sub_queries(
        self,
        question: str,
        db_assignments: Dict[str, Set[str]],
        context: ContextBundle,
        query_type: QueryType = QueryType.FILTER,
        table_selections: Optional[Dict[str, List[str]]] = None,
    ) -> List[SubQuery]:
        sub_queries: List[SubQuery] = []

        for db_name, entities in db_assignments.items():
            schema_info = context.schema.get(db_name)
            schema_text = _format_schema(schema_info) if schema_info else "Schema unavailable"

            # Filter KB docs to those relevant to this database to avoid truncation
            # cutting off schema entries for later datasets (e.g. bookreview at line 471)
            relevant_docs = [
                doc for doc in context.institutional_knowledge
                if db_name.lower() in doc.content.lower()
                or db_name.replace("_database", "").lower() in doc.content.lower()
            ] or context.institutional_knowledge  # fall back to all docs if none match
            kb_text = "\n\n".join(doc.content for doc in relevant_docs)

            correction_text = ""
            for entry in context.corrections[-10:]:  # last 10 corrections
                if entry.database == db_name or entry.database is None:
                    correction_text += (
                        f"- Query: {entry.query}\n"
                        f"  Fix: {entry.correction}\n"
                    )

            dialect = self.detect_dialect(db_name)
            # 5.3: use query_type to set the correct query_type string for SubQuery
            query_type_str = "sql" if dialect != QueryDialect.MONGODB else "mongo"
            dialect_hint = self._get_dialect_hint(db_name, query_type)

            # Discovery hint: tables confirmed by the pre-generation schema scan
            confirmed_tables = (table_selections or {}).get(db_name, [])
            discovery_note = (
                f"Confirmed tables for this query (from discovery phase): "
                f"{', '.join(confirmed_tables)}\n"
                "Start your query from one of these tables unless the full schema "
                "shows a better choice.\n\n"
                if confirmed_tables else ""
            )

            prompt = (
                f"Generate a {dialect.value} query to answer this question using only the "
                f"{db_name} database.\n\n"
                f"Question: {question}\n\n"
                f"Query intent: {query_type.value}\n\n"
                f"Entities of interest: {', '.join(entities)}\n\n"
                f"{discovery_note}"
                f"Schema:\n{schema_text}\n\n"
                + (f"{dialect_hint}\n\n" if dialect_hint else "")
                + f"Domain knowledge:\n{kb_text}\n\n"
                + (f"Known corrections:\n{correction_text}\n\n" if correction_text else "")
                + "Return ONLY the raw query string, no explanation."
            )

            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            query_text = response.content[0].text.strip()
            # Strip markdown code fences — LLM sometimes adds them despite the instruction
            query_text = re.sub(r"^```[a-z]*\n?", "", query_text, flags=re.IGNORECASE)
            query_text = re.sub(r"\n?```$", "", query_text).strip()

            sub_queries.append(
                SubQuery(
                    database=db_name,
                    query=query_text,
                    query_type=query_type_str,
                    description=f"Fetch {', '.join(entities)} from {db_name} ({query_type.value})",
                )
            )

        return sub_queries

    # ── 5.1 Join detection ────────────────────────────────────────────────────

    def _detect_join_ops(
        self, sub_queries: List[SubQuery], context: ContextBundle
    ) -> List[JoinOp]:
        if len(sub_queries) < 2:
            return []

        raw_joins = resolve_join_keys(sub_queries, context.schema)

        # Enrich each JoinOp with a selected join strategy
        enriched: List[JoinOp] = []
        for jo in raw_joins:
            left_sq = next((sq for sq in sub_queries if sq.database == jo.left_db), None)
            right_sq = next((sq for sq in sub_queries if sq.database == jo.right_db), None)
            strategy = (
                self._select_join_strategy(left_sq, right_sq, context.schema)
                if left_sq and right_sq
                else JoinStrategy.HASH
            )
            enriched.append(
                JoinOp(
                    left_db=jo.left_db,
                    right_db=jo.right_db,
                    left_key=jo.left_key,
                    right_key=jo.right_key,
                    left_table=jo.left_table,
                    right_table=jo.right_table,
                    join_type=jo.join_type,
                    strategy=strategy.value,
                )
            )
        return enriched

    # ── Sandbox detection ─────────────────────────────────────────────────────

    def _check_sandbox_needed(self, entities: List[str]) -> bool:
        for entity in entities:
            if entity.lower() in self._unstructured_fields:
                return True
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_schema(schema_info: Any) -> str:
    lines = [f"Database: {schema_info.database} ({schema_info.db_type})"]
    for table, columns in schema_info.tables.items():
        lines.append(f"  {table}: {', '.join(columns)}")
    return "\n".join(lines)


def _load_unstructured_fields() -> Set[str]:
    if not _UNSTRUCTURED_FIELDS_FILE.exists():
        return set()
    text = _UNSTRUCTURED_FIELDS_FILE.read_text(encoding="utf-8")
    fields: Set[str] = set()
    for line in text.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped and not stripped.startswith("#"):
            fields.add(stripped.lower())
    return fields
