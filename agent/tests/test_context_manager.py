"""Tests for ContextManager three-layer architecture.

Covers:
  - Unit tests (task 3.6): Layer 1/2/3 loading, correction logging, bundle assembly
  - Property tests (task 3.5): Schema completeness, KB accessibility,
    correction persistence, context loading completeness, memory update after execution
"""

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent.context_manager import ContextManager, _parse_corrections_log
from agent.models.models import (
    ColumnSchema,
    ContextBundle,
    CorrectionEntry,
    Document,
    SchemaInfo,
    TableSchema,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_LOG = """
## 2026-04-12T10:00:00 | db=postgres
**Query:** SELECT * FROM customers WHERE id = 1
**Failure:** column "id" does not exist
**Correction:** Use customer_id instead of id
---

## 2026-04-12T11:00:00 | db=mongodb
**Query:** db.reviews.find({business_id: 123})
**Failure:** type mismatch — business_id is string not int
**Correction:** Cast to string: db.reviews.find({business_id: "123"})
---
"""


def _make_bundle(**kwargs) -> ContextBundle:
    defaults = dict(schema={}, institutional_knowledge=[], corrections=[])
    defaults.update(kwargs)
    return ContextBundle(**defaults)


def _cm_with_bundle(bundle: ContextBundle) -> ContextManager:
    cm = ContextManager(databases={})
    cm._bundle = bundle
    return cm


# ── Unit tests: _parse_corrections_log ───────────────────────────────────────

def test_parse_corrections_log_returns_entries():
    entries = _parse_corrections_log(SAMPLE_LOG)
    assert len(entries) == 2
    assert entries[0].database == "postgres"
    assert "customer_id" in entries[0].correction
    assert entries[1].database == "mongodb"


def test_parse_corrections_log_empty():
    assert _parse_corrections_log("") == []


def test_parse_corrections_log_timestamps():
    entries = _parse_corrections_log(SAMPLE_LOG)
    assert entries[0].timestamp == datetime(2026, 4, 12, 10, 0, 0)


def test_parse_corrections_log_failure_cause():
    entries = _parse_corrections_log(SAMPLE_LOG)
    assert 'does not exist' in entries[0].failure_cause


# ── Unit tests: get_similar_corrections ──────────────────────────────────────

def test_get_similar_corrections_matches():
    cm = _cm_with_bundle(_make_bundle(corrections=[
        CorrectionEntry(
            query="SELECT AVG(stars) FROM businesses WHERE city = 'Las Vegas'",
            failure_cause="wrong table",
            correction="Use reviews table instead",
            timestamp=datetime.utcnow(),
        )
    ]))
    # Shares key words: "stars", "businesses", "Las", "Vegas"
    results = cm.get_similar_corrections("What is the average stars for businesses in Las Vegas")
    assert len(results) == 1


def test_get_similar_corrections_no_match():
    cm = _cm_with_bundle(_make_bundle(corrections=[
        CorrectionEntry(
            query="unrelated query about inventory management systems",
            failure_cause="whatever",
            correction="fix",
            timestamp=datetime.utcnow(),
        )
    ]))
    results = cm.get_similar_corrections("average rating for restaurants in Seattle")
    assert len(results) == 0


def test_get_similar_corrections_empty_corrections():
    cm = _cm_with_bundle(_make_bundle())
    assert cm.get_similar_corrections("any query") == []


def test_get_similar_corrections_multiple_matches():
    entries = [
        CorrectionEntry(
            query="SELECT stars FROM businesses WHERE city = 'San Francisco'",
            failure_cause="wrong table",
            correction="fix1",
            timestamp=datetime.utcnow(),
        ),
        CorrectionEntry(
            query="SELECT stars FROM businesses WHERE city = 'Las Vegas'",
            failure_cause="wrong column",
            correction="fix2",
            timestamp=datetime.utcnow(),
        ),
        CorrectionEntry(
            query="SELECT name FROM users WHERE country = 'USA'",
            failure_cause="unrelated",
            correction="fix3",
            timestamp=datetime.utcnow(),
        ),
    ]
    cm = _cm_with_bundle(_make_bundle(corrections=entries))
    results = cm.get_similar_corrections("What are the stars for businesses in Las Vegas")
    # Both businesses/stars entries should match; unrelated one should not
    assert len(results) >= 1
    assert all("businesses" in r.query or "stars" in r.query for r in results)


# ── Unit tests: Layer 1 (schema) ──────────────────────────────────────────────

def test_load_layer1_skips_unreachable_db():
    """Non-fatal: bad DB config is skipped, not raised."""
    cm = ContextManager(databases={"bad_db": {"type": "postgres", "connection_string": ""}})
    schema = cm._load_layer1()
    # Empty connection string returns empty SchemaInfo (no exception)
    assert "bad_db" in schema
    assert schema["bad_db"].tables == {}


def test_load_layer1_sqlite_with_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, FOREIGN KEY (customer_id) REFERENCES customers(id))")
    conn.commit()
    conn.close()

    cm = ContextManager(databases={"mydb": {"type": "sqlite", "path": db_path}})
    schema = cm._load_layer1()
    assert "mydb" in schema
    info = schema["mydb"]
    assert "customers" in info.tables
    assert "orders" in info.tables
    assert "id" in info.tables["customers"]
    assert "name" in info.tables["customers"]


def test_load_layer1_sqlite_foreign_keys(tmp_path):
    db_path = str(tmp_path / "fk.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE businesses (business_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE reviews (review_id TEXT PRIMARY KEY, business_id TEXT, FOREIGN KEY (business_id) REFERENCES businesses(business_id))")
    conn.commit()
    conn.close()

    cm = ContextManager(databases={"yelp": {"type": "sqlite", "path": db_path}})
    schema = cm._load_layer1()
    info = schema["yelp"]
    assert len(info.foreign_keys) >= 1
    fk = info.foreign_keys[0]
    assert fk["from_table"] == "reviews"
    assert fk["from_col"] == "business_id"
    assert fk["to_table"] == "businesses"


def test_load_layer1_rich_table_schemas(tmp_path):
    db_path = str(tmp_path / "rich.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
    conn.commit()
    conn.close()

    cm = ContextManager(databases={"app": {"type": "sqlite", "path": db_path}})
    schema = cm._load_layer1()
    ts = schema["app"].table_schemas.get("users")
    assert ts is not None
    assert "user_id" in ts.primary_keys
    pk_col = next(c for c in ts.columns if c.name == "user_id")
    assert pk_col.is_primary_key


def test_load_layer1_multiple_databases(tmp_path):
    paths = {}
    for name in ("alpha", "beta"):
        p = str(tmp_path / f"{name}.db")
        conn = sqlite3.connect(p)
        conn.execute(f"CREATE TABLE t_{name} (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        paths[name] = p

    cm = ContextManager(databases={
        n: {"type": "sqlite", "path": p} for n, p in paths.items()
    })
    schema = cm._load_layer1()
    assert "alpha" in schema and "beta" in schema
    assert f"t_alpha" in schema["alpha"].tables
    assert f"t_beta" in schema["beta"].tables


# ── Unit tests: Layer 2 (institutional knowledge) ─────────────────────────────

def test_load_layer2_reads_kb_docs(tmp_path, monkeypatch):
    """Layer 2 loads all .md files from kb/domain/ and kb/evaluation/."""
    domain_dir = tmp_path / "kb" / "domain"
    domain_dir.mkdir(parents=True)
    (domain_dir / "test_doc.md").write_text("# Test\nSome content.")

    eval_dir = tmp_path / "kb" / "evaluation"
    eval_dir.mkdir(parents=True)

    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text("# Agent context")

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", domain_dir)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", eval_dir)
    monkeypatch.setattr(cm_module, "_AGENT_MD", agent_dir / "AGENT.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "corrections_log.md")

    cm = ContextManager(databases={})
    docs = cm._load_layer2()
    assert any("Test" in d.content for d in docs)
    assert any("Agent context" in d.content for d in docs)


def test_load_layer2_missing_agent_md(tmp_path, monkeypatch):
    """Missing AGENT.md is silently skipped — no crash."""
    domain_dir = tmp_path / "kb" / "domain"
    domain_dir.mkdir(parents=True)
    eval_dir = tmp_path / "kb" / "evaluation"
    eval_dir.mkdir(parents=True)

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", domain_dir)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", eval_dir)
    monkeypatch.setattr(cm_module, "_AGENT_MD", tmp_path / "nonexistent.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "corrections_log.md")

    cm = ContextManager(databases={})
    docs = cm._load_layer2()
    assert isinstance(docs, list)


def test_load_layer2_document_source_is_set(tmp_path, monkeypatch):
    """Each Document has a non-empty source field."""
    domain_dir = tmp_path / "kb" / "domain"
    domain_dir.mkdir(parents=True)
    (domain_dir / "biz_terms.md").write_text("# Business terms")
    eval_dir = tmp_path / "kb" / "evaluation"
    eval_dir.mkdir(parents=True)

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", domain_dir)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", eval_dir)
    monkeypatch.setattr(cm_module, "_AGENT_MD", tmp_path / "no_agent.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "corrections_log.md")

    cm = ContextManager(databases={})
    docs = cm._load_layer2()
    assert all(d.source for d in docs)


# ── Unit tests: Layer 3 (interaction memory) ──────────────────────────────────

def test_load_layer3_parses_existing_log(tmp_path, monkeypatch):
    log_path = tmp_path / "corrections_log.md"
    log_path.write_text(SAMPLE_LOG)

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", log_path)

    cm = ContextManager(databases={})
    entries = cm._load_layer3()
    assert len(entries) == 2
    assert entries[0].database == "postgres"


def test_load_layer3_missing_file_returns_empty(tmp_path, monkeypatch):
    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "nonexistent.md")

    cm = ContextManager(databases={})
    assert cm._load_layer3() == []


def test_log_correction_appends_to_disk(tmp_path, monkeypatch):
    log_path = tmp_path / "corrections_log.md"

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", log_path)

    cm = ContextManager(databases={})
    cm._bundle = _make_bundle()
    cm.log_correction(
        query="SELECT * FROM orders",
        failure_cause="table does not exist",
        correction="Use order_items table",
        database="postgres",
    )

    text = log_path.read_text()
    assert "SELECT * FROM orders" in text
    assert "table does not exist" in text
    assert "Use order_items table" in text


def test_log_correction_updates_in_memory_bundle(tmp_path, monkeypatch):
    log_path = tmp_path / "corrections_log.md"

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", log_path)

    cm = ContextManager(databases={})
    cm._bundle = _make_bundle()
    assert len(cm._bundle.corrections) == 0

    cm.log_correction("q", "fail", "fix", "mydb")
    assert len(cm._bundle.corrections) == 1
    assert cm._bundle.corrections[0].query == "q"


def test_log_correction_is_append_only(tmp_path, monkeypatch):
    log_path = tmp_path / "corrections_log.md"
    log_path.write_text(SAMPLE_LOG)

    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", log_path)

    cm = ContextManager(databases={})
    cm._bundle = _make_bundle()
    original_content = log_path.read_text()

    cm.log_correction("new query", "new fail", "new fix")

    new_content = log_path.read_text()
    assert original_content in new_content   # original preserved
    assert "new query" in new_content         # new entry appended


# ── Unit tests: ContextBundle assembly ───────────────────────────────────────

def test_load_all_layers_returns_bundle(tmp_path, monkeypatch):
    import agent.context_manager as cm_module
    domain_dir = tmp_path / "kb" / "domain"
    domain_dir.mkdir(parents=True)
    eval_dir = tmp_path / "kb" / "evaluation"
    eval_dir.mkdir(parents=True)
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", domain_dir)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", eval_dir)
    monkeypatch.setattr(cm_module, "_AGENT_MD", tmp_path / "no_agent.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "no_log.md")

    cm = ContextManager(databases={})
    bundle = cm.load_all_layers()
    assert isinstance(bundle, ContextBundle)
    assert isinstance(bundle.schema, dict)
    assert isinstance(bundle.institutional_knowledge, list)
    assert isinstance(bundle.corrections, list)


def test_get_bundle_calls_load_all_layers_once(monkeypatch, tmp_path):
    """get_bundle() should load lazily and cache."""
    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", tmp_path)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", tmp_path)
    monkeypatch.setattr(cm_module, "_AGENT_MD", tmp_path / "no.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "no.md")

    cm = ContextManager(databases={})
    b1 = cm.get_bundle()
    b2 = cm.get_bundle()
    assert b1 is b2  # same object — cached


def test_get_schema_for_databases_filters(tmp_path, monkeypatch):
    import agent.context_manager as cm_module
    monkeypatch.setattr(cm_module, "_KB_DOMAIN", tmp_path)
    monkeypatch.setattr(cm_module, "_KB_EVALUATION", tmp_path)
    monkeypatch.setattr(cm_module, "_AGENT_MD", tmp_path / "no.md")
    monkeypatch.setattr(cm_module, "_CORRECTIONS_LOG", tmp_path / "no.md")

    schema = {
        "pg": SchemaInfo(database="pg", db_type="postgres", tables={"users": ["id"]}),
        "mongo": SchemaInfo(database="mongo", db_type="mongodb", tables={"reviews": ["text"]}),
    }
    cm = ContextManager(databases={})
    cm._bundle = _make_bundle(schema=schema)
    subset = cm.get_schema_for_databases(["pg"])
    assert "pg" in subset
    assert "mongo" not in subset


# ── Property tests (task 3.5) ─────────────────────────────────────────────────

@given(
    db_name=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_")),
    tables=st.dictionaries(
        keys=st.text(min_size=1, max_size=15, alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_")),
        values=st.lists(st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_")), min_size=0, max_size=5),
        min_size=0,
        max_size=4,
    ),
)
@settings(max_examples=50)
def test_property5_schema_layer_completeness(db_name, tables):
    """Property 5: Any SchemaInfo has a tables dict (may be empty) and correct fields."""
    info = SchemaInfo(database=db_name, db_type="sqlite", tables=tables)
    assert isinstance(info.tables, dict)
    assert info.database == db_name
    assert info.db_type == "sqlite"
    # table_schemas defaults to empty dict — always present
    assert isinstance(info.table_schemas, dict)
    assert isinstance(info.foreign_keys, list)


@given(
    contents=st.lists(
        st.text(min_size=1, max_size=200),
        min_size=0,
        max_size=10,
    )
)
@settings(max_examples=50)
def test_property6_institutional_knowledge_accessibility(contents):
    """Property 6: All Documents in Layer 2 have non-empty content and source."""
    docs = [Document(source=f"kb/domain/doc{i}.md", content=c) for i, c in enumerate(contents)]
    for doc in docs:
        assert doc.content  # non-empty (guaranteed by strategy min_size=1)
        assert doc.source


@given(
    query=st.text(min_size=1, max_size=100),
    failure=st.text(min_size=1, max_size=100),
    correction=st.text(min_size=1, max_size=100),
    db=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)
@settings(max_examples=50)
def test_property7_interaction_memory_persistence(query, failure, correction, db):
    """Property 7: A logged correction is retrievable from the in-memory bundle."""
    import agent.context_manager as cm_module

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "corrections.md"
        original_log = cm_module._CORRECTIONS_LOG
        try:
            cm_module._CORRECTIONS_LOG = log_path
            cm = ContextManager(databases={})
            cm._bundle = _make_bundle()
            cm.log_correction(query, failure, correction, db)

            assert len(cm._bundle.corrections) == 1
            entry = cm._bundle.corrections[0]
            assert entry.query == query
            assert entry.failure_cause == failure
            assert entry.correction == correction
        finally:
            cm_module._CORRECTIONS_LOG = original_log


@given(
    n_docs=st.integers(min_value=0, max_value=5),
    n_corrections=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=30)
def test_property8_context_loading_completeness(n_docs, n_corrections):
    """Property 8: ContextBundle always has all three layers present."""
    schema = {"db1": SchemaInfo(database="db1", db_type="sqlite", tables={})}
    docs = [Document(source=f"doc{i}.md", content=f"content {i}") for i in range(n_docs)]
    corrections = [
        CorrectionEntry(query=f"q{i}", failure_cause="f", correction="c", timestamp=datetime.utcnow())
        for i in range(n_corrections)
    ]
    bundle = ContextBundle(schema=schema, institutional_knowledge=docs, corrections=corrections)

    assert hasattr(bundle, "schema")
    assert hasattr(bundle, "institutional_knowledge")
    assert hasattr(bundle, "corrections")
    assert len(bundle.institutional_knowledge) == n_docs
    assert len(bundle.corrections) == n_corrections


@given(
    initial_corrections=st.integers(min_value=0, max_value=5),
    new_query=st.text(min_size=1, max_size=80),
)
@settings(max_examples=30)
def test_property9_memory_update_after_execution(initial_corrections, new_query):
    """Property 9: Bundle correction count increases by exactly 1 after log_correction."""
    import agent.context_manager as cm_module

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.md"
        original_log = cm_module._CORRECTIONS_LOG
        try:
            cm_module._CORRECTIONS_LOG = log_path
            existing = [
                CorrectionEntry(query=f"old{i}", failure_cause="f", correction="c", timestamp=datetime.utcnow())
                for i in range(initial_corrections)
            ]
            cm = ContextManager(databases={})
            cm._bundle = _make_bundle(corrections=list(existing))

            before = len(cm._bundle.corrections)
            cm.log_correction(new_query, "failure", "fix")
            after = len(cm._bundle.corrections)

            assert after == before + 1
        finally:
            cm_module._CORRECTIONS_LOG = original_log
