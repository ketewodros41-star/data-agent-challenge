# Two Weeks, One Benchmark, Six People: What We Actually Learned Building a Production Data Agent

**Published on LinkedIn:** https://www.linkedin.com/pulse/two-weeks-one-benchmark-six-people-what-we-actually-learned-daniel-kr8nf

---

Two weeks ago our team started with a challenge: build a production-grade data analytics agent and compete on UC Berkeley's DataAgentBench — a benchmark designed to expose exactly why AI data agents fail on real enterprise data.

Today is submission day. Here is what we built, what broke, and what we learned.

## What DataAgentBench Actually Tests

Most AI benchmarks test clean, single-database, well-formatted data. DataAgentBench tests the opposite. 54 queries across 12 real-world datasets and 4 database systems — PostgreSQL, MongoDB, SQLite, and DuckDB — often in the same query session.

The best current score on the leaderboard is 54.3%. Not because the models are weak. Because the problem is genuinely hard. The benchmark tests four things that break every data agent in production: multi-database routing, ill-formatted join keys, unstructured text extraction, and domain knowledge gaps.

That gap between demo performance and production reality is what our team spent two weeks engineering against.

## What We Built

Our agent is a natural language data analyst. A user asks a complex business question. The agent figures out which databases to query, routes sub-queries correctly, resolves mismatched entity formats, extracts structured facts from unstructured fields, and returns a verifiable answer with a full query trace.

The architecture draws from two sources: the Claude Code source leak from March 2026, which revealed a three-layer memory system, and OpenAI's internal data agent writeup, which described a six-layer context architecture. We synthesised both into three context layers:

**Layer 1 — Schema and Metadata Knowledge.** Everything about the databases loaded before the agent answers its first question. What tables exist, what columns, what types, what relationships.

**Layer 2 — Institutional and Domain Knowledge.** What "active customer" means in this dataset. How join keys are formatted differently across systems. Which tables are authoritative. The things that are not in the schema but that a human analyst would know on day one.

**Layer 3 — Corrections Log.** A running structured log of every failure the agent makes — what failed, why it failed, what the correct approach was. The agent reads this at the start of every session. This is the self-learning loop. The agent improves without retraining. Just better context.

## The Thing That Surprised Me Most

I came into this thinking the hard part of building a data agent was query generation. Getting the SQL right. Getting the MongoDB aggregation pipeline right.

I was wrong.

Query generation is the easy part. The hard part is everything that has to be true before the query is written.

On Day 1 we hit the join key problem. Same customer. Stored as integer 10023 in PostgreSQL. Stored as string CUST-10023 in MongoDB. The agent tried to join them. Got zero results. No error message. Just a wrong answer that looked correct.

Nothing in the schema explained this. The knowledge lived in the heads of experienced analysts — not in any database, not in any schema file. Our Intelligence Officers spent most of two weeks making that invisible institutional knowledge visible to the agent before it needed it.

That is context engineering. And it is what actually moves the needle.

## What the Evaluation Taught Us

We built the evaluation harness before we optimised the agent. Every query the agent runs is traced. Every answer is scored. Every failure is logged with a root cause.

Databricks' 2026 State of AI Agents report found that companies using evaluation tools get 6x more AI projects into production. We believe this now. The harness is the product. The agent is what the harness improves.

The corrections log has real data — tool name mismatches, query failures, join resolution errors — all logged from actual runs and fed back into the agent's context for the next session. The agent is genuinely learning from its own mistakes. Not through retraining. Through better context.

## What Is Still Hard

The hardest unsolved problem is not query generation. It is self-correction on unstructured text. When the answer requires extracting structured facts from a free-text field — a support note, a product description, a review — even the best current agents fail consistently. Both the PromptQL agent and the ReAct baseline fail entirely on these queries.

We made progress on this. We did not fully solve it. That is an honest answer.

## The Lesson I Am Taking Away

Six people. Three roles — Drivers who built and ran the code, Intelligence Officers who built and maintained the knowledge base, Signal Corps who documented and communicated the work externally. Each role made the others more effective.

The Intelligence Officers' Knowledge Base made the Drivers' agent smarter. The Drivers' failure logs made the Knowledge Base more accurate. The Signal Corps' external posts brought back community intelligence that changed the team's technical approach.

That compounding — where each person's work makes everyone else's work more powerful — is the thing worth taking from this. Not the benchmark score. The discipline that produced it.

---

*Team PaLM — TRP1 FDE Programme, April 2026. Submitted to the DataAgentBench public leaderboard at github.com/ucbepic/DataAgentBench*
