# Sales CSV Preparation Agent and CLI

> 🌿 **Branch:** `feat/sales-csv-agent-cli` · 📅 **Date:** 2026-11-16

## Problem & Solution
**Problem:** The repository has no sales-data agent or CLI. The next agent cannot yet rely on consistently typed, validated sales records or inspect rejected rows and cleanup decisions.

**Solution:** Build a deterministic, standalone LangGraph that reads and prepares the sales CSV, then expose it as the `sales-data` uv console command. Return a JSON result; do not write output files.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Runtime and dependencies | Python 3.11+, uv, LangGraph, Pandas | Existing project metadata and the requested stack |
| Constraint | Sales-order meaning | One row is one single-item sales order, keyed by `order_id` | Agreed domain glossary in `CONTEXT.md` |
| Choice | Validation | Deterministic staged graph; no LLM decides validity | Reproducible validation and repair behavior |
| Choice | Invalid records | Quarantine bad rows; reject unreadable, malformed, or wrong-schema files | Preserve valid data without silently skipping input |
| Choice | CLI contract | `uv run sales-data [--csv-path PATH]`; JSON stdout, logs stderr | Explicit CLI trigger and machine-readable output |
| Choice | Exit codes | `0` clean; `1` quarantines/empty data; `2` file-level failure | Allows shell callers to distinguish outcomes |

## Architecture

```text
uv run sales-data [--csv-path PATH]
             │
             ▼
      CLI: resolve path ──► invoke compiled graph
             │                        │
             │                 ┌──────▼────────┐
             │                 │ Read + schema │
             │                 └──────┬────────┘
             │                 ┌──────▼────────────┐
             │                 │ Validate/normalize│
             │                 └──────┬────────────┘
             │                 ┌──────▼────────┐
             │                 │ Assemble result│
             │                 └──────┬────────┘
             ◄────────────────────────┘
       JSON to stdout; structured logs to stderr;
       CLI maps result status to exit code
```

- Package the project with uv's build backend so `[project.scripts]` can install the `sales-data` entry point; replace the current `package = false` setting.
- Scope all new Python implementation, tests, and feature documentation to `langgraph/`. Do not add or modify files under `a2a/` or `adk/`. Root `pyproject.toml` and `uv.lock` are the only planned changes outside `langgraph/`, required for dependency and CLI registration.
- Keep `langgraph/` as the existing documentation directory, not a Python package; package `sales_data_agent` from `langgraph/src` to avoid shadowing the installed `langgraph` dependency.
- Graph input: optional `csv_path`; default to `dataset/shared_sales_dataset.csv`. Resolve relative paths from the repository root; accept absolute paths unchanged.
- Graph stages: read/check file and schema → validate and normalize records → assemble one result envelope. Graph returns data in-memory; it does not persist files.

## Code Shape

- `langgraph/src/sales_data_agent/graph.py`: compiled `StateGraph` and staged node functions; `csv_path: str | None` input.
- `langgraph/src/sales_data_agent/validation.py`: schema, catalog, row validation, duplicate detection, and normalization.
- `langgraph/src/sales_data_agent/models.py`: typed graph state and JSON result structures.
- `langgraph/src/sales_data_agent/cli.py:main`: parse `--csv-path`, invoke graph, emit JSON, and select exit code.
- Result envelope:
  - `status`: `completed`, `completed_with_errors`, or `failed`.
  - `records`: valid normalized rows, preserving source order.
  - `quarantined_rows`: each has 1-based physical CSV `line_number`, `raw_values`, and all `{code, message}` issues.
  - `report`: resolved `source_path`, source/valid/quarantined counts, normalization-change count and entries (`line_number`, `field`, `original_value`, `normalized_value`), and file-level issues.
- Record fields remain the seven CSV fields. Serialize `date` as `YYYY-MM-DD`, `quantity` as an integer, and `unit_price` as a fixed two-decimal string; keep `unit_price` currency-unspecified.

## Validation Rules

- Require exactly `order_id`, `date`, `product`, `category`, `region`, `quantity`, `unit_price`; names are case-sensitive, order may vary, extras/missing columns fail the file.
- Read values without Pandas' default NA-token conversion; blank or whitespace-only cells are missing. Literal strings such as `NA` are not missing markers.
- Trim surrounding whitespace and record each change. Do not infer missing values or alter labels' case.
- `order_id`: non-empty text; unique within the file after trimming; comparisons are case-sensitive. Quarantine every row in a duplicate group.
- `date`: valid calendar date in exact `YYYY-MM-DD` form; output in the same canonical form. It means the order placement date.
- `quantity`: positive whole number. Plain decimal input such as `3.0` is accepted and normalized to integer `3`.
- `unit_price`: finite positive decimal in plain decimal notation; reject currency symbols and thousands separators; serialize to two decimal places. No currency is inferred.
- `product`, `category`, `region`: exact case-sensitive catalog labels after trimming. Enforce product/category pairings:
  - Mechanical Keyboard, Laptop Stand, USB-C Hub, Wireless Mouse → Accessories
  - Headphones, Desktop Speaker → Audio
  - 27-inch Monitor → Displays
  - Webcam → Electronics
  - Categories: Accessories, Audio, Displays, Electronics
  - Regions: East, North, South, West (customer destination)
- Collect all row issues, retain invalid rows in quarantine with original values, and preserve source order in both output lists. Do not add derived fields such as line totals.
- A header-only CSV returns `completed_with_errors` with `empty_dataset`. Unreadable files, malformed CSV rows, and schema mismatches return `failed` with the same envelope and no records.
- Use stable issue codes (for example `missing_value`, `invalid_date`, `duplicate_order_id`, `product_category_mismatch`, `invalid_quantity`, `invalid_unit_price`, `schema_mismatch`, `malformed_csv`, `empty_dataset`) plus readable messages.

## Implementation Plan

### Phase 1: Build the data-preparation graph
| File | What changes |
|---|---|
| `pyproject.toml` | Add Pandas at runtime, pytest to the `dev` dependency group, and configure uv build/package discovery with `module-root = "langgraph/src"`. |
| `uv.lock` | Lock the new runtime and test dependencies. |
| `langgraph/src/sales_data_agent/__init__.py` | Define the package surface. |
| `langgraph/src/sales_data_agent/models.py` | Define typed state, record, issue, and result shapes. |
| `langgraph/src/sales_data_agent/validation.py` | Implement schema/catalog/type checks, duplicate handling, and normalization audit. |
| `langgraph/src/sales_data_agent/graph.py` | Build and compile the staged deterministic graph. |
| `langgraph/tests/test_validation.py` | Cover valid rows and validation/normalization cases. |
| `langgraph/tests/test_graph.py` | Cover result statuses, ordering, and file-level failures. |

- [ ] Add dependencies and package configuration; run `uv sync`.
- [ ] Implement the typed result contract and staged graph.
- [ ] Add focused validator and graph tests.

### Phase 2: Add CLI and usage documentation
| File | What changes |
|---|---|
| `pyproject.toml` | Register `sales-data = "sales_data_agent.cli:main"` under `[project.scripts]`. |
| `langgraph/src/sales_data_agent/cli.py` | Parse optional `--csv-path`, invoke graph, write JSON to stdout, and map statuses to exit codes. |
| `langgraph/README.md` | Document default invocation, path override, JSON output, and exit codes. |
| `langgraph/tests/test_cli.py` | Exercise help, default/override paths, stdout/stderr, and exit codes. |

- [ ] Implement the CLI and registered console entry point.
- [ ] Document CLI usage and run CLI integration tests.

## Acceptance Criteria

- `uv sync` installs the project, and `uv run sales-data --help` displays the CLI help.
- With no path argument, `uv run sales-data` reads the supplied dataset and emits a JSON envelope with `completed`, 500 valid records, and no quarantines.
- `--csv-path` accepts absolute and repository-root-relative paths; output remains JSON on stdout and logs remain on stderr.
- All feature source, tests, and usage docs remain under `langgraph/`; no files under `a2a/` or `adk/` are added or changed.
- All schema, catalog, type, missing-value, duplicate, normalization, ordering, and error-status rules above are enforced and tested.
- Exit codes are `0` for `completed`, `1` for `completed_with_errors`, and `2` for `failed`; file-level failures still emit the result envelope.
- No LLM is used to validate or repair records, no values are inferred, and no output file is written.

## Testing

- Use the supplied 500-row CSV as the clean-path fixture; assert all rows are valid, canonical types/formatting are emitted, and order is preserved.
- Use small synthetic CSVs for missing/blank cells, literal `NA`, whitespace normalization, invalid/ambiguous dates, invalid quantities/prices, unknown labels, product/category mismatch, and duplicate IDs (verify every duplicate is quarantined).
- Cover reordered headers, missing/extra columns, malformed rows, unreadable paths, and header-only input.
- Assert the full result envelope, physical line numbers, raw quarantine values, all issue codes/messages, normalization audit entries, and all three statuses.
- Run the CLI as a subprocess; assert JSON stdout, diagnostics stderr, path behavior, and exit codes.

## Logging

Use structured logs with a LangGraph run ID (or CLI-generated run ID). Never dump the full CSV or every output record. Include concrete path, issue, and normalization values; keep JSON result output on stdout and logs on stderr.

| Event | Level | Fields | Example |
|---|---|---|---|
| Agent started | `info` | `run_id`, `csv_path` | `{"event":"agent_started","run_id":"cli-7d2a","csv_path":"dataset/shared_sales_dataset.csv"}` |
| Node entry/exit | `debug` | `run_id`, `node`, `args`, `return_preview`, `duration_ms` | `{"run_id":"cli-7d2a","node":"validate_rows","args":{"source_rows":500},"return_preview":{"status":"completed","valid_rows":500,"quarantined_rows":0},"duration_ms":18}` |
| Normalization | `debug` | `run_id`, `line_number`, `field`, `original_value`, `normalized_value` | `{"run_id":"cli-7d2a","line_number":12,"field":"quantity","original_value":"3.0","normalized_value":3}` |
| Row rejected | `warning` | `run_id`, `line_number`, `field`, `code`, `message`, `observed_value` | `{"run_id":"cli-7d2a","line_number":8,"field":"unit_price","code":"invalid_unit_price","message":"Expected a finite positive decimal","observed_value":"NaN"}` |
| File-level failure | `error` | `run_id`, `source_path`, `code`, `message` | `{"run_id":"cli-7d2a","source_path":"dataset/missing.csv","code":"file_not_found","message":"CSV file does not exist"}` |
| Agent finished | `info` | `run_id`, `status`, `source_rows`, `valid_rows`, `quarantined_rows`, `exit_code` | `{"run_id":"cli-7d2a","status":"completed_with_errors","source_rows":10,"valid_rows":8,"quarantined_rows":2,"exit_code":1}` |

## Edge Cases

- Duplicate IDs are found after trimming; every member of each duplicate group is quarantined.
- Product/category labels with wrong case are rejected, not silently corrected.
- `NaN` is not a blank marker; it fails numeric validation where used as a number.
- A valid date-shaped but impossible calendar date is quarantined.
- File/schema/parser failures produce no partially prepared records.

## Risks & Unknowns

- Product, category, and region catalogs are fixed to the supplied dataset; legitimate catalog changes require an explicit code update.
- No unresolved design questions remain from the grill. CLI-specific command, output, logging, and exit behavior were confirmed separately.

## Out of Scope

- The second/analytics agent, A2A serving, LLM-based validation or repair, dynamic catalog management, currency inference, derived revenue fields, and writing prepared data to disk.

## Docs to Update

_N/A — no root `INDEX.md` exists; skipped per planning instructions. CLI usage is included in Phase 2's `langgraph/README.md` change._
