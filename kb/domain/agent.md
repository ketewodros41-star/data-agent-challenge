# Agent Instructions
> Inject this file FIRST at every session start. Do not skip.

## File Map (load on demand)

| If question involves...            | Load this file           |
|------------------------------------|--------------------------|
| Table names, column names, types   | schema.md                |
| Dataset overview, join keys        | dataset_overview.md      |
| Join key patterns, domain terms    | kb_v2_domain.md          |
| Past failures, corrections         | kb/corrections/log.md    |

---

## Operating Rules

1. **SCHEMA FIRST** — Before writing any query, confirm which database and
   table owns the field. Check `schema.md`. Never assume a field exists in the
   most obvious location. Many fields with similar names live in different DBs
   with different formats.

2. **JOIN KEY CHECK** — Before joining across databases, check `dataset_overview.md`
   for the join key entry for that dataset. If a mismatch is listed, apply the
   resolution exactly. Do not attempt raw equality joins on mismatched keys.

   Known mismatches — apply before querying:
   - yelp: `business_id` (MongoDB, prefix `businessid_N`) ↔ `business_ref` (DuckDB, prefix `businessref_N`) — strip prefix, match integer suffix
   - crmarenapro: ~25% of Id fields have a leading `#` — strip `#` and trailing whitespace before every join
   - bookreview: `book_id` ↔ `purchase_id` — fuzzy match, not exact equality
   - stockindex: Exchange full name (SQLite) ↔ Index symbol (DuckDB) — no FK, use semantic mapping table in dataset_overview.md
   - PANCANCER_ATLAS: `Patient_description` is NL text — extract `ParticipantBarcode` with regex `TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}` before joining

3. **UNSTRUCTURED FIELDS** — These fields require extraction before aggregation.
   Do not count, sum, or filter on raw text:
   - yelp: `description` (city/state embedded in NL text), `attributes` (Python dict as string — use `ast.literal_eval`)
   - googlelocal: `description` (category/US state in NL), `MISC` (JSON-like amenities dict)
   - bookreview: `categories`, `features`, `description`, `details` — all Python-repr strings, parse with `ast.literal_eval`
   - PATENTS: all date fields are NL strings (e.g. "March 15th, 2020") — parse with dateparser before date arithmetic; HTML fields need tag stripping
   - DEPS_DEV_V1: `Licenses`, `Advisories`, `VersionInfo` are JSON-like strings — parse before use; `UpstreamPublishedAt` is milliseconds, divide by 1000
   - agnews: no `category` column — classify from `title` + `description` text; exactly 4 categories: World, Sports, Business, Science/Technology
   - GITHUB_REPOS: `language_description` is NL with byte counts — extract primary language as highest-byte language
   - PANCANCER_ATLAS: RNA expression — apply `log10(normalized_count + 1)` before averaging

4. **DOMAIN TERMS** — Use these definitions, not general knowledge:
   - `active customer` = purchase in last 90 days (NOT just row existence)
   - `churned customer` = no purchase in 180+ days AND had 3+ prior purchases
   - `revenue` = SUM(unit_price × quantity) from orders table — NOT from snapshot tables
   - `churn window` = 90 days (never 30)
   - crmarenapro `won deal` = `StageName = 'Closed Won'`
   - stockmarket `up day` = Close > Open; `down day` = Close < Open
   - googlelocal `state` field = operating status (OPEN/CLOSED/TEMPORARILY_CLOSED) — NOT a US state abbreviation
   - bookreview `rating_number` = count of ratings, NOT average score
   - PANCANCER_ATLAS cancer types: LGG = Brain Lower Grade Glioma; BRCA = Breast Invasive Carcinoma; GBM = Glioblastoma

5. **TOOL ROUTING** — One tool per database type. Never mix query languages:
   - PostgreSQL → `query_postgresql` (Standard SQL)
   - MongoDB    → `query_mongodb` (aggregation pipeline only — SQL returns empty silently)
   - SQLite     → `query_sqlite` (simple SQL, no ILIKE — use `LOWER(x) LIKE`)
   - DuckDB     → `query_duckdb` (analytical SQL, QUALIFY supported)
   For multi-DB questions: call each tool separately, merge results in sandbox.

6. **SELF-CORRECT** — If a query returns an error or implausible result (including
   zero rows on a join), diagnose before retrying:
   - Zero rows → check join key format mismatch first (see Rule 2)
   - Empty MongoDB result → verify you used aggregation pipeline, not SQL
   - Wrong number → check domain term definition (see Rule 4)
   - Syntax error → verify SQL dialect for this DB engine (see Rule 5)
   Max 3 retries. After 3 failures: return honest error with full trace. Never guess.

7. **QUERY TRACE** — Every answer must include: databases queried, tools called,
   join keys used, any corrections applied, confidence level (high/medium/low).

---

## Session Loading Order

```
1. Load this file (agent.md)
2. Load kb/corrections/log.md — last 10 entries — BEFORE planning
3. Receive question
4. Load topic files on demand only (schema.md, dataset_overview.md, kb_v2_domain.md)
5. Execute with scoped tools
6. Write failures to corrections log (autoDream)
```
