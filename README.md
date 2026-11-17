# adk-langgraph-a2a

Build agents using Google ADK, LangGraph and using Google A2A protocol.

## Set up

Install [uv](https://docs.astral.sh/uv/), then run this from the repository root:

```sh
uv sync
```

This creates or updates `.venv` and `uv.lock` from `pyproject.toml`. Activate the
environment with `source .venv/bin/activate`, or run commands through uv, for
example `uv run python --version`.

## Manage dependencies

- Add a library: `uv add <package>`
- Add a development-only library: `uv add --dev <package>`
- Remove a library: `uv remove <package>`
- Reconcile the environment after changing dependency declarations: `uv sync`

Commit both `pyproject.toml` and `uv.lock` so everyone gets the same resolved
dependency versions. Use `uv lock --upgrade` when you intentionally want to
refresh locked versions.


## Run workflow

### LangGraph
```bash
uv run sales-pipeline
```

### Google ADK
```bash
uv run adk-sales run
```