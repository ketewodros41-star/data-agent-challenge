# The Join Key Problem: Why the Same Customer Is a Different Person in Every Database

*By Mistire — Signal Corps, PaLM Team*

**Platform:** Medium
**Published:** April 2026
**URL:** [The Join Key Problem](https://medium.com/@mistiredan/the-join-key-problem-why-the-same-customer-is-a-different-person-in-every-database-10985194c39c)

---

There is a problem sitting quietly inside almost every enterprise data system that nobody talks about until an AI agent hits it face first. It does not show up in demos. It does not appear in the clean academic benchmarks that most AI evaluation is built on. But the moment you point an AI agent at real company data — the kind that has been collected across years, systems, and teams — it is everywhere.

We ran into it in Week 1 of building our data agent. And honestly, it changed how I think about the whole problem.

---

## The Same Customer. Two Databases. Two Completely Different Identities.

Here is the scenario. Your company has a transactions database running on PostgreSQL. It also has a CRM system running on MongoDB. A user asks: *"Which customers had declining purchases in Q3 and also raised support tickets in the same period?"*

Simple question. Two databases needed. One join required.

Your agent goes to PostgreSQL and finds the customer. Their ID is `10023` — a plain integer.

Your agent goes to MongoDB and looks for the same customer. Their ID is `CUST-10023` — a string with a prefix.

Your agent tries to join them. It fails. Not because the query was wrong. Not because the agent picked the wrong table. Because the same real-world person is represented in two completely different formats across two systems that were never designed to talk to each other.

This is called the **ill-formatted join key problem**. And according to UC Berkeley's DataAgentBench — the benchmark our team is competing on — it is one of the four core reasons AI data agents fail on real enterprise workloads.

---

## Why This Happens in the Real World

This is not a bug. It is the natural result of how companies actually build their data infrastructure.

The PostgreSQL transactions database was built by one engineering team five years ago. They used auto-incrementing integers for customer IDs because that is the PostgreSQL default and it is efficient.

The MongoDB CRM was bought as a SaaS product three years later and migrated in-house. The vendor used prefixed string IDs — `CUST-XXXXX` — because that is their convention and it makes IDs human-readable in support tickets.

Nobody standardised them because at the time nobody needed to join them automatically. A human analyst doing this manually just knows — from experience, from documentation, from asking a colleague — that `10023` and `CUST-10023` are the same person. They strip the prefix mentally before running the join.

An AI agent has no such intuition. It sees two different values and treats them as two different entities. The join produces zero results, or worse — wrong results that look plausible.

---

## Why It Is So Hard to Detect Automatically

The obvious question is: can the agent just figure this out on its own?

In theory, yes. The agent could inspect both columns, notice that one is an integer and one is a string, find the pattern `CUST-` prepended to what looks like a number, and infer that stripping the prefix and casting to integer would allow the join.

In practice this is genuinely difficult for three reasons.

**First, the pattern is not always obvious.** Sometimes it is a prefix. Sometimes it is a suffix. Sometimes the formats are `10023` and `C10023` and `customer_10023` and `id:10023` all in different systems. Pattern detection that works on one dataset breaks on the next.

**Second, the schema does not tell you.** Nothing in the database schema says "this column corresponds to that column in the other system." The relationship exists in institutional knowledge — in the heads of the analysts who work with this data — not in any structured metadata the agent can read.

**Third, a wrong inference is worse than no inference.** If the agent guesses the wrong resolution logic, it joins the wrong records, produces an answer that looks correct, and the user has no way of knowing it is wrong. A silent wrong answer is more dangerous than a visible failure.

---

## What Our Team Is Doing About It

Our Intelligence Officers — Estif and Melkam — are building what they call a **join key glossary** as part of the agent's Knowledge Base. It is a structured document that explicitly maps how entity identifiers appear differently across each database in the benchmark.

For every dataset in DataAgentBench, the glossary records: what the entity is, how its ID appears in each database system, and what transformation is needed to resolve them before a join.

This document gets injected into the agent's context before it answers any question. So when the agent encounters `CUST-10023` in MongoDB and `10023` in PostgreSQL, it already knows — from the glossary — that these are the same entity and exactly what to do about it.

Is this manual? Yes. Every entry in that glossary was written by a human who inspected the actual data. Is that a limitation? Absolutely — it does not scale automatically to new databases the agent has never seen before.

But here is the thing: for the databases in the benchmark, it works. And it works reliably. Which means the agent can focus its reasoning on the actual question rather than on resolving identity mismatches from first principles on every query.

The open question — the one we are still working through — is whether this detection can eventually be automated. Whether an agent given enough examples of resolved mismatches can learn to detect new ones without being told. That is a harder problem than it looks and we do not have the answer yet.

---

## What This Taught Me About the Whole Problem

Before this week I thought the hard part of building a data agent was generating the right query. Getting the SQL or the MongoDB aggregation pipeline correct. That is what most of the research focuses on. That is what most benchmarks measure.

What I understand now is that query generation is actually the easy part. The hard part is everything that has to be true before the query is written.

The agent has to know which databases exist. It has to know what the tables mean. It has to know what the business terms mean. And it has to know how the same real-world entity appears differently across systems that were never designed to work together.

None of that knowledge lives in the schema. All of it lives in the heads of experienced analysts. The entire job of context engineering — the thing our Intelligence Officers are spending most of their time on — is making that invisible institutional knowledge visible to the agent before it needs it.

The join key problem is not a technical quirk. It is a window into why production data agents are so much harder than demo data agents. And solving it, even partially, even manually for a specific set of databases, is the difference between an agent that produces a plausible-looking wrong answer and one that gets it right.

---

*PaLM Team is participating in the TRP1 FDE Programme, April 2026. Our agent will be submitted to the DataAgentBench public leaderboard at github.com/ucbepic/DataAgentBench. Follow for updates as we build.*

*Tags: Data Engineering · AI Agents · Machine Learning · LLM · DataAgentBench*
