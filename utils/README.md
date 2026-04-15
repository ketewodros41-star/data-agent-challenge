# utils — Shared Utility Library

Shared utilities consumed by the Oracle Forge agent components.
Built by Intelligence Officers; used by Drivers.

## Modules

| Module | Purpose |
|---|---|
| `schema_introspector.py` | Live schema discovery for PostgreSQL, MongoDB, SQLite, DuckDB |
| `join_key_resolver.py` | Cross-database join key detection and type normalisation |
| `multi_pass_retrieval.py` | Keyword + LLM-ranked KB document retrieval |

## Tests

```bash
pytest utils/tests/ -v
```

## Usage

```python
from utils.schema_introspector import introspect_schema
from utils.join_key_resolver import resolve_join_keys
from utils.multi_pass_retrieval import retrieve
```
