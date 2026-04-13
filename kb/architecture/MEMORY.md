# MEMORY.md — Architecture Knowledge Index

Load this file at every session start.
Load topic files on demand only. Never pre-load all.
Load corrections log BEFORE receiving the question — not after.

## Always load at session start
- kb/architecture/tool_scoping.md
- kb/corrections/log.md (last 10 entries)

## Load on demand

| If question involves...              | Load this file                       |
|--------------------------------------|--------------------------------------|
| Memory layers, MEMORY.md             | memory_system.md                     |
| Which tool, query language           | tool_scoping.md                      |
| Context layers, OpenAI pattern       | context_layer.md                     |
| Self-correction, retry loop          | self_correcting_execution.md         |
| Business terms, definitions          | kb/domain/business_terms.md          |
| Table names, column formats          | kb/domain/schemas.md                 |
| ID formats, join key mismatch        | kb/domain/join_keys.md               |
| Past agent failures                  | kb/corrections/log.md                |

## CHANGELOG
2026-04-08: KB v1 initial commit. 4 documents. All injection-tested.
2026-04-13: context_layer.md — layers labeled MANDATORY/OPTIONAL, Layer 4 DAB-specific, [Outcome] field added to corrections format.
2026-04-13: memory_system.md — added working memory role, query pattern examples, consolidation rules, injection tests expanded to 4 questions.
2026-04-13: self_correcting_execution.md — corrections log loads before question, known DAB failure table added.
2026-04-13: tool_scoping.md — routing table with data types, cross-DB join procedure, silent failure explanation added.

## Index size rule
This file must stay under 200 words.
Remove oldest CHANGELOG entries before removing topic pointers.
