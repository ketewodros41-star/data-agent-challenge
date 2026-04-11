# We're Building a Data Agent That Competes on a 
# UC Berkeley Benchmark. Here's What We've Learned 
# in Week 1.

**Authors:** Kidus Tewodros & Mistire Daniel  
**Role:** Signal Corps, PaLM Team  
**Published:** April 10, 2026  
**Platform:** Medium  
**URL:** https://medium.com/@ktewodros41/were-building-a-data-agent-that-competes-on-a-uc-berkeley-benchmark-937d6370eee4  
**Word count:** ~800  

---

Most AI agent demos look the same. A clean question 
goes in, a clean answer comes out, and everyone 
applauds. What they don't show you is what happens 
when the customer ID is an integer in one database 
and "CUST-00123" in another. Or when the answer to 
a business question lives across PostgreSQL and 
MongoDB simultaneously. Or when the word "active 
customer" means something specific to this 
organisation that no model was trained to know.

That gap between the demo and the production reality 
is exactly what UC Berkeley's DataAgentBench was 
designed to expose. And for the past week, our team 
— PaLM — has been building an agent to compete on it.

## What DAB Actually Tests

DataAgentBench is the first benchmark built on 
realistic enterprise data workloads. 54 queries. 
12 datasets. 4 database systems: PostgreSQL, MongoDB, 
SQLite, and DuckDB — often in the same query. The 
best score on the leaderboard right now is 54.3%, 
achieved by PromptQL running Gemini. That ceiling 
isn't a flaw in the benchmark. It's a signal about 
how hard the real problem is.

The four things DAB specifically tests are the four 
things that break every data agent in production: 
multi-database routing, ill-formatted join keys, 
unstructured text extraction, and domain knowledge 
gaps. These aren't edge cases. They are the norm 
in enterprise environments.

## What We're Building and Why

Our agent is a natural language data analyst. A user 
asks a complex business question. The agent figures 
out which databases to query, routes sub-queries 
correctly, resolves mismatched entity formats, 
extracts structured facts from unstructured fields, 
and returns a verifiable answer with a full 
query trace.

The architecture we settled on draws from two sources 
that converged on the same insight: the Claude Code 
source leak from March 2026, which revealed a 
three-layer memory system built around a MEMORY.md 
index, and OpenAI's internal data agent writeup, 
which described a six-layer context architecture. 
We synthesised both into three context layers:

**Layer 1 — Schema and Metadata Knowledge.**
Everything about the databases loaded before the 
agent answers its first question.

**Layer 2 — Institutional and Domain Knowledge.**
What "active customer" means in this dataset. How 
join keys are formatted differently across systems.

**Layer 3 — Corrections Log.**
A running structured log of every failure the agent 
makes. The agent reads this at the start of every 
session. Improvement without retraining.

## The Decision We're Most Confident About

We built the evaluation harness before we optimised 
the agent. Databricks' 2026 State of AI Agents report 
found that companies using evaluation tools get 6x 
more AI projects into production. The harness is 
the product. The agent is what the harness improves.

## What's Still Hard

Token optimisation. Schema documents, domain 
knowledge, corrections log, and session context 
all compete for the same context window. We posted 
about this on Reddit and got three strong responses 
pointing toward lazy loading and on-demand schema 
expansion — that discussion is now feeding directly 
into our architecture decision.

## Where We Are

Inception document approved. Architecture diagrams 
completed. Knowledge Base v1 in progress. 
Interim submission: Tuesday April 14.
Benchmark submission: Saturday April 18.

---

*PaLM Team — TRP1 FDE Programme, April 2026.*  
*github.com/ucbepic/DataAgentBench*

---

