# kb/architecture/ CHANGELOG

## 2026-04-08 — Initial commit (4 documents)

All documents written from primary sources:
  - Claude Code v2.1.88 (src/commands/memory/, src/tools/, src/query.ts)
  - OpenAI data agent writeup (January 29, 2026)

Injection tests run before commit. Results:

| File                                  | Test question                                          | Result |
|---------------------------------------|--------------------------------------------------------|--------|
| claude_code_memory_system.md          | What is MEMORY.md for, its word limit, and what       | PASS   |
|                                       | triggers a topic file to load?                        |        |
| claude_code_tool_scoping.md           | Which tool for MongoDB complaints, what language,     | PASS   |
|                                       | why not query_postgresql?                             |        |
| openai_agent_six_layer_context.md     | What is Codex Enrichment and which layer is it?       | PASS   |
| self_correcting_execution.md          | Sandbox returns ID mismatch — next steps and what     | PASS   |
|                                       | happens after 3 retries fail?                         |        |

## Rules for future entries

Every ADDITION must record:
  - Filename, injection test question used, result (PASS only)

Every REMOVAL must record:
  - Filename, reason for removal, date
  - "Failed injection test" is a valid reason — remove immediately

Growth without removal = noise.
Never commit a document that failed its injection test.
Never commit a document without running its injection test.