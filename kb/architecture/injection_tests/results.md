# Injection Test Results

**Last run:** 2026-04-09 15:49 UTC  
**Status:** 16/16 tests passing

---

## MS-1 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What is MEMORY.md for, what is its word limit, and what triggers a topic file to be loaded from memory?

**Required keywords:** `index`, `200`, `on-demand`, `topic`

**Answer:**

Based on the document:

**What is MEMORY.md for:**
MEMORY.md is an index file that is loaded at every session start. It contains pointers to actual knowledge, not the content itself. Actual knowledge lives in separate topic files.

**Word limit:**
MEMORY.md must stay under 200 words. If it exceeds 200 words, the oldest changelog entries should be removed. Topic file pointers must never be removed.

**What triggers a topic file to be loaded:**
Topic files are loaded on-demand when the current question requires that specific topic. Examples include:
- Question involves customer join → load kb/architecture/tool_scoping.md
- Question uses "revenue" → load kb/domain/business_terms.md
- Question previously failed → load kb/corrections/log.md

The rule is: load a topic file only when the current question requires it, and never pre-load all files to keep the context window efficient.

---

## MS-2 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What is the autoDream pattern and when does it run?

**Required keywords:** `session end`, `corrections`, `consolidat`

**Answer:**

Based on the document:

**autoDream pattern** is a background thinking task (DreamTask pattern) that runs **at session end**.

When it runs, the autoDream consolidation performs these steps:

1. Review what was learned
2. Write new corrections to kb/corrections/log.md
3. Update relevant topic files with successful patterns
4. Update MEMORY.md index if new files were added

This is described as the **self-learning loop** — the agent improves across sessions without retraining. The document emphasizes: "Do not skip this step."

---

## MS-3 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> Where are Layer 3 session transcripts stored and how are they accessed?

**Required keywords:** `jsonl`, `search`, `never load`

**Answer:**

According to the document:

**Storage location:** Layer 3 session transcripts are stored at `~/.claude/projects/<hash>/sessions/<session-id>.jsonl`

**Format:** Sessions are stored as append-only JSONL logs.

**How they are accessed:** 
- Resume flow: `getLastSessionLog()` → parse JSONL → rebuild `messages[]`
- The agent can search transcripts when a new question resembles a past one.

**Usage rule:** Search transcripts only when relevant. Never load all transcript history into context.

---

## MS-4 — memory_system.md

**Verdict:** ✅ PASS

**Question:**
> What is the maximum word count for a topic file?

**Required keywords:** `400`

**Answer:**

According to the document, the maximum word count for a topic file is **400 words**.

The document states: "Rule for this agent: each topic file maximum 400 words."

---

## TS-1 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> A DAB question asks: which customers had support complaints this week? Which database tool do you use, what query language, and why can't you use query_postgresql for this?

**Required keywords:** `query_mongodb`, `aggregation`, `empty`

**Answer:**

Based on the document:

**Database tool:** query_mongodb

**Query language:** Aggregation pipeline

**Why you can't use query_postgresql:** Because the document states "Never send SQL to query_mongodb. It will return empty silently." This implies that support complaints data is stored in MongoDB (not PostgreSQL). If you sent SQL to query_postgresql instead, you would be querying the wrong database system that doesn't contain the support complaints data.

The routing rule in the document requires you to:
1. Identify the data type needed (support complaints)
2. Check which DB holds it (MongoDB, based on context)
3. Select the matching tool (query_mongodb)
4. Generate the query in its language (aggregation pipeline)

---

## TS-2 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> What happens if you send a SQL query to query_mongodb?

**Required keywords:** `empty`, `silent`

**Answer:**

According to the document:

**It will return empty results silently.**

The document explicitly states: "Never send SQL to query_mongodb. It will return empty silently."

This is part of the tool scoping philosophy where each database tool expects its own query language. `query_mongodb` expects an aggregation pipeline, not SQL. If you send SQL to it anyway, rather than throwing an error, it silently returns empty results.

---

## TS-3 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> A question requires data from both PostgreSQL and MongoDB. What is the correct procedure?

**Required keywords:** `separately`, `sandbox`

**Answer:**

According to the document, the correct procedure for a question requiring data from both PostgreSQL and MongoDB is:

**Step 1:** Call each tool separately
- Use `query_postgresql` for the PostgreSQL data with Standard SQL
- Use `query_mongodb` for the MongoDB data with an aggregation pipeline

**Step 2:** Send both results to sandbox for merging

The document explicitly states: "For multi-DB questions: call each tool separately. Never merge across tools in a single call. Send both results to sandbox for merging."

This follows Claude Code's scoping philosophy where each database tool has tight domain boundaries and handles only its specific database type and query language.

---

## TS-4 — tool_scoping.md

**Verdict:** ✅ PASS

**Question:**
> What tool is used for analytical SQL queries against the data warehouse?

**Required keywords:** `query_duckdb`

**Answer:**

According to the document, the tool used for analytical SQL queries against the data warehouse is **query_duckdb**.

The document states:
> query_duckdb    → Analytical SQL only → DuckDB warehouse

---

## OC-1 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What is Codex Enrichment and which of the six layers is it?

**Required keywords:** `layer 3`, `pipeline`, `join key`

**Answer:**

According to the document, **Codex Enrichment is Layer 3** of the six-layer context architecture.

Codex Enrichment is a daily async process where Codex inspects pipeline code for each table. It derives:
- Upstream/downstream dependencies
- Ownership
- Granularity
- Join keys
- Similar tables
- Filter assumptions

The document notes that Codex Enrichment reveals **what is INSIDE a table, not just its schema**, and describes it as "the hardest sub-problem at scale."

---

## OC-2 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What does Layer 4 contain and what does it map to in this agent's KB?

**Required keywords:** `institutional`, `business_terms`

**Answer:**

According to the document:

**Layer 4 — Institutional Knowledge** contains:
- Agent searches of Slack, Google Docs, and Notion for:
  - Product launches
  - Technical incidents
  - Metric definitions
  - Internal terminology (e.g., what "active user" means at OpenAI)

**It maps to in this agent's KB:**
- `kb/domain/business_terms.md` (institutional knowledge)

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

In other words, investing time in the discovery phase to compare and validate which table to use leads to better results.

---

## OC-4 — context_layer.md

**Verdict:** ✅ PASS

**Question:**
> What is Layer 6 used for and when is it triggered?

**Required keywords:** `live`, `stale`, `real-time`

**Answer:**

According to the document, Layer 6 — Live runtime queries is used for:

**Purpose:** When no prior information exists or data is stale, the agent queries live data.

**How it works:** MCP connections to the data warehouse for real-time schema inspection.

The document does not provide specific details about the exact conditions or thresholds that trigger Layer 6, only that it is used when prior information is unavailable or outdated.

---

## EL-1 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> The sandbox returns validation_status: failed, error: ID format mismatch. What are the exact next steps and what happens after 3 retries all fail?

**Required keywords:** `strip`, `convert`, `retry`, `honest`, `never`

**Answer:**

According to the document, here are the exact next steps:

**Immediate next steps:**
1. Strip prefix from the ID
2. Convert the ID type
3. Retry the query

**After 3 retries all fail:**
- Return an honest error with the full query trace
- Never hallucinate an answer

The document explicitly states: "After 3 failures: return honest error with full trace. Never hallucinate an answer."

---

## EL-2 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> What are the 6 steps of the execution loop in order?

**Required keywords:** `plan`, `execute`, `check`, `diagnose`, `deliver`, `log`

**Answer:**

According to the document, the 6 steps of the execution loop for this agent are:

1. **PLAN** — Check corrections log first. Select tools. Identify databases. Spend time validating which table to use before querying.

2. **EXECUTE** — Call scoped tools. Send results to sandbox for merging/validation.

3. **CHECK SANDBOX RESPONSE** — Read validation_status field. "ok" → proceed to delivery. "failed" → diagnose from error_if_any field.

4. **DIAGNOSE AND RETRY** — (maximum 3 attempts) Handle specific errors like ID format mismatch, empty results, or syntax errors. After 3 failures: return honest error with full trace. Never hallucinate an answer.

5. **DELIVER** — Package: answer + query_trace + confidence level. Confidence: high (direct result), medium (inferred), low (partial).

6. **LOG (autoDream)** — Write failures to kb/corrections/log.md. Write new successful patterns to relevant topic file. Update MEMORY.md if new files created.

---

## EL-3 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> A tool call returns an empty result set with no error. What does the agent do next?

**Required keywords:** `verify`, `table`, `schemas`, `retry`

**Answer:**

According to the document, when a tool call returns an empty result set, the agent follows Step 3 — CHECK SANDBOX RESPONSE and Step 4 — DIAGNOSE AND RETRY:

1. The agent reads the `validation_status` field from the sandbox response
2. If the status is "failed" with an "empty result" error, the agent diagnoses this as one of the known failure types
3. The specific next step for "empty result" is: **verify table name in schemas, retry**
4. This retry attempt counts toward the maximum of 3 attempts
5. If all 3 retries fail, the agent returns an honest error with the full query trace rather than hallucinating an answer

The document emphasizes that the agent should "Spend more time in the discovery phase first" and not be overconfident about which table to use, so verifying the table name in the schemas is the appropriate diagnostic step before retrying.

---

## EL-4 — self_correcting_execution.md

**Verdict:** ✅ PASS

**Question:**
> What confidence levels does the agent assign and when?

**Required keywords:** `high`, `medium`, `low`

**Answer:**

According to the document, the agent assigns confidence levels as follows:

**Confidence levels:**
- **High** — direct result
- **Medium** — inferred
- **Low** — partial

These confidence levels are packaged along with the answer and query_trace in Step 5 (DELIVER) of the execution loop.

The document does not provide additional details about the specific criteria for determining when each confidence level should be assigned beyond these three categories.

---
