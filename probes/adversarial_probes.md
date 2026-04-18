# Adversarial Probe Library
**Oracle Forge · TRP1 FDE Programme · April 2026**
**Maintained by:** Intelligence Officers
**Last updated:** 2026-04-14

---

## Purpose
Structured set of queries designed to deliberately expose known failure modes
in the data agent before the benchmark does. Each probe targets one of DAB's
four failure categories. Probes are run after every major agent change to
verify fixes hold and regressions are caught.

## How to Run a Probe
1. Send the query to the running agent on the shared server
2. Record the exact agent response in the "Observed Response" field
3. If the agent fails — diagnose, apply fix, record fix in "Fix Applied"
4. Re-run to confirm fix works — record post-fix score
5. Log the failure in `kb/corrections/corrections_log.md`

---

## Failure Category Reference

| Code | Full Name | Signal |
|------|-----------|--------|
| `CAT-1` | Multi-database routing | Syntax error, wrong dialect, connection to wrong DB |
| `CAT-2` | Ill-formatted join key | Empty result on expected non-empty join |
| `CAT-3` | Unstructured text extraction | Null value, raw text fragment, type error |
| `CAT-4` | Domain knowledge gap | Plausible-but-wrong result, wrong metric definition |

---

## Summary Table

| Probe | Dataset | Category | Status |
|-------|---------|----------|--------|
| P-01 | crmarenapro | CAT-1 | ⬜ Pending |
| P-02 | agnews | CAT-1 | ⬜ Pending |
| P-03 | yelp | CAT-1 | ⬜ Pending |
| P-04 | pancancer_atlas | CAT-1 | ⬜ Pending |
| P-05 | bookreview | CAT-1 | ⬜ Pending |
| P-06 | crmarenapro | CAT-2 | ⬜ Pending |
| P-07 | bookreview | CAT-2 | ⬜ Pending |
| P-08 | yelp | CAT-2 | ⬜ Pending |
| P-09 | music_brainz_20k | CAT-2 | ⬜ Pending |
| P-10 | googlelocal | CAT-2 | ⬜ Pending |
| P-11 | yelp | CAT-3 | ⬜ Pending |
| P-12 | bookreview | CAT-3 | ⬜ Pending |
| P-13 | crmarenapro | CAT-3 | ⬜ Pending |
| P-14 | crmarenapro | CAT-4 | ⬜ Pending |
| P-15 | stockmarket | CAT-4 | ⬜ Pending |

Status legend: ⬜ Pending · 🔄 Running · ✅ Fixed · ❌ Unresolved

---

## Category 1 — Multi-Database Routing (5 Probes)

---

### P-01 · crmarenapro · CAT-1

**Query:**
> "How many support tickets were opened by customers who made more than three purchases in the last quarter? Cross-reference the orders table with the support tickets."

**Datasets involved:** crmarenapro (PostgreSQL orders + SQLite tickets)

**Expected Failure Mode:**
Agent routes both parts of the query to the same database type — either attempting SQL against the MongoDB-style ticket collection or trying to run a PostgreSQL join against a SQLite file. Result is a connection error or dialect mismatch error that surfaces raw to the user.

**Why This Probe Is Hard:**
The query sounds like a single-database question but requires two different database types. The word "cross-reference" does not signal a database boundary to a naive agent.

**Observed Agent Response:**
```
[ Fill in after running — paste exact agent output here ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in: was it wrong tool selection? wrong dialect? connection error? ]
```

**Fix Applied:**
Agent must check `DATASET_DB_MAP` in `schema_introspector.py` before routing.
The `multi_pass_retrieval.py` discovery phase should flag that crmarenapro
spans DuckDB + PostgreSQL + SQLite and force explicit tool selection per table.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-02 · agnews · CAT-1

**Query:**
> "What are the top 3 news categories by article count, and how does that compare to the category distribution in the classification metadata?"

**Datasets involved:** agnews (MongoDB articles + SQLite categories)

**Expected Failure Mode:**
Agent attempts to write SQL against the MongoDB articles collection, producing
a syntax error. MongoDB requires aggregation pipelines, not SELECT statements.
Agent may silently fall back to SQLite only and miss the MongoDB data entirely,
returning a partial answer with no error signal.

**Why This Probe Is Hard:**
The silent partial answer failure is harder to detect than an outright error —
the agent returns something that looks complete but is missing half the data.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
`mcp__mongodb__aggregate` must be called for the articles collection.
The agent must never use `mcp__sqlite__query` against a MongoDB collection.
Tool scoping rules in `tool_scoping_philosophy.md` operational rule 1 applies.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-03 · yelp · CAT-1

**Query:**
> "Which businesses have the highest average star rating among those with more than 100 reviews? Also pull their check-in frequency from the check-in records."

**Datasets involved:** yelp (DuckDB business + MongoDB checkin)

**Expected Failure Mode:**
Agent constructs a single DuckDB analytical SQL query that attempts to JOIN
against the MongoDB checkin collection. DuckDB cannot access MongoDB directly.
Query fails with a table-not-found error. Agent may retry with the same approach
rather than diagnosing the database boundary.

**Why This Probe Is Hard:**
DuckDB and MongoDB look joinable from a query-logic perspective. The agent
must explicitly recognise that the join crosses a database type boundary and
route to two separate tools before merging results.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Run `mcp__duckdb__query` for business ratings, `mcp__mongodb__aggregate` for
checkin data, then `mcp__result__merge` to combine. The join must happen in
Python after both tool results are retrieved, not inside a single database query.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-04 · pancancer_atlas · CAT-1

**Query:**
> "What is the average survival time for patients with TP53 mutations, broken down by cancer type? Join the clinical outcomes with the mutation records."

**Datasets involved:** pancancer_atlas (DuckDB clinical + PostgreSQL mutations)

**Expected Failure Mode:**
Agent writes a PostgreSQL JOIN query that references a DuckDB table, or vice
versa. The clinical and mutation tables live in different database systems.
Error will be a relation-not-found or cross-server join failure. Agent likely
retries with the same dialect rather than splitting the query.

**Why This Probe Is Hard:**
The query is naturally expressed as a JOIN. Nothing in the natural language
signals that the two tables live in different database systems.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
KB v2 `dab_database_schemas.md` must explicitly document that pancancer_atlas
clinical data is in DuckDB and mutation data is in PostgreSQL. Agent must
load this document before routing any pancancer query.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-05 · bookreview · CAT-1

**Query:**
> "List the top 5 users by number of reviews, and show their average rating alongside the book metadata for the books they reviewed most."

**Datasets involved:** bookreview (PostgreSQL books_info + SQLite review_query)

**Expected Failure Mode:**
Agent queries PostgreSQL for both user review counts and book metadata,
missing that review data lives in SQLite. Returns only partial results —
book metadata without review counts — or throws a table-not-found error
when trying to access the review table in PostgreSQL.

**Why This Probe Is Hard:**
Both tables sound like they belong together. The agent has no signal from
the query that the data is split across two database types.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Schema introspection must run at session start for bookreview. The agent
must know before executing that `books_info` is PostgreSQL and `review_query`
is SQLite. Multi-pass retrieval Pass 1 must flag this split.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

## Category 2 — Ill-Formatted Join Keys (5 Probes)

---

### P-06 · crmarenapro · CAT-2

**Query:**
> "Which customers who raised a support ticket in Q1 also made a purchase within 7 days of opening that ticket?"

**Datasets involved:** crmarenapro (PostgreSQL customers + SQLite tickets)

**Expected Failure Mode:**
Agent joins on `customer_id` directly. PostgreSQL stores customer_id as plain
integer (e.g. `1042`). SQLite stores it as `CUST-1042`. The join returns zero
results because no ID matches across the format boundary. Agent reports
"no customers found" — a plausible-looking wrong answer, not an error.

**Why This Probe Is Hard:**
Zero results is a valid answer in some contexts. The agent must recognise that
zero results on a join query is a Category 2 signal requiring diagnosis,
not a legitimate empty result.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Call `join_key_resolver.resolve("CUST-1042", from_db="sqlite", to_db="postgresql",
dataset="crmarenapro", entity="customer_id")` before the join.
Normalise all SQLite customer IDs to integers before passing to PostgreSQL query.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-07 · bookreview · CAT-2

**Query:**
> "Find users who gave 5-star reviews and show their full reading history."

**Datasets involved:** bookreview (PostgreSQL books_info + SQLite review_query)

**Expected Failure Mode:**
Agent joins on `user_id`. SQLite stores user_id as `user_42`, PostgreSQL
stores it as integer `42`. Join returns empty result set. Agent either
reports no users found or returns only records from one database without
flagging the mismatch.

**Why This Probe Is Hard:**
The prefix `user_` looks like it might be a meaningful field qualifier.
A naive agent might treat `user_42` as a valid ID and not recognise it
as a formatting issue.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
`join_key_resolver` strips the `user_` prefix from SQLite IDs before
passing to PostgreSQL. Rule already defined in `join_key_resolver.py` RULES.
Agent must call resolver before any bookreview cross-database user join.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-08 · yelp · CAT-2

**Query:**
> "Which businesses with more than 4 stars on Yelp also have the highest check-in counts in the past year?"

**Datasets involved:** yelp (DuckDB business + MongoDB checkin)

**Expected Failure Mode:**
Agent joins on `business_id`. DuckDB stores business_id as raw UUID
(`3f2a4b5c-1234-...`). MongoDB stores it with a `biz_` prefix
(`biz_3f2a4b5c-1234-...`). Join returns empty result. Agent reports
no matching businesses — a wrong answer that looks plausible.

**Why This Probe Is Hard:**
UUID strings are hard to visually inspect for prefix mismatches.
The agent is unlikely to notice the `biz_` prefix difference without
explicitly checking the join key glossary.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
`join_key_resolver.resolve(value, from_db="mongodb", to_db="duckdb",
dataset="yelp", entity="business_id")` strips the `biz_` prefix.
Agent must call this before passing any business_id from MongoDB to DuckDB.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-09 · music_brainz_20k · CAT-2

**Query:**
> "List all releases by artists from the United Kingdom and show their recording counts."

**Datasets involved:** music_brainz_20k (DuckDB releases + SQLite artists)

**Expected Failure Mode:**
Agent joins on `release_id`. SQLite stores the MusicBrainz UUID with
hyphens (`3f2a4b5c-1234-5678-abcd-ef0123456789`). DuckDB stores without
hyphens (`3f2a4b5c1234567abcdef0123456789`). Join returns zero results.

**Why This Probe Is Hard:**
Both values are valid UUID representations. The agent may not recognise
that the same entity is encoded differently and will treat the empty
join result as genuine — no UK artists found.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
`join_key_resolver` removes hyphens from SQLite UUIDs before passing to
DuckDB, or adds hyphens to DuckDB UUIDs before passing to SQLite.
Rule defined in `join_key_resolver.py`. Agent must normalise before any
music_brainz cross-database release join.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-10 · googlelocal · CAT-2

**Query:**
> "Which places have an average rating above 4.5 and also appear in both the places and reviews tables?"

**Datasets involved:** googlelocal (PostgreSQL places + SQLite reviews)

**Expected Failure Mode:**
Agent joins on `place_id`. PostgreSQL stores place_id as BIGINT.
SQLite stores it as TEXT. Even though the values are numerically identical,
the type mismatch causes the join to silently return zero results in some
query planners, or produces a type coercion error.

**Why This Probe Is Hard:**
The values look identical (`123456789` in both) but the type mismatch
is invisible without inspecting the schema. This is the subtlest of the
join key failures.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Explicit CAST in the join condition: `CAST(sqlite.place_id AS BIGINT)`.
Agent must check the join key glossary for googlelocal before executing
any cross-database join on place_id.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

## Category 3 — Unstructured Text Extraction (3 Probes)

---

### P-11 · yelp · CAT-3

**Query:**
> "What are the most common complaints mentioned in 1-star Yelp reviews for restaurants in San Francisco?"

**Datasets involved:** yelp (DuckDB review.text field)

**Expected Failure Mode:**
Agent queries the `text` field and attempts to aggregate it with SQL GROUP BY
or COUNT — treating free text as a categorical field. Returns either a SQL
error, an empty result, or a meaningless count of unique text strings.
Does not attempt NLP extraction or LLM-based classification of complaint themes.

**Why This Probe Is Hard:**
The question is answerable from the data but requires extracting structured
facts (complaint categories) from unstructured text. A SQL-only agent cannot
do this. The agent must recognise the text extraction requirement and call
`mcp__text__extract` rather than attempting a pure SQL approach.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Agent must: (1) retrieve 1-star review texts with SQL, (2) pass them to
`mcp__text__extract` with prompt "identify the main complaint category from
this review text", (3) aggregate the extracted categories.
KB v2 `unstructured_fields_inventory.md` must flag `review.text` as
requiring extraction, not SQL aggregation.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-12 · bookreview · CAT-3

**Query:**
> "Summarise the most common themes in negative book reviews and identify which genres receive the most criticism about pacing."

**Datasets involved:** bookreview (SQLite review text fields)

**Expected Failure Mode:**
Agent returns the raw review text strings rather than extracted themes.
Alternatively, it attempts a LIKE '%pacing%' SQL query which misses
synonyms ("slow", "dragged", "tedious") and returns an artificially
low count. Both failures produce a wrong answer with no error signal.

**Why This Probe Is Hard:**
A LIKE query produces a result that looks like an answer. The agent
must know that keyword matching is insufficient for theme extraction
and that an LLM extraction pass is required.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
Two-stage approach: (1) SQL retrieves all reviews with rating ≤ 2,
(2) `mcp__text__extract` classifies each review for pacing-related
complaints using semantic matching, not keyword matching.
Extraction prompt: "Does this review mention pacing, plot speed, or
narrative tempo? Return: yes/no and the relevant excerpt."

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-13 · crmarenapro · CAT-3

**Query:**
> "Which support tickets mention billing errors or incorrect charges, and how many of those customers also have overdue invoices?"

**Datasets involved:** crmarenapro (SQLite ticket description field + PostgreSQL invoices)

**Expected Failure Mode:**
Agent queries tickets with `WHERE description LIKE '%billing%'` — missing
alternative phrasings like "wrong charge", "overcharged", "invoice dispute".
Returns a count that is significantly lower than the true number. Then joins
this incomplete set to PostgreSQL invoices, compounding the error.

**Why This Probe Is Hard:**
The LIKE query returns some results, making the failure invisible without
knowing the true count. This is the most dangerous failure mode — a
confident wrong answer.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
`mcp__text__extract` with semantic classification prompt covering billing
synonyms: "Does this support ticket describe a billing error, incorrect
charge, or invoice dispute? Include: overcharged, wrong amount, refund
request, payment dispute." Then join the classified set to PostgreSQL invoices.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

## Category 4 — Domain Knowledge Gap (2 Probes)

---

### P-14 · crmarenapro · CAT-4

**Query:**
> "What is the churn rate for customers in Q3, and which customer segments are most at risk?"

**Datasets involved:** crmarenapro (DuckDB + PostgreSQL + SQLite)

**Expected Failure Mode:**
Agent interprets "churn" as any customer who did not make a purchase in Q3.
The correct domain definition for CRM churn is customers who were active in
Q2 but had zero activity in Q3 AND did not respond to a re-engagement campaign.
Agent returns a number, but it is the wrong number — a confident wrong answer
based on the wrong metric definition.

**Why This Probe Is Hard:**
The agent's answer looks completely reasonable. The error is invisible without
knowing the domain-specific definition of churn for this dataset. This is
exactly the failure that KB v2 `domain_terms.md` is designed to prevent.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
KB v2 `domain_terms.md` must define: "Churn (crmarenapro): a customer is
churned if they were active (≥1 purchase) in the prior quarter AND had zero
purchases AND zero support contact in the current quarter. Customers with
open tickets are NOT counted as churned."
Agent must load `domain_terms.md` before any query containing "churn".

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

### P-15 · stockmarket · CAT-4

**Query:**
> "Which stocks had the highest returns in Q3, and how does this compare to the broader market index performance?"

**Datasets involved:** stockmarket (DuckDB prices) + stockindex (DuckDB index_values)

**Expected Failure Mode:**
Agent calculates Q3 returns using calendar Q3 (July–September). The stockmarket
dataset uses fiscal Q3 which begins in October for this domain. Agent returns
numbers for the wrong time window — a plausible-looking wrong answer. It also
may not know what "broader market index" refers to and either picks an arbitrary
index or fails to join the stockindex dataset at all.

**Why This Probe Is Hard:**
The agent has no way to know fiscal year boundaries without explicit domain
knowledge. The calendar Q3 answer is internally consistent and will not
trigger any error — only comparison against ground truth reveals the failure.

**Observed Agent Response:**
```
[ Fill in after running ]
```

**Failure Confirmed:** ⬜ YES  ⬜ NO

**Root Cause Diagnosis:**
```
[ Fill in ]
```

**Fix Applied:**
KB v2 `domain_terms.md` must define: "Q3 (stockmarket dataset): fiscal Q3
runs October 1 – December 31. Fiscal year begins October 1."
"Broader market index: refers to the stockindex dataset, specifically the
`index_values` table. Default to the S&P 500 equivalent entry unless
the user specifies otherwise."
Agent must load domain_terms.md before any stockmarket temporal query.

**Post-Fix Score:** ___/1

**Corrections Log Entry:** `kb/corrections/corrections_log.md` Entry ___

---

## Scoring Summary

Fill this in after running all probes:

| Category | Probes | Passed | Pass Rate |
|----------|--------|--------|-----------|
| CAT-1 Multi-database routing | 5 | ___ | ___% |
| CAT-2 Ill-formatted join key | 5 | ___ | ___% |
| CAT-3 Unstructured text | 3 | ___ | ___% |
| CAT-4 Domain knowledge gap | 2 | ___ | ___% |
| **Total** | **15** | **___** | **___%** |

---

## How Probes Feed Back Into the System

```
Probe run → failure observed
        ↓
Failure classified into CAT-1/2/3/4
        ↓
Entry added to kb/corrections/corrections_log.md
        ↓
Fix applied to agent or KB document
        ↓
Probe re-run to confirm fix
        ↓
Score log updated in eval/score_log.jsonl
        ↓
Regression suite includes this probe permanently
```

Every probe that finds a real failure and produces a verified fix is
a direct improvement to the benchmark score. The probe library is not
a test suite — it is a compound engineering input.
