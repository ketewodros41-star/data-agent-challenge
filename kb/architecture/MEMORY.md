# MEMORY.md — Architecture Knowledge Index

Load this file at every session start.
Load topic files on demand only. Never pre-load all.

## Always load at session start
- kb/architecture/tool_scoping → claude_code_tool_scoping.md
- kb/corrections/log.md (last 10 entries)

## Load on demand

| If question involves...         | Load this file                              |
|---------------------------------|---------------------------------------------|
| Memory layers, MEMORY.md        | memory_system.md               |
| Which tool, query language      | tool_scoping.md                |
| Context layers, OpenAI pattern  | context_layer.md          |
| Self-correction, retry loop     | self_correcting_execution.md               |
| Business terms, definitions     | kb/domain/business_terms.md                |
| Table names, column formats     | kb/domain/schemas.md                       |
| ID formats, join key mismatch   | kb/domain/join_keys.md                     |
| Past agent failures             | kb/corrections/log.md                      |

## CHANGELOG
2026-04-08: KB v1 initial commit. 4 documents. All injection-tested.

## Index size rule
This file must stay under 200 words.
Remove oldest CHANGELOG entries before removing topic pointers.