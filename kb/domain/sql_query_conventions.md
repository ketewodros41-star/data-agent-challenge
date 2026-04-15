# SQL Query Conventions

Rules the agent MUST follow when generating queries across all DAB datasets.
Loaded at session start (Layer 2). Apply these before the first execution attempt —
they prevent failures rather than correcting them after.

---

## 1. NULL Ordering — PostgreSQL

**Rule:** PostgreSQL treats NULL as *greater than* any non-null value.
- `ORDER BY col DESC` → NULLs appear **first** (before real values)
- `ORDER BY col ASC`  → NULLs appear **last**

**Impact:** Any question asking for "highest", "most expensive", "top N by X" on a
column that may contain NULLs will return null rows instead of real values.

**Fix — always add `WHERE col IS NOT NULL` when ordering by a nullable metric:**

```sql
-- WRONG: returns null-priced books first
SELECT title, price FROM books_info ORDER BY price DESC LIMIT 5;

-- CORRECT: filters nulls before sorting
SELECT title, price FROM books_info
WHERE price IS NOT NULL
ORDER BY price DESC LIMIT 5;
```

**Known nullable metric columns across DAB datasets:**

| Dataset | DB | Table | Column | Notes |
|---|---|---|---|---|
| bookreview | books_database (PostgreSQL) | books_info | price | Mostly null in this dataset |
| amazon | amazon_database | meta_Books | price | May be null |
| stockmarket | stockmarket_database | prices | Adj Close | May be null for delisted stocks |
| stockindex | stockindex_database | prices | CloseUSD | May be null |

When in doubt: if the column you are ordering by could be null (it's a price, rating,
score, amount, count, etc.), add `WHERE col IS NOT NULL` before `ORDER BY`.

---

## 2. NULL Ordering — SQLite and DuckDB

**SQLite:** NULL sorts as *less than* any value — `ORDER BY col DESC` puts NULLs
**last** (safe). But `ORDER BY col ASC LIMIT N` puts NULLs **first**.

**DuckDB:** Same as SQLite — NULLs are smallest. `DESC` is safe; `ASC` is not.

**Rule:** When using `ASC` ordering on nullable columns in SQLite or DuckDB,
add `WHERE col IS NOT NULL` or `ORDER BY col ASC NULLS LAST`.

---

## 3. Aggregation and NULL

`COUNT(*)` counts all rows including nulls. `COUNT(col)` skips null values.
`SUM`, `AVG`, `MAX`, `MIN` all skip nulls automatically.

When the question asks "how many X have a Y value", use `COUNT(col)` not `COUNT(*)`.

---

## 4. String Matching — Case Sensitivity

| Engine | Default | Fix |
|---|---|---|
| PostgreSQL | case-sensitive LIKE | Use `ILIKE` or `LOWER(col) LIKE LOWER(...)` |
| SQLite | case-insensitive LIKE for ASCII | Safe as-is |
| DuckDB | case-sensitive LIKE | Use `LOWER(col) LIKE LOWER(...)` |
| MongoDB | case-sensitive regex | Use `/pattern/i` flag |

---

## 5. LIMIT Clauses

Always include `LIMIT` on exploratory queries. The MCP Toolbox enforces a
server-side row cap, but explicit `LIMIT` protects against context overflow.

Default safe limits: 100 rows for exploration, 10 for "top N" questions unless
the question specifies a different N.

---

## 6. Date and Timestamp Handling

- PostgreSQL date columns: use `CAST(col AS DATE)` or `DATE_TRUNC` for grouping.
- SQLite has no native DATE type: use `strftime('%Y', col)` or `substr(col, 1, 4)`.
- DuckDB: native `DATE`/`TIMESTAMP` — use `date_trunc`, `year()`, `month()` etc.
- Many DAB datasets store dates as strings — check schema.md for the column type
  before applying date functions.

---

## 7. MongoDB Aggregation Pipeline vs SQL

MongoDB queries use aggregation pipelines, not SQL. Route MongoDB questions to
`find_yelp_businesses` / `find_yelp_checkins` tools, not `run_query`.

When a question needs a JOIN between MongoDB and another DB:
1. Fetch the MongoDB side first with `find_*` tools.
2. Extract the join key values from the result.
3. Run the second query against the SQL DB using `WHERE key IN (...)`.

---

## 8. Boolean-Like Fields in DAB Datasets

Several datasets store booleans as strings or integers:

| Dataset | Field | Values | Meaning |
|---|---|---|---|
| yelp (MongoDB) | attributes.* | `"True"` / `"False"` | String, not Python bool |
| yelp | is_open | `1` / `0` | Integer |
| googlelocal | state | `'OPEN'` / `'CLOSED'` | Operating status, not US state |
| stockmarket | ETF | `'Y'` / `'N'` | String |

Always match the stored type: `WHERE is_open = 1`, not `WHERE is_open = true`.
