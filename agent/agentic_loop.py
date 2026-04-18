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
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.llm_client import LLMClient, LLMToolCall, LLMToolCallResponse
from agent.sandbox_client import SandboxClient
from agent.types import SandboxExecutionRequest


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
            "YOU MUST ALWAYS use print() to output your findings (e.g. print(df.head())). "
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

Rules:
- Read the "Domain Knowledge" section carefully. It contains required CROSS-DATABASE JOIN KEY mappings.
- Always explore the schema (list_db) before querying if table/column names are unclear.
- Write precise SQL/Mongo queries to fetch the data.
- If you need to join data across TWO DIFFERENT DATABASES, you MUST query each database separately, then use the `execute_python` tool to merge the data using pandas. SQL cannot cross database boundaries here.
- DO NOT SELECT * for large tables. Push filters down to SQL.
- If a query returns an error, fix it and try again.
- Call return_answer with a concise final value (number, string, or list).
- IMPORTANT: Data returned by `query_db` is ALREADY a Python list/dict whenever possible. DO NOT use `json.loads()` on variables from the `env` dictionary unless the preview specifically shows a raw escaped JSON string.
- For MongoDB/Yelp databases use query_type="mongo" with a JSON filter object.
- For all other databases use query_type="sql" with standard SQL.
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

        while final_answer is None and iteration < self.max_iterations:
            iteration += 1

            # Call LLM with tool definitions
            response: LLMToolCallResponse = self._client.create_with_tools(
                messages=messages,
                tools=AGENTIC_TOOLS,
                max_tokens=1024,
                temperature=0.0,
                system=self._system_prompt,
            )

            if not response.has_tool_calls:
                # LLM returned plain text without a tool call — use as answer (fallback)
                final_answer = response.text or ""
                terminate_reason = "no_tool_call"
                # Append assistant response to conversation
                messages.append({"role": "assistant", "content": response.text})
                break

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
                result_content, success = self._execute_tool(
                    tc, available_databases, iteration
                )

                trace.append({
                    "iteration": iteration,
                    "tool": tc.name,
                    "input": tc.input,
                    "output": result_content[:500],  # truncate for trace
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
            result = self._toolbox.call_tool(mcp_tool, {"sql": query})
            if result.success:
                self._dataset_counter += 1
                data_key = f"data_{self._dataset_counter}"
                self._query_results[data_key] = result.data

                data_str = json.dumps(result.data, default=str)
                preview = data_str[:2000] + "\n... (truncated)" if len(data_str) > 2000 else data_str
                
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

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, "env.json")
            with open(env_file, "w", encoding="utf-8") as f:
                json.dump(self._query_results, f, default=str)
            
            script_file = os.path.join(tmpdir, "script.py")
            wrapper_code = (
                "import json\n"
                "import sys\n"
                "with open('/workspace/env.json', 'r', encoding='utf-8') as f:\n"
                "    env = json.load(f)\n\n"
                + code
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
                result = self._toolbox.call_tool(list_tool, {})
                if result.success:
                    data_str = json.dumps(result.data, default=str)
                    return f"Schema for '{database}':\n{data_str}", True
                else:
                    return f"Schema lookup error: {result.error}", False
            except Exception as exc:
                return f"Schema lookup failed: {exc}", False

        # Fallback: return a generic message pointing to known schema
        return (
            f"Schema not available via tool for '{database}'. "
            f"DB type: {db_type}. Try querying a known table.",
            False,
        )

    # ── MCP tool name resolution ───────────────────────────────────────────

    def _resolve_mcp_tool(self, database: str, query_type: str) -> Optional[str]:
        """
        Map a database identifier + query_type to the MCPToolbox tool name.

        Uses the db_config's explicit mcp_tool if set, otherwise derives from
        MCPToolbox's default_source_map conventions.
        """
        db_config = self._db_configs.get(database, {})
        explicit = db_config.get("mcp_tool", "")
        if explicit:
            return explicit

        db_type = db_config.get("type", "").lower()

        # MongoDB (Yelp) uses find_yelp_businesses / find_yelp_checkins
        if db_type == "mongodb" or database == "yelp_db":
            return "find_yelp_businesses"

        # DuckDB datasets
        if db_type == "duckdb" or database in ("user_database", "review_database", "sales_database"):
            duckdb_tool_map = {
                "user_database": "duckdb_yelp_query",
                "review_database": "duckdb_yelp_query", # fallback for yelp
                "sales_database": "duckdb_crm_sales_pipeline_query",
                "stockmarket": "duckdb_stockmarket_query",
                "stockindex": "duckdb_stockindex_query",
                "music_brainz_20k": "duckdb_music_brainz_query",
                "DEPS_DEV_V1": "duckdb_deps_dev_v1_query",
                "GITHUB_REPOS": "duckdb_github_repos_query",
                "PANCANCER_ATLAS": "duckdb_pancancer_query",
                "crmarenapro": "duckdb_crm_activities_query",
            }
            return duckdb_tool_map.get(database, "duckdb_query")

        # SQLite datasets
        if db_type == "sqlite" or "metadata" in database.lower():
            sqlite_tool_map = {
                "bookreview": "sqlite_bookreview_query",
                "review_database": "sqlite_bookreview_query", # fallback
                "googlelocal": "sqlite_googlelocal_query",
                "agnews": "sqlite_agnews_query",
            }
            return sqlite_tool_map.get(database, "sqlite_query")

        # PostgreSQL
        if db_type in ("postgres", "postgresql"):
            return "run_query"

        return None

    def _resolve_list_tool(self, database: str, db_type: str) -> Optional[str]:
        """Return the MCP tool name for listing tables in a database."""
        # PostgreSQL has a native list_tables tool
        if db_type in ("postgres", "postgresql"):
            return "list_tables"

        # For SQLite/DuckDB we don't have a dedicated list tool in the toolbox;
        # the caller will fall through to the schema context fallback.
        return None


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
