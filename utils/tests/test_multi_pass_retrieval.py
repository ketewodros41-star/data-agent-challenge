"""Tests for multi_pass_retrieval."""

import pytest
from agent.models import Document
from utils.multi_pass_retrieval import retrieve, retrieve_with_scores


def _doc(source, content):
    return Document(source=source, content=content)


DOCS = [
    _doc("a.md", "PostgreSQL customers orders transactions relational database"),
    _doc("b.md", "MongoDB reviews text unstructured documents collections"),
    _doc("c.md", "DuckDB analytics aggregation large dataset columnar"),
    _doc("d.md", "SQLite reference dimension lookup categories regions"),
]


def test_retrieve_returns_relevant_docs():
    results = retrieve("customer orders database", DOCS, top_k=2)
    assert any("customers" in d.content for d in results)


def test_retrieve_top_k_limit():
    results = retrieve("postgres mongodb sqlite duckdb", DOCS, top_k=2)
    assert len(results) <= 2


def test_retrieve_empty_documents():
    assert retrieve("anything", [], top_k=5) == []


def test_retrieve_with_scores_returns_pairs():
    results = retrieve_with_scores("reviews mongodb", DOCS, top_k=3)
    assert len(results) <= 3
    for doc, score in results:
        assert isinstance(doc, Document)
        assert 0.0 <= score <= 1.0


def test_retrieve_min_score_filters():
    results = retrieve("absolutely unrelated xyzzy quantum", DOCS, top_k=5, min_score=0.5)
    assert len(results) == 0
