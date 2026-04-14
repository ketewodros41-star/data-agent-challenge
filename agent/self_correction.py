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


class SelfCorrectionLoop:
    """
    Coordinates retry attempts around ExecutionEngine with structured
    failure classification, diagnosis, and targeted correction.

    Returns dict with keys: results, correction_applied, retries_used, success.
    """

    def __init__(
        self,
        execution_engine: "ExecutionEngine",
        context_manager: "ContextManager",
        client: Optional[LLMClient] = None,
    ):
        self._engine = execution_engine
        self._ctx = context_manager
        self._client = client or LLMClient()

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

        print(f"[SelfCorrection] current_plan={current_plan!r}")
        print(f"[SelfCorrection] current_plan_type={type(current_plan)}")
        results: List[QueryResult] = []
        assert current_plan is not None, "SelfCorrectionLoop received a None plan"
        for attempt in range(MAX_RETRIES):
            results = self._engine.execute_plan(
                current_plan,
                self._ctx.get_bundle().__dict__,
            )
            failures = [r for r in results if not r.success]

            if not failures:
                return {
                    "results": results,
                    "correction_applied": correction_applied,
                    "retries_used": attempt,
                    "success": True,
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

    def _apply_proactive_corrections(
        self,
        plan: QueryPlan,
        question: str,
    ) -> tuple[QueryPlan, bool]:
        """
        Self-learning loop: before the first execution attempt, check Layer 3
        for similar past failures and apply the known fix proactively.

        When a match is found the LLM rewrites the query incorporating the
        stored correction.  On the second run correction_applied=True is set
        in the trace without ever hitting the failure again.
        """
        corrected_sub_queries = list(plan.sub_queries)
        any_corrected = False

        for idx, sq in enumerate(plan.sub_queries):
            try:
                similar = self._ctx.get_similar_corrections(sq.query)
            except Exception:
                continue

            if not similar or not isinstance(similar, list) or len(similar) == 0:
                continue

            latest = similar[-1]
            corrected_query = self._llm_apply_correction(
                question=question,
                query=sq.query,
                correction_description=getattr(latest, "correction", ""),
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

            # 8.4 log to Layer 3
            self._ctx.log_correction(
                query=original_sq.query,
                failure_cause=(
                    f"{failure_info.failure_type}: {failure_info.error_message}"
                ),
                correction=(
                    f"{strategy.strategy_type}: {corrected_query[:120]}"
                ),
                database=failure_result.database,
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
        Returns the corrected query string, or None on failure.
        """
        hint_section = f"\nHint: {hint}" if hint else ""
        prompt = (
            "A database query failed. Produce a corrected query.\n\n"
            f"Original question: {question}\n"
            f"Database: {db_name}\n"
            f"Failed query:\n{query}\n\n"
            f"Error message:\n{error}{hint_section}\n\n"
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
