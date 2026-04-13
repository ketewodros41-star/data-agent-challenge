# Claude Code Tool Scoping Philosophy

Source: Claude Code v2.1.88, src/tools/, src/Tool.ts, src/tools.ts

## The principle: 40+ tools with tight domain boundaries

Claude Code uses 40+ built-in tools. Each tool has ONE job,
connects to ONE system, and returns ONE structured format.
Tools are never combined into a general-purpose handler.

From source (Tool.ts interface):
  validateInput()      → reject bad args before any execution
  checkPermissions()   → tool-specific authorisation
  isConcurrencySafe()  → can this run in parallel?
  isReadOnly()         → does this have side effects?
  prompt()             → description given to the LLM

The LLM sees the tool description. It selects the tool.
The tool's own validation and permission logic runs.
The result is returned in a fixed structured format.

## How this applies to this agent's database tools

This agent implements the same scoping pattern for databases.
Each database type gets its own scoped tool.

  Tool              Query language        Database       Data type
  query_postgresql  Standard SQL          PostgreSQL     Sales, transactions
  query_mongodb     Aggregation pipeline  MongoDB        Support, CRM
  query_sqlite      Simple SQL            SQLite         Reference, lookup
  query_duckdb      Analytical SQL        DuckDB         Warehouse, analytics

Never send SQL to query_mongodb. It will return empty silently.
Never send a pipeline to query_postgresql. It will error.
The tool name determines the query language. Always.

## Routing rule — how to select the right tool

Step 1: Identify what type of data the question needs.
Step 2: Check kb/domain/schemas.md for which DB holds it.
Step 3: Select the matching tool. Generate query in its language.
Step 4: For multi-DB questions: call each tool separately — never combined.
        Send both result sets to sandbox for merging.
        Never merge across tools in a single call.

Cross-database join procedure:
  1. Call query_postgresql → structured sales/transaction result
  2. Call query_mongodb    → aggregation pipeline result
  3. Normalize IDs in both sets: remove "CUST_", cast to int
  4. Merge in sandbox (never in a single tool call)

## Why silent failures make tool scoping critical

When the wrong tool receives the wrong query language:
  SQL → query_mongodb     → empty result, no error, agent unaware
  Pipeline → query_postgresql → explicit error, agent retries

Silent failures are worse. The agent produces a confident wrong
answer with no signal that anything failed. Tool scoping prevents
silent failures at the architectural level — not at retry time.

## Unstructured fields — additional tool required

Some fields require NLP extraction before querying:
  support_notes, product_description, comments

These must go through a text extraction step before joining
structured results. Do not filter on raw text fields directly.

## Sub-agent spawn modes (from source: AgentTool, worktree)

Claude Code also supports fork/worktree sub-agent spawning.
  default  → in-process, shared conversation
  fork     → child process, fresh messages[], shared file cache
  worktree → isolated git worktree + fork process

This agent uses the fork pattern via tenai-infra worktrees for
running parallel DAB experiments without interference.

## Injection test question
"A DAB question asks: which customers had support complaints
this week? Which database tool do you use, what query language,
and why can't you use query_postgresql for this?"

Expected: query_mongodb, aggregation pipeline, because SQL
sent to query_mongodb returns empty results silently.
