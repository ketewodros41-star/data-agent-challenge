# Claude Code Memory System — 3-Layer Architecture

Source: Claude Code v2.1.88 source leak (March 2026), src/commands/memory/

## How Claude Code actually manages memory

Claude Code uses three distinct memory layers. Each serves a
different purpose. They are not interchangeable.

## Layer 1 — MEMORY.md (the index file)

MEMORY.md is loaded at every session start without exception.
It is an index only — it contains pointers, not content.
Actual knowledge lives in separate topic files.

From source: MEMORY.md files are loaded lazily per directory
(see src/utils/memory/). The agent reads MEMORY.md first, then
decides which topic files to load based on the current task.

Rule for this agent: MEMORY.md stays under 200 words.
If it exceeds 200 words, remove the oldest changelog entries.
Never remove topic file pointers.

## Layer 2 — Topic files (loaded on demand)

Topic files contain actual knowledge — schemas, domain rules,
correction patterns. They are NOT pre-loaded.

From source: SkillTool + memdir/ handle on-demand injection.
Knowledge is injected via tool_result, not system prompt.
This keeps the context window efficient for long sessions.

Rule for this agent: each topic file maximum 400 words.
Load a topic file only when the current question requires it.
Never pre-load all files — context window fills up.

Trigger examples:
  Question involves customer join → load kb/architecture/tool_scoping.md
  Question uses "revenue" → load kb/domain/business_terms.md
  Question previously failed → load kb/corrections/log.md

## Layer 3 — Session transcripts (searchable, not pre-loaded)

From source: ~/.claude/projects/<hash>/sessions/<session-id>.jsonl
Sessions are stored as append-only JSONL logs.
Resume flow: getLastSessionLog() → parse JSONL → rebuild messages[]
The agent can search transcripts when a new question resembles
a past one.

Rule for this agent: search transcripts only when relevant.
Never load all transcript history into context.

## autoDream consolidation (DreamTask pattern)

From source: tasks/DreamTask/ — background thinking task.
At session end, the agent runs consolidation:
1. Review what was learned
2. Write new corrections to kb/corrections/log.md
3. Update relevant topic files with successful patterns
4. Update MEMORY.md index if new files were added

This is the self-learning loop. The agent improves across
sessions without retraining. Do not skip this step.

## Injection test question
"What is MEMORY.md for, what is its word limit, and what
triggers a topic file to be loaded from memory?"

Expected: index only, 200 words, on-demand when question
requires that specific topic.