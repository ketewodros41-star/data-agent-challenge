# data-agent-challenge

## MCP Toolbox

The repo now uses a single MCP Toolbox config at `mcp/tools.yaml`.

Full MCP usage manual: [mcp/MANUAL.md](/home/bethel/data-agent-challenge/mcp/MANUAL.md)

- Start the local Toolbox server with `./setup_dab.sh`
- Use `./toolbox` to run the Toolbox CLI with the repo config preloaded
- Launch the Toolbox UI with `./toolbox serve --enable-api --ui`
- Configure the server URL with `TOOLBOX_URL` in `.env`
- Set `DAB_DATASET_ROOT` in `.env` to the local `DataAgentBench` checkout that
  should be mounted into the toolbox container as `/datasets`
- Set `DUCKDB_MCP_URL` in `.env` for the custom DuckDB MCP service
- For local Docker usage, `./toolbox` defaults to PostgreSQL `127.0.0.1:55432`
  and MongoDB `127.0.0.1:57017` unless overridden in `.env`
- If port `5000` is already occupied by Docker or another toolbox process, run
  the UI on `5001` with
  `TOOLBOX_URL=http://127.0.0.1:5001 ./toolbox --ui --port 5001`
- Use `MCPToolbox` from `agent/mcp_toolbox.py` for hybrid routing:
  Google Toolbox handles Postgres/Mongo/SQLite and the custom DuckDB MCP
  service handles DuckDB-backed datasets

Quick verification command:

```bash
./toolbox invoke list_tables
```

List the MCP tools currently visible from the running toolbox service:

```bash
python3 main.py list-mcp-tools
```

Run a SQL query through the generic PostgreSQL MCP alias:

```bash
python3 main.py run-query "SELECT 1 AS ok"
```

## Runtime Manual

Oracle Forge runtime split:

- `MCP` handles direct database reads
- `Sandbox` handles `transform` / `extract` / `merge` / `validate`
- `Self_Correction_Loop` retries failed sandbox work

### Team Setup

From the repo root:

```bash
./setup_dab.sh
```

Set these in `.env` when available:

```env
TOOLBOX_URL=http://127.0.0.1:5000
DAB_DATASET_ROOT=/home/<your-user>/DataAgentBench
SANDBOX_URL=https://sandbox.<your-workers-subdomain>.workers.dev
```

`./setup_dab.sh` now starts the toolbox in Docker, mounts the repo at
`/workspace`, and mounts `${DAB_DATASET_ROOT}` at `/datasets` so the shared MCP
config can use stable SQLite paths inside the container. It also starts a
separate DuckDB MCP service on `${DUCKDB_MCP_URL:-http://127.0.0.1:8001}` for
the benchmark DuckDB-backed datasets.

Browser access after startup:

- Google Toolbox UI: `http://127.0.0.1:5000`
- DuckDB MCP UI: `http://127.0.0.1:8001`

### Verify MCP

```bash
./toolbox invoke preview_books_info
./toolbox invoke find_yelp_businesses
```

You can also test the generic SQL alias through the Python CLI:

```bash
python3 main.py run-query "SELECT * FROM books_info LIMIT 3"
```

### Verify Sandbox

```bash
curl -sS "$SANDBOX_URL/health"
```

### Demo Commands

Deterministic local runtime demo:

```bash
python3 main.py runtime-sandbox-demo
```

This uses:
- fake MCP responses
- fake sandbox responses
- real execution-engine routing

Real architecture demo:

```bash
python3 main.py real-runtime-sandbox-demo
```

This uses:
- real MCP toolbox calls for DB reads
- real sandbox HTTP calls for merge/transform
- self-correction retry on sandbox failure

### Important Architecture Rule

Do not use the sandbox for direct database access in the normal runtime flow.

- Database reads go through MCP
- Sandbox is only for `transform`, `extract`, `merge`, and `validate`

### Personal Cloudflare Setup

If a teammate does not have a shared `PaLM` Cloudflare account yet, they can
deploy the sandbox from their own personal Cloudflare account and use their own
`workers.dev` subdomain.

See [workers/sandbox/README.md](workers/sandbox/README.md).
