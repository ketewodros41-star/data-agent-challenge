# Injection Test Results

**Last run:** 2026-04-14 12:46 UTC  
**Status:** 36/36 tests passing

---

## MS-1 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What is MEMORY.md for, what is its word limit, and what triggers a topic file to be loaded from memory?

**Required keywords:** `index`, `200`, `on-demand`, `topic`

**Answer:**

Based on the document:

**What is MEMORY.md for:**
MEMORY.md is an index file that is loaded at every session start. It contains pointers to actual knowledge, not the content itself. It also acts as a working memory entry point—the agent uses it to orient before receiving a question and loads the corrections log before planning to avoid repeating past mistakes.

**Word limit:**
MEMORY.md must stay under 200 words. If it exceeds this limit, the oldest changelog entries should be removed. Topic file pointers must never be removed.

**What triggers a topic file to be loaded:**
Topic files are loaded on-demand only when the current question requires that specific topic. Examples include:
- Question involves customer join → load kb/architecture/tool_scoping.md
- Question uses "revenue" → load kb/domain/business_terms.md
- Question previously failed → load kb/corrections/log.md
- Question spans multiple DBs → load kb/domain/join_keys.md

The key rule is: never pre-load all files, as this fills up the context window.

---

## MS-2 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What fields must every corrections log entry contain, and which field is most often missing?

**Required keywords:** `query`, `failure`, `root cause`, `fix`, `outcome`

**Answer:**

According to the document, every corrections log entry must contain these fields:

1. **Query** — Natural language question that failed
2. **Failure** — What went wrong (symptom)
3. **Root Cause** — Why it went wrong (diagnosis)
4. **Fix** — Exact change applied
5. **Outcome** — Result after fix — MUST be verified, not assumed

The field most often missing is **Outcome**. The document explicitly states: "Outcome is most often missing — it must be verified, not assumed."

---

## MS-3 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What is the consolidation rule for the corrections log?

**Required keywords:** `recurring`, `one-off`, `noise`

**Answer:**

According to the document, the consolidation rule for the corrections log is:

**Keep:** recurring failures, high-impact join fixes, business logic corrections

**Remove:** one-off issues, environment errors, already-resolved schema issues

The document emphasizes that "A corrections log that only grows becomes noise. Discipline is removal." This means the agent should actively prune the log during consolidation, not just add to it.

---

## MS-4 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> Why is Claude memory architecture alone not enough for this data agent project?

**Required keywords:** `schema`, `domain`, `openai`

**Answer:**

According to the document, Claude memory architecture alone is not enough for this data agent project because it does not provide:

1. **Schema grounding** — which table, which DB
2. **Domain knowledge** — what "revenue" means in this dataset
3. **Cross-database entity mapping**

The document states that OpenAI's 6-layer context fills these gaps, and this agent uses both systems together.

---

## TS-1 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> A DAB question asks: which customers had support complaints this week? Which database tool do you use, what query language, and why can't you use query_postgresql for this?

**Required keywords:** `query_mongodb`, `aggregation`, `empty`

**Answer:**

Based on the document:

**Tool to use:** `query_mongodb`

**Query language:** Aggregation pipeline

**Why not query_postgresql:** According to the document, support complaints data is stored in MongoDB (the document states "query_mongodb" connects to "Support, CRM" data). If you send SQL to `query_mongodb`, it will return empty results silently with no error message. This silent failure is particularly dangerous because the agent would produce a confident wrong answer without any signal that the query failed. The document explicitly warns: "Never send SQL to query_mongodb. It will return empty silently."

The tool name determines the query language — SQL for PostgreSQL, aggregation pipeline for MongoDB. Using the wrong tool with the wrong query language leads to silent failures at the architectural level.

---

## TS-2 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> What happens if you send a SQL query to query_mongodb?

**Required keywords:** `empty`, `silent`

**Answer:**

According to the document:

If you send a SQL query to query_mongodb, it will **return empty results silently with no error**. The agent will be unaware that anything failed and may produce a confident wrong answer.

This is highlighted as a critical issue in the document:

> "When the wrong tool receives the wrong query language:
> SQL → query_mongodb     → empty result, no error, agent unaware"

The document emphasizes that silent failures are worse than explicit errors because the agent has no signal that something went wrong, making it produce incorrect results confidently.

---

## TS-3 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> A question requires data from both PostgreSQL and MongoDB. What is the correct procedure?

**Required keywords:** `separately`, `sandbox`

**Answer:**

According to the document, the correct procedure for a multi-database question is:

**Step 1:** Call `query_postgresql` → get structured sales/transaction result

**Step 2:** Call `query_mongodb` → get aggregation pipeline result

**Step 3:** Normalize IDs in both sets (remove "CUST_", cast to int)

**Step 4:** Merge in sandbox (never in a single tool call)

The key principle is: **call each tool separately — never combined**. Send both result sets to the sandbox for merging, and never merge across tools in a single call.

This approach prevents silent failures that would occur if you tried to combine the queries into one tool call, since sending the wrong query language to the wrong database (e.g., SQL to MongoDB) returns empty results silently with no error signal.

---

## TS-4 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> What tool is used for analytical SQL queries against the data warehouse?

**Required keywords:** `query_duckdb`

**Answer:**

According to the document, the tool used for analytical SQL queries against the data warehouse is **query_duckdb**.

From the tools table in the document:

| Tool | Query language | Database | Data type |
|------|---|---|---|
| query_duckdb | Analytical SQL | DuckDB | Warehouse, analytics |

---

## OC-1 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What is Codex Enrichment and which of the six layers is it?

**Required keywords:** `layer 3`, `pipeline`, `join key`

**Answer:**

According to the document:

**Codex Enrichment is Layer 3** — table enrichment.

It is a **daily async process** where Codex inspects pipeline code for each table to derive:
- Upstream/downstream dependencies
- Ownership
- Granularity
- Join keys
- Similar tables
- Filter assumptions

The document describes it as revealing **what is INSIDE a table, not just its schema**.

However, Codex Enrichment is marked as **OPTIONAL** for this project because it is considered too heavy for DAB scale. The document recommends implementing it only if `join_keys.md` is insufficient.

---

## OC-2 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What does Layer 4 contain and what does it map to in this agent's KB?

**Required keywords:** `institutional`, `business_terms`

**Answer:**

According to the document:

**Layer 4 — Institutional knowledge** contains:
- In OpenAI's system: Slack, Docs, Notion for metric definitions
- In this project: dataset-specific definitions that the schema does not capture
- Definitions MUST include examples like:
  - `revenue = total_price - refunds`
  - `repeat_purchase = count(orders per customer) > 1`
  - `churn = no transactions in last 90 days (NOT 30)`
  - Authoritative tables vs deprecated tables

**It maps to in this agent's KB:**
`kb/domain/business_terms.md` — MANDATORY for this project (institutional knowledge)

---

## OC-3 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> According to the document's key finding from OpenAI, what should the agent do before running analysis, and what happens the more time it spends in that phase?

**Required keywords:** `discovery`, `validate`, `before`

**Answer:**

According to the document's key finding from OpenAI:

**What the agent should do before running analysis:**
The agent should validate table choice BEFORE running analysis. It should not run ahead, but instead spend time in the discovery phase.

**What happens the more time it spends in that phase:**
"The more time the agent spends in the discovery phase — comparing which table to use — the better the results."

The document emphasizes that overconfidence is the biggest behavioral flaw, as the model often says "This is the right table" and runs ahead, which is wrong. The recommendation is to prioritize discovery and validation before execution.

---

## OC-4 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What is Layer 6 used for and when is it triggered?

**Required keywords:** `live`, `stale`, `real-time`

**Answer:**

According to the document:

**Layer 6 — Live runtime queries** is used for:
- Querying the live data warehouse for real-time schema inspection when no prior information exists or data is stale
- MCP connections to data warehouse for real-time schema inspection

**When it is triggered:**
Layer 6 is triggered only if the schema is stale. The document explicitly states: "OPTIONAL — only if schema is stale" and "Do not implement unless schemas.md lags."

The document also notes that Layer 6 adds infrastructure overhead and should not be implemented unless necessary, making it an optional layer (unlike Layers 1, 2, 4, and 5 which are mandatory for this project).

---

## EL-1 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> The sandbox returns validation_status: failed, error: ID format mismatch. What are the exact next steps and what happens after 3 retries all fail?

**Required keywords:** `strip`, `convert`, `retry`, `honest`, `never`

**Answer:**

Based on the document, here are the exact next steps and what happens after 3 retries fail:

## Exact Next Steps (Step 4 — DIAGNOSE AND RETRY):

1. **Diagnose the error**: Recognize "ID format mismatch" as the specific failure type
2. **Apply the fix**: Strip prefix, convert type, retry
3. **Retry up to 3 times maximum** with these corrections applied

## What Happens After 3 Retries All Fail:

**Return an honest error with full trace. Never hallucinate an answer. Never guess.**

The document explicitly states:
> "After 3 failures: return honest error with full trace. Never hallucinate an answer. Never guess."

This is part of the closed-loop self-correction pattern where the agent does not surface errors to the user by making up answers. Instead, the user receives either a correct answer or an honest "could not resolve" response with the complete query trace showing what was attempted and why it failed.

---

## EL-2 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> What are the 6 steps of the execution loop in order?

**Required keywords:** `plan`, `execute`, `check`, `diagnose`, `deliver`, `log`

**Answer:**

According to the document, the 6 steps of the execution loop for this agent are:

1. **PLAN** (discovery phase — do not skip) - Load corrections log first, validate which table to use, select scoped tools, identify all databases needed.

2. **EXECUTE** - Call scoped tools (one per database type), send results to sandbox for merging/validation.

3. **CHECK SANDBOX RESPONSE** - Read validation_status field ("ok" → proceed to delivery, "failed" → diagnose).

4. **DIAGNOSE AND RETRY** (maximum 3 attempts) - Handle specific errors like ID format mismatch, empty results, or syntax errors. After 3 failures, return honest error with full trace.

5. **DELIVER** - Package the answer with query_trace and confidence level (high, medium, or low).

6. **LOG** (autoDream) - Write failures to kb/corrections/log.md in the specified format, write successful patterns to relevant topic files, and update MEMORY.md if needed.

---

## EL-3 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> A tool call returns an empty result set with no error. What does the agent do next?

**Required keywords:** `verify`, `table`, `schemas`, `retry`

**Answer:**

According to the document, when a tool call returns an empty result set, the agent follows Step 4 — DIAGNOSE AND RETRY:

**"empty result" → verify table name in schemas, retry**

The agent should:
1. Verify the table name in schemas.md
2. Retry the query (up to a maximum of 3 attempts total)
3. If all 3 retries fail: return an honest error with the full query trace
4. Never hallucinate an answer or guess

The document also notes under "Known DAB failure → fix table" that empty results from MongoDB queries specifically occur because "SQL sent to query_mongodb returns empty silently" — the fix being to always use an aggregation pipeline for MongoDB instead.

---

## EL-4 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> What confidence levels does the agent assign and when?

**Required keywords:** `high`, `medium`, `low`

**Answer:**

According to the document, the agent assigns confidence levels in Step 5 — DELIVER:

- **high** — direct result
- **medium** — inferred
- **low** — partial

The document states: "Package: answer + query_trace + confidence level" with these three levels as the options, but it does not provide detailed criteria for when each level should be assigned beyond these brief descriptions.

---

## SC-1 — schema.md

**Verdict:** ✅ PASS

**Question:**
> What format is business_id in the Yelp MongoDB collection, and what format is business_ref in the Yelp DuckDB user_database?

**Required keywords:** `businessid_`, `businessref_`

**Answer:**

Based on the document:

**business_id in Yelp MongoDB collection (`business` collection):**
Format: `businessid_N` (as noted in the schema)

**business_ref in Yelp DuckDB user_database (in `review` and `tip` tables):**
Format: `businessref_N` (as noted in the schema)

Both follow a similar pattern with an underscore and a number suffix, but use different prefixes (`businessid_` vs `businessref_`).

---

## SC-2 — schema.md

**Verdict:** ✅ PASS

**Question:**
> What does the `state` column in the googlelocal business_description table represent?

**Required keywords:** `open`, `closed`, `operating`

**Answer:**

According to the document, the `state` column in the googlelocal `business_description` table represents the **operating status** of the business, not a US geographic state.

The possible values are:
- `OPEN`
- `CLOSED`
- `TEMPORARILY_CLOSED`

---

## SC-3 — schema.md

**Verdict:** ✅ PASS

**Question:**
> What data quality issue affects all ID fields in the crmarenapro databases, and what must you do before any join?

**Required keywords:** `#`, `before any join`

**Answer:**

According to the document, **all ID fields in the crmarenapro databases may have leading `#` and trailing whitespace**.

**What you must do before any join: Normalise the ID fields** by removing the leading `#` prefix and trailing whitespace.

This is explicitly stated in the critical note at the beginning of the crmarenapro section:

> **CRITICAL: All ID fields may have leading `#` and trailing whitespace. Normalise before any join.**

---

## SC-4 — schema.md

**Verdict:** ✅ PASS

**Question:**
> How is stock price history organised in the stocktrade_database, and how do you find which tables exist?

**Required keywords:** `ticker`, `show tables`

**Answer:**

# Stock Price History Organization in stocktrade_database

## Table Structure

The **stocktrade_database** (DuckDB) uses a **dynamic table-per-ticker model**:

- **One table per stock ticker symbol**
- Table name = the ticker symbol itself (e.g., `AAPL`, `MSFT`, `GOOGL`)
- All ticker tables share the same schema

## Schema (Per-Ticker Table)

| Field | Type | Notes |
|---|---|---|
| Date | str | Trading date |
| Open | float | Opening price |
| High | float | Day high |
| Low | float | Day low |
| Close | float | Closing price |
| Adj Close | float | Adjusted closing price |
| Volume | int | Shares traded |

## How to Find Which Tables Exist

Use the **`SHOW TABLES`** command in DuckDB:

```sql
SHOW TABLES;
```

This will enumerate all available ticker tables in the stocktrade_database.

Alternatively, you can query the information schema:

```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'main';
```

Then query any specific ticker table by name, e.g.:

```sql
SELECT * FROM AAPL WHERE Date = '2023-01-15';
```

---

## JK-1 — join_key_glossary.md

**Verdict:** ✅ PASS

**Question:**
> How is the Yelp business identifier formatted in MongoDB versus DuckDB, and what is the correct join procedure?

**Required keywords:** `businessid_`, `businessref_`, `strip`, `integer`

**Answer:**

# Yelp Business Identifier Format and Join Procedure

## Format Differences

**MongoDB (businessinfo_database):**
- Format: `businessid_` prefix with integer suffix
- Examples: `businessid_1`, `businessid_42`, `businessid_1008`
- Field name: `business.business_id`

**DuckDB (user_database):**
- Format: `businessref_` prefix with integer suffix
- Examples: `businessref_1`, `businessref_42`, `businessref_1008`
- Field names: `review.business_ref` and `tip.business_ref`

## Correct Join Procedure

**Resolution:** Strip the prefix from both sides and compare only the integer suffix.

**SQL approach:**
```sql
SUBSTR(business_ref, INSTR(business_ref, '_') + 1)
```

**Python approach:**
```python
normalize = lambda s: s.split("_", 1)[1]   # Returns "42"
```

## Critical Warning

**Never do:** `business_id = business_ref` — this will always return zero rows because the prefixes differ.

You must normalize both fields by extracting the integer suffix before performing the join.

---

## JK-2 — join_key_glossary.md

**Verdict:** ✅ PASS

**Question:**
> What transformation must be applied to every ID field in crmarenapro before joining, and what SQL expression does this?

**Required keywords:** `#`, `trim`, `replace`

**Answer:**

According to the document, the transformation that must be applied to every ID field in crmarenapro before joining is:

**Strip the leading `#` character and trim whitespace.**

The SQL expression is:

```sql
TRIM(REPLACE(field, '#', ''))
```

This must be applied to **BOTH sides of every join condition**. For example:

```sql
WHERE TRIM(REPLACE(t1.AccountId, '#', '')) = TRIM(REPLACE(t2.AccountId, '#', ''))
```

The document notes that ~25% of values have a leading `#` character (e.g., `#001Wt00000PFj4zIAD`) and ~20% of text fields have trailing whitespace. The affected fields include: `Id`, `AccountId`, `ContactId`, `OwnerId`, `OpportunityId`, and any foreign key column across all crmarenapro databases (core_crm, sales_pipeline, and all 6 CRMArena databases).

The document explicitly warns: **"Never do: raw equality join on any Id field in crmarenapro without normalisation."**

---

## JK-3 — join_key_glossary.md

**Verdict:** ✅ PASS

**Question:**
> In the stockmarket dataset, how do you join stockinfo to a specific ticker's price history in stocktrade_database?

**Required keywords:** `show tables`, `symbol`

**Answer:**

According to the document, in the **stockmarket** dataset:

**Fields:** `stockinfo.Symbol` ↔ table name in stocktrade_database

**Problem:** Each stock's price history is its own DuckDB table. You must enumerate tables first.

**Resolution:**

1. **List all tables in stocktrade_database:**
```python
tables = conn.execute("SHOW TABLES").fetchall()
```

2. **Then query the specific symbol's table:**
```python
SELECT * FROM "{symbol}" WHERE ...
```

3. **Use parameterised table names with quotes** to handle special characters.

In other words, you don't join `stockinfo` to a single `stocktrade` table. Instead, you:
- Look up the `Symbol` from `stockinfo`
- Use that symbol as the **table name** in `stocktrade_database`
- Query that individual table directly

---

## JK-4 — join_key_glossary.md

**Verdict:** ✅ PASS

**Question:**
> Which datasets have clean joins requiring no key transformation, and what are their join fields?

**Required keywords:** `googlelocal`, `gmap_id`, `agnews`, `article_id`

**Answer:**

According to the document, the datasets with clean joins requiring no key transformation are:

| Dataset | Join field | Notes |
|---|---|---|
| googlelocal | `gmap_id` | Exact string match — no transformation needed |
| agnews | `article_id` | Integer — exact match |
| GITHUB_REPOS | `repo_name` | Exact string `owner/repo` — match across all tables |

These three datasets do not require any format normalization, prefix stripping, fuzzy matching, or other transformations when performing joins.

---

## DT-1 — domain_term_definitions.md

**Verdict:** ✅ PASS

**Question:**
> In crmarenapro, what does 'won deal' mean and which column and value identify it?

**Required keywords:** `closed won`, `stagename`

**Answer:**

In crmarenapro, a **'won deal'** (also called a 'closed deal') is identified by:

- **Column:** `StageName`
- **Value:** `'Closed Won'`

So a won deal is an Opportunity with `StageName = 'Closed Won'`.

---

## DT-2 — domain_term_definitions.md

**Verdict:** ✅ PASS

**Question:**
> In the yelp dataset, how do you determine if a business has WiFi available, and what are the possible values?

**Required keywords:** `attributes.wifi`, `free`, `paid`, `no`

**Answer:**

According to the document, in the yelp dataset:

**How to determine if a business has WiFi available:**
Check the `attributes.WiFi` field in the `attributes` dictionary.

**Possible values:**
- `"free"`
- `"paid"`
- `"no"`

---

## DT-3 — domain_term_definitions.md

**Verdict:** ✅ PASS

**Question:**
> In the googlelocal dataset, what does the `state` column actually contain, and how do you find the real US state?

**Required keywords:** `operating status`, `description`

**Answer:**

According to the document:

In the **googlelocal** dataset:

- The `state` column contains **operating status** (NOT a US state)
- To find the real US state, you must **extract it from the `description` text** — there is no dedicated state column

This is explicitly stated in the googlelocal term definitions:
- "open business" = `state = 'OPEN'` in `business_description` (NOT a US state)
- "US state" = Must be extracted from `description` text — `state` column is operating status

---

## DT-4 — domain_term_definitions.md

**Verdict:** ✅ PASS

**Question:**
> What does 'unique track' mean in music_brainz_20k, and why should you not use track_id directly?

**Required keywords:** `title`, `artist`, `album`, `fuzzy`

**Answer:**

According to the document, in **music_brainz_20k**:

**"Unique track" / "unique song"** means a **deduplicated entity — NOT a unique `track_id`**. Instead, you should **group by (title, artist, album) with fuzzy matching**.

**Why you should not use track_id directly:**

The document explicitly states "NOT a unique `track_id`" because `track_id` alone does not account for duplicate or near-duplicate entries in the database. The same song may appear multiple times with different `track_id` values due to variations in how the data is recorded. By grouping on the combination of (title, artist, album) with fuzzy matching, you properly deduplicate and identify truly unique tracks.

---

## DO-1 — dataset_overview.md

**Verdict:** ✅ PASS

**Question:**
> What is the join key issue between the yelp businessinfo_database and user_database, and how is it resolved?

**Required keywords:** `businessid_`, `businessref_`, `strip`, `integer`

**Answer:**

# Yelp Join Key Issue and Resolution

## The Problem

The join key between the two databases has a **format mismatch**:

- **MongoDB (businessinfo_database):** Uses prefix `businessid_N` (e.g., `businessid_12345`)
- **DuckDB (user_database):** Uses prefix `businessref_N` (e.g., `businessref_12345`)

The actual join keys are:
- `business_id` in MongoDB
- `business_ref` in DuckDB

## The Solution

**Strip the prefix and match the integer suffix.**

The resolution process:
1. Remove the `businessid_` prefix from MongoDB's `business_id` values
2. Remove the `businessref_` prefix from DuckDB's `business_ref` values
3. Compare the remaining integer suffixes for equality

This allows you to join records across the two databases despite the different string prefixes, as long as the numeric portions match.

---

## DO-2 — dataset_overview.md

**Verdict:** ✅ PASS

**Question:**
> In the googlelocal dataset, what does the `state` column in business_description contain, and where is the US state found?

**Required keywords:** `operating status`, `description`

**Answer:**

According to the document, in the googlelocal dataset:

**What `state` contains:** The `state` column in business_description is the business *operating status*, NOT a US state abbreviation. It contains values like "OPEN", "CLOSED", or "TEMPORARILY_CLOSED".

**Where the US state is found:** The US geographic state must be inferred from the `description` text field, not from a dedicated state column.

---

## DO-3 — dataset_overview.md

**Verdict:** ✅ PASS

**Question:**
> What is the primary data quality challenge with the music_brainz_20k tracks table, and how should it be resolved?

**Required keywords:** `duplicate`, `title`, `artist`, `fuzzy`

**Answer:**

According to the document, the primary data quality challenge with the music_brainz_20k tracks table is **entity resolution — the `tracks` table contains duplicates**.

Specifically:
- Multiple `track_id`s can represent the same real-world track
- These duplicates should be deduplicated by comparing `title`, `artist`, `album`, and `year` fields
- **Important:** Do NOT use exact string equality for comparison; instead, use **fuzzy/semantic comparison**

This is the key distinction — because exact string matching would fail to identify duplicates that have minor variations in how the metadata is recorded, fuzzy matching is required to properly resolve these duplicate entities.

---

## DO-4 — dataset_overview.md

**Verdict:** ✅ PASS

**Question:**
> How many total queries exist in the DAB benchmark and across how many datasets?

**Required keywords:** `54`, `12`

**Answer:**

According to the document:

- **Total queries:** 54
- **Number of datasets:** 12

---

## UF-1 — unstructured_field_inventory.md

**Verdict:** ✅ PASS

**Question:**
> How should the `attributes` field in the Yelp MongoDB business collection be parsed before use?

**Required keywords:** `ast.literal_eval`

**Answer:**

According to the document, the `attributes` field in the Yelp MongoDB business collection should be parsed using:

**`ast.literal_eval()` then key lookup**

The field contains a Python dict serialised as string (or null), so you need to:
1. Use `ast.literal_eval()` to convert the string representation back into a Python dictionary
2. Then perform key lookup to access specific attributes

---

## UF-2 — unstructured_field_inventory.md

**Verdict:** ✅ PASS

**Question:**
> For the googlelocal dataset, how do you find a business's US state, and why can't you use the `state` column?

**Required keywords:** `description`, `operating status`

**Answer:**

According to the document, for the googlelocal dataset:

**How to find a business's US state:**
Extract it from the `description` field in the `business_description` table using regex to parse the natural language text containing the business address and US state.

**Why you can't use the `state` column:**
The `state` column in `business_description` is *operating status* (OPEN/CLOSED), NOT a US state. It indicates whether the business is open or closed, not its geographic location.

---

## UF-3 — unstructured_field_inventory.md

**Verdict:** ✅ PASS

**Question:**
> How are agnews article categories determined, and what are the four possible categories?

**Required keywords:** `title`, `description`, `world`, `sports`

**Answer:**

According to the document, agnews article categories are determined as follows:

**How categories are determined:**
Categories must be **inferred from the `title` and `description` fields** of articles in the MongoDB collection. The extraction approach uses **LLM classification**.

**The four possible categories are:**
1. World
2. Sports
3. Business
4. Science/Technology

**Category inference prompt:** "Given this news article title and description, classify it into exactly one of: World, Sports, Business, Science/Technology."

---

## UF-4 — unstructured_field_inventory.md

**Verdict:** ✅ PASS

**Question:**
> What format are PATENTS date fields stored in, and what parsing approach is recommended?

**Required keywords:** `natural language`, `dateparser`

**Answer:**

According to the document, PATENTS date fields (`publication_date`, `filing_date`, `grant_date`, `priority_date`) are stored as **NL date strings** (natural language format), with examples like "March 15th, 2020".

The recommended parsing approach uses the following priority:

1. Try `"%B %dth, %Y"` format
2. Try `"%B %dst, %Y"` format
3. Try `"%B %dnd, %Y"` format
4. Try `"%B %drd, %Y"` format
5. Fall back to `dateparser.parse()` if none of the above work

The document notes this can be done with either `datetime.strptime` with multiple formats or `dateparser.parse()` as a fallback.

---
