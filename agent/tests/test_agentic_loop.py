"""
Tests for AgenticLoop and LLMClient tool-calling support.

Tests cover:
  - LLMClient.create_with_tools() — both Anthropic and OpenRouter backends (mocked)
  - AgenticLoop.run() — termination paths and tool dispatch
  - OracleForgeAgent agentic mode wiring (agent_mode=True/False)

All LLM calls and MCPToolbox calls are mocked — tests run without external services.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from agent.llm_client import (
    LLMClient,
    LLMToolCall,
    LLMToolCallResponse,
    _convert_messages_to_anthropic,
)
from agent.agentic_loop import AgenticLoop, AgenticResult, build_schema_context, AGENTIC_TOOLS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tool_call(name: str, input_: dict, id_: str = "tc_001") -> LLMToolCall:
    return LLMToolCall(id=id_, name=name, input=input_)


def _make_tool_response(
    tool_calls: list | None = None,
    text: str = "",
    stop_reason: str = "tool_use",
) -> LLMToolCallResponse:
    return LLMToolCallResponse(
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,
        text=text,
    )


def _make_toolbox(success: bool = True, data: Any = [{"count": 42}]) -> MagicMock:
    toolbox = MagicMock()
    result = MagicMock()
    result.success = success
    result.data = data
    result.error = None if success else "mock error"
    toolbox.call_tool.return_value = result
    return toolbox


# ── LLMToolCall / LLMToolCallResponse ────────────────────────────────────────

class TestLLMToolCallDataclass:
    def test_has_id_name_input(self):
        tc = LLMToolCall(id="abc", name="query_db", input={"database": "pg", "query": "SELECT 1", "query_type": "sql"})
        assert tc.id == "abc"
        assert tc.name == "query_db"
        assert tc.input["database"] == "pg"

    def test_repr(self):
        tc = LLMToolCall(id="x", name="list_db", input={})
        assert "list_db" in repr(tc)


class TestLLMToolCallResponse:
    def test_has_tool_calls_true(self):
        resp = _make_tool_response([_make_tool_call("query_db", {})])
        assert resp.has_tool_calls is True

    def test_has_tool_calls_false_when_empty(self):
        resp = _make_tool_response([])
        assert resp.has_tool_calls is False

    def test_text_only_response(self):
        resp = _make_tool_response(text="42", stop_reason="end_turn")
        assert resp.text == "42"
        assert not resp.has_tool_calls


# ── _convert_messages_to_anthropic ────────────────────────────────────────────

class TestConvertMessagesToAnthropic:
    def test_user_message_passes_through(self):
        msgs = [{"role": "user", "content": "Hello"}]
        result = _convert_messages_to_anthropic(msgs)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_tool_message_converted_to_tool_result(self):
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc1", "function": {"name": "query_db", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "tc1", "name": "query_db", "content": "result"},
        ]
        result = _convert_messages_to_anthropic(msgs)
        # Last message should be user role with tool_result content block
        last = result[-1]
        assert last["role"] == "user"
        assert isinstance(last["content"], list)
        assert last["content"][0]["type"] == "tool_result"
        assert last["content"][0]["tool_use_id"] == "tc1"

    def test_assistant_tool_calls_converted_to_tool_use_blocks(self):
        msgs = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "thinking",
                "tool_calls": [
                    {"id": "tc2", "function": {"name": "list_db", "arguments": '{"database": "pg"}'}}
                ],
            },
        ]
        result = _convert_messages_to_anthropic(msgs)
        asst = result[-1]
        assert asst["role"] == "assistant"
        content = asst["content"]
        # Should have text block + tool_use block
        types = [b["type"] for b in content]
        assert "tool_use" in types
        tool_use = next(b for b in content if b["type"] == "tool_use")
        assert tool_use["name"] == "list_db"
        assert tool_use["input"] == {"database": "pg"}


# ── LLMClient.create_with_tools — OpenRouter backend ─────────────────────────

class TestLLMClientCreateWithToolsOpenRouter:
    """Tests the OpenRouter code path with a mocked HTTP session."""

    def _make_client(self) -> LLMClient:
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key", "ANTHROPIC_API_KEY": ""}):
            client = LLMClient.__new__(LLMClient)
            client._backend = "openrouter"
            client._openrouter_api_key = "test-key"
            client._openrouter_url = "https://openrouter.ai/api/v1"
            client._openrouter_model = "test-model"
            client._session = MagicMock()
        return client

    def _mock_response(self, client: LLMClient, payload: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status.return_value = None
        client._session.post.return_value = mock_resp

    def test_returns_tool_call_when_llm_emits_tool(self):
        client = self._make_client()
        self._mock_response(client, {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {"name": "query_db", "arguments": '{"database": "pg", "query": "SELECT 1", "query_type": "sql"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        })
        resp = client.create_with_tools(
            messages=[{"role": "user", "content": "q"}],
            tools=AGENTIC_TOOLS,
        )
        assert resp.has_tool_calls
        assert resp.tool_calls[0].name == "query_db"
        assert resp.tool_calls[0].input["database"] == "pg"
        assert resp.stop_reason == "tool_calls"

    def test_returns_text_when_no_tool_calls(self):
        client = self._make_client()
        self._mock_response(client, {
            "choices": [{
                "message": {"content": "The answer is 42", "tool_calls": []},
                "finish_reason": "stop",
            }]
        })
        resp = client.create_with_tools(
            messages=[{"role": "user", "content": "q"}],
            tools=AGENTIC_TOOLS,
        )
        assert not resp.has_tool_calls
        assert resp.text == "The answer is 42"
        assert resp.stop_reason == "stop"

    def test_sends_tools_in_payload(self):
        client = self._make_client()
        self._mock_response(client, {
            "choices": [{"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}]
        })
        client.create_with_tools(
            messages=[{"role": "user", "content": "test"}],
            tools=AGENTIC_TOOLS,
        )
        call_kwargs = client._session.post.call_args
        sent_payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert "tools" in sent_payload
        tool_names = [t["function"]["name"] for t in sent_payload["tools"]]
        assert "query_db" in tool_names
        assert "list_db" in tool_names
        assert "return_answer" in tool_names

    def test_system_prompt_injected(self):
        client = self._make_client()
        self._mock_response(client, {
            "choices": [{"message": {"content": "", "tool_calls": []}, "finish_reason": "stop"}]
        })
        client.create_with_tools(
            messages=[{"role": "user", "content": "q"}],
            tools=AGENTIC_TOOLS,
            system="You are a data agent.",
        )
        sent_payload = client._session.post.call_args[1]["json"]
        assert sent_payload["messages"][0]["role"] == "system"
        assert "data agent" in sent_payload["messages"][0]["content"]

    def test_raises_on_empty_choices(self):
        client = self._make_client()
        self._mock_response(client, {"choices": []})
        with pytest.raises(RuntimeError, match="no choices"):
            client.create_with_tools(
                messages=[{"role": "user", "content": "q"}],
                tools=AGENTIC_TOOLS,
            )


# ── AgenticLoop.run() ─────────────────────────────────────────────────────────

def _make_loop(
    client_responses: List[LLMToolCallResponse],
    toolbox: MagicMock | None = None,
    db_configs: dict | None = None,
) -> AgenticLoop:
    """Build an AgenticLoop with a mocked LLMClient that returns responses in order."""
    client = MagicMock(spec=LLMClient)
    client.create_with_tools.side_effect = client_responses

    loop = AgenticLoop(
        toolbox=toolbox or _make_toolbox(),
        db_configs=db_configs or {"testdb": {"type": "sqlite", "mcp_tool": "sqlite_query"}},
        client=client,
        schema_context="Table: reviews (id, rating)",
        max_iterations=5,
    )
    return loop


class TestAgenticLoopRun:
    def test_return_answer_terminates_immediately(self):
        """LLM calls return_answer on the first iteration."""
        loop = _make_loop([
            _make_tool_response(
                [_make_tool_call("return_answer", {"answer": "42"})],
                stop_reason="tool_use",
            )
        ])
        result = loop.run("How many rows?", ["testdb"])

        assert result.answer == "42"
        assert result.terminate_reason == "return_answer"
        assert result.iterations == 1

    def test_no_tool_call_fallback_uses_text_as_answer(self):
        """LLM returns plain text without a tool call — treated as final answer."""
        loop = _make_loop([
            _make_tool_response([], text="The answer is 7", stop_reason="end_turn")
        ])
        result = loop.run("What is 3+4?", ["testdb"])

        assert result.answer == "The answer is 7"
        assert result.terminate_reason == "no_tool_call"

    def test_query_db_then_return_answer(self):
        """LLM queries DB, gets result, then answers. Toolbox called once."""
        toolbox = _make_toolbox(success=True, data=[{"count": 5}])
        loop = _make_loop(
            [
                _make_tool_response(
                    [_make_tool_call("query_db", {"database": "testdb", "query": "SELECT COUNT(*) FROM t", "query_type": "sql"}, "tc1")],
                    stop_reason="tool_use",
                ),
                _make_tool_response(
                    [_make_tool_call("return_answer", {"answer": "5"}, "tc2")],
                    stop_reason="tool_use",
                ),
            ],
            toolbox=toolbox,
        )
        result = loop.run("How many rows?", ["testdb"])

        assert result.answer == "5"
        assert result.terminate_reason == "return_answer"
        assert result.iterations == 2
        toolbox.call_tool.assert_called_once()

    def test_list_db_tool_dispatches_correctly(self):
        """LLM calls list_db — triggers _tool_list_db() path."""
        toolbox = _make_toolbox(success=True, data=[{"table": "reviews"}])
        # Override db_configs to have postgres type (has a list tool)
        db_configs = {"pgdb": {"type": "postgres"}}
        loop = _make_loop(
            [
                _make_tool_response(
                    [_make_tool_call("list_db", {"database": "pgdb"}, "tc3")],
                    stop_reason="tool_use",
                ),
                _make_tool_response(
                    [_make_tool_call("return_answer", {"answer": "reviews"}, "tc4")],
                    stop_reason="tool_use",
                ),
            ],
            toolbox=toolbox,
            db_configs=db_configs,
        )
        result = loop.run("What tables exist?", ["pgdb"])

        assert result.answer == "reviews"
        assert result.iterations == 2
        # list_tables tool should have been called
        toolbox.call_tool.assert_called()

    def test_max_iterations_terminates_without_answer(self):
        """LLM never calls return_answer — loop terminates at max_iterations."""
        # Always return a query_db call (no return_answer)
        repeating_response = _make_tool_response(
            [_make_tool_call("query_db", {"database": "testdb", "query": "SELECT 1", "query_type": "sql"})],
            stop_reason="tool_use",
        )
        loop = _make_loop([repeating_response] * 10)
        loop.max_iterations = 3

        result = loop.run("What is the answer?", ["testdb"])

        assert result.terminate_reason == "max_iterations"
        assert result.iterations == 3
        assert result.answer == ""

    def test_unknown_tool_does_not_crash(self):
        """LLM calls a nonexistent tool — loop gets error message and continues."""
        loop = _make_loop([
            _make_tool_response(
                [_make_tool_call("magic_tool", {"x": 1}, "tc5")],
                stop_reason="tool_use",
            ),
            _make_tool_response(
                [_make_tool_call("return_answer", {"answer": "fallback"}, "tc6")],
                stop_reason="tool_use",
            ),
        ])
        result = loop.run("?", ["testdb"])

        assert result.answer == "fallback"
        # The unknown tool step should be in the trace
        tool_names = [step["tool"] for step in result.trace]
        assert "magic_tool" in tool_names

    def test_query_db_tool_failure_included_in_trace(self):
        """When query fails, the error is included in the trace."""
        toolbox = _make_toolbox(success=False, data=None)
        toolbox.call_tool.return_value.error = "syntax error near SELECT"
        loop = _make_loop(
            [
                _make_tool_response(
                    [_make_tool_call("query_db", {"database": "testdb", "query": "BAD SQL", "query_type": "sql"})],
                    stop_reason="tool_use",
                ),
                _make_tool_response(
                    [_make_tool_call("return_answer", {"answer": "unknown"})],
                    stop_reason="tool_use",
                ),
            ],
            toolbox=toolbox,
        )
        result = loop.run("q", ["testdb"])

        assert result.answer == "unknown"
        assert result.iterations == 2
        # First trace step should have success=False
        first_step = result.trace[0]
        assert first_step["success"] is False

    def test_database_not_in_available_returns_error(self):
        """query_db with a database not in available_databases gets error message."""
        loop = _make_loop(
            [
                _make_tool_response(
                    [_make_tool_call("query_db", {"database": "secret_db", "query": "SELECT 1", "query_type": "sql"})],
                    stop_reason="tool_use",
                ),
                _make_tool_response(
                    [_make_tool_call("return_answer", {"answer": "n/a"})],
                    stop_reason="tool_use",
                ),
            ]
        )
        result = loop.run("q", ["testdb"])

        # First trace step should be the failed query_db
        first_step = result.trace[0]
        assert first_step["tool"] == "query_db"
        assert first_step["success"] is False
        assert "not in the available databases" in first_step["output"]

    def test_trace_contains_one_entry_per_tool_call(self):
        """Each tool call in the loop creates one trace entry."""
        loop = _make_loop([
            _make_tool_response(
                [
                    _make_tool_call("query_db", {"database": "testdb", "query": "SELECT 1", "query_type": "sql"}, "a"),
                    _make_tool_call("return_answer", {"answer": "1"}, "b"),
                ],
                stop_reason="tool_use",
            ),
        ])
        result = loop.run("q", ["testdb"])
        assert len(result.trace) == 2


# ── build_schema_context ──────────────────────────────────────────────────────

class TestBuildSchemaContext:
    def test_empty_schema_returns_empty_string(self):
        assert build_schema_context({}) == ""

    def test_single_db_with_tables(self):
        schema = {
            "bookreview": MagicMock(db_type="sqlite", tables={"reviews": ["id", "rating", "text"]})
        }
        ctx = build_schema_context(schema)
        assert "bookreview" in ctx
        assert "reviews" in ctx
        assert "id" in ctx

    def test_multiple_databases(self):
        schema = {
            "db1": MagicMock(db_type="postgres", tables={"orders": ["id", "amount"]}),
            "db2": MagicMock(db_type="sqlite", tables={"products": ["id", "name"]}),
        }
        ctx = build_schema_context(schema)
        assert "db1" in ctx
        assert "db2" in ctx
        assert "orders" in ctx
        assert "products" in ctx


# ── OracleForgeAgent agentic mode wiring ──────────────────────────────────────

class TestOracleForgeAgentAgenticMode:
    """Verify that agent_mode=True/False routes correctly."""

    def _build_agent(self, agent_mode: bool):
        from agent.oracle_forge_agent import OracleForgeAgent

        mock_client = MagicMock()
        mock_ctx = MagicMock()
        from agent.models import ContextBundle, SchemaInfo
        mock_ctx.get_bundle.return_value = ContextBundle(
            schema={"pg": SchemaInfo(database="pg", db_type="postgres", tables={})},
            institutional_knowledge=[],
            corrections=[],
        )
        mock_ctx.get_similar_corrections.return_value = []
        mock_ctx.get_docs_for_question.return_value = []

        mock_router = MagicMock()
        from agent.models import QueryPlan, SubQuery
        mock_router.route.return_value = QueryPlan(
            sub_queries=[SubQuery(database="pg", query="SELECT 1", query_type="sql")],
            execution_order=[0],
            join_operations=[],
        )

        mock_scl = MagicMock()
        from agent.models import QueryResult
        mock_scl.execute_with_correction.return_value = {
            "success": True,
            "results": [QueryResult(database="pg", data=[[42]], success=True, rows_affected=1)],
            "correction_applied": False,
            "retries_used": 0,
        }

        mock_agentic = MagicMock(return_value=MagicMock(
            answer="99",
            terminate_reason="return_answer",
            iterations=2,
            trace=[],
        ))

        with (
            patch("agent.oracle_forge_agent.LLMClient", return_value=mock_client),
            patch("agent.oracle_forge_agent.ContextManager", return_value=mock_ctx),
            patch("agent.oracle_forge_agent.QueryRouter", return_value=mock_router),
            patch("agent.oracle_forge_agent.ExecutionEngine", return_value=MagicMock()),
            patch("agent.oracle_forge_agent.SelfCorrectionLoop", return_value=mock_scl),
        ):
            agent = OracleForgeAgent(
                db_configs={"pg": {"type": "postgres"}},
                agent_mode=agent_mode,
            )

        agent._client = mock_client
        agent._ctx_manager = mock_ctx
        agent._router = mock_router
        agent._correction_loop = mock_scl

        return agent, mock_router, mock_scl

    def test_agentic_mode_true_does_not_call_query_router(self):
        """With agent_mode=True, QueryRouter.route() should NOT be called."""
        agent, mock_router, _ = self._build_agent(agent_mode=True)

        # Patch _agentic_fallback to avoid needing real toolbox
        with patch.object(agent, "_agentic_fallback", return_value={
            "answer": "99",
            "query_trace": [],
            "confidence": 0.85,
            "tool_call_ids": [],
            "correction_applied": False,
            "terminate_reason": "return_answer",
            "iterations": 1,
        }) as mock_fallback:
            agent.answer({"question": "q", "available_databases": ["pg"], "schema_info": {}})

        mock_router.route.assert_not_called()
        mock_fallback.assert_called_once()

    def test_agentic_mode_false_uses_query_router(self):
        """With agent_mode=False, QueryRouter.route() SHOULD be called."""
        agent, mock_router, mock_scl = self._build_agent(agent_mode=False)

        mock_client = agent._client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="42")]
        )

        agent.answer({"question": "q", "available_databases": ["pg"], "schema_info": {}})
        mock_router.route.assert_called_once()

    def test_agent_mode_default_is_true(self):
        """agent_mode defaults to True when not specified (respects AGENT_MODE=true)."""
        with patch.dict("os.environ", {"AGENT_MODE": "true"}):
            from agent.oracle_forge_agent import OracleForgeAgent
            with (
                patch("agent.oracle_forge_agent.LLMClient"),
                patch("agent.oracle_forge_agent.ContextManager"),
                patch("agent.oracle_forge_agent.QueryRouter"),
                patch("agent.oracle_forge_agent.ExecutionEngine"),
                patch("agent.oracle_forge_agent.SelfCorrectionLoop"),
                patch("agent.oracle_forge_agent.AgenticLoop"),
                patch("agent.oracle_forge_agent.MCPToolbox"),
            ):
                agent = OracleForgeAgent(db_configs={"pg": {"type": "postgres"}})
        assert agent._agent_mode is True

    def test_agent_mode_env_false_overrides_default(self):
        """AGENT_MODE=false env var disables agentic mode."""
        with patch.dict("os.environ", {"AGENT_MODE": "false"}):
            from agent.oracle_forge_agent import OracleForgeAgent
            with (
                patch("agent.oracle_forge_agent.LLMClient"),
                patch("agent.oracle_forge_agent.ContextManager"),
                patch("agent.oracle_forge_agent.QueryRouter"),
                patch("agent.oracle_forge_agent.ExecutionEngine"),
                patch("agent.oracle_forge_agent.SelfCorrectionLoop"),
                patch("agent.oracle_forge_agent.AgenticLoop"),
                patch("agent.oracle_forge_agent.MCPToolbox"),
            ):
                agent = OracleForgeAgent(db_configs={"pg": {"type": "postgres"}})
        assert agent._agent_mode is False
