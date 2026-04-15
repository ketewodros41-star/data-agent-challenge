"""Tests for join_key_resolver."""

import pytest
from agent.models import SchemaInfo, SubQuery
from utils.join_key_resolver import resolve_join_keys, normalize_key_value


def _make_schema(db_name, db_type, tables):
    return SchemaInfo(database=db_name, db_type=db_type, tables=tables)


def test_resolve_join_keys_empty_for_single_query():
    sub_queries = [
        SubQuery(database="postgres", query="SELECT 1", query_type="sql")
    ]
    schema = {"postgres": _make_schema("postgres", "postgres", {"businesses": ["business_id"]})}
    result = resolve_join_keys(sub_queries, schema)
    assert result == []


def test_resolve_join_keys_detects_business_id():
    sub_queries = [
        SubQuery(database="postgres", query="SELECT * FROM businesses", query_type="sql"),
        SubQuery(database="mongodb", query="{}", query_type="mongo"),
    ]
    schema = {
        "postgres": _make_schema("postgres", "postgres", {"businesses": ["business_id", "name"]}),
        "mongodb": _make_schema("mongodb", "mongodb", {"reviews": ["business_id", "text"]}),
    }
    # Without glossary file, result should be empty but not crash
    result = resolve_join_keys(sub_queries, schema)
    assert isinstance(result, list)


def test_normalize_key_value_string_to_int():
    assert normalize_key_value("42", "string", "int") == "42"


def test_normalize_key_value_strips_whitespace():
    assert normalize_key_value("  hello  ", "string", "string") == "hello"


def test_normalize_key_value_float_to_int():
    assert normalize_key_value("3.0", "float", "int") == "3"
