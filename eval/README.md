# Evaluation Harness

This directory contains the complete evaluation system for measuring agent performance against the Data Agent Benchmark (DAB).

## Files Overview

### Core Evaluation System
- **`run_evaluation.py`** - Main evaluation script that scores agent performance
- **`score_log.json`** - Historical scores with timestamps and methodology notes
- **`trace_log.jsonl`** - Detailed execution traces for each query

## How Evaluation Works

### 1. Run Agent
First, run the agent on queries:
```bash
uv run python run_agent.py \
  --dataset bookreview \
  --query query_bookreview_benchmark/query1/query.json \
  --iterations 10 \
  --root_name run_0
```

### 2. Score Results
Then evaluate the performance:
```bash
uv run python eval/run_evaluation.py \
  --dataset bookreview \
  --run run_0 \
  --note "baseline_run"
```

### 3. View Progression
Track improvement over time:
```bash
uv run python eval/run_evaluation.py --progress
```

## Evaluation Criteria

The evaluation system measures:

### Pass@1 Score
- **Definition**: % of queries correct on first attempt (run_0)
- **Formula**: (correct on run_0) / (total queries) × 100
- **Importance**: This is the leaderboard score

### Automatic Fail Conditions
Queries automatically fail if:
- `terminate_reason == "no_tool_call"` - Agent never used any database tool
- `terminate_reason == "max_iterations"` - Agent ran out of thinking budget
- `final_result` is empty or None

### Validation Methods
- **Ground truth comparison**: Substring matching against expected answers
- **Schema validation**: Ensuring agent uses correct database structures
- **Tool usage validation**: Checking appropriate tool calls

## Score Log Format

Each entry in `score_log.json` contains:
```json
{
  "timestamp": "2026-04-18T16:08:36.767310+00:00",
  "dataset": "bookreview",
  "run": "run_0", 
  "pass_at_1": 100.0,
  "passed": 3,
  "total": 3,
  "note": "baseline_run",
  "per_query": [
    {
      "query_id": "bookreview/query1",
      "passed": true,
      "tool_call_trace": [...],
      "agent_answer": "2020s",
      "ground_truth": "2020s",
      "iterations_used": 4
    }
  ]
}
```

## Usage Examples

### Score Single Dataset
```bash
uv run python eval/run_evaluation.py --dataset bookreview --run run_0 --note "after_fix"
```

### Score All Datasets
```bash
uv run python eval/run_evaluation.py --all --note "final_submission"
```

### Show Progression
```bash
uv run python eval/run_evaluation.py --progress
uv run python eval/run_evaluation.py --progress --dataset bookreview
```

## Directory Structure for Evaluation

The evaluation system expects this structure:
```
results/
|-- query_bookreview/
|   |-- query1/
|   |   |-- query.json           # The question
|   |   |-- ground_truth.csv     # Expected answer
|   |   |-- validate.py          # Validation function
|   |   `-- logs/data_agent/
|   |       `-- run_0/
|   |           |-- final_agent.json    # Agent result
|   |           |-- llm_calls.jsonl     # LLM API calls
|   |           `-- tool_calls.jsonl    # Database queries
```

## Adding New Evaluation Queries

1. **Create query directory** under `results/query_<dataset>/query<N>/`
2. **Add query.json** with the natural language question
3. **Add ground_truth.csv** with expected answer
4. **Add validate.py** with validation logic (can use template)
5. **Run agent** to generate results
6. **Score results** to measure performance

## Validation Functions

Each query has a `validate.py` that implements:
```python
def validate(llm_answer: str) -> tuple[bool, str]:
    """Return (is_correct, reason)"""
    ground_truth = "expected_answer"
    if ground_truth.lower() in llm_answer.lower():
        return True, "Answer contains ground truth"
    else:
        return False, f"Expected '{ground_truth}', got '{llm_answer}'"
```

## Best Practices

- **Always add methodology notes** to score entries for reproducibility
- **Use consistent naming** for runs (run_0, run_1, etc.)
- **Check trace logs** for debugging failed queries
- **Keep ground truth current** when datasets change
- **Document changes** in the note field for improvement tracking

## Troubleshooting

### "run_not_found" Error
- Check that agent run completed successfully
- Verify directory structure matches expected pattern
- Ensure `final_agent.json` exists in the run directory

### "validate_missing" Error
- Add `validate.py` to the query directory
- Use existing validate.py as template
- Test validation function manually

### Empty Scores
- Check that ground truth files have content
- Verify validation functions are working
- Ensure agent actually answered the question
