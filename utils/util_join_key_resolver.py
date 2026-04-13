"""
join_key_resolver.py
────────────────────
Normalises entity IDs that are formatted differently across DAB databases.
This is DAB's second hardest challenge — cross-database joins silently return
empty results when IDs don't match.

Example mismatches in DAB datasets:
  bookreview:  PostgreSQL stores user_id as INTEGER (42)
               SQLite stores user_id as TEXT ("user_42")
  yelp:        DuckDB stores business_id as UUID
               MongoDB stores business_id as string with prefix ("biz_<uuid>")
  crmarenapro: customer_id is INT in PostgreSQL, "CUST-<id>" in SQLite

Usage:
    from utils.join_key_resolver import JoinKeyResolver

    resolver = JoinKeyResolver()
    normalised = resolver.resolve(
        value="CUST-1042",
        from_db="sqlite",
        to_db="postgresql",
        dataset="crmarenapro",
        entity="customer_id"
    )
    # → 1042
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ResolutionRule:
    """Single normalisation rule for one entity across two database types."""
    dataset:     str
    entity:      str       # logical entity name, e.g. "customer_id"
    from_db:     str       # source db type
    to_db:       str       # target db type
    description: str       # human-readable explanation for KB v2
    example_in:  str       # example value as it appears in from_db
    example_out: str       # example value as it should appear in to_db


# ── known rules grounded in DAB datasets ─────────────────────────────────
# Add new rules here as Drivers discover mismatches during benchmark runs.

RULES: list[ResolutionRule] = [
    ResolutionRule(
        dataset="bookreview",
        entity="user_id",
        from_db="sqlite",   to_db="postgresql",
        description="SQLite stores user_id as 'user_<int>', PostgreSQL as plain int",
        example_in="user_42", example_out="42",
    ),
    ResolutionRule(
        dataset="bookreview",
        entity="user_id",
        from_db="postgresql", to_db="sqlite",
        description="PostgreSQL int → SQLite 'user_<int>' prefix",
        example_in="42", example_out="user_42",
    ),
    ResolutionRule(
        dataset="crmarenapro",
        entity="customer_id",
        from_db="sqlite",   to_db="postgresql",
        description="SQLite uses 'CUST-<int>' prefix, PostgreSQL uses plain int",
        example_in="CUST-1042", example_out="1042",
    ),
    ResolutionRule(
        dataset="crmarenapro",
        entity="customer_id",
        from_db="postgresql", to_db="sqlite",
        description="PostgreSQL int → SQLite 'CUST-<int>' prefix",
        example_in="1042", example_out="CUST-1042",
    ),
    ResolutionRule(
        dataset="yelp",
        entity="business_id",
        from_db="mongodb",  to_db="duckdb",
        description="MongoDB stores business_id with 'biz_' prefix, DuckDB stores raw UUID",
        example_in="biz_3f2a...", example_out="3f2a...",
    ),
    ResolutionRule(
        dataset="yelp",
        entity="business_id",
        from_db="duckdb",   to_db="mongodb",
        description="DuckDB raw UUID → MongoDB 'biz_<uuid>' prefix",
        example_in="3f2a...", example_out="biz_3f2a...",
    ),
    ResolutionRule(
        dataset="googlelocal",
        entity="place_id",
        from_db="sqlite",   to_db="postgresql",
        description="SQLite stores place_id as TEXT, PostgreSQL as BIGINT",
        example_in="123456789", example_out="123456789",
    ),
    ResolutionRule(
        dataset="agnews",
        entity="article_id",
        from_db="sqlite",   to_db="mongodb",
        description="SQLite stores article_id as int, MongoDB as string",
        example_in="5001", example_out="5001",
    ),
    ResolutionRule(
        dataset="music_brainz_20k",
        entity="release_id",
        from_db="sqlite",   to_db="duckdb",
        description="SQLite uses MB UUID with hyphens, DuckDB stores without hyphens",
        example_in="3f2a4b5c-1234-...", example_out="3f2a4b5c1234...",
    ),
    ResolutionRule(
        dataset="music_brainz_20k",
        entity="release_id",
        from_db="duckdb",   to_db="sqlite",
        description="DuckDB UUID without hyphens → SQLite UUID with hyphens",
        example_in="3f2a4b5c1234...", example_out="3f2a4b5c-1234-...",
    ),
]


class JoinKeyResolver:
    """
    Resolves entity ID mismatches across DAB database boundaries.

    Methods:
        resolve()      — normalise a single value
        resolve_batch() — normalise a list of values
        get_rule()     — inspect the rule that would apply
        list_rules()   — return all known rules for a dataset
    """

    def __init__(self, extra_rules: list[ResolutionRule] | None = None):
        self._rules = RULES + (extra_rules or [])

    # ── public ────────────────────────────────────────────────────────────

    def resolve(
        self,
        value: Any,
        from_db: str,
        to_db: str,
        dataset: str,
        entity: str,
    ) -> Any:
        """
        Normalise a single entity ID from one database format to another.

        Returns:
            Normalised value ready for use in the target database query.

        Raises:
            KeyError: if no rule exists for this combination.
                      Callers MUST handle this — do not guess.
        """
        rule = self.get_rule(dataset, entity, from_db, to_db)
        return _apply_rule(value, rule)

    def resolve_batch(
        self,
        values: list[Any],
        from_db: str,
        to_db: str,
        dataset: str,
        entity: str,
    ) -> list[Any]:
        """Normalise a list of entity IDs in one call."""
        rule = self.get_rule(dataset, entity, from_db, to_db)
        return [_apply_rule(v, rule) for v in values]

    def get_rule(
        self,
        dataset: str,
        entity: str,
        from_db: str,
        to_db: str,
    ) -> ResolutionRule:
        """
        Return the matching rule or raise KeyError.
        Callers check for KeyError and log a Category 2 failure
        to the corrections log when no rule is found.
        """
        for r in self._rules:
            if (r.dataset == dataset and r.entity == entity
                    and r.from_db == from_db and r.to_db == to_db):
                return r
        raise KeyError(
            f"No join key rule for dataset='{dataset}' entity='{entity}' "
            f"from_db='{from_db}' to_db='{to_db}'. "
            f"Log this as a Category 2 failure and add a rule."
        )

    def list_rules(self, dataset: str | None = None) -> list[ResolutionRule]:
        """Return all rules, optionally filtered by dataset."""
        if dataset:
            return [r for r in self._rules if r.dataset == dataset]
        return list(self._rules)

    def to_markdown(self, dataset: str | None = None) -> str:
        """Format rules as markdown — paste directly into join_key_glossary.md."""
        rules = self.list_rules(dataset)
        if not rules:
            return "_No rules found._"
        lines = ["| Dataset | Entity | From DB | To DB | Example in | Example out | Notes |",
                 "|---------|--------|---------|-------|------------|-------------|-------|"]
        for r in rules:
            lines.append(
                f"| {r.dataset} | {r.entity} | {r.from_db} | {r.to_db} "
                f"| `{r.example_in}` | `{r.example_out}` | {r.description} |"
            )
        return "\n".join(lines)


# ── rule application logic ────────────────────────────────────────────────

def _apply_rule(value: Any, rule: ResolutionRule) -> Any:
    """Apply a single normalisation rule to a value."""
    s = str(value)

    # Strip known prefixes (sqlite → postgresql direction)
    if rule.from_db in ("sqlite", "mongodb") and rule.to_db in ("postgresql", "duckdb"):
        # "CUST-1042" → 1042
        if re.match(r'^[A-Z]+-\d+$', s):
            numeric = re.sub(r'^[A-Z]+-', '', s)
            return int(numeric) if numeric.isdigit() else numeric
        # "user_42" → 42
        if re.match(r'^[a-z]+_\d+$', s):
            numeric = s.split('_')[-1]
            return int(numeric) if numeric.isdigit() else numeric
        # "biz_<uuid>" → "<uuid>"
        if re.match(r'^[a-z]+_[0-9a-f-]{32,}$', s):
            return re.sub(r'^[a-z]+_', '', s)
        # UUID without hyphens → with hyphens (duckdb → sqlite)
        if re.match(r'^[0-9a-f]{32}$', s):
            return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"

    # Add known prefixes (postgresql/duckdb → sqlite/mongodb direction)
    if rule.from_db in ("postgresql", "duckdb") and rule.to_db in ("sqlite", "mongodb"):
        example_out = rule.example_out
        # "42" → "CUST-42"
        if re.match(r'^[A-Z]+-', example_out):
            prefix = re.match(r'^([A-Z]+-)', example_out).group(1)
            return f"{prefix}{s}"
        # "42" → "user_42"
        if re.match(r'^[a-z]+_', example_out):
            prefix = re.match(r'^([a-z]+_)', example_out).group(1)
            return f"{prefix}{s}"
        # UUID with hyphens → without
        if re.match(r'^[0-9a-f-]{36}$', s):
            return s.replace('-', '')

    # No transformation needed (type cast only, e.g. TEXT → BIGINT)
    return value
