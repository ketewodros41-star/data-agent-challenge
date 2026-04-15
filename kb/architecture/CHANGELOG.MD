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

## 2026-04-14 — Injection tests formalised and expanded (36 tests passing)

Full injection test suite run against all architecture documents.
Results recorded in [injection_tests/results.md](injection_tests/results.md).

| File | Tests run | Result |
|---|---|---|
| memory_system.md | MS-1 through MS-4 (MEMORY.md purpose, corrections log fields, consolidation rule, Claude memory limits) | 4/4 PASS |
| tool_scoping.md | TS-1 through TS-4 (MongoDB tool selection, SQL-to-MongoDB silent failure, multi-DB procedure, DuckDB analytical queries) | 4/4 PASS |
| context_layer.md | OC-1 through OC-4 (Codex Enrichment layer, Layer 4 institutional knowledge, discovery phase finding, Layer 6 live runtime) | 4/4 PASS |
| self_correcting_execution.md | EL-1 through EL-4 (ID mismatch retry steps, 6-step execution loop, empty result handling, confidence levels) | 4/4 PASS |

**Key finding confirmed during this round:**
`tool_scoping.md` injection test TS-2 confirmed that sending SQL to `query_mongodb` returns empty results silently with no error — the agent produces a confident wrong answer with no failure signal. This is now a mandatory warning in the document and reflected in agent operating rules (KB v2 Section 0).

**Total tests passing across all architecture documents: 36/36**

---

## Rules for future entries

Every ADDITION must record:
  - Filename, injection test question used, result (PASS only)

Every REMOVAL must record:
  - Filename, reason for removal, date
  - "Failed injection test" is a valid reason — remove immediately

Every UPDATE must record:
  - Filename, what changed, injection test re-run, result

Growth without removal = noise.
Never commit a document that failed its injection test.
Never commit a document without running its injection test.