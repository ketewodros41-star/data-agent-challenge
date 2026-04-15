"""
SelfCorrectionLoop — Failure detection, retry, and correction logging.

Implements the three-phase correction cycle (tasks 8.1–8.4):
  1. detect_failure()       — classify failure type from error messages
  2. diagnose_root_cause()  — consult Layer 2 (join key glossary) and
                              Layer 3 (corrections log) for context
  3. generate_correction()  — build a targeted CorrectionStrategy

execute_with_correction() orchestrates retries and proactively applies
Layer 3 corrections before the first attempt (self-learning loop).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agent.llm_client import LLMClient

from agent.models.models import (
    CorrectionStrategy,
    Diagnosis,
    FailureInfo,
    FormatTransform,
    QueryPlan,
    QueryResult,
    SubQuery,
)

if TYPE_CHECKING:
    from agent.context_manager import ContextManager
    from agent.execution_engine import ExecutionEngine

MAX_RETRIES = 3

# ── Failure-type pattern registry (task 8.1) ──────────────────────────────────

_SYNTAX_RE = re.compile(
    r"syntax error|invalid syntax|unexpected token|parse error|malformed|"
    r'near "[^"]+"'
    r"|unterminated|unexpected end|unknown column|"
    r"no such (?:column|table|function)|does not exist",
    re.IGNORECASE,
)

_JOIN_KEY_RE = re.compile(
    r"(?:join|merge).*(?:empty|0 rows|no rows|mismatch)|"
    r"type mismatch.*join|operator does not exist|"
    r"cannot cast|incompatible types|"
    r"(?:0 rows|no match).*(?:join|merge)",
    re.IGNORECASE,
)

_WRONG_DB_RE = re.compile(
    r"unsupported operation|not supported|invalid command|"
    r"command not found|unknown command|operation not supported|"
    r"pipeline.*invalid|invalid aggregation|sql.*not supported",
    re.IGNORECASE,
)

_DATA_QUALITY_RE = re.compile(
    r"null.*constraint|not null.*violated|"
    r"duplicate.*key|unique.*constraint|"
    r"violates.*constraint|check.*constraint|"
    r"referential.*integrity|foreign.*key.*violation",
    re.IGNORECASE,
)

_EXTRACTION_RE = re.compile(
    r"extraction.*fail|invalid json|json.*parse|"
    r"no data.*extract|extraction.*error|"
    r"unstructured.*fail|sandbox.*error",
    re.IGNORECASE,
)

# ── Known join-key format mismatches (kb/domain/dataset_overview.md) ──────────
# Applied proactively on every matching query before the first execution attempt.
# trigger  — regex that must match somewhere in the SQL text
# hint     — plain-English correction description passed to the LLM rewriter
_KNOWN_JOIN_FIXES: list[dict] = [
    {
        # Yelp: MongoDB business_id uses 'businessid_N'; DuckDB business_ref uses
        # 'businessref_N'.  Strip the text prefix and compare integer suffixes.
        "trigger": re.compile(r"\bbusiness(?:_id|_ref)\b", re.IGNORECASE),
        "hint": (
            "yelp join key mismatch: business_id (MongoDB) format is 'businessid_N'; "
            "business_ref (DuckDB) format is 'businessref_N'. "
            "Strip the text prefix and cast to integer to compare only the numeric suffix: "
            "e.g. CAST(REGEXP_REPLACE(business_id, '[^0-9]', '', 'g') AS INTEGER). "
            "Apply this normalisation to whichever column is present in this query."
        ),
    },
    {
        # Salesforce: ~25 % of Id-like fields carry a leading '#' character.
        # Trigger on Salesforce-specific FK column names.
        "trigger": re.compile(
            r"\b(?:AccountId|ContactId|OpportunityId|OwnerId|LeadId|CaseId)\b",
            re.IGNORECASE,
        ),
        "hint": (
            "salesforce Id fields: approximately 25 % of Id-like values carry a "
            "leading '#' character (e.g. '#001Wt00000PFj4z' instead of "
            "'001Wt00000PFj4z'). Strip '#' before joining: "
            "REPLACE(col, '#', '') or LTRIM(col, '#')."
        ),
    },
    {
        # TCGA / genomics: Patient_description contains the barcode as free text;
        # ParticipantBarcode is the structured FK in molecular tables.
        "trigger": re.compile(
            r"\bPatient_description\b|\bParticipantBarcode\b", re.IGNORECASE
        ),
        "hint": (
            "genomics join key: Patient_description (clinical_info) contains the "
            "patient barcode/UUID as embedded free text. Extract the barcode with "
            "a regex or LIKE pattern before joining to ParticipantBarcode in "
            "molecular tables."
        ),
    },
]


class SelfCorrectionLoop:
    """
    Coordinates retry attempts around ExecutionEngine with structured
    failure classification, diagnosis, and targeted correction.

    Returns dict with keys: results, correction_applied, retries_used, success.

    Can also be used as a base class: subclass and override ``handle_failure``
    to plug a custom retry policy into the typed ExecutionEngine.
    """

    def __init__(
        self,
        execution_engine: Optional["ExecutionEngine"] = None,
        context_manager: Optional["ContextManager"] = None,
        client: Optional[LLMClient] = None,
    ):
        self._engine = execution_engine
        self._ctx = context_manager
        self._client = client or LLMClient()

    # ── Typed scaffold hook ───────────────────────────────────────────────────

    def handle_failure(
        self,
        plan: Any,
        failure: Any,
    ) -> Any:
        """
        Default retry policy used by the typed ExecutionEngine scaffold.

        Subclass this method to implement custom correction logic.
        The default implementation always retries (the engine enforces
        ``plan.max_retries`` as the hard upper bound).

        Args:
            plan:    The current ``ExecutionPlan`` (from ``agent.types``).
            failure: A ``FailureRecord`` describing the failed step.

        Returns:
            A ``CorrectionDecision`` indicating whether to retry and an
            optional repaired plan.
        """
        from agent.types import CorrectionDecision
        return CorrectionDecision(retryable=True, reason="retry", updated_plan=None)

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_with_correction(
        self,
        plan: QueryPlan,
        question: str,
    ) -> Dict[str, Any]:
        """
        Execute the plan with up to MAX_RETRIES retry attempts on failure.

        Before the first attempt the self-learning loop (task 8.4) checks
        Layer 3 for similar past failures and applies them proactively, so
        the second run of the same query returns correction_applied=True
        without hitting the error again.

        Returns:
            {
                "results": List[QueryResult],
                "correction_applied": bool,
                "retries_used": int,
                "success": bool,
            }
        """
        # Proactive Layer 3 correction (self-learning loop)
        current_plan, correction_applied = self._apply_proactive_corrections(
            plan, question
        )

        results: List[QueryResult] = []
        null_patch_applied = False  # only patch null-metric queries once
        assert current_plan is not None, "SelfCorrectionLoop received a None plan"
        for attempt in range(MAX_RETRIES):
            results = self._engine.execute_plan(
                current_plan,
                self._ctx.get_bundle().__dict__,
            )
            failures = [r for r in results if not r.success]

            if not failures:
                # Semantic null-metric check: ORDER BY col returns all NULLs in
                # PostgreSQL because NULLs sort first in DESC order.  Retry once
                # with WHERE col IS NOT NULL injected.
                if not null_patch_applied and attempt < MAX_RETRIES - 1:
                    null_patched_plan, was_null_patched = self._patch_null_metric_queries(
                        current_plan, results
                    )
                    if was_null_patched:
                        current_plan = null_patched_plan
                        correction_applied = True
                        null_patch_applied = True
                        continue  # Re-run with null filter

                # Log verified outcome for any corrections applied on this attempt
                if correction_applied and attempt > 0:
                    for sq in current_plan.sub_queries:
                        if "[corrected:" in sq.description or "[proactive-correction]" in sq.description:
                            self._ctx.log_correction(
                                query=sq.query,
                                failure_cause="(previous failure — see prior entry)",
                                correction="correction verified successful",
                                database=sq.database,
                                root_cause="(see prior entry)",
                                outcome=f"success on attempt {attempt + 1}",
                            )
                return {
                    "results": results,
                    "correction_applied": correction_applied,
                    "retries_used": attempt,
                    "success": True,
                    "final_plan": current_plan,
                }

            if attempt == MAX_RETRIES - 1:
                break  # exhausted — fall through to error return

            corrected_plan, corrections_made = self._correct_plan(
                current_plan, failures, question
            )
            if corrections_made:
                correction_applied = True
            current_plan = corrected_plan

        return {
            "results": results,
            "correction_applied": correction_applied,
            "retries_used": MAX_RETRIES - 1,
            "success": False,
            "final_plan": current_plan,
        }

    # ── 8.1  Failure detection ────────────────────────────────────────────────

    def detect_failure(self, result: QueryResult) -> Optional[FailureInfo]:
        """
        Classify an execution failure into one of five canonical categories.
        Returns None when the result is successful.

        Categories:
          syntax              — malformed SQL / invalid aggregation pipeline
          join_key_mismatch   — empty join result or type incompatibility
          wrong_db_type       — dialect sent to wrong database engine
          data_quality        — null constraint / duplicate / integrity violation
          extraction_failure  — sandbox / unstructured-text extraction error
        """
        if result.success:
            return None
        error = result.error or ""
        return FailureInfo(
            failure_type=self._classify_error(error),
            error_message=error,
            failed_query=getattr(result, "query", ""),
            database=result.database,
            execution_trace=[error],
        )

    # ── 8.2  Failure diagnosis ────────────────────────────────────────────────

    def diagnose_root_cause(
        self,
        failure: FailureInfo,
        question: str = "",
    ) -> Diagnosis:
        """
        Determine the root cause of the failure using Layer 2 and Layer 3.

        - Checks Layer 3 (corrections log) for similar past failures.
        - For join_key_mismatch, also consults Layer 2 join key glossary.
        Confidence increases with supporting evidence found.
        """
        evidence: List[str] = [
            f"Failure type classified as: {failure.failure_type}"
        ]
        confidence = 0.5
        suggested_fix = ""

        # Layer 3: similar past failures
        similar = self._ctx.get_similar_corrections(failure.failed_query)
        if similar and isinstance(similar, list) and len(similar) > 0:
            evidence.append(
                f"Found {len(similar)} similar past failure(s) in corrections log."
            )
            for e in similar[:3]:
                evidence.append(f"Past fix: {e.correction}")
            suggested_fix = similar[-1].correction  # most recent fix
            confidence = min(0.9, 0.5 + len(similar) * 0.1)

        # Layer 2: join key glossary for join failures
        if failure.failure_type == "join_key_mismatch":
            glossary_hint = self._lookup_join_key_glossary(failure.failed_query)
            if glossary_hint:
                evidence.append(f"Join key glossary: {glossary_hint}")
                suggested_fix = suggested_fix or glossary_hint
                confidence = max(confidence, 0.8)

        return Diagnosis(
            root_cause=failure.failure_type,
            confidence=confidence,
            evidence=evidence,
            similar_past_failures=similar if isinstance(similar, list) else [],
            suggested_fix=suggested_fix,
        )

    # ── 8.3  Correction strategy generation ──────────────────────────────────

    def generate_correction(
        self,
        diagnosis: Diagnosis,
        original_query: str,
        question: str = "",
    ) -> CorrectionStrategy:
        """
        Build a CorrectionStrategy tailored to the diagnosed failure type.

        Strategies:
          regenerate_query       — LLM rewrites query (syntax errors)
          transform_join_key     — apply format transform from Layer 2 glossary
          reroute_database       — re-route to correct DB based on entity type
          apply_quality_rules    — add NULL filter / DISTINCT
          alternative_extraction — fallback extraction method
        """
        ft = diagnosis.root_cause

        if ft == "syntax":
            return CorrectionStrategy(
                strategy_type="regenerate_query",
                rationale=(
                    "Syntax error detected. "
                    + (diagnosis.suggested_fix or "Regenerate using schema.")
                ),
            )

        if ft == "join_key_mismatch":
            transform = self._build_format_transform(original_query, diagnosis)
            return CorrectionStrategy(
                strategy_type="transform_join_key",
                format_transformations=[transform] if transform else [],
                rationale=(
                    "Join key format mismatch. "
                    + (diagnosis.suggested_fix or "Apply type cast.")
                ),
            )

        if ft == "wrong_db_type":
            return CorrectionStrategy(
                strategy_type="reroute_database",
                rationale="Query dialect does not match target database engine.",
            )

        if ft == "data_quality":
            return CorrectionStrategy(
                strategy_type="apply_quality_rules",
                rationale=(
                    "Data quality issue. "
                    + (
                        diagnosis.suggested_fix
                        or "Apply NULL filtering and deduplication."
                    )
                ),
            )

        if ft == "extraction_failure":
            return CorrectionStrategy(
                strategy_type="alternative_extraction",
                extraction_method="regex_fallback",
                rationale="Unstructured text extraction failed; switching to fallback.",
            )

        # Unknown failure type — attempt LLM regeneration as last resort
        return CorrectionStrategy(
            strategy_type="regenerate_query",
            rationale=f"Unknown failure type '{ft}'; attempting LLM regeneration.",
        )

    # ── 8.4  Retry orchestration ──────────────────────────────────────────────

    def _apply_known_join_key_normalizations(
        self,
        plan: QueryPlan,
    ) -> tuple[QueryPlan, bool]:
        """
        Layer 2 proactive pass: rewrite sub-queries that reference columns with
        documented format mismatches (see _KNOWN_JOIN_FIXES / dataset_overview.md).

        Fires on the very first execution attempt regardless of whether Layer 3
        has a matching past failure, so the agent never pays the cost of a failed
        round-trip on well-known join-key problems.

        Uses the LLM rewriter with a targeted hint rather than fragile regex
        surgery, keeping the corrected SQL semantically valid.
        """
        corrected_sqs = list(plan.sub_queries)
        any_corrected = False

        for idx, sq in enumerate(plan.sub_queries):
            applicable = [
                fix for fix in _KNOWN_JOIN_FIXES
                if fix["trigger"].search(sq.query)
            ]
            if not applicable:
                continue

            combined_hint = " | ".join(fix["hint"] for fix in applicable)
            corrected = self._llm_regenerate_query(
                question="(proactive join-key normalisation)",
                query=sq.query,
                error="(no error — proactive normalisation before first attempt)",
                db_name=sq.database,
                hint=combined_hint,
            )
            if corrected and corrected != sq.query:
                corrected_sqs[idx] = SubQuery(
                    database=sq.database,
                    query=corrected,
                    query_type=sq.query_type,
                    dependencies=sq.dependencies,
                    description=sq.description + " [proactive-jk-norm]",
                )
                any_corrected = True

        if not any_corrected:
            return plan, False

        return (
            QueryPlan(
                sub_queries=corrected_sqs,
                execution_order=plan.execution_order,
                join_operations=plan.join_operations,
                requires_sandbox=plan.requires_sandbox,
                rationale=plan.rationale + " [proactive-jk-norm]",
            ),
            True,
        )

    def _apply_proactive_corrections(
        self,
        plan: QueryPlan,
        question: str,
    ) -> tuple[QueryPlan, bool]:
        """
        Self-learning loop: before the first execution attempt apply two passes.

        Pass 1 — Layer 2 known join-key normalization:
          Checks each sub-query against _KNOWN_JOIN_FIXES (patterns documented
          in kb/domain/dataset_overview.md) and rewrites via LLM when a
          risky pattern is detected, even if Layer 3 has no past failure yet.

        Pass 2 — Layer 3 past-failure application:
          Searches by the NL question (stable across iterations at temperature=0)
          and uses the stored corrected query directly — no extra LLM round-trip
          needed because the correction field already holds the full corrected SQL.
          On the second run correction_applied=True is set in the trace without
          ever hitting the failure again.
        """
        # Pass 1: proactive Layer 2 join-key normalization
        plan, jk_corrected = self._apply_known_join_key_normalizations(plan)

        corrected_sub_queries = list(plan.sub_queries)
        any_corrected = jk_corrected

        for idx, sq in enumerate(plan.sub_queries):
            try:
                # Search by NL question — keyed that way in _correct_plan
                similar = self._ctx.get_similar_corrections(question)
                # Only use corrections that were logged for this specific database
                similar = [
                    e for e in similar
                    if e.database is None or e.database == sq.database
                ]
            except Exception:
                continue

            if not similar:
                continue

            latest = similar[-1]
            correction_str = getattr(latest, "correction", "").strip()

            # Strip strategy-type prefix written by old code (e.g. "regenerate_query: SELECT ...")
            _STRATEGY_PREFIXES = (
                "regenerate_query:", "transform_join_key:", "apply_quality_rules:",
                "alternative_extraction:", "reroute_database:",
            )
            for _pfx in _STRATEGY_PREFIXES:
                if correction_str.lower().startswith(_pfx):
                    correction_str = correction_str[len(_pfx):].strip()
                    break

            # The correction field holds the full corrected SQL — use it directly.
            # Fall back to an LLM rewrite only when the stored value looks like a
            # description rather than a runnable query.
            if correction_str and correction_str.upper().startswith(
                ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "[{", "DB.")
            ):
                corrected_query = correction_str
            else:
                corrected_query = self._llm_apply_correction(
                    question=question,
                    query=sq.query,
                    correction_description=correction_str,
                    failure_cause=getattr(latest, "failure_cause", ""),
                    db_name=sq.database,
                )

            if corrected_query and corrected_query != sq.query:
                corrected_sub_queries[idx] = SubQuery(
                    database=sq.database,
                    query=corrected_query,
                    query_type=sq.query_type,
                    dependencies=sq.dependencies,
                    description=sq.description + " [proactive-correction]",
                )
                any_corrected = True

        if not any_corrected:
            return plan, False

        return (
            QueryPlan(
                sub_queries=corrected_sub_queries,
                execution_order=plan.execution_order,
                join_operations=plan.join_operations,
                requires_sandbox=plan.requires_sandbox,
                rationale=plan.rationale + " [proactive-correction]",
            ),
            True,
        )

    def _correct_plan(
        self,
        plan: QueryPlan,
        failures: List[QueryResult],
        question: str,
    ) -> tuple[QueryPlan, bool]:
        """
        For each failed sub-query:
          1. Detect failure type
          2. Diagnose root cause (Layer 2 + Layer 3)
          3. Generate correction strategy
          4. Apply strategy → corrected query
          5. Log to Layer 3 (append-only)
        Returns a new QueryPlan and whether any corrections were applied.
        """
        corrected_sub_queries = list(plan.sub_queries)
        corrections_made = False

        for failure_result in failures:
            idx = next(
                (
                    i
                    for i, sq in enumerate(plan.sub_queries)
                    if sq.database == failure_result.database
                ),
                None,
            )
            if idx is None:
                continue

            original_sq = plan.sub_queries[idx]

            # 8.1 detect
            failure_info = FailureInfo(
                failure_type=self._classify_error(failure_result.error or ""),
                error_message=failure_result.error or "Unknown error",
                failed_query=original_sq.query,
                database=failure_result.database,
                execution_trace=[failure_result.error or ""],
            )

            # 8.2 diagnose
            diagnosis = self.diagnose_root_cause(failure_info, question)

            # 8.3 generate correction strategy
            strategy = self.generate_correction(
                diagnosis, original_sq.query, question
            )

            # Apply strategy to get a concrete corrected query
            corrected_query = self._apply_strategy(
                strategy=strategy,
                original_query=original_sq.query,
                question=question,
                error=failure_info.error_message,
                db_name=original_sq.database,
                diagnosis=diagnosis,
            )
            if corrected_query is None:
                continue

            # 8.4 log to Layer 3 — key by NL question (stable across iterations),
            # store the FULL corrected SQL so _apply_proactive_corrections can
            # use it verbatim on the next run without an extra LLM call.
            self._ctx.log_correction(
                query=question,
                failure_cause=(
                    f"{failure_info.failure_type}: {failure_info.error_message}"
                ),
                correction=corrected_query,
                database=failure_result.database,
                root_cause=diagnosis.root_cause,
                outcome="pending verification",
            )

            corrected_sub_queries[idx] = SubQuery(
                database=original_sq.database,
                query=corrected_query,
                query_type=original_sq.query_type,
                dependencies=original_sq.dependencies,
                description=(
                    original_sq.description
                    + f" [corrected:{failure_info.failure_type}]"
                ),
            )
            corrections_made = True

        return (
            QueryPlan(
                sub_queries=corrected_sub_queries,
                execution_order=plan.execution_order,
                join_operations=plan.join_operations,
                requires_sandbox=plan.requires_sandbox,
                rationale=plan.rationale + " [self-corrected]",
            ),
            corrections_made,
        )

    # ── Null-metric semantic failure detection ────────────────────────────────

    def _patch_null_metric_queries(
        self,
        plan: QueryPlan,
        results: List[QueryResult],
    ) -> tuple[QueryPlan, bool]:
        """
        Detect queries where ORDER BY column returns all-NULL values and inject
        a WHERE col IS NOT NULL filter so NULLs are skipped.

        PostgreSQL (and most SQL engines) sort NULLs as greatest in DESC order,
        so 'ORDER BY price DESC LIMIT 5' returns null-priced rows instead of
        the highest-priced ones when many rows have null prices.
        """
        results_by_db = {r.database: r for r in results if r.success}
        patched_sqs = list(plan.sub_queries)
        any_patched = False

        for idx, sq in enumerate(plan.sub_queries):
            result = results_by_db.get(sq.database)
            if result is None:
                continue

            col = self._extract_orderby_col(sq.query)
            if col is None:
                continue

            data = result.data
            # Flatten single-element list wrappers that survive normalization
            if isinstance(data, list) and len(data) == 1:
                inner = data[0]
                if isinstance(inner, list):
                    data = inner
                elif isinstance(inner, str):
                    try:
                        import json as _json
                        data = _json.loads(inner)
                    except Exception:
                        pass

            if not self._all_null_in_col(data, col):
                continue

            patched_query = self._inject_null_filter(sq.query, col)
            if patched_query and patched_query != sq.query:
                print(
                    f"[SelfCorrection] Null-metric patch: '{col}' all-null "
                    f"in {sq.database}, retrying with WHERE {col} IS NOT NULL"
                )
                patched_sqs[idx] = SubQuery(
                    database=sq.database,
                    query=patched_query,
                    query_type=sq.query_type,
                    dependencies=sq.dependencies,
                    description=sq.description + f" [null-filter:{col}]",
                )
                any_patched = True

        if not any_patched:
            return plan, False

        return (
            QueryPlan(
                sub_queries=patched_sqs,
                execution_order=plan.execution_order,
                join_operations=plan.join_operations,
                requires_sandbox=plan.requires_sandbox,
                rationale=plan.rationale + " [null-metric-patch]",
            ),
            True,
        )

    @staticmethod
    def _extract_orderby_col(query: str) -> Optional[str]:
        """Return the first column name from ORDER BY, or None if absent."""
        m = re.search(r'\bORDER\s+BY\s+(\w+)', query, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _all_null_in_col(data: Any, col: str) -> bool:
        """Return True when every row in data has None/null for col."""
        if not isinstance(data, list) or len(data) == 0:
            return False
        rows = [r for r in data if isinstance(r, dict)]
        if not rows:
            return False
        return all(row.get(col) is None for row in rows)

    @staticmethod
    def _inject_null_filter(query: str, col: str) -> str:
        """Insert 'WHERE col IS NOT NULL' (or AND variant) before ORDER BY."""
        null_cond = f"{col} IS NOT NULL"
        if re.search(r'\bWHERE\b', query, re.IGNORECASE):
            return re.sub(
                r'(\bORDER\s+BY\b)',
                f'AND {null_cond} \\1',
                query,
                flags=re.IGNORECASE,
                count=1,
            )
        return re.sub(
            r'(\bORDER\s+BY\b)',
            f'WHERE {null_cond} \\1',
            query,
            flags=re.IGNORECASE,
            count=1,
        )

    # ── Classification helpers ────────────────────────────────────────────────

    def _classify_error(self, error: str) -> str:
        """Map a raw error message to one of five canonical failure types.

        Order matters: more-specific patterns are checked before broader ones
        so that, e.g., "operator does not exist: integer = text" is classified
        as join_key_mismatch rather than syntax.
        """
        if _JOIN_KEY_RE.search(error):
            return "join_key_mismatch"
        if _WRONG_DB_RE.search(error):
            return "wrong_db_type"
        if _DATA_QUALITY_RE.search(error):
            return "data_quality"
        if _EXTRACTION_RE.search(error):
            return "extraction_failure"
        if _SYNTAX_RE.search(error):
            return "syntax"
        # Default: treat as syntax so we attempt LLM regeneration
        return "syntax"

    # ── Layer 2 consultation ──────────────────────────────────────────────────

    def _lookup_join_key_glossary(self, query: str) -> str:
        """
        Search Layer 2 institutional knowledge for join key hints relevant
        to the query.  Returns the most relevant glossary line or "".
        """
        try:
            bundle = self._ctx.get_bundle()
            docs = bundle.institutional_knowledge
        except Exception:
            return ""

        if not isinstance(docs, list):
            return ""

        query_lower = query.lower()
        for doc in docs:
            source = getattr(doc, "source", "")
            content = getattr(doc, "content", "")
            if "join_key_glossary" not in source and "join key" not in content.lower():
                continue
            for line in content.splitlines():
                words = [w for w in line.lower().split() if len(w) > 3]
                if any(w in query_lower for w in words):
                    return line.strip()
        return ""

    def _build_format_transform(
        self, query: str, diagnosis: Diagnosis
    ) -> Optional[FormatTransform]:
        """
        Infer a FormatTransform from glossary evidence embedded in the Diagnosis.
        Returns None when no specific transformation can be determined.
        """
        for line in diagnosis.evidence:
            ll = line.lower()
            if "int" in ll and "string" in ll:
                # Decide direction from the evidence wording
                if "cast" in ll and "int" in ll:
                    return FormatTransform(
                        source_format="string",
                        target_format="integer",
                        transformation_function="int(value)",
                    )
                return FormatTransform(
                    source_format="integer",
                    target_format="string",
                    transformation_function="str(value)",
                )
        return None

    # ── Strategy application ──────────────────────────────────────────────────

    def _apply_strategy(
        self,
        strategy: CorrectionStrategy,
        original_query: str,
        question: str,
        error: str,
        db_name: str,
        diagnosis: Diagnosis,
    ) -> Optional[str]:
        """Convert a CorrectionStrategy into a concrete corrected query string."""
        st = strategy.strategy_type

        if st == "regenerate_query":
            return self._llm_regenerate_query(
                question=question,
                query=original_query,
                error=error,
                db_name=db_name,
                hint=diagnosis.suggested_fix,
            )

        if st == "transform_join_key":
            hint = strategy.rationale
            if strategy.format_transformations:
                ft = strategy.format_transformations[0]
                hint = (
                    f"Transform join key from {ft.source_format} to "
                    f"{ft.target_format} using: {ft.transformation_function}"
                )
            return self._llm_regenerate_query(
                question=question,
                query=original_query,
                error=error,
                db_name=db_name,
                hint=hint,
            )

        if st == "reroute_database":
            # Re-routing requires changing the sub-query's database field,
            # which can't be done here; signal the caller to skip.
            return None

        if st == "apply_quality_rules":
            return self._llm_regenerate_query(
                question=question,
                query=original_query,
                error=error,
                db_name=db_name,
                hint=(
                    strategy.rationale
                    or "Add WHERE col IS NOT NULL and DISTINCT to handle data quality issues."
                ),
            )

        if st == "alternative_extraction":
            return self._llm_regenerate_query(
                question=question,
                query=original_query,
                error=error,
                db_name=db_name,
                hint=(
                    strategy.rationale
                    or "Use a simpler extraction pattern or regex fallback."
                ),
            )

        return None

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _schema_hint_for_db(self, db_name: str) -> str:
        """
        Return a concise schema summary for db_name to ground the LLM during
        query regeneration.

        Priority:
          1. Layer 1 live introspection — table names + column lists
          2. Layer 2 KB docs — search institutional_knowledge for a section
             that mentions db_name (e.g. the bookreview section in schema.md)

        Returns "" when neither source yields useful data.
        """
        # Layer 1: live schema introspection
        try:
            schema_map = self._ctx.get_schema_for_databases([db_name])
            if db_name in schema_map:
                si = schema_map[db_name]
                if si.tables:
                    lines = [f"Database: {db_name} ({si.db_type})"]
                    for table, cols in si.tables.items():
                        col_preview = ", ".join(cols[:20])
                        lines.append(f"  Table: {table} — columns: {col_preview}")
                    return "\n".join(lines)
        except Exception:
            pass

        # Layer 2: KB docs — find the section that describes this database
        try:
            bundle = self._ctx.get_bundle()
            for doc in bundle.institutional_knowledge:
                content = doc.content
                if db_name.lower() not in content.lower():
                    continue
                # Extract up to 25 lines starting from the first mention
                lines = content.split("\n")
                relevant: List[str] = []
                capturing = False
                for line in lines:
                    if db_name.lower() in line.lower():
                        capturing = True
                    if capturing:
                        relevant.append(line)
                        if len(relevant) >= 25:
                            break
                if relevant:
                    return f"From KB ({doc.source}):\n" + "\n".join(relevant)
        except Exception:
            pass

        return ""

    def _llm_regenerate_query(
        self,
        question: str,
        query: str,
        error: str,
        db_name: str,
        hint: str = "",
    ) -> Optional[str]:
        """
        Ask the LLM to rewrite a failed query given the error and an optional hint.

        Injects Layer 1/2 schema context so the LLM uses the correct table and
        column names instead of guessing.  Returns the corrected query string,
        or None on failure.
        """
        hint_section = f"\nHint: {hint}" if hint else ""
        schema_hint = self._schema_hint_for_db(db_name)
        schema_section = f"\nSchema context:\n{schema_hint}" if schema_hint else ""
        prompt = (
            "A database query failed. Produce a corrected query.\n\n"
            f"Original question: {question}\n"
            f"Database: {db_name}\n"
            f"Failed query:\n{query}\n\n"
            f"Error message:\n{error}{hint_section}{schema_section}\n\n"
            "Return only the corrected query string (no explanation, no markdown)."
        )
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Strip markdown code fences when present
            text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\n?```$", "", text)
            return text.strip() or None
        except Exception as exc:
            print(f"[SelfCorrectionLoop] LLM regeneration failed: {exc}")
        return None

    def _llm_apply_correction(
        self,
        question: str,
        query: str,
        correction_description: str,
        failure_cause: str,
        db_name: str,
    ) -> Optional[str]:
        """
        Proactively apply a known correction (from Layer 3) to the query
        before the first execution attempt.
        """
        prompt = (
            "Apply a known fix to this database query before execution.\n\n"
            f"Original question: {question}\n"
            f"Database: {db_name}\n"
            f"Current query:\n{query}\n\n"
            f"Known failure cause: {failure_cause}\n"
            f"Known fix: {correction_description}\n\n"
            "Return only the updated query string (no explanation, no markdown). "
            "If no change is needed, return the original query unchanged."
        )
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\n?```$", "", text)
            return text.strip() or None
        except Exception as exc:
            print(f"[SelfCorrectionLoop] LLM proactive correction failed: {exc}")
        return None

    # ── Backward-compatibility shims ──────────────────────────────────────────

    def _diagnose_and_correct(
        self,
        plan: QueryPlan,
        failures: List[QueryResult],
        question: str,
    ) -> tuple[QueryPlan, bool]:
        """Thin wrapper kept so existing tests that call this directly still pass."""
        return self._correct_plan(plan, failures, question)

    def _llm_diagnose(
        self,
        question: str,
        query: str,
        error: str,
        db_name: str,
    ) -> Optional[Dict[str, str]]:
        """
        Legacy helper kept for backward compatibility.
        New code should use detect_failure → diagnose_root_cause → generate_correction.
        """
        corrected = self._llm_regenerate_query(
            question=question,
            query=query,
            error=error,
            db_name=db_name,
        )
        if corrected:
            failure_type = self._classify_error(error)
            return {
                "cause": failure_type,
                "fix": f"Applied {failure_type} correction",
                "corrected_query": corrected,
            }
        return None
