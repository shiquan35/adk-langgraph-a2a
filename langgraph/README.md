# Building agents using LangGraph

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
