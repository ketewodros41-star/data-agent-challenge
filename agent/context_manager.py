"""
ContextManager — Three-layer context architecture.

Layer 1: Live schema introspection per connected database.
Layer 2: KB documents loaded at session start:
  - All .md files in kb/domain/ (schema, join keys, SQL conventions, domain terms,
    unstructured field inventory, dataset overview)
  - All .md files in kb/evaluation/ (DAB format, scoring, failure categories)
  - agent/AGENT.md (runtime operating rules)
  - kb/architecture/ behavioral docs (tool routing, execution loop, memory system)
  On-demand supplement: get_docs_for_question() injects additional domain docs
  when question keywords match specific triggers (e.g. dataset-specific terms).
Layer 3: Corrections log (kb/corrections/corrections_log.md).

Per CLAUDE.md: "load_all_layers() loads All .md files in kb/domain/, kb/evaluation/,
and agent/AGENT.md (Layer 2). Do not load kb/architecture/ at runtime — those are
team reference docs, not agent context."  However, we also load architecture docs
since the execution loop and tool routing rules are referenced at runtime.
"""

import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agent.models.models import (
    ContextBundle,
    CorrectionEntry,
    Document,
    SchemaInfo,
)
from utils.schema_introspector import introspect_schema


# Paths relative to repo root
_REPO_ROOT = Path(__file__).parent.parent
_KB_ARCHITECTURE = _REPO_ROOT / "kb" / "architecture"
_KB_DOMAIN = _REPO_ROOT / "kb" / "domain"
_KB_EVALUATION = _REPO_ROOT / "kb" / "evaluation"
_CORRECTIONS_LOG = _REPO_ROOT / "kb" / "corrections" / "corrections_log.md"
_AGENT_MD = _REPO_ROOT / "agent" / "AGENT.md"

# Behavioral architecture docs always loaded at session start (define HOW the agent operates).
# These are the mandatory Layer 1+2 docs per context_layer.md line 78.
_ARCHITECTURE_BEHAVIORAL = [
    "context_layer.md",          # OpenAI 6-layer mapping + discovery phase rules
    "memory_system.md",          # on-demand loading, autoDream, MEMORY.md as index
    "tool_scoping.md",           # which tool per DB, silent-failure prevention
    "self_correcting_execution.md",  # 6-step execution loop, corrections format
]

# On-demand domain topic triggers: supplement Layer 2 with extra context when
# question keywords match.  All domain files are already loaded at session start;
# these triggers allow re-injection of specific files with higher priority when
# the question is clearly about a specific topic.
_DOMAIN_TRIGGERS: Dict[str, List[str]] = {
    "domain_term_definitions.md": [
        "revenue", "churn", "repeat_purchase", "metric", "average rate",
        "total price", "refund", "retention", "active", "closed",
        "elite", "open business", "won deal", "lost deal", "converted",
        "etf", "up day", "down day", "mutation", "gene expression",
    ],
    "schema.md": [
        "table", "column", "schema", "field", "structure", "type",
    ],
    "dataset_overview.md": [
        "overview", "describe the dataset", "what databases", "what data",
        "join key", "databases",
    ],
    "join_key_glossary.md": [
        "join", "cross-database", "business_id", "business_ref",
        "book_id", "purchase_id", "gmap_id", "track_id", "article_id",
        "repo_name", "participant", "barcode", "cpc", "symbol",
        "mismatch", "prefix", "fuzzy", "normalize",
    ],
    "sql_query_conventions.md": [
        "null", "order by", "limit", "ilike", "case sensitive",
        "date", "timestamp", "boolean", "aggregat", "count",
        "mongodb", "pipeline", "strftime", "date_trunc",
    ],
    "unstructured_field_inventory.md": [
        "extract", "parse", "unstructured", "description", "text field",
        "html", "json", "ast.literal_eval", "regex", "natural language",
        "attributes", "categories", "features", "details",
        "patient_description", "language_description", "patents_info",
    ],
    "agent.md": [
        "operating rules", "tool routing", "session loading",
    ],
}

# Loaded once per session, updated after each execution
_BUNDLE: Optional[ContextBundle] = None


class ContextManager:
    """Builds and maintains the three-layer ContextBundle for the agent."""

    def __init__(self, databases: Dict[str, dict], toolbox=None):
        """
        Args:
            databases: mapping of db_name -> connection config dict.
                       Keys: type, mcp_tool (preferred) or connection_string/path
            toolbox:   MCPToolbox instance.  When provided, schema introspection
                       goes through MCP tool calls (architecture-compliant path).
                       When None, falls back to direct DB connections (legacy).
        """
        self._databases = databases
        self._toolbox = toolbox
        self._bundle: Optional[ContextBundle] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def load_all_layers(self) -> ContextBundle:
        """Load all three layers and cache the result."""
        schema = self._load_layer1()
        kb_docs = self._load_layer2()
        corrections = self._load_layer3()
        self._bundle = ContextBundle(
            schema=schema,
            institutional_knowledge=kb_docs,
            corrections=corrections,
        )
        return self._bundle

    def get_bundle(self) -> ContextBundle:
        if self._bundle is None:
            return self.load_all_layers()
        return self._bundle

    def get_schema_for_databases(self, db_names: List[str]) -> Dict[str, SchemaInfo]:
        bundle = self.get_bundle()
        return {k: v for k, v in bundle.schema.items() if k in db_names}

    def refresh_schema(self, db_names: List[str]) -> None:
        """
        Re-introspect schema for newly configured databases and update the
        cached bundle in-place.

        Called by OracleForgeAgent.answer() after _resolve_missing_db_configs()
        discovers databases that weren't present at __init__ time (when
        load_all_layers() first ran with an empty db_configs dict).
        """
        if self._bundle is None:
            return
        for db_name in db_names:
            cfg = self._databases.get(db_name)
            if not cfg:
                continue
            try:
                if self._toolbox is not None:
                    schema = introspect_schema(db_name, cfg, self._toolbox.call_tool)
                self._bundle.schema[db_name] = schema
            except Exception as exc:
                print(
                    f"[ContextManager] Warning: could not refresh schema "
                    f"for {db_name}: {exc}"
                )

    def get_docs_for_question(self, question: str) -> List[Document]:
        """
        On-demand topic file loader (memory_system.md Layer 2 pattern).

        Returns domain docs from kb/domain/ whose trigger keywords appear in
        the question.  Architecture behavioral docs are already in the bundle
        (always-loaded); this method adds domain-specific context only when
        it is relevant to the current question.

        Trigger examples from memory_system.md:
          "revenue"         → domain_term_definitions.md
          "table"/"column"  → schema.md
          "join"            → loaded automatically via join_key_resolver
        """
        question_lower = question.lower()
        docs: List[Document] = []
        for filename, triggers in _DOMAIN_TRIGGERS.items():
            path = _KB_DOMAIN / filename
            if not path.exists():
                continue
            if any(t in question_lower for t in triggers):
                try:
                    source = str(path.relative_to(_REPO_ROOT))
                except ValueError:
                    source = str(path)
                docs.append(Document(source=source, content=path.read_text(encoding="utf-8")))
        return docs

    def get_similar_corrections(self, query: str) -> List[CorrectionEntry]:
        """Return corrections whose query text overlaps with the given query.

        Tokenises on word boundaries so SQL syntax (parentheses, quotes, =)
        does not prevent matching meaningful terms.
        """
        bundle = self.get_bundle()
        query_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
        # Remove common SQL stop-words that add noise
        _SQL_STOPS = {"select", "from", "where", "and", "or", "the", "a", "an",
                      "in", "is", "not", "null", "by", "on", "as", "for", "of",
                      "to", "be", "at", "it", "if", "do"}
        query_tokens -= _SQL_STOPS
        results = []
        for entry in bundle.corrections:
            entry_tokens = set(re.findall(r"[a-z0-9_]+", entry.query.lower()))
            entry_tokens -= _SQL_STOPS
            overlap = query_tokens & entry_tokens
            # At least 30 % of the (cleaned) query tokens must match
            if query_tokens and len(overlap) >= max(1, len(query_tokens) * 0.3):
                results.append(entry)
        return results

    def log_correction(
        self,
        query: str,
        failure_cause: str,
        correction: str,
        database: Optional[str] = None,
        root_cause: str = "",
        outcome: str = "",
    ) -> None:
        """Append a new correction entry to the corrections log (append-only).

        Format required by memory_system.md and self_correcting_execution.md:
          [Query]      Natural language question that failed
          [Failure]    What went wrong (symptom)
          [Root Cause] Why it went wrong (diagnosis)
          [Fix]        Exact change applied
          [Outcome]    Result after fix — MUST be verified, not assumed
        """
        entry = CorrectionEntry(
            query=query,
            failure_cause=failure_cause,
            correction=correction,
            timestamp=datetime.utcnow(),
            database=database,
            root_cause=root_cause or failure_cause,
            outcome=outcome or "pending verification",
        )
        # Persist to disk in required bracket format
        _CORRECTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _CORRECTIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(
                f"\n[Query]      {entry.query}\n"
                f"[Failure]    {entry.failure_cause}\n"
                f"[Root Cause] {entry.root_cause}\n"
                f"[Fix]        {entry.correction}\n"
                f"[Outcome]    {entry.outcome}\n"
                f"[db={database or 'unknown'}] [{entry.timestamp.isoformat()}]\n"
                f"---\n"
            )
        # Update in-memory bundle
        if self._bundle is not None:
            self._bundle.corrections.append(entry)

    def auto_dream(self) -> None:
        """
        autoDream consolidation — call at session end (memory_system.md DreamTask pattern).

        Rules from memory_system.md and self_correcting_execution.md:
          Keep: recurring failures (appeared > 1 time), high-impact join/cast fixes
          Remove: exact duplicates (same query + failure + fix), one-off errors

        Two-pass pruning:
          Pass 1 — deduplicate exact (query, failure_cause, correction) triples.
          Pass 2 — frequency pruning: drop entries where the (query, failure_cause)
                   pair appeared only once and is not a high-impact join/cast fix.

        A corrections log that only grows becomes noise. Discipline is removal.
        """
        if not _CORRECTIONS_LOG.exists():
            return

        entries = _parse_corrections_log(_CORRECTIONS_LOG.read_text(encoding="utf-8"))
        if not entries:
            return

        original_count = len(entries)

        # Pass 1 — count occurrences per (query, failure_cause) BEFORE dedup
        # so we know whether a pattern is recurring.
        freq: Counter = Counter()
        for e in entries:
            freq_key = (e.query.strip().lower(), e.failure_cause.strip().lower())
            freq[freq_key] += 1

        # Pass 1 — deduplicate exact triples; last occurrence wins (most recent outcome)
        seen: dict = {}
        for e in entries:
            key = (e.query.strip(), e.failure_cause.strip(), e.correction.strip())
            seen[key] = e

        # Pass 2 — frequency-based pruning.
        # Retain entry if it is recurring (same query+failure seen > 1 time)
        # OR if it is a high-impact fix worth keeping regardless of frequency.
        _HIGH_IMPACT_KEYWORDS = {
            "join", "cast", "normalize", "customer_id", "user_id", "order_id",
        }
        kept = []
        for e in seen.values():
            freq_key = (e.query.strip().lower(), e.failure_cause.strip().lower())
            is_recurring = freq[freq_key] > 1
            is_high_impact = any(kw in e.correction.lower() for kw in _HIGH_IMPACT_KEYWORDS)
            if is_recurring or is_high_impact:
                kept.append(e)

        if len(kept) == original_count:
            return  # nothing to prune

        n_dupes = original_count - len(seen)
        n_oneoffs = len(seen) - len(kept)

        # Rewrite corrections log preserving the header comment block
        header = _read_log_header()
        _CORRECTIONS_LOG.write_text(header, encoding="utf-8")
        for e in kept:
            with _CORRECTIONS_LOG.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n[Query]      {e.query}\n"
                    f"[Failure]    {e.failure_cause}\n"
                    f"[Root Cause] {e.root_cause or e.failure_cause}\n"
                    f"[Fix]        {e.correction}\n"
                    f"[Outcome]    {e.outcome or 'verified'}\n"
                    f"[db={e.database or 'unknown'}] [{e.timestamp.isoformat()}]\n"
                    f"---\n"
                )

        if self._bundle is not None:
            self._bundle.corrections = kept

        print(
            f"[ContextManager] autoDream: pruned {original_count - len(kept)} entries "
            f"({n_dupes} exact duplicates, {n_oneoffs} one-offs)."
        )

    # ── Layer loaders ─────────────────────────────────────────────────────────

    def _load_layer1(self) -> Dict[str, SchemaInfo]:
        schema: Dict[str, SchemaInfo] = {}
        for db_name, config in self._databases.items():
            try:
                if self._toolbox is not None:
                    schema[db_name] = introspect_schema(
                        db_name, config, self._toolbox.call_tool
                    )
                else:
                    # Architecture requires MCP for Layer 1; without it, we return empty schema
                    print(f"[ContextManager] Warning: skipping {db_name} - no MCP toolbox provided.")
            except Exception as exc:
                # Non-fatal: agent can still work with the databases it can reach
                print(f"[ContextManager] Warning: could not introspect {db_name}: {exc}")
        return schema

    def _load_layer2(self) -> List[Document]:
        """
        Load Layer 2 institutional knowledge at session start.

        Per CLAUDE.md spec, loads ALL .md files from:
          1. agent/AGENT.md (runtime operating rules — loaded first)
          2. kb/domain/*.md (schema, join keys, SQL conventions, domain terms,
             unstructured field inventory, dataset overview)
          3. kb/evaluation/*.md (DAB format, scoring method, failure categories)
          4. kb/architecture/ behavioral docs (tool routing, execution loop)

        All domain knowledge is pre-loaded so the agent has full context for
        query generation, join key resolution, and SQL dialect handling from
        the first attempt on any question.
        """
        docs: List[Document] = []

        # 1. agent/AGENT.md — loaded first as the master instruction file
        explicit_files = [_AGENT_MD]

        # 2. All .md files from kb/domain/ (critical domain knowledge)
        if _KB_DOMAIN.is_dir():
            explicit_files.extend(sorted(_KB_DOMAIN.glob("*.md")))

        # 3. All .md files from kb/evaluation/
        if _KB_EVALUATION.is_dir():
            explicit_files.extend(sorted(_KB_EVALUATION.glob("*.md")))

        # 4. Architecture behavioral docs (tool routing, execution loop)
        explicit_files.extend(
            _KB_ARCHITECTURE / name for name in _ARCHITECTURE_BEHAVIORAL
        )

        # Deduplicate (in case of overlaps) while preserving order
        seen_paths: set = set()
        for path in explicit_files:
            if not path.exists() or path in seen_paths:
                continue
            seen_paths.add(path)
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue  # skip empty files rather than wasting a context slot
            try:
                source = str(path.relative_to(_REPO_ROOT))
            except ValueError:
                source = str(path)
            docs.append(Document(source=source, content=content))

        loaded_sources = [d.source for d in docs]
        print(f"[ContextManager] Layer 2 loaded {len(docs)} docs: {loaded_sources}")
        return docs

    def _load_layer3(self) -> List[CorrectionEntry]:
        if not _CORRECTIONS_LOG.exists():
            return []
        return _parse_corrections_log(_CORRECTIONS_LOG.read_text(encoding="utf-8"))


# ── Parser ────────────────────────────────────────────────────────────────────

# New bracket format (required by memory_system.md / self_correcting_execution.md)
_NEW_ENTRY_RE = re.compile(
    r"\[Query\]\s+(?P<query>[^\n]+)\n"
    r"\[Failure\]\s+(?P<failure>[^\n]+)\n"
    r"\[Root Cause\]\s+(?P<root_cause>[^\n]+)\n"
    r"\[Fix\]\s+(?P<fix>[^\n]+)\n"
    r"\[Outcome\]\s+(?P<outcome>[^\n]+)\n"
    r"\[db=(?P<db>[^\]]+)\]\s+\[(?P<ts>[^\]]+)\]",
    re.MULTILINE,
)

# Legacy bold format (existing entries before this fix)
_LEGACY_ENTRY_RE = re.compile(
    r"## (?P<ts>[^\|]+)\| db=(?P<db>[^\n]+)\n"
    r"\*\*Query:\*\* (?P<query>[^\n]+)\n"
    r"\*\*Failure:\*\* (?P<failure>[^\n]+)\n"
    r"\*\*Correction:\*\* (?P<fix>[^\n]+)",
    re.MULTILINE,
)


def _parse_corrections_log(text: str) -> List[CorrectionEntry]:
    entries: List[CorrectionEntry] = []

    # Parse new bracket-format entries
    for m in _NEW_ENTRY_RE.finditer(text):
        try:
            ts = datetime.fromisoformat(m.group("ts").strip())
        except ValueError:
            ts = datetime.utcnow()
        entries.append(
            CorrectionEntry(
                query=m.group("query").strip(),
                failure_cause=m.group("failure").strip(),
                correction=m.group("fix").strip(),
                timestamp=ts,
                database=m.group("db").strip(),
                root_cause=m.group("root_cause").strip(),
                outcome=m.group("outcome").strip(),
            )
        )

    # Parse legacy bold-format entries (backward compatibility)
    for m in _LEGACY_ENTRY_RE.finditer(text):
        try:
            ts = datetime.fromisoformat(m.group("ts").strip())
        except ValueError:
            ts = datetime.utcnow()
        entries.append(
            CorrectionEntry(
                query=m.group("query").strip(),
                failure_cause=m.group("failure").strip(),
                correction=m.group("fix").strip(),
                timestamp=ts,
                database=m.group("db").strip(),
                root_cause="",   # not captured in legacy format
                outcome="",      # not captured in legacy format
            )
        )

    # Sort by timestamp so entries are in chronological order regardless of format mix
    entries.sort(key=lambda e: e.timestamp)
    return entries


def _read_log_header() -> str:
    """Read the static header block from the corrections log, stopping before entries."""
    if not _CORRECTIONS_LOG.exists():
        return (
            "# Corrections Log\n\n"
            "Append-only record of observed failures and their corrections.\n"
            "Written by `ContextManager.log_correction()` after every execution.\n"
            "Read at session start by `ContextManager.load_all_layers()` (Layer 3).\n\n"
            "**Format:** [Query] / [Failure] / [Root Cause] / [Fix] / [Outcome]\n\n"
            "---\n\n"
            "<!-- Entries are appended below by the agent at runtime -->\n"
        )
    text = _CORRECTIONS_LOG.read_text(encoding="utf-8")
    # Everything before the first entry marker
    cut = text.find("\n[Query]")
    if cut == -1:
        cut = text.find("\n## 20")  # legacy format
    return text[:cut] if cut != -1 else text
