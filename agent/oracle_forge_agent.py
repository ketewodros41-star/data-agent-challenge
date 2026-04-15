"""
OracleForgeAgent — Top-level orchestrator.

Receives DAB wire-format input, coordinates all components,
and returns DAB wire-format output.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import replace as _dc_replace
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from agent.context_manager import ContextManager
from agent.execution_engine import ExecutionEngine
from agent.llm_client import LLMClient
from agent.mcp_toolbox import MCPToolbox
from agent.models.models import QueryPlan, QueryResult
from agent.query_router import QueryRouter
from agent.self_correction import SelfCorrectionLoop
from eval.harness import EvaluationHarness

load_dotenv()

# DAB datasets that live in MongoDB (served via HTTP toolbox)
_MONGODB_DATASETS = {"yelp"}

# DAB datasets that live in PostgreSQL (served via HTTP toolbox)
_POSTGRES_DATASETS = set()

# Root directory where the DAB benchmark mounts dataset files
_DAB_ROOT = os.getenv("DAB_ROOT", "/DataAgentBench")


def _parse_tools_yaml(text: str) -> dict:
    """
    Minimal tools.yaml parser used when pyyaml is not installed.

    Handles the specific structure of mcp/tools.yaml:
      top_key:\n  child_key:\n    leaf_key: value
    All values are treated as strings.  No lists, no multi-line values.
    Indentation is 2 spaces per level.
    """
    result: dict = {}
    stack: list = [(-1, result)]  # (indent_level, dict_ref)

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        content = line.strip()
        if ":" not in content:
            continue

        key, sep, value = content.partition(":")
        key = key.strip()
        value = value.strip()

        # Pop stack entries that are deeper than or equal to current indent
        while stack and stack[-1][0] >= indent:
            stack.pop()

        parent = stack[-1][1] if stack else result
        if value:
            parent[key] = value
        else:
            new_dict: dict = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))

    return result


class OracleForgeAgent:
    """
    Main entry point for the Oracle Forge Data Agent.

    Database configs are keyed by DAB dataset name (e.g. "bookreview", "yelp"),
    not by DB type.  When no explicit db_configs are supplied the agent
    auto-discovers the connection for each name in available_databases by:
      1. Env vars  — BOOKREVIEW_DB_TYPE / BOOKREVIEW_DB_CONN (or _DB_PATH)
      2. DAB paths — /DataAgentBench/query_<id>/query_dataset/*.db  (SQLite/DuckDB)
      3. Known sets — _MONGODB_DATASETS / _POSTGRES_DATASETS for HTTP toolbox DBs

    Usage:
        # Auto-discovery (DAB benchmark runner)
        agent = OracleForgeAgent()
        result = agent.answer({
            "question": "How many 5-star reviews are there?",
            "available_databases": ["bookreview"],
            "schema_info": {}
        })

        # Explicit config (scripts, tests)
        agent = OracleForgeAgent(db_configs={
            "bookreview": {"type": "sqlite",
                           "path": "/DataAgentBench/query_bookreview/query_dataset/review_query.db"}
        })
    """

    def __init__(
        self,
        db_configs: Optional[Dict[str, dict]] = None,
        session_id: Optional[str] = None,
    ):
        self._session_id = session_id or str(uuid.uuid4())
        # Explicit configs take priority; discovery runs lazily per-query for any
        # database not already present (keyed by DAB dataset name, e.g. "bookreview").
        self._db_configs: Dict[str, dict] = db_configs or {}
        self._client = LLMClient()

        # Session state: per-session interaction history (multi-turn support)
        # Maps session_id -> list of {question, answer, confidence, ...} dicts
        self._sessions: Dict[str, List[Dict[str, Any]]] = {
            self._session_id: []
        }

        # Create the shared MCPToolbox first — all DB access (including schema
        # introspection) must go through this, never via direct DB connections.
        self._toolbox = MCPToolbox(db_configs=self._db_configs)

        # Initialise components (all share the same MCPToolbox instance)
        self._ctx_manager = ContextManager(self._db_configs, toolbox=self._toolbox)
        self._router = QueryRouter(client=self._client)
        self._engine = ExecutionEngine(toolbox=self._toolbox, db_configs=self._db_configs)
        self._correction_loop = SelfCorrectionLoop(
            execution_engine=self._engine,
            context_manager=self._ctx_manager,
            client=self._client,
        )

        # Load all context layers once at session start
        self._ctx_manager.load_all_layers()

        # Evaluation harness — trace tool calls and record query outcomes
        self._harness = EvaluationHarness()
        self._harness_session_id = self._harness.start_session()

    # ── Typed DAB interface (task 10.1) ───────────────────────────────────────

    def process_query(
        self,
        question: str,
        available_databases: List[str],
        schema_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process a natural language query against available databases.

        Accepts individual DAB format arguments and returns the DAB output
        format dict: {"answer": Any, "query_trace": List[dict], "confidence": float}.

        Args:
            question: Natural language query text.
            available_databases: List of database identifiers accessible for this query.
            schema_info: Schema metadata for available databases.

        Returns:
            DAB result dict containing answer, query_trace, and confidence score.
        """
        return self.answer(
            {
                "question": question,
                "available_databases": available_databases,
                "schema_info": schema_info,
            }
        )

    # ── Session management (task 10.3) ────────────────────────────────────────

    def load_session_context(self, session_id: str) -> None:
        """
        Load context layers for a session, switching the active session.

        Creates a new interaction history slot for the session_id if it has
        not been seen before, then reloads all three context layers so the
        agent picks up any corrections written during a previous session.

        Args:
            session_id: Identifier for the session to load.
        """
        self._session_id = session_id
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        # Reload all layers so Layer-3 corrections from prior sessions are visible
        self._ctx_manager.load_all_layers()

    def update_interaction_memory(
        self,
        query: str,
        correction: str,
        pattern: str,
    ) -> None:
        """
        Update Layer 3 with a user-supplied correction or successful pattern.

        Appends an entry to the corrections log so the agent can apply the
        fix proactively the next time it encounters a similar query.

        Args:
            query: The original query that was problematic or observed.
            correction: The corrected query or response.
            pattern: Description of the failure cause or pattern observed.
        """
        self._ctx_manager.log_correction(
            query=query,
            failure_cause=pattern,
            correction=correction,
        )

    # ── Database discovery ────────────────────────────────────────────────────

    def _discover_db_config(self, db_id: str) -> Optional[Dict[str, Any]]:
        """
        Auto-discover connection config for a DAB dataset name.

        Resolution order:
          1. Env vars  — {DB_ID_UPPER}_DB_TYPE  +  _DB_CONN or _DB_PATH
          2. mcp/tools.yaml — parse toolbox sources; match by db_id substring in path
          3. DAB paths — scan /DataAgentBench/query_<db_id>/query_dataset/ for .db files
          4. Known sets — yelp → mongodb, others → postgres via HTTP toolbox
        """
        import glob as _glob

        prefix = db_id.upper()

        # 1. Explicit env vars
        db_type = os.getenv(f"{prefix}_DB_TYPE", "").lower()
        db_conn = os.getenv(f"{prefix}_DB_CONN", "")
        db_path = os.getenv(f"{prefix}_DB_PATH", "")

        if db_type in ("sqlite", "duckdb"):
            path = db_path or db_conn
            if path:
                cfg: Dict[str, Any] = {"type": db_type, "path": os.path.expanduser(path)}
                mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "")
                if mcp_tool:
                    cfg["mcp_tool"] = mcp_tool
                return cfg
        elif db_type in ("postgres", "postgresql"):
            # All postgres access goes through MCP — no direct connections.
            # MCP tool name may be provided via env var; toolbox discovery fills it in otherwise.
            mcp_tool = os.getenv(f"{prefix}_MCP_TOOL", "")
            cfg: Dict[str, Any] = {"type": "postgres"}
            if mcp_tool:
                cfg["mcp_tool"] = mcp_tool
            return cfg
        elif db_type == "mongodb":
            return {"type": "mongodb"}

        # 2. mcp/tools.yaml discovery
        toolbox_cfg = self._discover_from_toolbox(db_id)
        if toolbox_cfg:
            return toolbox_cfg

        # 3. Scan known DAB directory structure for local files
        dataset_dir = os.path.join(_DAB_ROOT, f"query_{db_id}", "query_dataset")
        if os.path.isdir(dataset_dir):
            for ext, db_type_name in (("*.duckdb", "duckdb"), ("*.db", "sqlite")):
                matches = sorted(_glob.glob(os.path.join(dataset_dir, ext)))
                if matches:
                    return {"type": db_type_name, "path": matches[0]}

        # 4. Known HTTP-toolbox datasets (no direct connections — toolbox handles the routing)
        if db_id in _MONGODB_DATASETS:
            return {"type": "mongodb"}
        if db_id in _POSTGRES_DATASETS:
            return {"type": "postgres"}

        return None

    def _discover_from_toolbox(self, db_id: str) -> Optional[Dict[str, Any]]:
        """
        Parse mcp/tools.yaml and try to match *db_id* to a source.

        Matching rules:
          - SQLite source: container path contains a word from db_id
            (e.g. 'review' in 'review_database' appears in
            '/datasets/query_bookreview/…review_query.db').
            Host path is resolved via SQLITE_{KEYWORD_UPPER} env var.
          - Postgres source: db_id contains a word that appears in the
            postgres `database` field (e.g. 'books' → 'bookreview_db').
            DSN is built from PG_* env vars.
        """
        _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_yaml = os.path.join(_repo_root, "mcp", "tools.yaml")
        if not os.path.exists(tools_yaml):
            return None

        try:
            import yaml  # pyyaml in requirements.txt
            with open(tools_yaml, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
        except ImportError:
            # pyyaml not installed — use the lightweight built-in parser
            with open(tools_yaml, encoding="utf-8") as fh:
                raw = _parse_tools_yaml(fh.read())
        except Exception:
            return None

        sources = raw.get("sources", {}) if isinstance(raw, dict) else {}
        tools = raw.get("tools", {}) if isinstance(raw, dict) else {}

        # Derive candidate keywords from db_id (strip common suffixes)
        keywords = [
            w for w in re.split(r"[_\-]", db_id.lower())
            if w not in ("database", "db", "data", "info")
        ]

        for source_name, src_cfg in sources.items():
            kind = src_cfg.get("kind", "")

            if kind == "sqlite":
                container_path = src_cfg.get("database", "")
                # Match: any keyword from db_id appears in the container path
                if not any(kw in container_path.lower() for kw in keywords):
                    continue
                # Resolve to host path via SQLITE_{KEYWORD} env var
                host_path = ""
                for kw in keywords:
                    host_path = os.getenv(f"SQLITE_{kw.upper()}", "")
                    if host_path:
                        break
                path = os.path.expanduser(host_path) if host_path else container_path
                # Find the MCP tool name that uses this source
                mcp_tool = next(
                    (
                        tname for tname, tcfg in tools.items()
                        if isinstance(tcfg, dict) and tcfg.get("source") == source_name
                    ),
                    "",
                )
                cfg: Dict[str, Any] = {"type": "sqlite", "path": path}
                if mcp_tool:
                    cfg["mcp_tool"] = mcp_tool
                return cfg

            if kind == "postgres":
                pg_db = src_cfg.get("database", "").lower()
                sname = source_name.lower()
                # Match: any keyword appears in source name or database name, or vice versa
                if not any(
                    kw in sname or kw in pg_db or sname in kw or pg_db.replace("_", "") in kw
                    for kw in keywords
                ):
                    continue
                # Find the dynamic execute-sql tool for this source (skip static tools)
                mcp_tool = next(
                    (
                        tname for tname, tcfg in tools.items()
                        if isinstance(tcfg, dict)
                        and tcfg.get("source") == source_name
                        and tcfg.get("kind") == "postgres-execute-sql"
                    ),
                    "",
                )
                cfg: Dict[str, Any] = {"type": "postgres"}
                if mcp_tool:
                    cfg["mcp_tool"] = mcp_tool
                return cfg

        return None

    def _resolve_missing_db_configs(self, available_databases: List[str]) -> None:
        """
        Fill in self._db_configs for any database not yet configured.
        Propagates new configs to the engine and toolbox so routing works.
        """
        new_entries: Dict[str, dict] = {}
        for db_id in available_databases:
            if db_id not in self._db_configs:
                cfg = self._discover_db_config(db_id)
                if cfg:
                    new_entries[db_id] = cfg

        if new_entries:
            self._db_configs.update(new_entries)
            # Keep all components that hold db_configs in sync
            self._engine._db_configs.update(new_entries)
            self._toolbox._db_configs.update(new_entries)
            # self._engine.toolbox IS self._toolbox (same instance), so above is sufficient

    # ── DAB wire-format interface ──────────────────────────────────────────────

    def answer(self, dab_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a DAB benchmark question and return the DAB output format.

        Args:
            dab_input: {"question": str, "available_databases": List[str], "schema_info": dict}

        Returns:
            {"answer": Any, "query_trace": List[dict], "confidence": float}
        """
        question = dab_input["question"]
        available_databases = dab_input.get("available_databases") or list(self._db_configs.keys())

        # Auto-discover connection configs for any unknown dataset names
        self._resolve_missing_db_configs(available_databases)

        # Refresh Layer 1 schema for any database that was discovered above but
        # was absent from the bundle (load_all_layers() ran at __init__ time,
        # before _resolve_missing_db_configs had a chance to find the configs).
        missing_schema = [
            db for db in available_databases
            if db not in self._ctx_manager.get_bundle().schema
        ]
        if missing_schema:
            self._ctx_manager.refresh_schema(missing_schema)

        # Layer 3: check for proactive corrections before first attempt
        context = self._ctx_manager.get_bundle()
        prior_corrections = self._ctx_manager.get_similar_corrections(question)
        correction_applied_proactively = len(prior_corrections) > 0

        # Layer 2 on-demand: inject domain docs triggered by question keywords.
        # get_docs_for_question() matches trigger words (revenue, table, schema, …)
        # and loads the relevant kb/domain/ files.  We augment without mutating
        # the shared bundle so the next query starts with a clean base.
        on_demand_docs = self._ctx_manager.get_docs_for_question(question)
        if on_demand_docs:
            context = _dc_replace(
                context,
                institutional_knowledge=context.institutional_knowledge + on_demand_docs,
            )

        # Route: produce a QueryPlan
        plan = self._router.route(question, context, available_databases)

        # Execute with self-correction
        execution_result = self._correction_loop.execute_with_correction(plan, question)

        # Synthesise final answer with confidence score
        answer, confidence = self._synthesise_answer(
            question=question,
            execution_result=execution_result,
            prior_corrections=prior_corrections,
            plan=plan,
        )

        # Build trace for DAB output
        query_trace = self._build_trace(plan, execution_result)

        # Adjust confidence for proactive correction outcome
        if correction_applied_proactively and not execution_result["success"]:
            confidence = max(0.2, confidence - 0.1)
        elif correction_applied_proactively:
            confidence = min(1.0, confidence + 0.05)

        final_correction_applied = (
            correction_applied_proactively or execution_result["correction_applied"]
        )

        # Trace each sub-query as a tool call in the evaluation harness
        tool_call_ids: List[str] = []
        results_by_db = {r.database: r for r in execution_result["results"]}
        for sq in plan.sub_queries:
            result = results_by_db.get(sq.database)
            tool_name = "duckdb_query" if sq.query_type == "duckdb" else "run_query"
            tool_call_ids.append(
                self._harness.trace_tool_call(
                    session_id=self._harness_session_id,
                    tool_name=tool_name,
                    parameters={"query": sq.query, "database": sq.database},
                    result=result.data if result and result.success else None,
                    execution_time=0.0,
                    error=result.error if result else None,
                )
            )

        # Record the query outcome (expected_answer unknown at query time; filled in by run_benchmark)
        self._harness.record_query_outcome(
            session_id=self._harness_session_id,
            query=question,
            answer=answer,
            expected=None,
            tool_call_ids=tool_call_ids,
            available_databases=available_databases,
            confidence=confidence,
            correction_applied=final_correction_applied,
        )

        # Update session interaction history (multi-turn support)
        self._sessions.setdefault(self._session_id, []).append(
            {
                "question": question,
                "answer": answer,
                "confidence": confidence,
                "correction_applied": final_correction_applied,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        return {
            "answer": answer,
            "query_trace": query_trace,
            "confidence": confidence,
            "tool_call_ids": tool_call_ids,
            "correction_applied": final_correction_applied,
        }

    # ── Answer synthesis (task 10.2) ──────────────────────────────────────────

    def _synthesise_answer(
        self,
        question: str,
        execution_result: Dict[str, Any],
        prior_corrections: list,
        plan: Optional[QueryPlan] = None,
    ) -> tuple[Any, float]:
        """Synthesise a final answer from execution results and compute confidence."""
        results = execution_result["results"]
        success = execution_result["success"]

        if not results:
            return "Unable to retrieve data.", 0.1

        # Partition results.  Only successful data goes to the LLM — sending
        # error strings lets the model hallucinate an answer from failure text,
        # violating the self-correcting execution guidance ("max 3 attempts,
        # then return honest error with full trace").
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if not successful:
            retries = execution_result.get("retries_used", 0)
            errors = "; ".join(r.error or "unknown error" for r in failed)
            return (
                f"Unable to retrieve data after {retries + 1} attempt(s). "
                f"Errors: {errors}"
            ), 0.1

        result_summaries = []
        for r in successful:
            data = self._flatten_result_data(r.data)
            rows = len(data) if isinstance(data, list) else 1
            result_summaries.append(
                f"[{r.database}] rows={rows}: {json.dumps(data, default=str)}"
            )

        correction_note = ""
        if prior_corrections:
            correction_note = (
                f"Note: {len(prior_corrections)} prior correction(s) were applied.\n"
            )

        prompt = (
            "Based on the following query results, answer this question concisely.\n\n"
            f"Question: {question}\n\n"
            f"{correction_note}"
            "Results:\n" + "\n".join(result_summaries) + "\n\n"
            "Rules:\n"
            "- If rows were returned, ALWAYS extract and list the relevant field values "
            "(e.g. titles, names, ids) to form the answer — even if other fields are null.\n"
            "- Null values in metric/ordering fields (price, rating, etc.) mean the data "
            "is missing, but the rows themselves are valid results.\n"
            "- Never return 'None' or 'null' when rows are present.\n"
            "- Return only the final answer value (number, string, list, or dict). "
            "No explanation."
        )

        response = self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_answer = response.content[0].text.strip()

        # Try to parse as JSON for structured answers
        try:
            parsed = json.loads(raw_answer)
            answer = parsed
        except json.JSONDecodeError:
            answer = raw_answer

        confidence = self._calculate_confidence(
            success=success,
            correction_applied=execution_result["correction_applied"],
            retries_used=execution_result.get("retries_used", 0),
            plan=plan,
            results=results,
        )

        return answer, confidence

    def _calculate_confidence(
        self,
        success: bool,
        correction_applied: bool,
        retries_used: int,
        plan: Optional[QueryPlan] = None,
        results: Optional[List[QueryResult]] = None,
    ) -> float:
        """
        Calculate confidence score based on validation outcomes and query complexity.

        Factors:
        - Base confidence from success/failure
        - Penalty for retries needed (instability indicator)
        - Penalty for correction being applied (required rework)
        - Complexity penalty for multi-database queries
        - Penalty if any individual sub-result failed (partial failure)

        Returns:
            Float in [0.1, 1.0].
        """
        if not success:
            return 0.2  # Non-zero: partial results may still be useful

        confidence = 0.9

        # Each retry penalises confidence (instability)
        confidence -= retries_used * 0.1

        # Correction means rework was needed
        if correction_applied:
            confidence -= 0.1

        # Cross-database queries are more complex → lower baseline certainty
        if plan is not None:
            n_databases = len({sq.database for sq in plan.sub_queries})
            if n_databases > 1:
                confidence -= (n_databases - 1) * 0.05

        # Partial failures within an otherwise successful run
        if results:
            failed_count = sum(1 for r in results if not r.success)
            if failed_count > 0:
                confidence -= failed_count * 0.05

        return max(0.1, min(1.0, confidence))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _flatten_result_data(data: Any) -> Any:
        """
        Unwrap MCP toolbox double-encoding artefacts so the LLM always sees a
        clean list-of-dicts (or scalar) rather than a list-containing-a-string.

        The toolbox wraps query results as:
          content[0].text = '[{"col": val}, ...]'   (JSON string of the rows)
        After _normalize_mcp_content this becomes:
          data = ['[{"col": val}, ...]']             (Python list with one string element)
        or, if json.loads already decoded it once:
          data = [[{"col": val}, ...]]               (Python list with one list element)

        This helper iteratively unwraps until data is a flat list-of-dicts or a scalar.
        """
        for _ in range(3):  # max 3 unwrap passes
            if not isinstance(data, list) or len(data) != 1:
                break
            inner = data[0]
            if isinstance(inner, str):
                try:
                    data = json.loads(inner)
                except json.JSONDecodeError:
                    break
            elif isinstance(inner, list):
                data = inner
            else:
                break
        return data

    def _build_trace(self, plan: QueryPlan, execution_result: Dict[str, Any]) -> List[Dict]:
        trace = []
        # Prefer the corrected plan that was actually executed (if the correction loop
        # surfaced it); fall back to the original router plan only when unavailable.
        effective_plan = execution_result.get("final_plan", plan)
        results_by_db = {r.database: r for r in execution_result["results"]}
        for i, sq in enumerate(effective_plan.sub_queries):
            result = results_by_db.get(sq.database)
            trace.append(
                {
                    "step": i + 1,
                    "db": sq.database,
                    "query": sq.query,
                    "result": json.dumps(self._flatten_result_data(result.data), default=str)[:500] if result and result.success else None,
                    "error": result.error if result else None,
                    "correction_applied": execution_result["correction_applied"],
                }
            )
        return trace

    def end_session(self) -> None:
        """
        autoDream consolidation — call after all queries in a session are done.

        Implements the DreamTask pattern from kb/architecture/memory_system.md:
          1. Prune exact-duplicate corrections (same query + failure + fix)
          2. Keep recurring failures and high-impact join fixes
          3. A log that only grows becomes noise — discipline is removal

        The pruned log is written back to kb/corrections/corrections_log.md
        and the in-memory bundle is updated.
        """
        self._ctx_manager.auto_dream()

    def get_harness(self) -> EvaluationHarness:
        """Return the evaluation harness for external callers (e.g. run_benchmark)."""
        return self._harness

    def get_harness_session_id(self) -> str:
        """Return the active evaluation harness session id for this agent run."""
        return self._harness_session_id


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Oracle Forge Data Agent")
    parser.add_argument("--question", required=True, help="Natural language question")
    parser.add_argument(
        "--databases",
        nargs="+",
        default=[],
        help="Available database IDs (DAB dataset names, e.g. bookreview yelp)",
    )
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    agent = OracleForgeAgent()
    result = agent.answer(
        {
            "question": args.question,
            "available_databases": args.databases,
            "schema_info": {},
        }
    )

    output_json = json.dumps(result, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Result written to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
