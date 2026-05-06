# scripts — Entrypoints and Helpers

Scripts and wrappers used from the repo root.

| File | Purpose |
| --- | --- |
| [setup_dab.sh](setup_dab.sh) | Start MCP Toolbox (Docker) + DuckDB MCP (Python). Invoked by `./setup_dab.sh` at the repo root. |
| [scaffold_bench.py](scaffold_bench.py) | Scaffold `runs/<dataset>/queryN/` directories from DAB — creates `query.json`, `ground_truth.csv`, `validate.py` |
| [score_bench.py](score_bench.py) | Score a scaffolded run against its ground truth |
| [run_bookreview_query.py](run_bookreview_query.py) | BookReview-specific benchmark runner (legacy; prefer `run_agent.py`) |
| [main.py](main.py) | Simple entrypoint used by older demos |

## Common flows

**Scaffold a dataset, then run it:**

```bash
uv run python scripts/scaffold_bench.py --dataset agnews
uv run python run_agent.py --dataset agnews --query query1 --root_name run_0
uv run python scripts/score_bench.py --dataset agnews --root_name run_0
```

**Start MCP services:**

```bash
./setup_dab.sh   # root wrapper → scripts/setup_dab.sh
```
