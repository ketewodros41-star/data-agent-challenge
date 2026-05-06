"""
ContextManager — Three-layer context architecture.

Layer 1: Live schema introspection per connected database.
Layer 2: KB documents loaded at session start:
  - agent/AGENT.md (runtime operating rules)
  - Small, dataset-agnostic docs from kb/domain/ (domain terms, join key
    glossary, SQL conventions) via explicit allowlist.
  - All .md files in kb/evaluation/ (DAB format, scoring, failure categories)
  Dataset-scoped injection at answer() time:
    - schema.md, dataset_overview.md, unstructured_field_inventory.md are
      sliced to the sections relevant to the current `available_databases`
      (see `get_dataset_scoped_docs`).  Fail-open: unknown dataset → full doc.
  On-demand supplement: get_docs_for_question() injects additional docs when
  question keywords match specific triggers.
Layer 3: Corrections log (kb/corrections/corrections_log.md).

Per CLAUDE.md: kb/architecture/ is team reference material and is NOT loaded at
runtime.  Domain docs are loaded via an allowlist rather than a glob so that
incidental files (CHANGELOG.MD, drafts) do not leak into the prompt.
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
_KB_DOMAIN = _REPO_ROOT / "kb" / "domain"
# _KB_EVALUATION = _REPO_ROOT / "kb" / "evaluation"
_CORRECTIONS_LOG = _REPO_ROOT / "kb" / "corrections" / "corrections_log.md"
_AGENT_MD = _REPO_ROOT / "agent" / "AGENT.md"

# Small, dataset-agnostic kb/domain/ files loaded at session start.
# Dataset-partitioned files (schema.md, dataset_overview.md,
# unstructured_field_inventory.md) are injected on-demand per query via
# get_dataset_scoped_docs().
_DOMAIN_ALWAYS_LOAD = [
    "domain_term_definitions.md",
    "join_key_glossary.md",
    "sql_query_conventions.md",
]

# Files sliced per-dataset and injected at answer() time via
# get_dataset_scoped_docs().  Each one partitions its body into per-dataset
# `## ...` sections plus an optional preamble/trailing global sections.
_DATASET_SCOPED_FILES = [
    "dataset_overview.md",
    "schema.md",
    "unstructured_field_inventory.md",
]

# On-demand keyword triggers for the small always-loaded docs only.  Dataset-
# scoped files are NOT listed here — scoping is handled uniformly by
# get_dataset_scoped_docs() at answer() time to avoid double-injection.
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
}

# Regex matching `## N. dataset_name` headings in dataset_overview.md / schema.md
_DATASET_HEADING_RE = re.compile(r"^##\s+\d+\.\s+(\S+)", re.MULTILINE)

# Regex matching any level-2 heading `## Title` (for slicing; excludes `###`)
_H2_RE = re.compile(r"^## (.+?)$", re.MULTILINE)

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
        # Lazily built from dataset_overview.md.  One db_id may map to more
        # than one dataset (e.g. `review_database` exists in both googlelocal
        # and bookreview), so we keep a list not a single value.
        self._db_to_dataset: Optional[Dict[str, List[str]]] = None
        self._all_datasets: Optional[List[str]] = None

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
        the question, EXCLUDING any doc whose source is already present in the
        loaded bundle.  This prevents silent duplication when callers merge the
        result into context.institutional_knowledge, because most trigger files
        are also on the always-load allowlist (`_DOMAIN_ALWAYS_LOAD`).

        Trigger examples from memory_system.md:
          "revenue"         → domain_term_definitions.md
          "table"/"column"  → schema.md
          "join"            → loaded automatically via join_key_resolver
        """
        question_lower = question.lower()
        already_loaded = {
            doc.source for doc in (self._bundle.institutional_knowledge if self._bundle else [])
        }
        docs: List[Document] = []
        for filename, triggers in _DOMAIN_TRIGGERS.items():
            path = _KB_DOMAIN / filename
            if not path.exists():
                continue
            if not any(t in question_lower for t in triggers):
                continue
            try:
                source = str(path.relative_to(_REPO_ROOT))
            except ValueError:
                source = str(path)
            if source in already_loaded:
                continue
            docs.append(Document(source=source, content=path.read_text(encoding="utf-8")))
        return docs

    def get_dataset_scoped_docs(self, db_names: List[str]) -> List[Document]:
        """
        Return per-dataset slices of the large KB files (`schema.md`,
        `dataset_overview.md`, `unstructured_field_inventory.md`) for the given
        database ids.

        Slicing rules:
          - Preamble (text before first `## ` heading) is always kept.
          - Each `## ` section whose heading contains any *known* dataset name
            is treated as dataset-specific and kept only if that dataset is
            in the requested set.
          - `## ` sections whose heading does NOT match any known dataset are
            treated as global and kept unconditionally (e.g.
            "## SQL dialect quick notes", "## Summary: extraction library").

        Fail-open: if no dataset names can be resolved (empty input, unknown
        db ids, or dataset_overview.md is missing), the FULL file is returned.
        This guarantees no context loss.
        """
        db_to_dataset = self._build_db_to_dataset_map()
        all_datasets = set(self._all_datasets or [])
        wanted: set = set()
        for db in db_names:
            wanted.update(db_to_dataset.get(db, []))
        docs: List[Document] = []
        for filename in _DATASET_SCOPED_FILES:
            path = _KB_DOMAIN / filename
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            sliced = _slice_doc_by_datasets(text, wanted, all_datasets) if wanted else text
            try:
                source = str(path.relative_to(_REPO_ROOT))
            except ValueError:
                source = str(path)
            docs.append(Document(source=source, content=sliced))
        return docs

    def _build_db_to_dataset_map(self) -> Dict[str, List[str]]:
        """Parse dataset_overview.md once to map db_id → list of dataset_names.

        A db_id may belong to more than one dataset (e.g. `review_database`
        appears under both googlelocal and bookreview).  We collect all
        matches; the caller unions them to build the scoping set.
        """
        if self._db_to_dataset is not None:
            return self._db_to_dataset
        result: Dict[str, List[str]] = {}
        all_datasets: List[str] = []
        overview_path = _KB_DOMAIN / "dataset_overview.md"
        if not overview_path.exists():
            self._db_to_dataset = result
            self._all_datasets = all_datasets
            return result
        text = overview_path.read_text(encoding="utf-8")
        headings = list(_DATASET_HEADING_RE.finditer(text))
        row_re = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9_]*)\s*\|", re.MULTILINE)
        for idx, match in enumerate(headings):
            dataset_name = match.group(1).lower()
            all_datasets.append(dataset_name)
            start = match.start()
            end = headings[idx + 1].start() if idx + 1 < len(headings) else len(text)
            section = text[start:end]
            for row in row_re.finditer(section):
                db_id = row.group(1).strip()
                if db_id.lower() in ("database", "db", "databases"):
                    continue
                datasets = result.setdefault(db_id, [])
                if dataset_name not in datasets:
                    datasets.append(dataset_name)
        self._db_to_dataset = result
        self._all_datasets = all_datasets
        return result

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

        Loads, in order:
          1. agent/AGENT.md (runtime operating rules — loaded first)
          2. kb/domain/ files from _DOMAIN_ALWAYS_LOAD allowlist
          3. kb/evaluation/*.md (DAB format, scoring method, failure categories)

        kb/architecture/ is intentionally NOT loaded here — those docs describe
        how the agent itself is built and are team reference material, not
        query-solving context.  The domain allowlist avoids pulling in
        incidental files (CHANGELOG.MD, drafts) that a glob would sweep up.
        """
        docs: List[Document] = []

        # 1. agent/AGENT.md — loaded first as the master instruction file
        explicit_files = [_AGENT_MD]

        # 2. kb/domain/ — explicit allowlist
        explicit_files.extend(_KB_DOMAIN / name for name in _DOMAIN_ALWAYS_LOAD)

        # # 3. All .md files from kb/evaluation/
        # if _KB_EVALUATION.is_dir():
        #     explicit_files.extend(sorted(_KB_EVALUATION.glob("*.md")))

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


def _slice_doc_by_datasets(text: str, wanted: set, all_datasets: set) -> str:
    """Slice a dataset-partitioned KB doc.  See `ContextManager.get_dataset_scoped_docs`.

    - Text before the first `## ` heading is kept verbatim (preamble).
    - Each `## ` section is classified by whether its heading contains any
      name from `all_datasets` (case-insensitive, lowercased substring match).
    - Dataset-specific sections are kept only if their matched dataset is in
      `wanted`.  Global sections (no dataset in heading) are always kept.
    - Fail-open: empty `wanted` or empty `all_datasets` → return `text` unchanged.
    """
    if not wanted or not all_datasets:
        return text
    headings = list(_H2_RE.finditer(text))
    if not headings:
        return text
    wanted_lower = {w.lower() for w in wanted}
    all_lower = {a.lower() for a in all_datasets}
    # Preamble: everything before the first ## heading
    out_parts = [text[: headings[0].start()]]
    for i, m in enumerate(headings):
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section_text = text[m.start():section_end]
        heading_lower = m.group(1).lower()
        matched = next((ds for ds in all_lower if ds in heading_lower), None)
        if matched is None:
            out_parts.append(section_text)           # global — keep
        elif matched in wanted_lower:
            out_parts.append(section_text)           # wanted dataset — keep
        # else: other dataset — drop
    return "".join(out_parts)
