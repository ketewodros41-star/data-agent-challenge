# MCP Manual

This manual explains how teammates should start, access, and test the MCP
services used by this repo.

## Architecture

There are two MCP backends:

1. `Google Toolbox MCP`
- Handles `PostgreSQL`, `MongoDB`, and `SQLite`
- Runs at `http://127.0.0.1:5000`
- UI: `http://127.0.0.1:5000`

2. `DuckDB MCP`
- Handles DuckDB-backed benchmark datasets
- Runs at `http://127.0.0.1:8001`
- UI: `http://127.0.0.1:8001`

The agent routes by database type:

- `postgres` -> Google Toolbox MCP
- `mongodb` -> Google Toolbox MCP
- `sqlite` -> Google Toolbox MCP
- `duckdb` -> DuckDB MCP

## Prerequisites

Each teammate needs:

- this repo checked out locally
- the `DataAgentBench` datasets checked out locally
- Docker available
- the repo virtualenv installed if they want to run the local Python pieces

Recommended local layout:

```text
~/data-agent-challenge
~/DataAgentBench
```

## Required Environment

Set these values before startup:

```bash
export DAB_DATASET_ROOT=~/DataAgentBench
export TOOLBOX_URL=http://127.0.0.1:5000
export DUCKDB_MCP_URL=http://127.0.0.1:8001
```

Or place them in `.env`:

```env
DAB_DATASET_ROOT=/home/<your-user>/DataAgentBench
TOOLBOX_URL=http://127.0.0.1:5000
DUCKDB_MCP_URL=http://127.0.0.1:8001
```

## Startup

From the repo root:

```bash
cd ~/data-agent-challenge
./setup_dab.sh
```

What startup does:

- starts the Google Toolbox container
- mounts the repo into the container at `/workspace`
- mounts `${DAB_DATASET_ROOT}` into the container at `/datasets`
- starts the custom DuckDB MCP service locally
- health-checks both MCP endpoints

## Browser Access

After startup:

- Google Toolbox UI: `http://127.0.0.1:5000`
- DuckDB MCP UI: `http://127.0.0.1:8001`

## Database Mapping

### Google Toolbox MCP

#### PostgreSQL

- source: `postgres_main`
- host: `team-dab-postgres`
- port: `5432`
- database: `bookreview_db`

Tools:

- `list_tables`
- `describe_books_info`
- `preview_books_info`
- `run_query`

#### MongoDB

- source: `mongo_main`
- host: `team-dab-mongo`
- port: `27017`
- database: `yelp_db`

Tools:

- `find_yelp_businesses`
- `find_yelp_checkins`

#### SQLite

These are mounted into the toolbox container under `/datasets`.

Tools:

- `sqlite_bookreview_query`
  path: `/datasets/query_bookreview/query_dataset/review_query.db`
- `sqlite_googlelocal_query`
  path: `/datasets/query_googlelocal/query_dataset/review_query.db`
- `sqlite_agnews_query`
  path: `/datasets/query_agnews/query_dataset/metadata.db`
- `sqlite_crm_core_query`
  path: `/datasets/query_crmarenapro/query_dataset/core_crm.db`
- `sqlite_crm_products_query`
  path: `/datasets/query_crmarenapro/query_dataset/products_orders.db`
- `sqlite_crm_territory_query`
  path: `/datasets/query_crmarenapro/query_dataset/territory.db`

### DuckDB MCP

Tools:

- `duckdb_crm_activities_query`
  path: `${DAB_DATASET_ROOT}/query_crmarenapro/query_dataset/activities.duckdb`
- `duckdb_crm_sales_pipeline_query`
  path: `${DAB_DATASET_ROOT}/query_crmarenapro/query_dataset/sales_pipeline.duckdb`
- `duckdb_deps_dev_v1_query`
  path: `${DAB_DATASET_ROOT}/query_DEPS_DEV_V1/query_dataset/project_query.db`
- `duckdb_github_repos_query`
  path: `${DAB_DATASET_ROOT}/query_GITHUB_REPOS/query_dataset/repo_artifacts.db`
- `duckdb_music_brainz_query`
  path: `${DAB_DATASET_ROOT}/query_music_brainz_20k/query_dataset/sales.duckdb`
- `duckdb_pancancer_query`
  path: `${DAB_DATASET_ROOT}/query_PANCANCER_ATLAS/query_dataset/pancancer_molecular.db`
- `duckdb_stockindex_query`
  path: `${DAB_DATASET_ROOT}/query_stockindex/query_dataset/indextrade_query.db`
- `duckdb_stockmarket_query`
  path: `${DAB_DATASET_ROOT}/query_stockmarket/query_dataset/stocktrade_query.db`
- `duckdb_yelp_query`
  path: `${DAB_DATASET_ROOT}/query_yelp/query_dataset/yelp_user.db`

## Copy-Paste Smoke Tests

### Google Toolbox MCP

List tools:

```bash
curl -sS -X POST http://127.0.0.1:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

List Postgres tables:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/tool/list_tables/invoke \
  -H 'Content-Type: application/json' \
  -d '{}'
```

List SQLite BookReview tables:

```bash
curl -sS -X POST http://127.0.0.1:5000/api/tool/sqlite_bookreview_query/invoke \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT name FROM sqlite_master WHERE type = \"table\" ORDER BY name"}'
```

### DuckDB MCP

List tools:

```bash
curl -sS -X POST http://127.0.0.1:8001/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

List DuckDB tables:

```bash
curl -sS -X POST http://127.0.0.1:8001/api/tool/duckdb_stockmarket_query/invoke \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SHOW TABLES"}'
```

## How To Use The UIs

### Google Toolbox UI

Open `http://127.0.0.1:5000`.

Use:

- `run_query` for PostgreSQL SQL
- `sqlite_bookreview_query` and the other `sqlite_*` tools for SQLite SQL

Important:

- `run_query` is for PostgreSQL, not SQLite

### DuckDB MCP UI

Open `http://127.0.0.1:8001`.

Use the dropdown to choose a DuckDB tool, then run SQL such as:

```sql
SHOW TABLES
```

## Common Problems

### `Hello, World!` at port 5000

That means the server is up. Use the UI or the MCP/API endpoints to test actual
tools.

### `params not defined`

That came from an older broken `run_query` template. The correct template is
now `{{query}}`.

### SQLite file not found

Make sure:

- `DAB_DATASET_ROOT` is correct
- `./setup_dab.sh` was restarted after changing it
- the dataset folder really exists on disk

### DuckDB tool not responding

Check:

```bash
cat duckdb_mcp.log
```

### Google Toolbox not responding

Check:

```bash
cat toolbox.log
docker logs team-dab-toolbox
```
