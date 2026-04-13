# Shared Utility Library

Three reusable modules built specifically for the Oracle Forge data agent.
Any team member can import and use these. Each module is independently usable.

---

## Modules

### 1. `schema_introspector.py`
Connects to any of the four DAB database types and returns a standardised
schema dict — same output format regardless of source (PostgreSQL, MongoDB,
SQLite, DuckDB).

**Use it when:** Drivers need to populate KB v2 database schemas, or the agent
needs to inspect a live schema at runtime before executing a query.

```python
from utils.schema_introspector import introspect, introspect_to_markdown

# Get schema as Python dict
schema = introspect("bookreview", db_type="sqlite")
# → {"dataset": "bookreview", "databases": [{"type": "sqlite", "tables": [...]}]}

# Get schema as markdown — paste directly into kb/domain/dab_database_schemas.md
md = introspect_to_markdown("bookreview")
print(md)

# Introspect all databases for a dataset at once
all_dbs = introspect("crmarenapro")
```

---

### 2. `join_key_resolver.py`
Normalises entity IDs that are formatted differently across DAB databases.
Prevents cross-database joins from silently returning empty results.

**Use it when:** The agent is about to join data across two different database
types. Call this before passing any entity ID to a database tool.

```python
from utils.join_key_resolver import JoinKeyResolver

resolver = JoinKeyResolver()

# Resolve a single ID
normalised = resolver.resolve(
    value="CUST-1042",
    from_db="sqlite",
    to_db="postgresql",
    dataset="crmarenapro",
    entity="customer_id"
)
# → 1042

# Resolve a batch
ids = resolver.resolve_batch(
    values=["CUST-1", "CUST-2", "CUST-3"],
    from_db="sqlite", to_db="postgresql",
    dataset="crmarenapro", entity="customer_id"
)
# → [1, 2, 3]

# If no rule exists → KeyError → log as Category 2 failure to corrections log
try:
    resolver.resolve(value="X-999", from_db="sqlite", to_db="mongodb",
                     dataset="patents", entity="patent_id")
except KeyError as e:
    print(f"No rule found: {e}")
    # → log to kb/corrections/corrections_log.md

# Print all known rules as markdown for KB v2
print(resolver.to_markdown())
```

**Adding new rules:** When a Driver discovers a new join key mismatch, add a
`ResolutionRule` entry to the `RULES` list in `join_key_resolver.py` and log
the discovery in `kb/corrections/corrections_log.md`.

---

### 3. `multi_pass_retrieval.py`
Three-pass table discovery that narrows from all 12 DAB datasets to the
specific tables relevant to a query. Implements the discovery-first discipline
from the OpenAI data agent — prevents overconfident wrong-table selection.

**Use it when:** Before the agent executes any query. Always run retrieval
first to identify candidate tables, then validate selection before executing.

```python
from utils.multi_pass_retrieval import MultiPassRetriever

retriever = MultiPassRetriever()

result = retriever.retrieve(
    "Which customers had declining repeat purchases in Q3?"
)

print(result.datasets)      # ["crmarenapro"]
print(result.tables)        # [{"dataset": "crmarenapro", "table": "orders", "score": 0.87, ...}]
print(result.columns)       # [{"table": "orders", "columns": ["customer_id", "purchase_date"]}]
print(result.explanation)   # Full Pass 1/2/3 reasoning trace
print(result.warnings)      # Empty if retrieval succeeded

# Just get the explanation (useful for agent traces)
print(retriever.explain("book review ratings by genre"))
```

---

## Running Tests

```bash
# Unit tests (no live DB required)
pytest utils/tests/test_utils.py -v

# Integration tests (requires live PostgreSQL, MongoDB, SQLite, DuckDB)
pytest utils/tests/test_utils.py -v -m integration
```

Expected output for unit tests:
```
PASSED  test_crmarenapro_sqlite_to_pg
PASSED  test_crmarenapro_pg_to_sqlite
PASSED  test_bookreview_sqlite_to_pg
...
PASSED  test_crm_query_routes_to_crmarenapro
PASSED  test_book_query_routes_to_bookreview
... (22 tests total)
```

---

## Extending the Modules

| What changed | Where to update |
|---|---|
| New join key mismatch discovered | Add `ResolutionRule` to `RULES` in `join_key_resolver.py` + entry in `kb/corrections/corrections_log.md` |
| New dataset loaded on server | Add entry to `DATASET_DB_MAP` in `schema_introspector.py` and `DATASET_INDEX` in `multi_pass_retrieval.py` |
| New table discovered in a dataset | Add entry to `TABLE_INDEX` in `multi_pass_retrieval.py` |
| New domain keyword signal | Add to `DATASET_INDEX` keywords list in `multi_pass_retrieval.py` |

---

## Authors
Intelligence Officers — Oracle Forge Team, TRP1 FDE Programme, April 2026
