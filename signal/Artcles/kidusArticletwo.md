# Five Ways a Data Agent Fails — and What Each One
# Actually Looks Like in Practice

**Author:** Kidus Tewodros  
**Role:** Signal Corps, PaLM Team  
**Published:** April 15, 2026  
**Platform:** Medium  
**URL:** https://medium.com/@ktewodros41/five-ways-a-data-agent-fails-and-what-each-one-actually-looks-like-in-practice-4546a6e230dc  
**Word count:** ~1,500  

---

When you build a data agent from scratch, you discover
quickly that "it failed" is not a useful diagnosis. An
agent that returns a wrong answer, an agent that returns
no answer, and an agent that returns a plausible-looking
wrong answer are three completely different problems —
and they require completely different fixes.

While building our multi-database data agent for UC
Berkeley's DataAgentBench — 54 queries across PostgreSQL,
MongoDB, SQLite, and DuckDB — we classified every failure
we encountered into one of five categories before running
the full benchmark. The classification forced us to think
clearly about what was actually breaking and why. Here is
what each category looks like in practice, what we have
seen so far, and what we are still uncertain about.

## Category 1 — Syntax Failures

The name is slightly misleading. Most of the syntax
failures we have encountered are not SQL syntax errors —
the model is generally competent at writing valid SQL.
The failures are at the interface layer between the agent
and the tools it uses to execute queries.

In our setup, all database execution is routed through
the Google MCP Toolbox, which exposes standardised HTTP
tools defined in a tools.yaml configuration file. The
agent generates a query plan and then calls a tool by
name. The problem: if the name the agent constructs at
runtime does not match the registered tool name exactly,
the Toolbox returns HTTP 404. The tool exists. The
database is running. The query is valid SQL. But the
agent called the tool by a slightly wrong name and got
nothing back.

This is not a model failure in the traditional sense. It
is a system integration failure — a mismatch between the
agent's internal representation of what tools are
available and what is actually registered. The fix
requires strict tool name validation at plan generation
time, not at execution time. By the time execution fails,
you have already wasted a round trip.

## Category 2 — Join Key Mismatches

This is the failure mode DataAgentBench is most famous
for testing. The same real-world entity appears in
different formats across different database systems.
Customer ID 10023 in PostgreSQL. Customer ID CUST-10023
in MongoDB. The agent tries to join them. The join
produces zero results — or worse, wrong results — because
the formats do not match and the agent did not resolve
the mismatch before attempting the join.

We built a join key glossary in our institutional
knowledge layer that documents exactly how each entity's
ID appears across each database system, and what
transformation resolves the mismatch. The agent loads
this glossary before any cross-database query. In theory
it checks the glossary before attempting any join. In
practice we have not yet confirmed that it reads and
applies the glossary correctly under full benchmark
conditions. This is one of the things the benchmark run
will measure.

The deeper challenge with join key mismatches is that
they can fail silently. A wrong format produces zero
results, which the agent might interpret as "no matching
data" rather than "join failed." Silent wrong answers are
more dangerous than visible errors because they look like
results.

## Category 3 — Wrong Database Type Routing

The agent has to decide, for each sub-query, which
database to send it to. Twice during our testing it
routed a PostgreSQL query to SQLite. The symptom: SQLite
receives a query written in PostgreSQL dialect — using
PostgreSQL-specific functions or window syntax — and
either errors or returns wrong results because SQLite
does not support the same query language.

The root cause in both cases was the same: the query
router matched the entity name in the question to the
wrong database because both databases contained tables
with similar names. The router made a reasonable guess
that turned out to be wrong.

The fix we are building is explicit database type tagging
in the query plan — the router must declare which
database type it is targeting before generating
dialect-specific syntax. Then the execution engine
validates that the declared type matches the actual
connected database before running the query. Two
checkpoints instead of one.

We have not yet tested wrong database type routing
systematically on the benchmark. We know it happens. We
do not yet know how often, or how much it is costing us
on pass@1.

## Category 4 — Data Quality Failures

These are subtler than the previous three because the
failure does not come from the agent's logic — it comes
from a mismatch between what the schema says and what the
data actually contains.

The most common data quality failure we have hit is null
constraint violations. The schema declares a column as
NOT NULL. The agent generates a query that assumes the
column is non-null — a reasonable assumption given what
the schema says. The actual data has nulls in that column.
The query either fails or returns a result that silently
excludes rows the user expected to see.

This puts us in an awkward position. The schema is
technically correct — the NOT NULL constraint is declared.
The data violates it. The agent has no way to know this
without either running a data quality pre-check on every
query or having the data quality issues documented in the
institutional knowledge layer before query time. We chose
the latter — we document known data quality issues in our
KB domain layer rather than adding pre-check overhead to
every query.

The open question is where the line is between a data
quality failure and a domain knowledge gap. A null
constraint violation could be a data quality issue —
dirty data — or it could mean the agent is querying the
wrong table because it does not know which one is the
authoritative source of truth. Both failures look the
same from the outside.

## Category 5 — Extraction Failures

This is the failure mode we have theorised about but not
yet measured. Some DAB queries require extracting
structured facts from free-text fields before those facts
can be used in a calculation. Location embedded inside a
description field. Category hidden in a product
description. Status buried in a support note. The agent
cannot filter by location if location is not a column —
it has to extract the structured fact from the text first.

The challenge with extraction failures is measurement. A
syntax error is visible. A wrong database type produces
an obvious error. An extraction failure might produce a
plausible-looking wrong answer — the agent extracts the
wrong structured fact, uses it in the calculation, and
returns a result that is internally consistent but
factually wrong. There is no error signal. The answer
looks correct.

We have documented which DAB dataset fields contain
embedded structured data in our unstructured field
inventory — part of the institutional knowledge layer —
and flagged those fields for NLP extraction before any
calculation. Whether the agent actually does this
correctly under benchmark conditions is what the
evaluation harness will measure.

## What the Classification Taught Us

The most useful thing about classifying failures before
running the benchmark is that it forces you to think
about what correct looks like before you see what wrong
looks like. Each failure category requires a different
fix — strict tool name validation for syntax, glossary
injection for join key mismatches, type tagging for wrong
routing, KB documentation for data quality, NLP
pre-processing for extraction.

An agent that lumps all failures together as "it gave
the wrong answer" cannot improve systematically. An agent
with a typed failure taxonomy can identify which category
a failure belongs to, apply the right correction
strategy, and measure whether the fix worked.

The benchmark will tell us which categories are costing
us the most points. We will report back.

---

*PaLM Team — TRP1 FDE Programme, April 2026.*  
*github.com/ucbepic/DataAgentBench*

---
