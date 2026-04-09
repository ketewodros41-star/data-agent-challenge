# Self-Correcting Execution — Closed-Loop Pattern

Sources:
- Claude Code v2.1.88: src/query.ts (main agent loop), StreamingToolExecutor
- OpenAI data agent: closed-loop self-correction pattern

## The core agent loop (from Claude Code source)

From query.ts — the main loop structure:

  while stop_reason != "tool_use":
    call Claude API (streaming)
    if tool_use block returned:
      run StreamingToolExecutor → parallel where safe, serial otherwise
      canUseTool() permission check
      if DENY → append error, continue loop
      if ALLOW → tool.call() → append tool_result → loop back
    else:
      return final text

This is the loop this agent runs. Production harness adds:
  permission checks, streaming, compaction, sub-agents, persistence.

## Self-correction pattern (from OpenAI data agent)

OpenAI describes this as "closed-loop self-correction":
  - Agent evaluates its own progress after each step
  - If query fails or returns suspicious results:
    investigate the error → adjust approach → retry
  - Agent does not surface errors to user
  - User receives either correct answer or honest "could not resolve"

"Overconfidence is the biggest behavioral flaw. The model often
says 'This is the right table' and runs ahead. That is wrong.
Spend more time in the discovery phase first." — Emma Tang, OpenAI

## Execution loop for this agent

Step 1 — PLAN
  Check corrections log first. Select tools. Identify databases.
  Spend time validating which table to use before querying.

Step 2 — EXECUTE
  Call scoped tools. Send results to sandbox for merging/validation.

Step 3 — CHECK SANDBOX RESPONSE
  Read validation_status field.
  "ok" → proceed to delivery.
  "failed" → diagnose from error_if_any field.

Step 4 — DIAGNOSE AND RETRY (maximum 3 attempts)
  "ID format mismatch" → strip prefix, convert type, retry
  "empty result"       → verify table name in schemas, retry
  "syntax error"       → check query language for this tool, retry
  After 3 failures: return honest error with full trace.
  Never hallucinate an answer.

Step 5 — DELIVER
  Package: answer + query_trace + confidence level
  Confidence: high (direct result), medium (inferred), low (partial)

Step 6 — LOG (autoDream)
  Write failures to kb/corrections/log.md.
  Write new successful patterns to relevant topic file.
  Update MEMORY.md if new files created.

## Injection test question
"The sandbox returns validation_status: failed, error: ID format
mismatch. What are the exact next steps and what happens after
3 retries all fail?"

Expected: strip prefix, convert type, retry. After 3 failures:
return honest error with full query trace. Never guess.