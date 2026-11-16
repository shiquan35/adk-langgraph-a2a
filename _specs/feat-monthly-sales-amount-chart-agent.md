# Monthly Sales Amount Chart Agent

> 🌿 **Branch:** `feat/monthly-sales-amount-chart-agent` · 📅 **Date:** 2026-11-16

## Problem & Solution
**Problem:** Agent 1 prepares validated sales records, but there is no way to turn its result into a reusable monthly visualization.

**Solution:** Add a deterministic LangGraph agent and `sales-chart` CLI that validates Agent 1 output, aggregates monthly sales amount, and writes a standalone interactive HTML chart.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Runtime and packaging | Python 3.11+, uv, existing LangGraph project; package feature code under `langgraph/src` | Match repository setup and avoid shadowing the installed `langgraph` dependency |
| Constraint | Source data contract | Consume Agent 1's JSON-serializable `Result`; record dates are `YYYY-MM-DD`, quantities positive integers, and unit prices positive two-decimal strings | Reuse the validated contract in `sales_data_agent.models` |
| Constraint | Scope | New agent source/tests/docs under `langgraph/`; only root `pyproject.toml` and `uv.lock` may change outside it | Keep A2A and ADK examples isolated |
| Choice | Chart and measure | Plotly interactive line chart of monthly sales amount only; title “Monthly Sales Amount”; axes “Order month” and “Sales amount” | Avoid implying a currency or recognized revenue |
| Choice | Aggregation | Sum `quantity × unit_price` by order-date calendar month with `Decimal`; sort chronologically and omit months without orders | Preserve exact totals and follow the domain definition |
| Choice | Partial input | Chart valid records from `completed_with_errors`; return `completed_with_warnings` and annotate “Partial input: N rows quarantined” | Make partial coverage visible in both artifact and result |
| Choice | Input failures | Reject failed/unknown statuses, inconsistent source counts/status, zero records, or any malformed record; do not write a chart | Prevent silent omission or misleading charts/annotations |
| Choice | Record contract | Require canonical ISO dates and two-decimal price strings, non-empty text fields, and positive non-boolean integer quantities; do not repeat catalog validation | Detect malformed or altered Agent 1 output without duplicating its domain checks |
| Choice | Output | Default `langgraph/outputs/monthly_sales_amount.html`; relative paths resolve from repository root; create parents, do not open a browser | Predictable CLI and composable automation |
| Choice | Safe writes | Render to a temporary sibling file and atomically replace target only after success | Preserve an existing chart on failure |
| Choice | Result and CLI | Return status, absolute written path or null, exact decimal-string monthly totals, source status/counts, and `{code, message}` error or null; CLI emits one compact JSON line | Machine-readable programmatic and shell contracts |
| Choice | Exit codes | `0` clean generation, `1` partial-input generation, `2` invalid/no data or read/render failure | Let shell callers distinguish outcomes |
| Choice | HTML portability | Embed Plotly JavaScript; no CDN dependency | Chart remains interactive offline |

## Architecture

```text
sales-chart --input result.json [--output path.html]
        │ read JSON (CLI errors become failure result)
        ▼
┌─────────────────────┐
│ LangGraph: validate │──invalid──┐
└──────────┬──────────┘           │
           ▼                      │
┌─────────────────────┐           │
│ Decimal aggregation │           │
└──────────┬──────────┘           │
           ▼                      │
┌─────────────────────┐           │
│ Plotly HTML render  │──failure──┤
│ temp + atomic replace│          │
└──────────┬──────────┘           │
           └──────────────┬───────┘
                          ▼
                  result envelope
                    ├─ stdout JSON (CLI)
                    └─ logs to stderr
```

- Package `sales_chart_agent` alongside `sales_data_agent`; list both module names in uv build configuration.
- Graph input is `{source_result: Agent1Result, output_path: str | None}`. Omitted path uses the default above. The CLI loads `--input` JSON and passes the mapping to the same graph.
- Graph nodes validate the source contract, aggregate values, render safely, and assemble a result. Validation/render failures route to result assembly without replacing the target.
- Result fields: `status` (`completed`, `completed_with_warnings`, `failed`), `output_path`, `monthly_totals` (`[{month: "YYYY-MM", sales_amount: "<exact decimal>"}]`), `source_status`, `source_row_count`, `valid_row_count`, `quarantined_row_count`, and `error` (`{code, message}` or null). Unavailable counts/status are null; unavailable totals are an empty list.
- Accept only Agent 1 statuses `completed` and `completed_with_errors`. Require non-negative integer report counts (excluding booleans) and enforce `len(records) == report.valid_rows`, `len(quarantined_rows) == report.quarantined_rows`, and `report.source_rows == report.valid_rows + report.quarantined_rows`. `completed` requires zero quarantines; `completed_with_errors` requires at least one quarantine when valid records exist. Extract provenance counts from Agent 1's `report` (`source_rows`, `valid_rows`, `quarantined_rows`).
- Resolve input and output relative paths from repository root. The CLI emits one compact JSON object plus newline after argument parsing; diagnostics remain on stderr. Argparse usage errors retain normal argparse behavior.

## Code Shape

- `langgraph/src/sales_chart_agent/models.py`: typed graph input/state, monthly totals, status, and result envelope.
- `validation.py`: validate envelope/count/status invariants, required record fields/types, exact ISO calendar dates, positive integer quantities, and canonical finite positive two-decimal price strings.
- `aggregation.py`: use `Decimal` to group `quantity × unit_price` by `YYYY-MM`; sort and serialize exact totals.
- `rendering.py`: construct the labeled Plotly line chart, partial-input annotation, and self-contained HTML; convert totals to finite numeric plot values and atomically replace the target.
- `graph.py`: deterministic validation → aggregation → rendering → result graph with failure routing.
- `cli.py`: parse required `--input` and optional `--output`, translate file/JSON errors into the same failure envelope, print JSON, and map exit codes.
- `observability.py`: structured `sales_chart_agent` logger; never configure the root logger.

## Validation Rules

- Input must contain Agent 1's `status`, `records`, `quarantined_rows`, and `report` contract with arrays/mapping of the expected types. Accept only `completed` or `completed_with_errors`; reject `failed` and unknown statuses.
- `report.source_rows`, `report.valid_rows`, and `report.quarantined_rows` must be non-negative integers (not booleans). Enforce `len(records) == report.valid_rows`, `len(quarantined_rows) == report.quarantined_rows`, and `report.source_rows == report.valid_rows + report.quarantined_rows`.
- `completed` requires `report.quarantined_rows == 0`. `completed_with_errors` requires at least one quarantined row whenever valid records exist. Reject any status/count contradiction.
- Require at least one record. Reject the entire input if a record is malformed; do not skip records.
- Each record requires string `order_id`, `date`, `product`, `category`, `region`, and `unit_price`, plus positive integer `quantity` (explicitly reject booleans). Require `order_id`, `product`, `category`, and `region` to be non-empty after trimming; do not repeat product/category/region catalog validation.
- `date` must be exactly `YYYY-MM-DD` and a real calendar date. `unit_price` must be a canonical string with exactly two fractional digits (for example, `"39.90"`, not `"39.9"`), and parse as finite, positive `Decimal`.
- Calculate each record's sales amount as `Decimal(quantity) × Decimal(unit_price)`. Result totals remain exact decimal strings; Plotly values must convert to finite numbers. A non-finite conversion is a render failure.
- Months without orders have no point. The x-axis is a true date axis with `YYYY-MM` labels; hover shows month and sales amount with two decimal places and no currency symbol.
- On input, aggregation, or render failure, return `failed`, `output_path: null`, an empty totals list when unavailable, and a stable error code plus concise message. Preserve any pre-existing target.

## Implementation Plan

### Phase 1: Build the chart graph and renderer
| File | What changes |
|---|---|
| `pyproject.toml` | Add Plotly runtime dependency and package both `sales_data_agent` and `sales_chart_agent`. |
| `uv.lock` | Lock Plotly and its dependencies. |
| `langgraph/src/sales_chart_agent/__init__.py` | Expose the compiled graph. |
| `langgraph/src/sales_chart_agent/models.py` | Define typed input, state, total, status, and result shapes. |
| `langgraph/src/sales_chart_agent/validation.py` | Validate Agent 1 envelope and every record. |
| `langgraph/src/sales_chart_agent/aggregation.py` | Compute exact sorted monthly totals. |
| `langgraph/src/sales_chart_agent/rendering.py` | Render self-contained Plotly HTML and atomically replace output. |
| `langgraph/src/sales_chart_agent/graph.py` | Add deterministic nodes, failure routing, and result assembly. |
| `langgraph/src/sales_chart_agent/observability.py` | Add structured, opt-in feature logging. |
| `langgraph/tests/test_sales_chart_graph.py` | Cover contract validation, aggregation, HTML, and preservation on failure. |

- [ ] Add Plotly and package-discovery configuration; lock dependencies with uv.
- [ ] Implement typed graph, validation, exact aggregation, safe rendering, and result assembly.
- [ ] Test clean/partial results, invalid input, exact totals, chart semantics, and atomic failure behavior.

### Phase 2: Add CLI and usage documentation
| File | What changes |
|---|---|
| `pyproject.toml` | Register `sales-chart = "sales_chart_agent.cli:main"`. |
| `langgraph/src/sales_chart_agent/cli.py` | Implement input/output arguments, JSON/file error envelopes, stdout/stderr behavior, and exit codes. |
| `langgraph/README.md` | Document Agent 2 invocation, output, statuses, and graph composition. |
| `langgraph/tests/test_sales_chart_cli.py` | Cover help, paths, JSON stdout, stderr diagnostics, file failures, and exit codes. |

- [ ] Add and test the `sales-chart` console command.
- [ ] Document direct graph use and CLI operation.

## Acceptance Criteria

- `uv sync --locked` succeeds; `uv run sales-chart --help` displays required `--input` and optional `--output`.
- The graph accepts an Agent 1 result mapping directly; CLI relative input/output paths resolve from repository root.
- Valid inputs produce chronologically ordered monthly Decimal sums, exact decimal-string result values, and self-contained interactive Plotly HTML with the specified title, axes, labels, and hover values.
- Missing months are omitted; partial source rows produce `completed_with_warnings` and the specified quarantine annotation.
- Failed/unknown source status, inconsistent array/report counts, status/count contradictions, no valid records, malformed JSON/envelope/record, noncanonical dates/prices, invalid values, and rendering errors produce a failure envelope and exit code 2; partial success exits 1 and clean success exits 0.
- Failed runs never replace an existing target; successful runs create parent directories and replace the target atomically.
- CLI writes exactly one compact JSON line to stdout after argument parsing; logs/diagnostics go to stderr.
- Source, tests, and feature docs remain under `langgraph/`; no files under `a2a/` or `adk/` change.
- `uv run pyright`, `uv run ruff check langgraph`, and `uv run pytest -q` pass.

## Testing

- Assert aggregation across multiple records/months, year boundaries, chronological order, omitted no-order months, and exact decimal strings.
- Verify chart title, axis labels, `YYYY-MM` month labels, hover formatting, partial annotation, and embedded Plotly JavaScript.
- Exercise every Agent 1 status; missing/invalid envelope keys; report counts that disagree with either array or each other; status/count contradictions; malformed record fields; blank text; noncanonical/impossible dates; boolean/non-positive quantities; noncanonical prices (including `"39.9"`), zero, negative, and non-finite prices; and no-record results.
- Assert failures return the documented envelope and leave an existing target byte-for-byte unchanged; simulate render/write errors and verify temporary files are cleaned up.
- Run CLI tests for valid, partial, missing/unreadable input, malformed JSON, output override, relative path resolution, stdout/stderr separation, and exit codes. Argument-parser errors need not emit an envelope.

## Logging

Use structured JSON logs through a dedicated `sales_chart_agent` logger; never configure the root logger. Attach a run ID to each event. Emit entry and exit events for each graph node, recording its actual arguments and returned values (representative record details and all monthly totals, not every source record or full HTML). Keep stdout reserved for the CLI result.

| Event | Level | Fields | Example |
|---|---|---|---|
| Agent started | `info` | `run_id`, `source_status`, `input_path`, `output_path` | `{"event":"agent_started","run_id":"chart-8c31","source_status":"completed","input_path":"result.json","output_path":"/Users/ongshiquan/Documents/GitHub/adk-langgraph-a2a/langgraph/outputs/monthly_sales_amount.html"}` |
| Node entry | `debug` | `run_id`, `node`, `args` | `{"event":"node_entry","run_id":"chart-8c31","node":"validate_input","args":{"source_status":"completed","record_preview":{"date":"2026-01-05","quantity":2,"unit_price":"12.50"}}}` |
| Node exit | `debug` | `run_id`, `node`, `return_preview`, `duration_ms` | `{"event":"node_exit","run_id":"chart-8c31","node":"aggregate_monthly","return_preview":{"monthly_totals":[{"month":"2026-01","sales_amount":"25.00"}]},"duration_ms":1.8}` |
| Envelope rejected | `warning` | `run_id`, `code`, `message`, `records_length`, `reported_valid_rows` | `{"event":"input_rejected","run_id":"chart-8c31","code":"inconsistent_source_report","message":"records length does not match report.valid_rows","records_length":1,"reported_valid_rows":95}` |
| Input rejected | `warning` | `run_id`, `code`, `message`, 1-based `record_index`, `field`, `observed_value` | `{"event":"input_rejected","run_id":"chart-8c31","code":"invalid_unit_price","message":"Price must be positive and exact to cents","record_index":2,"field":"unit_price","observed_value":"4.999"}` |
| Render failed | `error` | `run_id`, `output_path`, `code`, `message` | `{"event":"render_failed","run_id":"chart-8c31","output_path":"/Users/ongshiquan/Documents/GitHub/adk-langgraph-a2a/langgraph/outputs/monthly_sales_amount.html","code":"html_write_failed","message":"Permission denied"}` |
| Agent finished | `info` | `run_id`, `status`, `output_path`, `monthly_totals`, `exit_code` | `{"event":"agent_finished","run_id":"chart-8c31","status":"completed","output_path":"/Users/ongshiquan/Documents/GitHub/adk-langgraph-a2a/langgraph/outputs/monthly_sales_amount.html","monthly_totals":[{"month":"2026-01","sales_amount":"25.00"}],"exit_code":0}` |

## Edge Cases

- A source with `completed_with_errors` but no valid records must fail without writing an empty chart.
- Mismatches among record/quarantine array lengths and `report` counts, or a status inconsistent with those counts, must fail before aggregation or rendering.
- Canonical Agent 1 prices such as `"39.90"` are accepted; alternate spellings such as `"39.9"` are rejected rather than normalized.
- Missing months remain absent while the true date axis retains calendar spacing.
- A valid Decimal total that cannot be represented as a finite Plotly number must fail before replacing the target.
- Output-parent creation may succeed before rendering fails; the target file itself must remain unchanged.
- Invalid JSON or unreadable CLI input must still produce a failure envelope after argparse succeeds.

## Risks & Unknowns

- No unresolved design questions remain from the grill. Plotly chart values are finite numeric approximations; the result envelope remains the exact Decimal-string source of truth.

## Out of Scope

- Additional chart types/series, currency inference, revenue recognition, data repair or row skipping, browser launching, A2A/ADK integration, and LLM use.

## Docs to Update

_N/A — no root `INDEX.md` exists; skipped per planning instructions. Update `langgraph/README.md` as listed in Phase 2._
