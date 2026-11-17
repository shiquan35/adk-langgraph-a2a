# Building agents using Google ADK

## Sales CSV-to-chart workflow

Implemented with Google ADK's graph-based `Workflow` and deterministic `BaseNode` stages: prepare CSV data, then validate and aggregate it into an offline Plotly monthly sales amount chart. Invalid rows are quarantined; chartable partial data produces a warning chart; failed or empty preparation skips charting and fails the parent run.

No LLM, model credentials, or external model calls are used. Preparation and visualization logic is copied into this package rather than invoking LangGraph graphs; parity tests compare their results with the existing implementation.

## CLI usage

Run from the repository with dependencies installed by `uv sync --group dev`:

- Parent workflow: `uv run adk-sales run`.
- Custom CSV and destination: `uv run adk-sales run --csv-path dataset/shared_sales_dataset.csv --output-dir adk/outputs`.
- Standalone preparation: `uv run adk-sales ingest --csv-path dataset/shared_sales_dataset.csv --output adk/outputs/prepared.json`.
- Standalone charting: `uv run adk-sales chart --input adk/outputs/prepared.json --output-dir adk/outputs`.

### Path resolution

All relative input and output paths resolve against the repository root, not the current working directory; absolute paths are accepted. `ADK_SALES_ROOT` overrides discovery and must name an existing directory. Otherwise, discovery checks the current working directory and its parents, then the module location and its parents, for both the dataset and project metadata. A clean installed wheel outside a checkout cannot infer an unrelated repository: set `ADK_SALES_ROOT` to the checkout's absolute path before running `adk-sales`. Missing discovery or an invalid override produces an explicit error rather than writing into site-packages.

The default CSV is [dataset/shared_sales_dataset.csv](../dataset/shared_sales_dataset.csv). `run` and `chart` default to `adk/outputs`, publishing `monthly_sales_amount.html` (self-contained HTML) and `monthly_sales_amount.json`. `ingest` writes no artifact unless `--output` is supplied; that file contains the full preparation envelope, including an ordinary failed preparation result.

After argument parsing, each command emits one compact JSON envelope to stdout; diagnostics go to stderr. Exit status is **0** for `completed`, `completed_with_errors` (preparation), and `completed_with_warnings` (chart/parent), and **2** for failure. Invalid CLI arguments also exit 2 via argparse.

## Result contracts and runtime

- `ingest`: `{status, records, quarantined_rows, report}`. The report includes source path, row counts, normalization changes, and file issues.
- `chart`: `{status, output_path, monthly_totals, source_status, source_row_count, valid_row_count, quarantined_row_count, error}`. Monthly totals contain `month` and exact decimal-string `sales_amount` values.
- `run`: `{status, preparation_result, chart_result, error}`. Children retain the standalone shapes; a skipped or unexpectedly interrupted child is null. Parent errors include `stage`, `code`, and `message`; completed earlier-stage results are retained.

Each call uses a real ADK `Runner`, a fresh `InMemorySessionService` session, and invocation-scoped `temp:` shared state for child handoff and parent assembly. State is not persisted between invocations; the runner closes after execution.

Chart generation validates rendering without writing files or creating directories. Its successful `output_path` is an intended destination, not proof of publication. Only the CLI artifact publisher writes chart files: it renders/serializes and stages **both** complete files beside their destinations before atomically replacing HTML, then JSON. This is atomic per file, **not** a pair transaction. A prepublication or first-replacement failure preserves existing files; a second-replacement failure may leave new HTML with old JSON. Publication failure is reported on stdout with `artifact_write_failed` and exit 2, without republishing the failure JSON or rolling back HTML. Parent child results remain unchanged.

## Verification

- ADK tests: `uv run pytest -q adk/tests`.
- Full regression suite: `uv run pytest -q`.
- Focused lint/format checks: `uv run ruff check adk` and `uv run ruff format --check adk`.

The ADK suite covers real Runner state handoff, routing and isolated sessions, copied-logic parity, CLI envelopes, repository discovery, and publication failures. Packaging uses Hatchling with explicit multi-root wheel packages; wheel/sdist construction and archive inspection have demonstrated that layout. Clean-installed wheel verification succeeded outside the checkout with `ADK_SALES_ROOT` set: the ADK workflow processed the supplied dataset end-to-end, and help checks passed for `adk-sales` and the existing `sales-data`, `sales-chart`, and `sales-pipeline` commands.

See the [workflow specification](../_specs/feat-adk-sales-workflow.md) and [ADR 0001](../docs/adr/0001-adk-workflow-and-package-layout.md) for the contract and architectural decisions.
