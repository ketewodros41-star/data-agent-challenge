# tests — Top-Level Test Suites

Cross-component tests that exercise the full system. Unit tests tied to a single component live next to that component (e.g. [agent/tests/](../agent/tests/), [utils/tests/](../utils/tests/)).

## Layout

| Path | Purpose |
| --- | --- |
| [unit/](unit/) | Top-level unit tests that do not fit inside a single component |
| [integration/](integration/) | End-to-end integration tests (require MCP + sandbox running) |
| [property/](property/) | Property-based tests (Hypothesis) |

## Running

```bash
# Everything
uv run pytest -v

# Just integration (requires ./setup_dab.sh + SANDBOX_URL)
uv run pytest tests/integration -v

# Property tests with a pinned seed (reproducible)
uv run pytest tests/property --hypothesis-seed=0
```
