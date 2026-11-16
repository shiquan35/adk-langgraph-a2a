# Building agents using LangGraph

## Combined sales pipeline

Run `uv sync`, then `uv run sales-pipeline` from the repository root to prepare
the shared sales dataset and generate the monthly sales amount chart in one run.
No intermediate JSON file is created; a parent LangGraph invokes both compiled
child graphs sequentially in memory.

```sh
uv run sales-pipeline
uv run sales-pipeline --csv-path dataset/shared_sales_dataset.csv --output langgraph/outputs/custom.html
```

The CSV defaults to `dataset/shared_sales_dataset.csv` and the HTML to
`langgraph/outputs/monthly_sales_amount.html`. Relative paths resolve from the
repository root. The chart remains offline-capable and is not opened automatically.
The standalone `sales-data` and `sales-chart` commands remain available.

Stdout contains one compact JSON line with `status`, `preparation_result`,
`chart_result`, and `error`. Child results are retained unchanged, including
quarantines, normalization audit, monthly totals, and chart provenance. Errors
have `stage` (`preparation` or `chart`), `code`, and `message`.

- Exit **0**: `completed`, clean chart generated.
- Exit **1**: `completed_with_warnings`, partial-data chart generated.
- Exit **2**: `failed`, preparation/no-data/chart failure.

Failed or empty preparation skips chart generation and returns null
`chart_result`; no-data errors use `no_valid_records`. Expected child errors
retain the child's error code/message. Unexpected child exceptions use
`unexpected_stage_error`, preserve earlier results, and set the throwing child's
result to null. Existing HTML remains unchanged on normal preparation/render
failures; unexpected failures after side effects do not promise rollback.

```python
from sales_pipeline_agent import graph

result = graph.invoke({})
# Optional input keys: csv_path and output_path (strings or None).
```

Parent wrappers forward LangGraph execution configuration for callbacks and
tracing. Parent/child diagnostics go to stderr with a shared `pipeline_run_id`
and the children's own `run_id` values. Unexpected exceptions include stack
evidence in logs, not stdout; arbitrary exception messages are excluded. Enable
DEBUG on the agent loggers for safe node argument/result previews. Programmatic
use never configures handlers; the CLI restores logger settings after execution.
There are no automatic retries, added timeouts, streaming CLI, or checkpoints.

## Sales CSV preparation agent

From the repository root, run `uv sync` and activate the environment with
`source .venv/bin/activate`. Trigger the standalone compiled graph with
`uv run sales-data`. It defaults to the shared dataset under the repository's
dataset directory. Override it with `uv run sales-data --csv-path /path/to/sales.csv`.
Relative CSV paths resolve from the repository root, not your current directory.
Use `uv run sales-data --help` for command help.

The command writes one JSON result to stdout and structured diagnostics to stderr.
It does not write a cleaned-data file or use an LLM. The result contains:

- `status`: `completed`, `completed_with_errors`, or `failed`.
- `records`: valid rows in source order; quantities are integers, dates are ISO
	date strings, and prices are exact two-decimal strings (currency unspecified).
- `quarantined_rows`: original values, starting physical CSV line number, and all
	validation issues for each rejected row.
- `report`: resolved source path, row counts, normalization audit, and file issues.

Exit codes are **0** for clean completion, **1** for rejected rows or header-only
data, and **2** for file-level failure. File failures still emit the JSON envelope
and bypass row validation. Normalization alone does not make a clean run fail.

The seven headers must match exactly, in any order. CSV structure is checked
before Pandas processing; duplicate headers, wrong-width rows, and malformed
quoting fail the entire file. Valid quoted multiline fields retain their starting
physical line number. Blank lines are wrong-width records, not silently skipped.

Only surrounding whitespace and valid numeric representations are normalized.
Missing values are never inferred. Unknown labels, invalid dates/numbers, all
duplicate order IDs, and incorrect product/category pairs are quarantined.
Prices needing rounding are rejected (`39.900` becomes `"39.90"`, but `39.999`
is invalid).

For programmatic composition, import `graph` from `sales_data_agent` and invoke it
with `{}` or `{"csv_path": "dataset/shared_sales_dataset.csv"}`. The public graph
output is the same JSON-serializable result, without internal DataFrames.

Source is under `langgraph/src/sales_data_agent/` and tests under `langgraph/tests/`.
Run `uv run pyright` for typechecking, `uv run pytest` for tests, and
`uv run ruff check langgraph` for linting. Programmatic callers can enable DEBUG
logging on the `sales_data_agent` logger for node and normalization diagnostics;
full row dumps are deliberately excluded.

## Monthly sales amount chart agent

Run `uv sync` from the repository root to install both agents and Plotly. Save
Agent 1's JSON output, then generate an offline interactive chart:

```sh
uv run sales-data > langgraph/source_result.json
uv run sales-chart --input langgraph/source_result.json
uv run sales-chart --input langgraph/source_result.json --output langgraph/outputs/custom.html
```

Both input and output relative paths resolve from the repository root, not the
current directory. The default output is
`langgraph/outputs/monthly_sales_amount.html`. Parent directories are created;
successful runs replace the HTML atomically, and failed runs leave an existing
chart untouched. The command does not open a browser. Plotly JavaScript is
embedded so the chart works offline.

The chart plots monthly sums of `quantity × unit_price` by the order placement
date. Months without orders have no point; a true date axis preserves calendar
spacing. The title is **Monthly Sales Amount**, axes are **Order month** and
**Sales amount**, and hover shows `YYYY-MM` and the exact two-decimal total.
No currency or recognized revenue is inferred. Partial input is visibly labeled
`Partial input: N rows quarantined`.

The JSON result has:

- `status`: `completed`, `completed_with_warnings`, or `failed`.
- `output_path`: resolved absolute path after a successful write, otherwise null.
- `monthly_totals`: sorted `{month, sales_amount}` entries; amounts are exact
	decimal strings, even though plotted values are finite numeric approximations.
- `source_status`, `source_row_count`, `valid_row_count`, and
	`quarantined_row_count`: source provenance; unavailable counts are null.
- `error`: `{code, message}` on failure, otherwise null. Unavailable totals are
	an empty list; render failures retain already-computed totals.

Exit codes are **0** for clean generation, **1** for a generated chart from
partial input, and **2** for input/validation/render failures. After argument
parsing, stdout contains one compact JSON line and diagnostics go to stderr;
argument usage errors use normal argparse output without a result envelope.

The agent accepts `completed` and `completed_with_errors` source results with
records. It rejects failed/unknown statuses, zero records, malformed records,
and array/report count or status inconsistencies. Counts must be non-negative
integers (not booleans), equal the supplied array lengths, and reconcile to the
source total. Clean status requires no quarantines; partial status with valid
records requires quarantines. Record dates and two-decimal price strings must
be canonical, text fields non-empty, and quantities positive integers excluding
booleans. Agent 2 does not repair records or repeat Agent 1's catalog validation.

For in-memory composition (no intermediate JSON file required):

```python
from sales_data_agent import graph as preparation_graph
from sales_chart_agent import graph as chart_graph

source_result = preparation_graph.invoke({})
chart_result = chart_graph.invoke({"source_result": source_result})
# Optional: {"source_result": source_result, "output_path": "langgraph/outputs/custom.html"}
```

Source is under `langgraph/src/sales_chart_agent/`; focused tests are
`langgraph/tests/test_sales_chart_graph.py` and
`langgraph/tests/test_sales_chart_cli.py`. Enable DEBUG on the `sales_chart_agent`
logger to inspect node inputs/outputs and monthly totals. It never configures
the root logger, and CLI logging settings are restored on return.
