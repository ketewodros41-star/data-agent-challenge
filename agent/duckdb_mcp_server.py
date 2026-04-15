#!/usr/bin/env python3
"""Minimal DuckDB MCP HTTP server for local benchmark datasets."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import duckdb


@dataclass(frozen=True)
class DuckDBTool:
    name: str
    description: str
    database_path: Path


def _dataset_root() -> Path:
    root = os.getenv("DAB_DATASET_ROOT", str(Path.home() / "DataAgentBench"))
    return Path(root).expanduser().resolve()


def _tool_registry(root: Path) -> Dict[str, DuckDBTool]:
    return {
        "duckdb_crm_activities_query": DuckDBTool(
            name="duckdb_crm_activities_query",
            description="Execute SQL against the CRM Arena Pro activities DuckDB database.",
            database_path=root / "query_crmarenapro" / "query_dataset" / "activities.duckdb",
        ),
        "duckdb_crm_sales_pipeline_query": DuckDBTool(
            name="duckdb_crm_sales_pipeline_query",
            description="Execute SQL against the CRM Arena Pro sales pipeline DuckDB database.",
            database_path=root / "query_crmarenapro" / "query_dataset" / "sales_pipeline.duckdb",
        ),
        "duckdb_deps_dev_v1_query": DuckDBTool(
            name="duckdb_deps_dev_v1_query",
            description="Execute SQL against the DEPS_DEV_V1 DuckDB-backed project dataset.",
            database_path=root / "query_DEPS_DEV_V1" / "query_dataset" / "project_query.db",
        ),
        "duckdb_github_repos_query": DuckDBTool(
            name="duckdb_github_repos_query",
            description="Execute SQL against the GitHub Repos DuckDB-backed artifacts dataset.",
            database_path=root / "query_GITHUB_REPOS" / "query_dataset" / "repo_artifacts.db",
        ),
        "duckdb_music_brainz_query": DuckDBTool(
            name="duckdb_music_brainz_query",
            description="Execute SQL against the Music Brainz sales DuckDB database.",
            database_path=root / "query_music_brainz_20k" / "query_dataset" / "sales.duckdb",
        ),
        "duckdb_pancancer_query": DuckDBTool(
            name="duckdb_pancancer_query",
            description="Execute SQL against the PANCANCER molecular DuckDB-backed dataset.",
            database_path=root / "query_PANCANCER_ATLAS" / "query_dataset" / "pancancer_molecular.db",
        ),
        "duckdb_stockindex_query": DuckDBTool(
            name="duckdb_stockindex_query",
            description="Execute SQL against the Stock Index DuckDB-backed trade dataset.",
            database_path=root / "query_stockindex" / "query_dataset" / "indextrade_query.db",
        ),
        "duckdb_stockmarket_query": DuckDBTool(
            name="duckdb_stockmarket_query",
            description="Execute SQL against the Stock Market DuckDB-backed trade dataset.",
            database_path=root / "query_stockmarket" / "query_dataset" / "stocktrade_query.db",
        ),
        "duckdb_yelp_query": DuckDBTool(
            name="duckdb_yelp_query",
            description="Execute SQL against the Yelp DuckDB-backed user dataset.",
            database_path=root / "query_yelp" / "query_dataset" / "yelp_user.db",
        ),
    }


class DuckDBMCPHandler(BaseHTTPRequestHandler):
    server_version = "DuckDBMCP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(200, _render_ui(self.server.tools))  # type: ignore[attr-defined]
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            self._handle_mcp()
            return

        match = re.fullmatch(r"/api/tool/([^/]+)/invoke", parsed.path)
        if match:
            self._handle_invoke(match.group(1))
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _handle_mcp(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return

        request_id = payload.get("id")
        method = payload.get("method")
        if method != "tools/list":
            self._send_json(
                400,
                {"jsonrpc": "2.0", "id": request_id, "error": {"message": "unsupported method"}},
            )
            return

        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string"},
                    },
                    "required": ["sql"],
                },
            }
            for tool in self.server.tools.values()  # type: ignore[attr-defined]
        ]
        self._send_json(200, {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})

    def _handle_invoke(self, tool_name: str) -> None:
        tool = self.server.tools.get(tool_name)  # type: ignore[attr-defined]
        if tool is None:
            self._send_json(404, {"error": f"unknown tool: {tool_name}"})
            return

        payload = self._read_json_body()
        if payload is None:
            return
        sql = payload.get("sql") or payload.get("query")
        if not isinstance(sql, str) or not sql.strip():
            self._send_json(400, {"error": "missing required string field 'sql'"})
            return
        if not tool.database_path.exists():
            self._send_json(500, {"error": f"database file not found: {tool.database_path}"})
            return

        try:
            conn = duckdb.connect(str(tool.database_path), read_only=True)
            rows = conn.execute(sql).fetchall()
            description = conn.description or []
            cols = [col[0] for col in description]
            conn.close()
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return

        self._send_json(200, {"result": [dict(zip(cols, row)) for row in rows]})

    def _read_json_body(self) -> Dict[str, Any] | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length"})
            return None
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"request body was invalid JSON: {exc}"})
            return None

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _render_ui(tools: Dict[str, DuckDBTool]) -> str:
    tool_options = "\n".join(
        f'<option value="{tool.name}">{tool.name}</option>'
        for tool in tools.values()
    )
    tool_cards = "\n".join(
        (
            "<article class=\"tool-card\">"
            f"<h3>{tool.name}</h3>"
            f"<p>{tool.description}</p>"
            f"<code>{tool.database_path}</code>"
            "</article>"
        )
        for tool in tools.values()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DuckDB MCP UI</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: #fffaf1;
      --ink: #1f2a37;
      --accent: #0f766e;
      --accent-2: #b45309;
      --border: #dcc9a8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15,118,110,0.12), transparent 30%),
        radial-gradient(circle at right, rgba(180,83,9,0.16), transparent 25%),
        var(--bg);
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 40px 20px 56px;
    }}
    .hero {{
      display: grid;
      gap: 20px;
      grid-template-columns: 1.2fr 1fr;
      align-items: start;
      margin-bottom: 28px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 14px 30px rgba(31,42,55,0.08);
      padding: 22px;
    }}
    h1, h2, h3 {{ margin-top: 0; }}
    h1 {{
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1.05;
      margin-bottom: 12px;
    }}
    .lede {{
      font-size: 1.05rem;
      line-height: 1.6;
      max-width: 44rem;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(255,255,255,0.8);
      font-size: 0.92rem;
    }}
    form {{
      display: grid;
      gap: 12px;
    }}
    label {{
      font-weight: 700;
      font-size: 0.95rem;
    }}
    select, textarea, button {{
      width: 100%;
      font: inherit;
      border-radius: 12px;
      border: 1px solid var(--border);
      padding: 12px 14px;
      background: #fff;
    }}
    textarea {{
      min-height: 160px;
      resize: vertical;
      font-family: "SFMono-Regular", Consolas, monospace;
    }}
    button {{
      border: none;
      cursor: pointer;
      color: white;
      background: linear-gradient(135deg, var(--accent), #155e75);
      font-weight: 700;
    }}
    button:hover {{ filter: brightness(1.05); }}
    .results {{
      margin-top: 20px;
      white-space: pre-wrap;
      background: #17212b;
      color: #ecfdf5;
      border-radius: 14px;
      padding: 16px;
      min-height: 180px;
      overflow: auto;
      font-family: "SFMono-Regular", Consolas, monospace;
    }}
    .tools-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
    }}
    .tool-card {{
      background: rgba(255,255,255,0.75);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
    }}
    code {{
      display: block;
      margin-top: 10px;
      font-size: 0.84rem;
      color: var(--accent-2);
      word-break: break-word;
    }}
    @media (max-width: 800px) {{
      .hero {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="panel">
        <h1>DuckDB MCP Workbench</h1>
        <p class="lede">
          Browse the custom DuckDB MCP tools, run SQL against benchmark datasets,
          and inspect raw results directly from the browser.
        </p>
        <div class="badges">
          <span class="badge">Custom DuckDB MCP</span>
          <span class="badge">{len(tools)} dataset tools</span>
          <span class="badge">API at <strong>/mcp</strong> and <strong>/api/tool/*/invoke</strong></span>
        </div>
      </div>
      <div class="panel">
        <h2>Run a Query</h2>
        <form id="query-form">
          <div>
            <label for="tool">DuckDB tool</label>
            <select id="tool" name="tool">{tool_options}</select>
          </div>
          <div>
            <label for="sql">SQL</label>
            <textarea id="sql" name="sql">SHOW TABLES</textarea>
          </div>
          <button type="submit">Run SQL</button>
        </form>
        <div class="results" id="results">Results will appear here.</div>
      </div>
    </section>

    <section class="panel">
      <h2>Available Tools</h2>
      <div class="tools-grid">
        {tool_cards}
      </div>
    </section>
  </main>
  <script>
    const form = document.getElementById("query-form");
    const results = document.getElementById("results");
    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const tool = document.getElementById("tool").value;
      const sql = document.getElementById("sql").value;
      results.textContent = "Running...";
      try {{
        const response = await fetch(`/api/tool/${{tool}}/invoke`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ sql }})
        }});
        const payload = await response.json();
        results.textContent = JSON.stringify(payload, null, 2);
      }} catch (error) {{
        results.textContent = `Request failed: ${{error}}`;
      }}
    }});
  </script>
</body>
</html>"""


def main() -> None:
    host = os.getenv("DUCKDB_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("DUCKDB_MCP_PORT", "8001"))
    server = ThreadingHTTPServer((host, port), DuckDBMCPHandler)
    server.tools = _tool_registry(_dataset_root())  # type: ignore[attr-defined]
    server.serve_forever()


if __name__ == "__main__":
    main()
