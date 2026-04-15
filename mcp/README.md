# MCP Setup Guide

This guide explains how to use the shared MCP Toolbox configuration in this repo so any team member can test and use the current database tools without repeating setup/debugging.

For the full team-facing manual, see [MANUAL.md](/home/bethel/data-agent-challenge/mcp/MANUAL.md).

## What this setup covers

Right now the MCP config supports the shared DAB databases currently running on the team server:

- **PostgreSQL** -> `bookreview_db`
- **MongoDB** -> `yelp_db`

This setup is designed for:

- Docker-networked PostgreSQL and MongoDB sources
- Host-stored benchmark datasets mounted into the toolbox container at `/datasets`
- A separate custom DuckDB MCP service for DuckDB-backed benchmark datasets

---

## Files

- **Toolbox binary:** `bin/toolbox`
- **Project wrapper:** `./toolbox`
- **Docker startup script:** `./setup_dab.sh`
- **MCP config:** `mcp/tools.yaml`

---

## Current database connections

### PostgreSQL
- Host: `team-dab-postgres`
- Port: `5432`
- Database: `bookreview_db`

### MongoDB
- Host: `team-dab-mongo`
- Port: `27017`
- Database: `yelp_db`

### SQLite
- BookReview: `/datasets/query_bookreview/query_dataset/review_query.db`
- GoogleLocal: `/datasets/query_googlelocal/query_dataset/review_query.db`
- AG News: `/datasets/query_agnews/query_dataset/metadata.db`
- CRM Arena Pro core: `/datasets/query_crmarenapro/query_dataset/core_crm.db`
- CRM Arena Pro products/orders: `/datasets/query_crmarenapro/query_dataset/products_orders.db`
- CRM Arena Pro territory: `/datasets/query_crmarenapro/query_dataset/territory.db`

---

## Current tools

### PostgreSQL tools
- `list_tables`
- `describe_books_info`
- `preview_books_info`

### MongoDB tools
- `find_yelp_businesses`
- `find_yelp_checkins`

### SQLite tools
- `sqlite_bookreview_query`
- `sqlite_googlelocal_query`
- `sqlite_agnews_query`
- `sqlite_crm_core_query`
- `sqlite_crm_products_query`
- `sqlite_crm_territory_query`

### DuckDB MCP tools
- `duckdb_crm_activities_query`
- `duckdb_crm_sales_pipeline_query`
- `duckdb_deps_dev_v1_query`
- `duckdb_github_repos_query`
- `duckdb_music_brainz_query`
- `duckdb_pancancer_query`
- `duckdb_stockindex_query`
- `duckdb_stockmarket_query`
- `duckdb_yelp_query`

---

## Current config

The working config is stored in `mcp/tools.yaml`.

## How to test in the SSH instance

From the repo root:

```bash
cd ~/data-agent-challenge

export DAB_DATASET_ROOT=~/DataAgentBench
export DUCKDB_MCP_URL=http://127.0.0.1:8001
./setup_dab.sh

# Browser UIs
# Google Toolbox UI: http://127.0.0.1:5000
# DuckDB MCP UI: http://127.0.0.1:8001

./toolbox invoke list_tables
./toolbox invoke describe_books_info
./toolbox invoke preview_books_info
./toolbox invoke find_yelp_businesses
./toolbox invoke find_yelp_checkins
./toolbox invoke sqlite_bookreview_query '{"sql":"SELECT name FROM sqlite_master WHERE type = \"table\" ORDER BY name"}'
curl -X POST http://127.0.0.1:5000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
curl -X POST http://127.0.0.1:8001/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

The startup script mounts `${DAB_DATASET_ROOT}` into the toolbox container as
`/datasets`. Team configs should reference SQLite files with container paths
such as `/datasets/query_bookreview/query_dataset/review_query.db` rather than
personal host paths like `/home/<user>/DataAgentBench/...`.
