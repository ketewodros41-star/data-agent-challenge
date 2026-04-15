import json

from eval.harness import EvaluationHarness


class StubAgent:
    def __init__(self, responses):
        self.responses = list(responses)

    def process_query(self, question, available_databases, schema_info):
        return self.responses.pop(0)


def build_harness(tmp_path):
    eval_dir = tmp_path / "eval"
    return EvaluationHarness(
        eval_dir=eval_dir,
        score_log_path=eval_dir / "score_log.json",
        trace_log_path=eval_dir / "trace_log.jsonl",
    )


def test_trace_tool_call_and_record_query_append_jsonl(tmp_path):
    harness = build_harness(tmp_path)
    session = harness.start_session()

    tool_call_id = harness.trace_tool_call(
        session_id=session,
        tool_name="run_query",
        parameters={"query": "select 1"},
        result={"rows": 1},
        execution_time=0.123,
    )
    query_event = harness.record_query_outcome(
        session_id=session,
        query="How many rows?",
        answer="1",
        expected="1",
        tool_call_ids=[tool_call_id],
        available_databases=["postgres"],
        execution_time=0.125,
    )

    parsed = harness.parse_trace_log()

    assert len(parsed) == 2
    assert parsed[0]["tool_name"] == "run_query"
    assert parsed[1]["query_text"] == "How many rows?"
    assert query_event.correct is True


def test_calculate_pass_at_1_excludes_corrected_queries(tmp_path):
    harness = build_harness(tmp_path)
    session = harness.start_session()

    harness.record_query_outcome(session, "q1", "ok", "ok", [], correction_applied=False)
    harness.record_query_outcome(session, "q2", "ok", "ok", [], correction_applied=True)
    harness.record_query_outcome(session, "q3", "bad", "ok", [], correction_applied=False)

    assert harness.calculate_pass_at_1() == 33.33


def test_log_score_and_progression_round_trip(tmp_path):
    harness = build_harness(tmp_path)

    entry = harness.log_score(
        pass_at_1=50.0,
        total_queries=2,
        correct=1,
        corrections=1,
        avg_time=0.4,
        changes="baseline",
    )
    progression = harness.get_score_progression()

    assert entry.pass_at_1_score == 50.0
    assert progression[0]["changes_since_last_run"] == "baseline"


def test_run_benchmark_records_results_and_score(tmp_path):
    harness = build_harness(tmp_path)
    agent = StubAgent(
        [
            {"answer": "10", "tool_call_ids": ["a"], "confidence": 0.9, "correction_applied": False},
            {"answer": "oops", "tool_call_ids": ["b"], "confidence": 0.7, "correction_applied": True},
        ]
    )
    queries = [
        {"question": "How many books?", "expected_answer": "10"},
        {"question": "How many authors?", "expected_answer": "12"},
    ]

    result = harness.run_benchmark(agent, queries, n_trials=1, changes_description="first pass")

    score_log = json.loads(harness.score_log_path.read_text(encoding="utf-8"))
    assert result["pass_at_1"] == 50.0
    assert result["total_queries"] == 2
    assert score_log[0]["corrections_applied"] == 1


def test_run_regression_suite_detects_regressions_and_improvements(tmp_path):
    harness = build_harness(tmp_path)
    agent = StubAgent(
        [
            {"answer": "wrong"},
            {"answer": "fixed"},
        ]
    )
    test_set = [
        {"id": "q1", "question": "old good", "expected_answer": "right"},
        {"id": "q2", "question": "old bad", "expected_answer": "fixed"},
    ]
    baseline = {"q1": True, "q2": False}

    result = harness.run_regression_suite(agent, test_set, baseline)

    assert result.regressions == ["q1"]
    assert result.improvements == ["q2"]


def test_export_dab_results_writes_submission_file(tmp_path):
    harness = build_harness(tmp_path)
    session = harness.start_session()
    harness.record_query_outcome(session, "Question A", "one", "one", ["tool-1"], execution_time=0.1)

    output_path = tmp_path / "dab_results.json"
    harness.export_dab_results(str(output_path), team_name="Team PaLM")
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["team_name"] == "Team PaLM"
    assert payload["pass_at_1"] == 100.0
    assert payload["results"][0]["trials"][0]["tool_calls"] == 1
