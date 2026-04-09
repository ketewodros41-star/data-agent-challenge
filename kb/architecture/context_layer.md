# OpenAI Data Agent — Six-Layer Context Architecture

Source: OpenAI engineering blog "Inside our in-house data agent"
January 29, 2026. Agent runs over 70,000 datasets, 600 petabytes.

## Why context beats raw intelligence

Without context, GPT-5.2 vastly misestimates user counts and
misinterprets internal terminology. The same model with 6 context
layers cuts analysis time from 22 minutes to 90 seconds on the
same query. The bottleneck is never query generation — it is context.

## The six layers (in order of loading)

Layer 1 — Schema metadata and query history
  Column names, data types, table lineage (upstream/downstream).
  Historical queries showing which tables are joined together.
  This tells the agent WHERE data lives and HOW it is used.

Layer 2 — Curated expert descriptions
  Domain experts write descriptions of key tables and dashboards.
  Captures semantics, business meaning, known limitations.
  What the column names do not tell you.

Layer 3 — Codex Enrichment (table enrichment)
  Daily async process: Codex inspects pipeline code for each table.
  Derives: upstream/downstream deps, ownership, granularity,
  join keys, similar tables, filter assumptions.
  Reveals what is INSIDE a table, not just its schema.
  This is the hardest sub-problem at scale.

Layer 4 — Institutional knowledge
  Agent searches Slack, Google Docs, Notion for:
  product launches, technical incidents, metric definitions,
  internal terminology (e.g. what "active user" means at OpenAI).
  This is what KB v2 domain knowledge replicates for DAB.

Layer 5 — Self-learning memory
  Corrections and nuances from previous conversations stored.
  Applied to future requests automatically.
  Stateless agents repeat the same mistakes. This prevents it.
  This is what KB v3 corrections log replicates for this agent.

Layer 6 — Live runtime queries
  When no prior info exists or data is stale: query live.
  MCP connections to data warehouse for real-time schema inspection.

## How this maps to this agent's KB

Layer 1+2 = kb/architecture/ + kb/domain/schemas.md (KB v1+v2)
Layer 3   = kb/domain/join_keys.md (enriched field meanings)
Layer 4   = kb/domain/business_terms.md (institutional knowledge)
Layer 5   = kb/corrections/log.md (self-learning memory, KB v3)
Layer 6   = MCP tools live queries (tools.yaml connections)

## Key finding from OpenAI: discovery phase

"The more time the agent spends in the discovery phase —
comparing which table to use — the better the results."
Prompt the agent to validate table choice BEFORE running analysis.
Do not run ahead. Spend time in discovery. Then execute.

## Injection test question
"What is Codex Enrichment and which of the six layers is it?"

Expected: Layer 3, daily async process where Codex inspects
pipeline code to derive what a table actually contains —
upstream/downstream deps, join keys, filter assumptions.