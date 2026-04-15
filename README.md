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

 **For facilitators and team members only.** Access credentials available in `FACILITATOR_GUIDE.md`.

The agent runs on a shared server. To query it:

1. **Via SSH tunnel** (recommended for team access):
   ```bash
   ssh ubuntu@<SERVER_IP> -L 8080:localhost:8080
   curl http://localhost:8080/health
   ```

2. **Direct access** (requires authorization):
   Contact the team lead for the server address and API key.

### Test the agent locally (after `./setup_dab.sh`)

```bash
# Health check
curl http://127.0.0.1:8080/health

# Ask a question
curl -s http://127.0.0.1:8080/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "How many businesses are in the yelp dataset?", "dataset": "yelp"}' \
  | python3 -m json.tool
```

Request body fields:

| Field | Required | Description |
|---|---|---|
| `question` | yes | Natural language question |
| `dataset` | no | DAB dataset name (default: `yelp`) |

Available datasets: `yelp`, `bookreview`, `googlelocal`, `agnews`, `crmarenapro`, `stockindex`, `PANCANCER_ATLAS`, `DEPS_DEV_V1`, `GITHUB_REPOS`

### Restart the agent server (after a reboot)

From the repo root on the shared server:

```bash
./start_agent_server.sh          # start or restart
./start_agent_server.sh status   # check running status
./start_agent_server.sh stop     # stop both processes
```

This script starts the Python agent on port 8080 and an nginx Docker container
that proxies port 80 → 8080.

### SSH into the shared server

```bash
ssh ubuntu@<SERVER_IP>
cd /home/yosef/data-agent-challenge
```

*Server address available in `FACILITATOR_GUIDE.md` (for team use only).*

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

Single question via the CLI:

```bash
echo '"How many businesses are in the yelp dataset?"' > /tmp/q.json
uv run python run_agent.py \
  --dataset yelp \
  --query /tmp/q.json \
  --iterations 1 \
  --root_name smoke_test
```

Expected output ends with `Final answer :` and a `Confidence :` line.
Results are written to `results/yelp/smoke_test_iter_1.json`.

Or run via the HTTP API (once `start_agent_server.sh` is running):

```bash
curl -s http://127.0.0.1:8080/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "How many businesses are there?", "dataset": "yelp"}' \
  | python3 -m json.tool
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
- real shared-server access
