# Oracle Forge

Oracle Forge is Team PaLM's multi-database data analytics agent for the UC Berkeley DataAgentBench (DAB) benchmark. It answers natural-language questions across PostgreSQL, MongoDB, SQLite, and DuckDB, keeps traceable execution logs, and uses a sandbox for post-retrieval work such as extraction, merge, and validation.

The system is built around three ideas from the design and sprint plan:

- explicit context layers instead of prompt sprawl
- MCP as the database access layer
- self-correcting execution with measurable traces

## Team

Team: `PaLM`

| Member | Role Stream | Current Focus |
| --- | --- | --- |
| Bethel Yohannes | Drivers / Architecture & Infra | Agent integration, MCP setup, repo packaging |
| Yosef Zewdu | Drivers / Architecture & Infra | Shared environment, dataset setup, architecture |
| Estifanos Teklay | Intelligence Officers | Knowledge base and context layers |
| Melkam Berhane | Intelligence Officers | Knowledge base and context layers |
| Kidus Tewodros | Signal Corps | Progress reporting, external comms, benchmark narrative |
| Mistire Daniel | Signal Corps | Progress reporting, external comms, benchmark narrative |

Source for team roster and role grouping: [planning/inception.md](planning/inception.md) and [signals/engagmentlog.md](signals/engagmentlog.md).

## What We Built

Oracle Forge is organized around four runtime layers:

1. `OracleForgeAgent` handles the user question and assembles context.
2. `QueryRouter` selects the right databases and decomposes multi-database work.
3. `ExecutionEngine` dispatches database reads through MCP and post-processing through the sandbox.
4. `Evaluation` traces tool calls and stores benchmark-style run artifacts.

The current system supports:

- PostgreSQL, MongoDB, and SQLite through Google MCP Toolbox
- DuckDB through a separate custom MCP service
- sandbox-backed `extract`, `merge`, `transform`, and `validate` operations
- DAB-style query packaging under dataset folders such as `query_bookreview/query1/`

## Architecture Diagram

![alt text](<mermaid-diagram (1).svg>)

## Repository Map

- [agent/](agent) — agent runtime, router, execution engine, sandbox client, MCP clients
- [mcp/](mcp) — shared toolbox config and team MCP manual
- [workers/sandbox/](workers/sandbox) — Cloudflare Worker sandbox implementation
- [kb/](kb) — architecture, domain, and memory knowledge base
- [scripts/](scripts) — setup and runnable entrypoints
- [design.md](design.md) — design document
- [task.md](task.md) — implementation plan and task breakdown

## Live Agent / Shared Server

Add the shared server URL or access instructions here before submission.

- Shared agent URL: `TBD - replace with team server URL`
- Shared toolbox UI: `TBD - replace with team server URL if exposed`
- Shared DuckDB MCP UI: `TBD - replace with team server URL if exposed`
- Deployed sandbox used during development: `https://sandbox.oracleforget.workers.dev`


## Fresh Machine Setup

These instructions assume a facilitator is starting from a fresh Linux machine with Git, Docker, Python 3.10+, and `uv` available.



### 1. Clone the repos

```bash
cd ~
git clone <your-org-or-fork>/data-agent-challenge.git
git clone <your-org-or-fork>/DataAgentBench.git
cd data-agent-challenge
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Create `.env`

Copy the example file:

```bash
cp .env.example .env
```

Set at least these values:

```env
TOOLBOX_URL=http://127.0.0.1:5000
DAB_DATASET_ROOT=/home/<your-user>/DataAgentBench
DUCKDB_MCP_URL=http://127.0.0.1:8001
SANDBOX_URL=https://.....dev
```

Optional for live natural-language runs that call the external LLM backend:

```env
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=google/gemini-2.5-flash-lite
```

The local test suite does not require `OPENROUTER_API_KEY`.

If you are using the shared Dockerized Postgres and MongoDB containers, the defaults in [.env.example](.env.example) are already aligned with this repo:

```env
PG_HOST=127.0.0.1
PG_PORT=55432
PG_DATABASE=bookreview_db
PG_USER=postgres
PG_PASSWORD=teampalm
MONGODB_URI=mongodb://127.0.0.1:57017
MONGODB_DATABASE=yelp_db
```

### 4. Start MCP services

From the repo root:

```bash
./setup_dab.sh
```

This starts:

- Google Toolbox MCP in Docker at `http://127.0.0.1:5000`
- DuckDB MCP at `http://127.0.0.1:8001`

It also mounts your local `DataAgentBench` checkout into the toolbox container as `/datasets`, which is how the SQLite datasets are shared into MCP.

If `./setup_dab.sh` fails immediately, first check whether these database containers already exist:

```bash
docker ps -a --format '{{.Names}}' | grep -E 'team-dab-postgres|team-dab-mongo'
```

If they do not exist on the machine, the facilitator needs either:

- the team's shared database containers running locally with those names, or
- an updated `mcp/tools.yaml` plus startup path that points to the actual shared database host

### 5. Verify MCP is live

List the registered tools:

```bash
curl -sS -X POST http://127.0.0.1:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

You should see tools such as:

- `run_query`
- `list_tables`
- `sqlite_bookreview_query`
- `find_yelp_businesses`
- `find_yelp_checkins`

### 6. Verify the sandbox

```bash
curl -sS "$SANDBOX_URL/health"
```

Optional extraction smoke test:

```bash
curl -sS "$SANDBOX_URL/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "code_plan": "{\"operation\":\"keyword_sentiment\",\"input_ref\":\"review\",\"text_field\":\"text\",\"output_mode\":\"record\"}",
    "trace_id": "manual-extract-check",
    "db_type": "extract",
    "inputs_payload": {
      "review": { "text": "This book is amazing, loved every page" }
    },
    "step_id": "manual-extract"
  }'
```

### 7. Run the agent

Single question:

```bash
PYTHONPATH=. uv run python scripts/run_bookreview_query.py \
  --question "what columns does the books_info table have" \
  --eval-dir my_query_run
```

BookReview benchmark preset:

```bash
PYTHONPATH=. uv run python scripts/run_bookreview_query.py \
  --bookreview-benchmark \
  --eval-dir query_bookreview_benchmark
```

The generated run artifacts are stored in DAB-style folders such as:

```text
my_query_run/
└─ query1/
   ├─ query.json
   ├─ validate.py
   └─ run_result.json
```

## How We Know We Are Using MCP

We do not connect directly from the agent process to PostgreSQL or MongoDB in the main runtime path. The proof chain is:

1. `tools/list` on the live MCP endpoint returns the tool registry.
2. agent run artifacts record tool names such as `run_query` in `trace_events`.
3. those same tools are directly invokable over the Toolbox HTTP API.

Example:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/tool/run_query/invoke \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT 1 AS ok"}'
```

That request goes to the MCP service, which then talks to the database.

## Sandbox Contract

The sandbox is the safe execution layer for operations that should happen outside the LLM but after retrieval. It currently handles structured:

- `extract`
- `merge`
- `transform`
- `validate`

Request shape:

```json
{
  "code_plan": "string",
  "trace_id": "step-id:attempt-n",
  "inputs_payload": {},
  "db_type": "extract|transform|merge|validate",
  "context": {
    "shared_context": {},
    "step_parameters": {},
    "available_outputs": {}
  },
  "step_id": "string"
}
```

Response shape:

```json
{
  "result": {},
  "trace": [],
  "validation_status": "PASSED|FAILED|ERROR|RUNTIME_ERROR",
  "error_if_any": null
}
```

## Evidence and Evaluation

This repo is designed to keep evaluation artifacts legible:

- every agent run can export `query.json`, `run_result.json`, and `validate.py`
- `trace_events` record tool usage and outcomes
- benchmark-style datasets can be stored under folders like `query_bookreview/`

Current BookReview workflow:

```bash
PYTHONPATH=. uv run python scripts/run_bookreview_query.py \
  --bookreview-benchmark \
  --eval-dir query_bookreview_benchmark \
  --output /tmp/bookreview-benchmark-results.json
```

## Additional Docs

- [design.md](design.md)
- [task.md](task.md)
- [mcp/MANUAL.md](mcp/MANUAL.md)
- [workers/sandbox/README.md](workers/sandbox/README.md)
- [planning/inception.md](planning/inception.md)

## Current Status

What is working now:

- Query Routing and Self correction
- MCP-backed Postgres, MongoDB, and SQLite access
- DuckDB through a separate MCP service
- sandbox-backed extraction and merge operations
- DAB-style query export for BookReview
- typed traces for runtime and benchmark artifacts


What still needs final team packaging:

- replace the live server placeholders with the real shared-server access details
- add the final photographed architecture diagram if the team wants a hand-drawn version in the README
- add final Pass@1 numbers after the full benchmark run
