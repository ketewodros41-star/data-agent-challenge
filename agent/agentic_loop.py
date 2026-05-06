"""
AgenticLoop — DAB-runner-style "LLM-decides-every-iteration" execution loop.

Architecture:
  The LLM receives 3 LLM-facing tool definitions (query_db, list_db, return_answer).
  These are NOT direct DB connections — all data access goes through MCPToolbox,
  which is an HTTP client to the running MCP server. The loop:

    1. Sends the full conversation (question + all prior tool calls + results) to the LLM
    2. LLM responds with a tool call or plain text (final answer)
    3. Tool call dispatches to MCPToolbox → result appended as tool message
    4. Loop continues until return_answer is called, text-only response, or max_iterations

  This mirrors DataAgent.run() from dab-runner but uses LLMClient.create_with_tools()
  and MCPToolbox instead of the openai client + direct DB drivers.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.llm_client import LLMClient, LLMToolCall, LLMToolCallResponse
from agent.sandbox_client import SandboxClient
from agent.types import SandboxExecutionRequest
from agent.loop_detector import LoopDetector
from agent.planner_fallback import PlannerFallback

TOOL_LOG_MAX_PREVIEW = 10_000  # matches DAB BaseTool.exec truncation

DEFAULT_MAX_TOKENS = 16384
LENGTH_RETRY_MAX_TOKENS = 32768  # one-shot bump when backend returns stop_reason=length


# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class AgenticResult:
    """
    Result from AgenticLoop.run().

    Attributes:
        answer: The final answer string (empty string if loop exhausted without answer).
        terminate_reason: Why the loop stopped:
            "return_answer" — LLM called return_answer tool
            "no_tool_call"  — LLM returned text without any tool call (fallback)
            "max_iterations" — loop hit the iteration cap without an answer
        iterations: Number of LLM calls made.
        trace: List of step dicts, one per tool call:
               {"iteration": int, "tool": str, "input": dict, "output": str, "success": bool}
        messages: Full conversation history (for debug / Layer 3 logging).
    """
    answer: str
    terminate_reason: str
    iterations: int
    total_usage: Dict[str, Any] = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "cost": 0.0,
    })
    trace: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)


# ── Tool definitions sent to the LLM ──────────────────────────────────────────

# These are LLM-facing abstractions. The LLM calls them; the _execute_tool()
# method maps them to MCPToolbox.call_tool() calls (MCP-only, no direct DB).

AGENTIC_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "query_db",
        "description": (
            "Execute a SQL or MongoDB query against a named database. "
            "Returns the query results as JSON rows. "
            "IMPORTANT: MongoDB queries also support aggregation pipelines (list of stages). "
            "The environment 'env' is a dictionary: { 'data_1': [ {col: val, ...}, ... ], ... }. "
            "- IMPORTANT: DATA TENACITY. If your analytics result in very few matches (e.g., zero or only a handful of rows), do NOT give up. Instead: "
            "1. Print the length of the input dataframes: `print(len(env['data_1']))`. "
            "2. Check for parsing errors in your logic (e.g., regex mismatches in unstructured fields). "
            "3. Try alternative extraction patterns. "
            "4. Only return 'Unable to determine answer' if you have confirmed the database actually contains no matching records after multiple checks. "
            "- ABSOLUTELY NEVER return an answer as plain text if you are still missing data or encounter errors. Use another `query_db` or `execute_python` step to debug and fix. "
            "The result is saved to env['data_N'] where N is unique per query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "The database identifier (e.g. 'bookreview', 'yelp', 'stockmarket').",
                },
                "query": {
                    "type": "string",
                    "description": "SQL query (for SQL databases) or MongoDB filter JSON (for Yelp/MongoDB).",
                },
                "query_type": {
                    "type": "string",
                    "enum": ["sql", "mongo"],
                    "description": "Type of query: 'sql' for SQL databases, 'mongo' for MongoDB/Yelp.",
                },
            },
            "required": ["database", "query", "query_type"],
        },
    },
    {
        "name": "list_db",
        "description": (
            "List the tables (and their columns) available in a database. "
            "Use this to discover the schema when you are unsure of table or column names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "The database identifier to introspect.",
                },
            },
            "required": ["database"],
        },
    },
    {
        "name": "execute_python",
        "description": (
            "Execute a Python script to process data (join, filter, aggregate). "
            "A dictionary named 'env' is pre-loaded with results of ALL previous queries. "
            "Example: env['data_1'], env['data_2']. "
            "YOU MUST ALWAYS use print() for summaries or final results (e.g. print(df.groupby('decade').size())). "
            "Avoid printing thousands of raw rows; use head() or value_counts() to keep context clean. "
            "Available libs: pandas, numpy, rapidfuzz, re, json, math."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute. You can import pandas, json, math, pyarrow, etc. Read data from 'env', merge it, and print() the answer.",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "return_answer",
        "description": (
            "Return the final answer to the user's question. "
            "Call this ONLY when you are confident in the answer. "
            "The answer should be a concise value: a number, string, or list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The final answer to return.",
                },
            },
            "required": ["answer"],
        },
    },
]


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_BASE = """You are a data analysis agent with access to databases through tools.

Your job is to answer the user's question by:
1. Using list_db to discover available tables and columns if you're unsure of the schema
2. Using query_db to execute SQL or MongoDB queries against the databases
3. Analyzing the results and calling return_answer with the final answer

Data Tenacity & Verification:
- If your analytics result in very few matches (e.g., zero or only a handful of rows for a large dataset), do NOT give up. 
- You MUST print the length of your environment variables: `print(len(env['data_1']))` to confirm data volume.
- If data volume is significant but matches are few, check for parsing errors (e.g., regex mismatches in unstructured fields) and try alternative extraction patterns.
- ONLY return 'Unable to determine answer' if you have confirmed the database actually contains no matching records after multiple verification steps.
- ABSOLUTELY NEVER return an answer as plain text if you are still missing data or encounter processing errors. Use another `execute_python` step to debug and fix.

Rules:
- Read the "Domain Knowledge" section carefully. It contains required CROSS-DATABASE JOIN KEY mappings.
- Always explore the schema (list_db) before querying if table/column names are unclear.
- Write precise SQL/Mongo queries to fetch the data.
- If you need to join data across TWO DIFFERENT DATABASES, you MUST query each database separately, then use the `execute_python` tool to merge the data using pandas. SQL cannot cross database boundaries here.
- DO NOT SELECT * for large tables. Push filters down to SQL.
- If a query returns an error, fix it and try again.
- IMPORTANT: Data returned by `query_db` is ALREADY a Python list/dict whenever possible. DO NOT use `json.loads()` on variables from the `env` dictionary unless the preview specifically shows a raw escaped JSON string.
- For MongoDB/Yelp databases use query_type="mongo" with a JSON filter object.
- For all other databases use query_type="sql" with standard SQL.
- CRITICAL: Before returning "No decade meets the criteria" or similar negative answers, you MUST verify the data pipeline:
  * Check raw data counts from both databases
  * Verify join success rates (book_id/purchase_id matching)
  * Confirm publication year extraction worked
  * Show books per decade counts
  * Only return negative answer if debug output clearly supports it
- If schema inspection fails for DuckDB or SQLite, try discovery queries like "SHOW TABLES" or query known tables directly
- If you detect repetitive query patterns, the system will stop you - try a different approach
- When using execute_python, always ensure referenced env keys exist from previous query_db calls
"""


def _build_system_prompt(kb_context: str) -> str:
    """Construct the full system prompt, appending Layer 2 KB docs when available."""
    if not kb_context:
        return _SYSTEM_PROMPT_BASE
    return (
        _SYSTEM_PROMPT_BASE
        + "\n\n--- Domain Knowledge (KB Layer 2) ---\n"
        + kb_context
    )


# ── Agentic loop ───────────────────────────────────────────────────────────────


class AgenticLoop:
    """
    DAB-runner-style agentic execution loop for Oracle Forge.

    The LLM drives all decisions via tool calls. All database access goes through
    MCPToolbox (MCP server HTTP calls) — no direct database connections.

    Usage:
        loop = AgenticLoop(
            toolbox=mcp_toolbox_instance,
            db_configs={"bookreview": {"type": "sqlite", ...}},
            client=llm_client_instance,
            schema_context="Table: reviews (id, rating, text)\\n...",
        )
        result = loop.run("How many 5-star reviews are there?", ["bookreview"])
    """

    def __init__(
        self,
        toolbox: Any,  # MCPToolbox — typed as Any to avoid circular import
        db_configs: Dict[str, dict],
        client: LLMClient,
        schema_context: str = "",
        kb_context: str = "",
        max_iterations: int = 20,
        sandbox_client: Optional[SandboxClient] = None,
        log_dir: Optional[Path] = None,
    ):
        self._toolbox = toolbox
        self._db_configs = db_configs
        self._client = client
        self._schema_context = schema_context
        self._system_prompt = _build_system_prompt(kb_context)
        self.max_iterations = max_iterations
        self._sandbox_client = sandbox_client
        self._query_results: Dict[str, Any] = {}
        self._dataset_counter = 0
        # self._loop_detector = LoopDetector(window_size=10, max_repeats=3)  # Temporarily disabled
        # self._planner_fallback = PlannerFallback(window_size=10, max_repeats=3)  # Temporarily disabled

        # DAB-format JSONL loggers. When log_dir is None, all `_log_*` calls are no-ops.
        self._log_dir = Path(log_dir) if log_dir else None
        self._llm_log_path: Optional[Path] = None
        self._tool_log_path: Optional[Path] = None
        if self._log_dir is not None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._llm_log_path = self._log_dir / "llm_calls.jsonl"
            self._tool_log_path = self._log_dir / "tool_calls.jsonl"

    # ── DAB-format logging helpers (no-op when log_dir is None) ─────────────

    def _log_llm_call(
        self,
        start: float,
        end: float,
        response: Optional[LLMToolCallResponse],
        messages: List[Dict[str, Any]],
    ) -> None:
        if self._llm_log_path is None:
            return
        response_dict: Optional[Dict[str, Any]] = None
        if response is not None:
            response_dict = {
                "text": response.text,
                "stop_reason": response.stop_reason,
                "usage": response.usage,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.input}
                    for tc in response.tool_calls
                ],
            }
        entry = {
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "start_time": start,
            "end_time": end,
            "duration": end - start,
            "model": getattr(self._client, "_openrouter_model", None),
            "response": response_dict,
            "messages": messages,
        }
        with open(self._llm_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def _log_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        success: bool,
        result_payload: Any,
        start_ts: str,
        end_ts: str,
        elapsed: float,
    ) -> None:
        if self._tool_log_path is None:
            return
        serialized = json.dumps(result_payload, default=str)
        preview = serialized[:TOOL_LOG_MAX_PREVIEW]
        entry = {
            "start": start_ts,
            "end": end_ts,
            "time": elapsed,
            "tool_name": tool_name,
            "result": {"success": success, "preview": preview},
            "args": args,
            "val_args": args,
        }
        with open(self._tool_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def run(self, question: str, available_databases: List[str]) -> AgenticResult:
        """
        Run the agentic loop for a single question.

        Args:
            question: Natural language question to answer.
            available_databases: List of db identifiers available for this query.

        Returns:
            AgenticResult with the final answer and execution trace.
        """
        # Build the initial user message (mirrors DataAgent prompt_builder)
        db_list = ", ".join(available_databases)
        schema_block = (
            f"\n\nAvailable schema:\n{self._schema_context}" if self._schema_context else ""
        )
        user_content = (
            f"Question: {question}\n\n"
            f"Available databases: {db_list}"
            f"{schema_block}"
        )

        messages: List[Dict[str, Any]] = [{"role": "user", "content": user_content}]

        final_answer: Optional[str] = None
        terminate_reason = "max_iterations"
        trace: List[Dict[str, Any]] = []
        iteration = 0
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost": 0.0,
        }

        while final_answer is None and iteration < self.max_iterations:
            iteration += 1

            # Call LLM with tool definitions
            llm_start = time.time()
            response: LLMToolCallResponse = self._client.create_with_tools(
                messages=messages,
                tools=AGENTIC_TOOLS,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.0,
                system=self._system_prompt,
            )
            llm_end = time.time()
            self._log_llm_call(llm_start, llm_end, response, messages)

            # If the backend truncated us before any tool call was emitted,
            # retry once with a bigger output budget. Thinking models can burn
            # the whole output cap on reasoning and emit nothing. Retrying with
            # the same messages but a higher max_tokens lets them finish.
            if (
                not response.has_tool_calls
                and str(response.stop_reason).lower() == "length"
            ):
                llm_start = time.time()
                response = self._client.create_with_tools(
                    messages=messages,
                    tools=AGENTIC_TOOLS,
                    max_tokens=LENGTH_RETRY_MAX_TOKENS,
                    temperature=0.0,
                    system=self._system_prompt,
                )
                llm_end = time.time()
                self._log_llm_call(llm_start, llm_end, response, messages)

            # Accumulate usage (cache_read_tokens / cache_creation_tokens are
            # populated by LLMClient when the backend supports prompt caching).
            u = response.usage
            total_usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += u.get("completion_tokens", 0)
            total_usage["total_tokens"] += u.get("total_tokens", 0)
            total_usage["cache_read_tokens"] += u.get("cache_read_tokens", 0)
            total_usage["cache_creation_tokens"] += u.get("cache_creation_tokens", 0)
            total_usage["cost"] += u.get("cost", 0.0)

            if not response.has_tool_calls:
                # Plain text is never accepted as a final answer — the harness
                # only records `return_answer` tool calls. Push back every turn
                # and rely on max_iterations as the safety net.
                loaded_keys = list(self._query_results.keys())
                if loaded_keys:
                    env_hint = (
                        f" You have already loaded data into: {', '.join(loaded_keys)}. "
                        "Use `execute_python` to analyze it, or call `return_answer` "
                        "with the final value if you already have it."
                    )
                else:
                    env_hint = (
                        " Use `query_db` to fetch data, `list_db` to explore schema, "
                        "or `return_answer` if you already have the final value."
                    )

                length_hint = ""
                if str(response.stop_reason).lower() == "length":
                    length_hint = (
                        " Your last response was cut off by the output-token limit "
                        "even after a retry. Respond with a single tool call only — "
                        "no prose, no multi-step reasoning in the reply text. If a "
                        "batch is too large to classify in one turn, slice it in "
                        "Python and process chunks."
                    )

                error_msg = (
                    "Error: every turn must contain a tool call. Plain text is not "
                    "recorded as an answer." + env_hint + length_hint + " If you "
                    "have the final answer, call `return_answer(answer=<value>)` — "
                    "do not write it as narrative text."
                )
                messages.append({"role": "user", "content": error_msg})
                trace.append({
                    "iteration": iteration,
                    "tool": "system_reminder",
                    "input": {},
                    "output": error_msg,
                    "success": False,
                })
                continue

            # Build assistant message with tool calls (OpenAI-style)
            assistant_tool_calls = []
            for tc in response.tool_calls:
                assistant_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input),
                    },
                })
            messages.append({
                "role": "assistant",
                "content": response.text or "",
                "tool_calls": assistant_tool_calls,
            })

            # Execute each tool call and append results
            for tc in response.tool_calls:
                tool_start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                tool_start = time.time()
                result_content, success = self._execute_tool(
                    tc, available_databases, iteration
                )
                tool_end = time.time()
                tool_end_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._log_tool_call(
                    tool_name=tc.name,
                    args=tc.input,
                    success=success,
                    result_payload=result_content,
                    start_ts=tool_start_ts,
                    end_ts=tool_end_ts,
                    elapsed=tool_end - tool_start,
                )

                trace.append({
                    "iteration": iteration,
                    "tool": tc.name,
                    "input": tc.input,
                    "output": result_content[:2000],  # truncate for trace
                    "success": success,
                })

                # Append tool result message
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result_content,
                })

                # Check if return_answer was called
                if tc.name == "return_answer" and success:
                    final_answer = tc.input.get("answer", "")
                    terminate_reason = "return_answer"
                    break

            if final_answer is not None:
                break

        # Ensure we always have a string answer
        if final_answer is None:
            final_answer = ""

        return AgenticResult(
            answer=final_answer,
            terminate_reason=terminate_reason,
            iterations=iteration,
            total_usage=total_usage,
            trace=trace,
            messages=messages,
        )

    # ── Tool execution (MCP-only, no direct DB) ────────────────────────────

    def _execute_tool(
        self,
        tc: LLMToolCall,
        available_databases: List[str],
        iteration: int,
    ) -> tuple[str, bool]:
        """
        Dispatch a tool call to MCPToolbox and return (result_content, success).

        All database access goes through self._toolbox.call_tool() — this is the
        MCPToolbox HTTP client. No direct database connections anywhere.
        """
        if tc.name == "query_db":
            return self._tool_query_db(tc.input, available_databases, iteration)
        elif tc.name == "list_db":
            return self._tool_list_db(tc.input, available_databases)
        elif tc.name == "execute_python":
            return self._tool_execute_python(tc.input, iteration)
        elif tc.name == "return_answer":
            # No execution needed — the loop handles termination above
            answer = tc.input.get("answer", "")
            return f"Answer recorded: {answer}", True
        else:
            return f"Unknown tool: {tc.name!r}. Available tools: query_db, list_db, execute_python, return_answer", False

    def _tool_query_db(
        self,
        args: Dict[str, Any],
        available_databases: List[str],
        iteration: int,
    ) -> tuple[str, bool]:
        """Execute a query via MCPToolbox. Routes to the correct MCP tool name."""
        database = args.get("database", "")
        query = args.get("query", "")
        query_type = args.get("query_type", "sql")

        # Loop detection temporarily disabled
        # self._loop_detector.record_tool_call("query_db", {"database": database, "query_type": query_type, "query": query[:100]})  # Truncate for comparison
        # 
        # # Check for loops before executing
        # if self._loop_detector.is_looping():
        #     loop_summary = self._loop_detector.get_loop_summary()
        #     return (
        #         f"Loop detected! {loop_summary['loops_detected']}. "
        #         f"Please try a different approach or query pattern.",
        #         False
        #     )

        if not database or not query:
            return "Error: query_db requires 'database' and 'query' arguments.", False

        if database not in available_databases:
            return (
                f"Error: database '{database}' is not in the available databases: "
                f"{available_databases}. Use one of those.",
                False,
            )

        # Resolve the MCP tool name for this database
        mcp_tool = self._resolve_mcp_tool(database, query_type)
        if not mcp_tool:
            return f"Error: no MCP tool found for database '{database}' ({query_type}).", False

        try:
            # Package parameters based on query type
            if query_type == "mongo":
                params = {"database": database, "query": query, "query_type": "mongo"}
            else:
                params = {"sql": query, "database": database}

            result = self._toolbox.call_tool(mcp_tool, params)
            if result.success:
                self._dataset_counter += 1
                data_key = f"data_{self._dataset_counter}"
                self._query_results[data_key] = result.data

                data_str = json.dumps(result.data, default=str)
                preview = data_str[:5000] + "\n... (truncated)" if len(data_str) > 5000 else data_str
                
                msg = (
                    f"Query successful. Full dataset saved to env['{data_key}'] for use in execute_python.\n"
                    f"Preview:\n{preview}"
                )
                return msg, True
            else:
                return f"Query error: {result.error}", False
        except Exception as exc:
            return f"Query execution failed: {exc}", False

    def _tool_execute_python(self, args: Dict[str, Any], iteration: int) -> tuple[str, bool]:
        """Run a Python script with 'env' locally in a subprocess."""
        code = args.get("code", "")
        if not code:
            return "Error: execute_python requires 'code' argument.", False

        import tempfile
        import subprocess
        import os

        # Safe environment handling temporarily disabled
        safe_env = self._query_results.copy()
        # safe_env = self._planner_fallback.safe_execute_python_env(code, self._query_results.copy())
        
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, "env.json")
            with open(env_file, "w", encoding="utf-8") as f:
                json.dump(safe_env, f, default=str)
            
            script_file = os.path.join(tmpdir, "script.py")
            # Add debug instrumentation for BookReview dataset processing
            debug_instrumentation = (
                "\n# DEBUG: BookReview data pipeline instrumentation\n"
                "if any('bookreview' in key.lower() for key in env.keys()):\n"
                "    import pandas as pd\n"
                "    from rapidfuzz import fuzz, process\n"
                "    import ast\n"
                "    import re\n"
                "    \n"
                "    print(\"=== BOOKREVIEW DATA PIPELINE DEBUG ===\")\n"
                "    \n"
                "    # Count raw data\n"
                "    books_data = None\n"
                "    review_data = None\n"
                "    for key, data in env.items():\n"
                "        if isinstance(data, list) and data:\n"
                "            if 'book' in key.lower() or 'books_info' in str(data[0]).lower():\n"
                "                books_data = data\n"
                "                print(f\"books_info raw count: {len(data)}\")\n"
                "            elif 'review' in key.lower() and 'purchase_id' in str(data[0]).lower():\n"
                "                review_data = data\n"
                "                print(f\"review raw count: {len(data)}\")\n"
                "    \n"
                "    if books_data and review_data:\n"
                "        # Convert to DataFrames\n"
                "        books_df = pd.DataFrame(books_data)\n"
                "        reviews_df = pd.DataFrame(review_data)\n"
                "        print(f\"books_info columns: {list(books_df.columns)}\")\n"
                "        print(f\"review columns: {list(reviews_df.columns)}\")\n"
                "        \n"
                "        # Debug book_id/purchase_id matching\n"
                "        if 'book_id' in books_df.columns and 'purchase_id' in reviews_df.columns:\n"
                "            book_ids = set(str(bid).strip() for bid in books_df['book_id'].dropna())\n"
                "            purchase_ids = set(str(pid).strip() for pid in reviews_df['purchase_id'].dropna())\n"
                "            print(f\"Unique book_ids: {len(book_ids)}\")\n"
                "            print(f\"Unique purchase_ids: {len(purchase_ids)}\")\n"
                "            \n"
                "            # Test fuzzy matching\n"
                "            matches = 0\n"
                "            for pid in list(purchase_ids)[:100]:  # Sample first 100\n"
                "                match = process.extractOne(pid, list(book_ids), scorer=fuzz.ratio, score_cutoff=80)\n"
                "                if match:\n"
                "                    matches += 1\n"
                "            fuzzy_match_rate = matches / 100 if purchase_ids else 0\n"
                "            print(f\"Fuzzy match rate (sample): {fuzzy_match_rate:.2%}\")\n"
                "            \n"
                "            # Test exact matching after normalization\n"
                "            normalized_book_ids = set(bid.lower().strip() for bid in book_ids)\n"
                "            normalized_purchase_ids = set(pid.lower().strip() for pid in purchase_ids)\n"
                "            exact_matches = normalized_book_ids & normalized_purchase_ids\n"
                "            print(f\"Exact matches after normalization: {len(exact_matches)}\")\n"
                "        \n"
                "        # Debug publication year extraction\n"
                "        if 'details' in books_df.columns:\n"
                "            years = []\n"
                "            for details in books_df['details'].dropna():\n"
                "                try:\n"
                "                    details_dict = ast.literal_eval(details)\n"
                "                    # Look for year in various fields\n"
                "                    year = None\n"
                "                    for field in ['publication date', 'publish date', 'year', 'published']:\n"
                "                        if field in details_dict:\n"
                "                            year_str = str(details_dict[field])\n"
                "                            year_match = re.search(r'\\b(19|20)\\d{2}\\b', year_str)\n"
                "                            if year_match:\n"
                "                                year = int(year_match.group())\n"
                "                                break\n"
                "                    if year:\n"
                "                        years.append(year)\n"
                "                except:\n"
                "                    pass\n"
                "            print(f\"Successfully extracted publication years: {len(years)}\")\n"
                "            if years:\n"
                "                print(f\"Year range: {min(years)} - {max(years)}\")\n"
                "                # Group by decade\n"
                "                decades = {}\n"
                "                for year in years:\n"
                "                    decade = (year // 10) * 10\n"
                "                    decades[decade] = decades.get(decade, 0) + 1\n"
                "                print(f\"Books per decade: {dict(sorted(decades.items()))}\")\n"
                "                decades_with_10_plus = {d: c for d, c in decades.items() if c >= 10}\n"
                "                print(f\"Decades with >=10 books: {dict(sorted(decades_with_10_plus.items()))}\")\n"
                "        \n"
                "        print(\"=== END DEBUG ===\")\n"
            )
            
            wrapper_code = (
                "import json\n"
                "import sys\n"
                "with open('/workspace/env.json', 'r', encoding='utf-8') as f:\n"
                "    env = json.load(f)\n\n"
                + debug_instrumentation + "\n" + code
            )
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(wrapper_code)
                
            try:
                proc = subprocess.run(
                    [
                        "docker", "run", "--rm",
                        "-v", f"{tmpdir}:/workspace",
                        "-w", "/workspace",
                        "python-data:3.12",
                        "python3", "script.py"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    out = proc.stdout.strip()
                    if len(out) > 20000:
                        out = out[:20000] + "\n... (truncated)"
                    return f"Execution successful. Output:\n{out}", True
                else:
                    return f"Execution failed. Error:\n{proc.stderr.strip()}", False
            except subprocess.TimeoutExpired:
                return "Execution timed out after 60 seconds.", False
            except Exception as e:
                return f"Execution error: {e}", False

    def _tool_list_db(
        self,
        args: Dict[str, Any],
        available_databases: List[str],
    ) -> tuple[str, bool]:
        """List tables/schema for a database via MCPToolbox."""
        database = args.get("database", "")

        if not database:
            return "Error: list_db requires 'database' argument.", False

        if database not in available_databases:
            return (
                f"Error: database '{database}' is not available. "
                f"Available: {available_databases}",
                False,
            )

        # Try the schema from db_config context first (fast path)
        db_config = self._db_configs.get(database, {})
        db_type = db_config.get("type", "")

        # Resolve list/describe tool from MCPToolbox tool map
        list_tool = self._resolve_list_tool(database, db_type)
        if list_tool:
            try:
                # For DuckDB, use SHOW TABLES query
                if db_type == "duckdb":
                    result = self._toolbox.call_tool(list_tool, {"sql": "SHOW TABLES"})
                else:
                    result = self._toolbox.call_tool(list_tool, {})
                
                if result.success:
                    data_str = json.dumps(result.data, default=str)
                    return f"Schema for '{database}':\n{data_str}", True
                else:
                    return f"Schema lookup error: {result.error}", False
            except Exception as exc:
                return f"Schema lookup failed: {exc}", False

        # Fallback: try discovery queries for DuckDB and SQLite
        if db_type in ("duckdb", "sqlite"):
            discovery_queries = [
                "SHOW TABLES",
                "SELECT name FROM sqlite_master WHERE type='table'",
                "SELECT table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
            ]
            
            for query in discovery_queries:
                try:
                    # Try to find a query tool for this database
                    query_tool = self._resolve_mcp_tool(database, "sql")
                    if query_tool:
                        result = self._toolbox.call_tool(query_tool, {"sql": query})
                        if result.success and result.data:
                            data_str = json.dumps(result.data, default=str)
                            return f"Discovered tables for '{database}' using query '{query}':\n{data_str}", True
                except Exception:
                    continue
        
        # Final fallback: return helpful message with known tables for common databases
        known_tables = self._get_known_tables_for_database(database)
        if known_tables:
            return (
                f"Schema not available via tool for '{database}'. "
                f"DB type: {db_type}. Known tables: {', '.join(known_tables)}. "
                f"Try querying one of these tables directly.",
                False,
            )
        
        return (
            f"Schema not available via tool for '{database}'. "
            f"DB type: {db_type}. No known tables available. "
            f"Try a simple query like 'SELECT * FROM table_name LIMIT 5' to discover tables.",
            False,
        )

    # ── MCP tool name resolution ───────────────────────────────────────────

    def _resolve_mcp_tool(self, database: str, query_type: str) -> Optional[str]:
        """
        Map a database identifier + query_type to the MCPToolbox tool name.

        Uses the db_config's explicit mcp_tool if set (from tools.yaml), 
        otherwise falls back to engine-based defaults.
        """
        db_config = self._db_configs.get(database, {})
        explicit = db_config.get("mcp_tool")
        if explicit:
            return explicit

        db_type = db_config.get("type", "").lower()

        # Engine-based fallbacks if no explicit tool is configured
        if db_type == "mongodb":
            return "mongodb_query"
        if db_type == "duckdb":
            return "duckdb_query"
        if db_type == "sqlite":
            return "sqlite_query"
        if db_type in ("postgres", "postgresql"):
            return "run_query"

        return None

    def _resolve_list_tool(self, database: str, db_type: str) -> Optional[str]:
        """Return the MCP tool name for listing tables in a database."""
        # PostgreSQL has a native list_tables tool
        if db_type in ("postgres", "postgresql"):
            return "list_tables"

        # For DuckDB, use the duckdb query tool with SHOW TABLES
        if db_type == "duckdb":
            # Try to find the appropriate duckdb tool for this database
            for tool_name in self._toolbox._tool_source_map:
                if "duckdb" in tool_name.lower() and database.lower() in tool_name.lower():
                    return tool_name
            # Fallback to generic duckdb tool
            return "sqlite_duckdb_query"  # This might not exist, but we'll handle fallback

        # For SQLite we don't have a dedicated list tool in the toolbox;
        # the caller will fall through to the schema context fallback.
        return None

    def _get_known_tables_for_database(self, database: str) -> List[str]:
        """Return known tables for common databases as fallback."""
        known_tables = {
            "user_database": ["review", "tip", "user"],
            "yelp_db": ["business", "checkin"],
            "bookreview_db": ["books_info"],
            "review_database": ["review"],
            "googlelocal_db": ["business_description"],
            "review_database": ["review"],
        }
        return known_tables.get(database, [])

# ── Schema context builder ─────────────────────────────────────────────────────


def build_schema_context(schema: Dict[str, Any]) -> str:
    """
    Convert a ContextBundle.schema dict to a compact text description for the LLM.

    Args:
        schema: Dict[db_name, SchemaInfo] from the ContextBundle.

    Returns:
        Multi-line string describing tables and columns per database.
    """
    lines: List[str] = []
    for db_name, schema_info in schema.items():
        lines.append(f"Database: {db_name} ({getattr(schema_info, 'db_type', 'unknown')})")
        tables = getattr(schema_info, "tables", {})
        for table_name, columns in tables.items():
            col_list = ", ".join(str(c) for c in columns) if columns else "(no columns)"
            lines.append(f"  Table: {table_name} — {col_list}")
    return "\n".join(lines)
