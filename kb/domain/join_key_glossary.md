# Ill-Formatted Join Key Glossary

This document is for agent injection. Every cross-database join in DAB has a documented quirk.
Before any join, look up the dataset here and apply the resolution logic listed.

---

## Rule: always check this glossary before writing a join condition.

---

## yelp — businessid_ / businessref_ prefix mismatch

**Databases:** yelp_db (MongoDB) ↔ user_database (DuckDB)
**Fields:** `business.business_id` ↔ `review.business_ref` and `tip.business_ref`
**Format in MongoDB:** `businessid_1`, `businessid_42`, `businessid_1008`
**Format in DuckDB:** `businessref_1`, `businessref_42`, `businessref_1008`
**Resolution:** Strip prefix, compare integer suffix.
```python
# Python
mongo_id = "businessid_42"
duckdb_ref = "businessref_42"
# Normalize both to just the integer
normalize = lambda s: s.split("_", 1)[1]   # "42"
# In SQL: SUBSTR(business_ref, INSTR(business_ref, '_') + 1)
```
**Never do:** `business_id = business_ref` — this will always return zero rows.

---

## bookreview — book_id / purchase_id name and value mismatch

**Databases:** bookreview_db (PostgreSQL) ↔ review_database (SQLite)
**Fields:** `books_info.book_id` ↔ `review.purchase_id`
**Problem:** Field names differ AND values may not be identical strings — fuzzy join required.
**Resolution:** Use fuzzy string matching (e.g. Levenshtein distance ≤ 2) or normalise both to lowercase and strip whitespace/punctuation before joining.
```python
from rapidfuzz import fuzz
# or: join on LOWER(TRIM(book_id)) = LOWER(TRIM(purchase_id)) as first attempt
```

---

## crmarenapro — leading # in ID fields

**Databases:** core_crm (SQLite), sales_pipeline (DuckDB), and all 6 CRMArena databases
**Affected fields:** Id, AccountId, ContactId, OwnerId, OpportunityId, and any foreign key column
**Problem:** ~25% of values have a leading `#` character (e.g., `#001Wt00000PFj4zIAD`).
**Additional problem:** ~20% of text fields have trailing whitespace.
**Resolution:**
```sql
-- In SQL: strip # prefix and whitespace
TRIM(REPLACE(field, '#', '')) 
-- Apply to BOTH sides of every join condition
WHERE TRIM(REPLACE(t1.AccountId, '#', '')) = TRIM(REPLACE(t2.AccountId, '#', ''))
```
**Never do:** raw equality join on any Id field in crmarenapro without normalisation.

---

## stockindex — exchange name ↔ index symbol semantic gap

**Databases:** indexinfo_database (SQLite) ↔ indextrade_database (DuckDB)
**Fields:** `index_info.Exchange` (full name) ↔ `index_trade.Index` (abbreviated symbol)
**Problem:** No shared key — requires knowledge-based mapping.
**Resolution:** Use the mapping table in 00_dataset_overview.md (Exchange → Index Symbol section).
There is no SQL or regex that can resolve this — the agent must have the mapping pre-loaded.

---

## stockmarket — Symbol ↔ dynamic table name

**Databases:** stockinfo_database (SQLite) ↔ stocktrade_database (DuckDB)
**Fields:** `stockinfo.Symbol` ↔ table name in stocktrade_database
**Problem:** Each stock's price history is its own DuckDB table. Must enumerate tables first.
**Resolution:**
```python
# DuckDB: list all tables
tables = conn.execute("SHOW TABLES").fetchall()
# Then: SELECT * FROM "{symbol}" WHERE ...
# Use parameterised table name with quotes to handle special chars
```

---

## PATENTS — CPC code hierarchical matching

**Databases:** publication_database (SQLite) ↔ patent_CPCDefinition
**Fields:** `publicationinfo.cpc` ↔ `cpc_definition.symbol`
**Problem:** `cpc` field may contain multiple codes as a list/string; codes are hierarchical (A61K 31/00 is a subclass of A61K).
**Resolution:** Extract individual codes from the `cpc` field (split on delimiter), then join to `cpc_definition` on `symbol`. For hierarchy queries, use prefix matching: `symbol LIKE 'A61K%'`.

---

## PANCANCER_ATLAS — ParticipantBarcode embedded in NL text

**Databases:** pancancer_clinical (PostgreSQL) ↔ molecular_database (SQLite)
**Fields:** `clinical_info.Patient_description` ↔ `Mutation_Data.ParticipantBarcode`
**Problem:** `Patient_description` is natural language text; barcode is embedded within it.
**Resolution:** Extract using regex pattern `TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}`.
```python
import re
barcode = re.search(r'TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}', patient_description).group()
```

---

## DEPS_DEV_V1 — composite key join

**Databases:** package_database (SQLite) ↔ project_database
**Fields:** (`System`, `Name`, `Version`) composite key
**Problem:** All three columns must match; version strings may have whitespace or case variation.
**Resolution:** Normalise all three fields with `LOWER(TRIM(...))` before joining.

---

## music_brainz_20k — track_id is exact BUT deduplication required

**Databases:** tracks_database (SQLite) ↔ sales_database (DuckDB)
**Fields:** `track_id` integer — exact match, no format mismatch.
**Problem:** Multiple distinct `track_id` values in `tracks` may represent the same real-world track (duplicates from different ingestion sources).
**Resolution:** Group by (`title`, `artist`, `album`) with fuzzy comparison before aggregating sales. Do not aggregate sales by raw `track_id` if the query asks about "songs" or "tracks" by name.

---

## Datasets with clean joins (no format issues)

| Dataset | Join field | Notes |
|---|---|---|
| googlelocal | `gmap_id` | Exact string match — no transformation needed |
| agnews | `article_id` | Integer — exact match |
| GITHUB_REPOS | `repo_name` | Exact string `owner/repo` — match across all tables |
