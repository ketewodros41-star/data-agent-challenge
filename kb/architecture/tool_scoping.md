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

  query_postgresql → Standard SQL only → PostgreSQL connections
  query_mongodb    → Aggregation pipeline only → MongoDB collections
  query_sqlite     → Simple SQL only → SQLite files
  query_duckdb     → Analytical SQL only → DuckDB warehouse

Never send SQL to query_mongodb. It will return empty silently.
Never send a pipeline to query_postgresql. It will error.
The tool name determines the query language. Always.

## Routing rule — how to select the right tool

Step 1: Identify what type of data the question needs.
Step 2: Check kb/domain/schemas.md for which DB holds it.
Step 3: Select the matching tool. Generate query in its language.
Step 4: For multi-DB questions: call each tool separately.
        Never merge across tools in a single call.
        Send both results to sandbox for merging.

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