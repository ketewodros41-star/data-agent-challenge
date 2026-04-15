# Scoring Method — DAB Pass@1

The DataAgentBench benchmark uses **Pass@1** as the primary metric:
the agent gets one attempt per question and scores 1 if the answer matches, 0 otherwise.

---

## Pass@1 Definition

```
Pass@1 = (number of correct answers) / (total questions)
```

A correct answer must match the expected answer within the following tolerance:

| Answer type | Match rule |
|---|---|
| Float / int | Within ±5% relative error, or ±0.01 absolute |
| String | Exact string match (case-insensitive, trimmed) |
| List | Same elements (order-insensitive) |
| Boolean | Exact match |

---

## Score Log Format (`eval/score_log.jsonl`)

Each line is one JSONL record:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-04-13T10:00:00",
  "session_id": "uuid",
  "query_text": "What is the avg rating for businesses in Las Vegas?",
  "available_databases": ["postgres", "mongodb"],
  "tool_calls": ["postgres"],
  "answer": 3.7,
  "expected_answer": 3.68,
  "correct": true,
  "confidence": 0.92,
  "correction_applied": false,
  "error": null
}
```

---

## Improvement Checkpoints

1. **Baseline**: First run with no corrections — establishes floor score.
2. **Post-KB**: After adding domain knowledge to kb/domain/ — should improve on routing/join errors.
3. **Post-corrections**: After at least one correction loop cycle — `correction_applied: true` entries should score higher than uncorrected equivalents.

The evaluator expects at least two checkpoint scores in `eval/score_log.jsonl`.
