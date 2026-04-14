# data-agent-challenge

## MCP Toolbox

The repo now uses a single MCP Toolbox config at `mcp/tools.yaml`.

- Start the local Toolbox server with `./setup_dab.sh`
- Configure the server URL with `TOOLBOX_URL` in `.env`
- Use `MCPToolbox` from `agent/mcp_toolbox.py` for hybrid routing:
  non-DuckDB tools go through the Toolbox CLI and DuckDB uses a direct driver path

Quick verification command:

```bash
./bin/toolbox invoke --config mcp/tools.yaml list_tables
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
SANDBOX_URL=https://sandbox.<your-workers-subdomain>.workers.dev
```

### Verify MCP

```bash
./bin/toolbox invoke --config mcp/tools.yaml preview_books_info
./bin/toolbox invoke --config mcp/tools.yaml find_yelp_businesses
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
