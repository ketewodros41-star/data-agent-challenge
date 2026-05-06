# runs — DAB-Compatible Query Scaffolds

Per-dataset, per-query scaffolds in the exact format DataAgentBench expects.

## Layout

```
runs/
  <dataset>/
    query1/
      query.json          # the natural-language question
      ground_truth.csv    # expected answer rows
      validate.py         # DAB validator
      logs/
        data_agent/
          <root_name>/    # one directory per run (e.g. run_0, run_1)
            final_agent.json
            llm_calls.jsonl
            tool_calls.jsonl
    query2/
      ...
```

## How entries get created

Scaffolded from DAB by [scripts/scaffold_bench.py](../scripts/scaffold_bench.py):

```bash
uv run python scripts/scaffold_bench.py --dataset agnews
```

## How runs get produced

Executed by [run_agent.py](../run_agent.py):

```bash
uv run python run_agent.py --dataset agnews --query query1 --root_name run_0
uv run python run_agent.py --dataset agnews --all --root_name run_0
```

Each run is written into `logs/data_agent/<root_name>/` alongside the query.

## Datasets scaffolded

`agnews`, `bookreview`, `crmarenapro`, `deps_dev_v1`, `github_repos`, `googlelocal`, `music_brainz_20k`, `pancancer_atlas`, `patents`, `stockindex`, `stockmarket`, `yelp`.

`submission.json` at the top of this directory is the aggregated submission bundle.
