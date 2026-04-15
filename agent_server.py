#!/usr/bin/env python3
"""Oracle Forge Agent — HTTP API server.

Exposes the OracleForgeAgent over HTTP so a facilitator can reach the live
agent from any machine without SSH access.

Endpoints
---------
GET  /          → landing page (HTML)
GET  /health    → {"status": "ok", "agent": "oracle-forge"}
POST /answer    → run the agent

POST /answer request body (JSON):
    {
        "question": "What are the top 5 businesses by review count?",
        "dataset": "yelp"
    }

POST /answer response body (JSON):
    {
        "answer": ...,
        "confidence": 0.0-1.0,
        "query_trace": [...],
        "correction_applied": false,
        "_meta": {"dataset": "...", "elapsed_seconds": ...}
    }

Usage
-----
    python agent_server.py              # listens on 0.0.0.0:8080
    python agent_server.py --port 9090  # custom port
    AGENT_PORT=9090 python agent_server.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv()

# Import KB parser and db-config builder from run_agent.py
from run_agent import (
    KB_DATASET_OVERVIEW,
    build_db_configs_from_env,
    parse_kb_dataset_registry,
)
from agent.oracle_forge_agent import OracleForgeAgent

_PORT = int(os.getenv("AGENT_PORT", "8080"))

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Oracle Forge — Live Agent</title>
  <style>
    body { font-family: monospace; max-width: 800px; margin: 40px auto; padding: 0 20px; background: #0d1117; color: #c9d1d9; }
    h1   { color: #58a6ff; }
    h2   { color: #79c0ff; margin-top: 2em; }
    pre  { background: #161b22; padding: 16px; border-radius: 6px; overflow-x: auto; }
    code { color: #e6edf3; }
    a    { color: #58a6ff; }
    .tag { color: #3fb950; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Oracle Forge — Live Agent</h1>
  <p><span class="tag">&#x25CF; RUNNING</span> &nbsp; Team PaLM · DataAgentBench</p>

  <h2>Health check</h2>
  <pre><code>GET /health</code></pre>

  <h2>Run a query</h2>
  <pre><code>POST /answer
Content-Type: application/json

{
  "question": "What are the top 5 cities by number of businesses?",
  "dataset":  "yelp"
}
</code></pre>

  <h2>Available datasets</h2>
  <pre><code>bookreview · yelp · googlelocal · agnews · crmarenapro
stockindex · PANCANCER_ATLAS · DEPS_DEV_V1 · GITHUB_REPOS</code></pre>

  <h2>Example (curl)</h2>
  <pre><code>curl -s http://localhost:8080/answer \\
  -H 'Content-Type: application/json' \\
  -d '{"question": "How many businesses are there?", "dataset": "yelp"}' \\
  | python3 -m json.tool</code></pre>

  <h2>MCP Toolbox UI</h2>
  <p>Available via SSH tunnel from localhost:5000</p>
</body>
</html>
"""


def _load_registry() -> Dict[str, Any]:
    if KB_DATASET_OVERVIEW.exists():
        return parse_kb_dataset_registry(KB_DATASET_OVERVIEW)
    return {}


def _run_query(question: str, dataset: str) -> Dict[str, Any]:
    registry = _load_registry()
    dataset_key = dataset.lower()

    if dataset_key in registry:
        databases_info = registry[dataset_key]
        db_ids = [d["db_id"] for d in databases_info]
        db_configs = build_db_configs_from_env(databases_info, dataset_name=dataset_key)
    else:
        db_ids = [dataset_key]
        db_configs = {}

    agent = OracleForgeAgent(db_configs=db_configs or None)
    t0 = time.perf_counter()
    result = agent.answer(
        {
            "question": question,
            "available_databases": db_ids,
            "schema_info": {},
        }
    )
    elapsed = round(time.perf_counter() - t0, 3)
    agent.end_session()

    result["_meta"] = {
        "dataset": dataset,
        "databases": db_ids,
        "question": question,
        "elapsed_seconds": elapsed,
    }
    return result


class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        print(f"[{self.address_string()}] {fmt % args}", flush=True)

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/"):
            self._send_html(200, _LANDING_HTML)
        elif path == "/health":
            self._send_json(200, {"status": "ok", "agent": "oracle-forge", "team": "PaLM"})
        else:
            self._send_json(404, {"error": f"Unknown path: {self.path}"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0].rstrip("/")
        if path != "/answer":
            self._send_json(404, {"error": f"Unknown path: {self.path}"})
            return

        try:
            body = self._read_json_body()
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(400, {"error": f"Invalid JSON body: {exc}"})
            return

        if not body or "question" not in body:
            self._send_json(
                400,
                {
                    "error": "Request body must include 'question' (string) and "
                             "optionally 'dataset' (string)."
                },
            )
            return

        question: str = body["question"]
        dataset: str = body.get("dataset", "yelp")

        print(f"[query] dataset={dataset!r} question={question!r}", flush=True)

        try:
            result = _run_query(question, dataset)
            self._send_json(200, result)
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[error] {exc}\n{tb}", flush=True)
            self._send_json(
                500,
                {
                    "error": str(exc),
                    "question": question,
                    "dataset": dataset,
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Oracle Forge Agent HTTP server")
    parser.add_argument("--port", type=int, default=_PORT, help="Port to listen on (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"Oracle Forge Agent API listening on http://{args.host}:{args.port}", flush=True)
    print(f"Landing page : http://localhost:{args.port}/", flush=True)
    print(f"Health check : http://localhost:{args.port}/health", flush=True)
    print(f"Query API    : POST http://localhost:{args.port}/answer", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
