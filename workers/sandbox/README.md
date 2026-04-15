# Sandbox Worker Manual

This guide lets each teammate deploy and test the Oracle Forge sandbox from a
personal Cloudflare account.

## What The Sandbox Is For

Use the sandbox only for runtime steps that need code execution:

- `transform`
- `extract`
- `merge`
- `validate`

Do not use the sandbox for normal database reads in the main runtime flow.

- Database reads should go through MCP Toolbox
- The sandbox should process results after MCP returns them

## URL Pattern

Each teammate can deploy the Worker from their own Cloudflare account.

The URL will look like:

```text
https://sandbox.<your-workers-subdomain>.workers.dev
```

Examples:

- `https://sandbox.palm-team.workers.dev`
- `https://sandbox.alexsmith.workers.dev`

If the team later creates a shared Cloudflare account, the same Worker can be
redeployed there and the URL can be updated.

## One-Time Setup

From the repo root:

```bash
cd workers/sandbox
```

Install dependencies:

```bash
npm install
```

Log into Cloudflare:

```bash
npx wrangler login
```

Confirm which account you are using:

```bash
npx wrangler whoami
```

If you are using a personal account, that is fine for now.

## Worker Config

The repo is already configured with:

- Worker name: `sandbox`
- compatibility flag: `nodejs_compat`

So after deploy, your Worker URL should be:

```text
https://sandbox.<your-workers-subdomain>.workers.dev
```

## Required Secrets

Set the runtime secrets from inside `workers/sandbox`:

```bash
npx wrangler secret put POSTGRES_URL
npx wrangler secret put MONGODB_URI
npx wrangler secret put MONGODB_DATABASE
```

Use values appropriate for your environment.

Example values for the current shared EC2 server:

```text
POSTGRES_URL=postgresql://postgres:teampalm@3.80.87.124:55432/bookreview_db?sslmode=disable
MONGODB_URI=mongodb://3.80.87.124:57017
MONGODB_DATABASE=yelp_db
```

Important:

- if your databases are only reachable on `127.0.0.1`, a deployed Cloudflare
  Worker will not be able to reach them
- for a deployed Worker, the database host must be externally reachable or
  exposed through a tunnel/proxy

## Deploy

Deploy from `workers/sandbox`:

```bash
npx wrangler deploy
```

Wrangler prints the live URL at the end.

## Team .env Value

After deploy, each teammate should set their own sandbox URL:

```env
SANDBOX_URL=https://sandbox.<your-workers-subdomain>.workers.dev
```

Example:

```env
SANDBOX_URL=https://sandbox.<your-workers-subdomain>.workers.dev
```

## Verify The Worker

Health check:

```bash
curl -sS "$SANDBOX_URL/health"
```

Expected result:

```json
{
  "status": "ok",
  "service": "oracle-forge-sandbox",
  "version": "1.0.0"
}
```

## Verify Sandbox Execution

Test an extraction-style sandbox call:

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

Expected shape:

```json
{
  "result": {
    "sentiment": "positive",
    "text": "This book is amazing, loved every page",
    "source": "review"
  },
  "trace": [...],
  "validation_status": "PASSED",
  "error_if_any": null
}
```

Test a merge-style sandbox call:

```bash
curl -sS "$SANDBOX_URL/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "code_plan": "{\"operation\":\"merge_on_key\",\"left_input\":\"postgres_rows\",\"right_input\":\"mongo_docs\",\"left_key\":\"business_id\",\"right_key\":\"business_id\",\"join_type\":\"inner\",\"require_repaired\":false,\"repaired\":true}",
    "trace_id": "manual-merge-check",
    "db_type": "merge",
    "inputs_payload": {
      "postgres_rows": [{ "business_id": "b1", "title": "Cafe Blue" }],
      "mongo_docs": [{ "business_id": "b1", "category": "Cafe" }]
    },
    "step_id": "manual-merge"
  }'
```

## Verify Runtime Integration

From the repo root, first start MCP:

```bash
./setup_dab.sh
```

Then verify MCP tools:

```bash
./bin/toolbox invoke --config mcp/tools.yaml preview_books_info
./bin/toolbox invoke --config mcp/tools.yaml find_yelp_businesses
```

Then run the local architecture demo:

```bash
python3 main.py runtime-sandbox-demo
```

This shows:

- MCP-style DB reads
- sandbox merge step
- self-correction retry after sandbox validation failure

If your deployed Worker is configured and reachable, you can also run:

```bash
python3 main.py real-runtime-sandbox-demo
```

This uses:

- real MCP toolbox calls for DB reads
- real sandbox HTTP calls for merge/transform

## Troubleshooting

### `Could not resolve "net"` / `tls` / `crypto`

Make sure the active Wrangler config includes:

```json
"compatibility_flags": ["nodejs_compat"]
```

In this repo that is already set in:

- `workers/sandbox/wrangler.jsonc`
- `workers/sandbox/wrangler.toml`

### Worker deploys but DB calls time out

That usually means Cloudflare can reach the Worker, but the Worker cannot reach
the database host.

Check:

- Docker ports are published on the host
- the database listens on non-local interfaces
- host firewall rules are open
- cloud/network security rules allow inbound access

### Team Wants A Shared URL Later

If the team later creates a shared Cloudflare account, redeploy the same Worker
from that account. The URL will then become:

```text
https://sandbox.<team-subdomain>.workers.dev
```

Only the account-level `workers.dev` subdomain changes. The code and repo
configuration can stay the same.
