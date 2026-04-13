"""
tests/test_utils.py
───────────────────
Unit tests for all three utility modules.
Run with:  pytest utils/tests/test_utils.py -v

Tests that require live DB connections are marked @pytest.mark.integration
and skipped by default. Run them with:  pytest -m integration
"""

import pytest
from utils.join_key_resolver import JoinKeyResolver, ResolutionRule
from utils.multi_pass_retrieval import MultiPassRetriever


# ══════════════════════════════════════════════════════
# join_key_resolver tests
# ══════════════════════════════════════════════════════

class TestJoinKeyResolver:

    def setup_method(self):
        self.r = JoinKeyResolver()

    def test_crmarenapro_sqlite_to_pg(self):
        result = self.r.resolve(
            value="CUST-1042",
            from_db="sqlite", to_db="postgresql",
            dataset="crmarenapro", entity="customer_id"
        )
        assert result == 1042, f"Expected 1042, got {result}"

    def test_crmarenapro_pg_to_sqlite(self):
        result = self.r.resolve(
            value=1042,
            from_db="postgresql", to_db="sqlite",
            dataset="crmarenapro", entity="customer_id"
        )
        assert result == "CUST-1042", f"Expected 'CUST-1042', got {result}"

    def test_bookreview_sqlite_to_pg(self):
        result = self.r.resolve(
            value="user_42",
            from_db="sqlite", to_db="postgresql",
            dataset="bookreview", entity="user_id"
        )
        assert result == 42, f"Expected 42, got {result}"

    def test_bookreview_pg_to_sqlite(self):
        result = self.r.resolve(
            value=42,
            from_db="postgresql", to_db="sqlite",
            dataset="bookreview", entity="user_id"
        )
        assert result == "user_42", f"Expected 'user_42', got {result}"

    def test_yelp_mongodb_to_duckdb_strips_prefix(self):
        result = self.r.resolve(
            value="biz_abc123def456",
            from_db="mongodb", to_db="duckdb",
            dataset="yelp", entity="business_id"
        )
        assert not result.startswith("biz_"), f"Prefix not stripped: {result}"

    def test_music_brainz_uuid_hyphen_removal(self):
        uuid_with = "3f2a4b5c-1234-5678-abcd-ef0123456789"
        result = self.r.resolve(
            value=uuid_with,
            from_db="sqlite", to_db="duckdb",
            dataset="music_brainz_20k", entity="release_id"
        )
        assert "-" not in result, f"Hyphens not removed: {result}"

    def test_missing_rule_raises_key_error(self):
        with pytest.raises(KeyError) as exc_info:
            self.r.resolve(
                value="UNKNOWN-999",
                from_db="sqlite", to_db="mongodb",
                dataset="patents", entity="patent_id"
            )
        assert "Log this as a Category 2 failure" in str(exc_info.value)

    def test_resolve_batch(self):
        results = self.r.resolve_batch(
            values=["CUST-1", "CUST-2", "CUST-3"],
            from_db="sqlite", to_db="postgresql",
            dataset="crmarenapro", entity="customer_id"
        )
        assert results == [1, 2, 3]

    def test_list_rules_filtered_by_dataset(self):
        rules = self.r.list_rules("bookreview")
        assert all(r.dataset == "bookreview" for r in rules)
        assert len(rules) >= 2

    def test_custom_rule_injected(self):
        custom = ResolutionRule(
            dataset="test_ds", entity="test_id",
            from_db="sqlite", to_db="postgresql",
            description="test", example_in="TEST-1", example_out="1",
        )
        r = JoinKeyResolver(extra_rules=[custom])
        rule = r.get_rule("test_ds", "test_id", "sqlite", "postgresql")
        assert rule.description == "test"

    def test_to_markdown_returns_table(self):
        md = self.r.to_markdown("bookreview")
        assert "| Dataset |" in md
        assert "bookreview" in md


# ══════════════════════════════════════════════════════
# multi_pass_retrieval tests
# ══════════════════════════════════════════════════════

class TestMultiPassRetrieval:

    def setup_method(self):
        self.ret = MultiPassRetriever()

    def test_crm_query_routes_to_crmarenapro(self):
        result = self.ret.retrieve("Which customers had declining repeat purchases in Q3?")
        assert "crmarenapro" in result.datasets

    def test_book_query_routes_to_bookreview(self):
        result = self.ret.retrieve("What is the average rating for books published after 2010?")
        assert "bookreview" in result.datasets

    def test_stock_query_routes_to_stockmarket(self):
        result = self.ret.retrieve("Which stocks had the highest trading volume last month?")
        assert "stockmarket" in result.datasets or "stockindex" in result.datasets

    def test_yelp_query_routes_correctly(self):
        result = self.ret.retrieve("Which restaurants on Yelp have the most useful reviews?")
        assert "yelp" in result.datasets

    def test_cancer_query_routes_to_pancancer(self):
        result = self.ret.retrieve("What is the survival rate for patients with BRCA mutations?")
        assert "pancancer_atlas" in result.datasets

    def test_tables_are_ranked(self):
        result = self.ret.retrieve("customer support ticket volume by account")
        assert len(result.tables) > 0
        scores = [t["score"] for t in result.tables]
        assert scores == sorted(scores, reverse=True), "Tables not ranked by score"

    def test_result_has_explanation(self):
        result = self.ret.retrieve("book review ratings")
        assert "Pass 1" in result.explanation
        assert "Pass 2" in result.explanation

    def test_no_match_returns_warning(self):
        result = self.ret.retrieve("xyzzy frobnicator quantum blorp")
        assert len(result.warnings) > 0

    def test_top_datasets_limit(self):
        result = self.ret.retrieve("review rating stars", top_datasets=2)
        assert len(result.datasets) <= 2

    def test_top_tables_limit(self):
        result = self.ret.retrieve("customer order purchase review", top_tables=3)
        assert len(result.tables) <= 3

    def test_columns_returned_for_each_table(self):
        result = self.ret.retrieve("book author rating")
        for tbl in result.tables:
            matching = [c for c in result.columns if c["table"] == tbl["table"]]
            assert len(matching) > 0

    def test_explain_returns_string(self):
        explanation = self.ret.explain("stock price volume")
        assert isinstance(explanation, str)
        assert len(explanation) > 50


# ══════════════════════════════════════════════════════
# schema_introspector integration tests (require live DBs)
# ══════════════════════════════════════════════════════

@pytest.mark.integration
class TestSchemaIntrospector:
    """
    These tests require live database connections.
    Run with:  pytest -m integration
    """

    def test_introspect_sqlite_bookreview(self):
        from utils.schema_introspector import introspect
        result = introspect("bookreview", db_type="sqlite")
        assert result["dataset"] == "bookreview"
        assert len(result["databases"]) == 1
        assert result["databases"][0]["type"] == "sqlite"
        assert len(result["databases"][0]["tables"]) > 0

    def test_introspect_returns_columns(self):
        from utils.schema_introspector import introspect
        result = introspect("bookreview", db_type="sqlite")
        for tbl in result["databases"][0]["tables"]:
            assert "columns" in tbl
            assert len(tbl["columns"]) > 0
            for col in tbl["columns"]:
                assert "name" in col
                assert "type" in col

    def test_introspect_to_markdown(self):
        from utils.schema_introspector import introspect_to_markdown
        md = introspect_to_markdown("bookreview", db_type="sqlite")
        assert "## Schema: bookreview" in md
        assert "| Column | Type |" in md

    def test_unknown_dataset_raises(self):
        from utils.schema_introspector import introspect
        with pytest.raises(ValueError, match="Unknown dataset"):
            introspect("nonexistent_dataset")
