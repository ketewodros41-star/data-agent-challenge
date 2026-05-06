# Agent Directory

This directory contains the core agent logic and runtime components.

## Files Overview

### Core Agent Files
- **`oracle_forge_agent.py`** - Main agent class that handles user questions and orchestrates the entire process
- **`agentic_loop.py`** - LLM + tool execution loop with iteration management and error handling
- **`mcp_toolbox.py`** - Database connector toolbox that interfaces with MCP servers
- **`llm_client.py`** - LLM API client supporting multiple providers (Anthropic, OpenRouter, etc.)

### Specialized Components
- **`loop_detector.py`** - Detects repetitive tool calls to prevent infinite loops
- **`planner_fallback.py`** - Error recovery and safe execution environment handling
- **`duckdb_mcp_server.py`** - Custom MCP server for DuckDB databases

### Testing
- **`tests/`** - Unit tests for agent components
  - `test_planner_fallback.py` - Tests for loop detection and fallback mechanisms
  - `test_duckdb_fallback_regression.py` - Regression tests for DuckDB schema discovery

## How It Works

1. **OracleForgeAgent** receives a question and available databases
2. **Context Manager** loads knowledge base and schema information
3. **AgenticLoop** runs LLM + tool interactions until answer is found
4. **MCPToolbox** routes database queries to appropriate MCP servers
5. **LoopDetector** prevents repetitive query patterns
6. **PlannerFallback** provides error recovery and safe execution

## Key Features

- **Multi-database support**: PostgreSQL, MongoDB, SQLite, DuckDB
- **Loop detection**: Prevents infinite repetitive queries
- **Error recovery**: Graceful handling of connection failures and missing data
- **Safe execution**: Environment variable management for Python sandbox
- **Comprehensive logging**: Full trace of tool calls and decisions

## Common Issues

### LoopDetector Error
If you get "LoopDetector.__init__() got an unexpected keyword argument", clear Python cache:
```bash
find . -name "__pycache__" -type d -exec rm -rf {} +
```

### DuckDB Server Not Starting
The agent/types.py conflicts with Python's standard library types module. Use `uv run` to avoid:
```bash
uv run python agent/duckdb_mcp_server.py
```

## Testing

Run unit tests:
```bash
uv run python -m pytest agent/tests/
```

Run specific test:
```bash
uv run python agent/tests/test_planner_fallback.py
```
