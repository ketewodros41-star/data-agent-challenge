# DAB Benchmark Format

Reference for the DataAgentBench (DAB) input/output wire format.

---

## Input Format

```json
{
  "question": "What is the average star rating for businesses in Las Vegas?",
  "available_databases": ["postgres", "mongodb"],
  "schema_info": {
    "postgres": { "tables": { "businesses": ["business_id", "city", "stars"] } },
    "mongodb":  { "collections": { "reviews": ["business_id", "stars", "text"] } }
  }
}
```

- `question`: Natural language business question
- `available_databases`: List of database IDs the agent may use
- `schema_info`: Optional partial schema hint (do not rely on this exclusively — use live introspection)

---

## Output Format

```json
{
  "answer": 3.7,
  "query_trace": [
    {
      "step": 1,
      "db": "postgres",
      "query": "SELECT AVG(stars) FROM businesses WHERE city = 'Las Vegas'",
      "result": "3.7",
      "error": null,
      "correction_applied": false
    }
  ],
  "confidence": 0.92
}
```

- `answer`: The final answer value (number, string, list, or object)
- `query_trace`: Ordered list of steps taken (required for Pass@1 evaluation)
- `confidence`: Float 0.0–1.0 indicating agent certainty

---

## Answer Types

| Question pattern | Expected answer type |
|---|---|
| "What is the average..." | float |
| "How many..." | int |
| "Which businesses..." | list of strings |
| "What percentage..." | float (0–100) |
| "Is/Does..." | bool or "yes"/"no" |
| "List the top N..." | list of objects |
