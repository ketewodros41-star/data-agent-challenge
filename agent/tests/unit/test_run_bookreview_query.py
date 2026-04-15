import json

from scripts.run_bookreview_query import export_eval_bundle


def test_export_eval_bundle_writes_dab_style_layout(tmp_path):
    dataset_dir = tmp_path / "query_bookreview"
    result = {
        "answer": "title, author",
        "confidence": 0.9,
        "query_trace": [{"step": 1, "db": "books_database"}],
    }
    db_configs = {
        "books_database": {
            "type": "postgres",
            "connection_string": "postgresql://example",
        }
    }
    trace_events = [{"session_id": "abc123", "tool_name": "run_query"}]

    query_dir = export_eval_bundle(
        dataset_dir=dataset_dir,
        question="what columns does the books_info table have",
        result=result,
        db_configs=db_configs,
        trace_events=trace_events,
    )

    assert query_dir.name == "query1"
    assert (dataset_dir / "query_dataset").is_dir()
    assert (dataset_dir / "db_config.yaml").exists()
    assert json.loads((query_dir / "query.json").read_text(encoding="utf-8")) == (
        "what columns does the books_info table have"
    )
    assert (query_dir / "ground_truth.csv").exists()
    assert (query_dir / "validate.py").exists()
    run_result = json.loads((query_dir / "run_result.json").read_text(encoding="utf-8"))
    assert run_result["result"]["answer"] == "title, author"
    assert run_result["trace_events"][0]["tool_name"] == "run_query"
