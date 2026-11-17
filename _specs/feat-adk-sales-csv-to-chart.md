# Google ADK Sales CSV-to-Chart Workflow

> 🌿 **Branch:** `feat/adk-sales-csv-to-chart` · 📅 **Date:** 2026-11-17

## Problem & Solution
**Problem:** The repository has no Google ADK sales workflow; users must rely on the separate LangGraph pipeline or manually prepare CSV data and generate a chart.
**Solution:** Add a deterministic ADK workflow that validates/prepares the sales CSV, passes its structured result to a chart stage, and produces an offline monthly sales amount chart. Provide a parent command and independently executable stage commands.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Sales contract | Match `_specs/feat-sales-csv-agent-cli.md`, `_specs/feat-monthly-sales-amount-chart-agent.md`, and `_specs/feat-sales-pipeline-parent-graph-cli.md` | Preserve established domain rules and result semantics. |
| Constraint | Feature location | ADK source, tests, and docs live under `adk/`; existing LangGraph implementation remains unchanged | Keep the examples isolated. |
| Choice | ADK API | Pin `google-adk >=2.14,<2.15`; use graph `Workflow` with deterministic `BaseNode` stages, not deprecated `SequentialAgent` | Use the installed, verified route-based graph API. |
| Choice | Model | No OpenAI/GPT-6 Luna configuration or calls | CSV validation, exact aggregation, and rendering are deterministic. |
| Choice | Stage implementations | Self-contained ADK implementations, with parity tests against LangGraph | Satisfy the requirement that ADK code is under `adk/`; detect duplicated-rule drift. |
| Choice | State and runner | Store JSON-safe stage envelopes in temporary invocation state; run through ADK `Runner` with in-memory sessions | Preserve provenance without cross-run leakage or persistent infrastructure. |
| Choice | CLI | Register `adk-sales run`, `adk-sales ingest`, and `adk-sales chart` | Support the full workflow and standalone stages. |
| Choice | Paths | CSV defaults to `dataset/shared_sales_dataset.csv`; outputs default to `adk/outputs`; all relative paths resolve from repository root; accept `--csv-path` and `--output-dir` overrides | Match existing CLI path conventions while keeping ADK artifacts together. |
| Choice | Artifacts | Use `monthly_sales_amount.html` and `monthly_sales_amount.json`; atomically replace each on successful charting only | Preserve old artifacts on failure; pairwise atomicity is not promised. |
| Choice | CLI results | Print compact JSON to stdout; send diagnostics to stderr. Completed and warning runs exit 0; failures exit 2. | Keep shell integration machine-readable without treating partial data as process failure. |
| Choice | Packaging | First prove whether current `uv_build` can include both source roots; if not, use Hatchling explicit package selection for existing `langgraph/src/*_agent` packages and `adk/src/adk_sales_workflow` | Avoid an unnecessary backend migration; preserve existing script imports and verify wheel/sdist before feature work. |

## Architecture

```text
adk-sales run [--csv-path ...] [--output-dir ...]
                    │
                    ▼
             ADK Runner (memory)
                    │
                    ▼
           Google ADK Workflow
                    │
                    ▼
     [Ingest node: strict CSV + validate]
           │                    │
    valid records          failed / empty
           │                    │
           ▼                    │
 [Chart node: validate + Decimal aggregate]
           │                    │
           ▼                    ▼
       [Result assembly ◄───────┘]
           │
           ├── stdout: parent JSON
           ├── success/warning: HTML + result JSON
           └── failure: preserve prior artifacts
```

The full parent envelope is `{status, preparation_result, chart_result, error}`. The chart node receives the complete prepared-result mapping, not prose or an intermediate file. `error` is null or `{stage, code, message}`, where `stage` is `preparation`, `chart`, or `artifact_write`. On a stage exception, keep any earlier child result, leave the throwing stage result null, and log traceback to stderr. On artifact-write failure, preserve the successful in-memory chart result and report the persistence failure in the parent error.

## Code Shape

- `adk/src/adk_sales_workflow/ingestion.py`: strict CSV preflight, row validation, normalization, quarantines, and preparation envelope.
- `adk/src/adk_sales_workflow/chart.py`: source-envelope validation, exact monthly aggregation, Plotly HTML, and chart result.
- `adk/src/adk_sales_workflow/nodes.py`: independently executable ingestion/chart `BaseNode`s and final result node.
- `adk/src/adk_sales_workflow/workflow.py`: graph `Workflow`, explicit `chart`/`skip` routes, and state keys for full stage envelopes.
- `adk/src/adk_sales_workflow/cli.py`: Runner/session setup, three CLI subcommands, path handling, JSON output, and exit mapping.
- `adk/tests/`: stage, graph, CLI, and contract-parity tests.
- Root `pyproject.toml`/`uv.lock`: ADK version, Hatchling package selection, `adk-sales` entry point, pytest and Pyright scope.

## Validation Rules

- Require exactly the seven case-sensitive CSV fields; permit any header order. Strict parser, duplicate/header/schema/record-width and unreadable-file failures reject the whole file.
- Support quoted multiline records and retain starting physical line numbers. Trim whitespace, preserve literal `NA`, retain normalization audit, and collect all row issues.
- Validate real `YYYY-MM-DD` dates; positive whole quantities; positive exact-cent `Decimal` prices (no rounding); catalog labels and product/category pairs; unique trimmed case-sensitive order IDs. Quarantine every row in a duplicate-ID group.
- Chart stage verifies preparation status, record/quarantine arrays, report counts, and each record. Reject failed/unknown/contradictory status, malformed records, and zero valid records; never silently drop chart input rows.
- Sum `quantity × unit_price` by order-date calendar month with `Decimal`, chronologically, omitting months without orders. Render offline Plotly titled “Monthly Sales Amount”, axes “Order month” and “Sales amount”, no currency symbol. Partial charts disclose quarantined-row count.
- File failure or zero valid records skips charting. Partial valid data charts with `completed_with_warnings`. Preserve existing HTML/JSON outputs on failure.

## Implementation Plan

### Phase 0: Verify ADK and packaging prerequisites
| File | What changes |
|---|---|
| `adk/tests/test_adk_workflow_smoke.py` | Add a minimal two-node ADK `Workflow` + `Runner` smoke test against the pinned API. |
| `pyproject.toml` (only if needed) | Prove existing `uv_build` package discovery for both roots; if unsupported, test Hatchling's explicit package selection before migrating. |

- [ ] With Google ADK 2.14.x, construct and run a two-node graph through an in-memory `Runner`; verify node inputs, route selection, and terminal output.
- [ ] Verify whether the current backend can package `langgraph/src` and `adk/src` in one wheel. If not, build a minimal Hatchling wheel/sdist and confirm existing package paths and entry-point metadata before changing the backend.
- [ ] Do not begin stage implementation until both prerequisites pass; keep the verified smoke test as a regression test.

### Phase 1: Package ADK stages and deterministic contracts
| File | What changes |
|---|---|
| `pyproject.toml`, `uv.lock` | Pin ADK, apply the backend/layout proven in Phase 0, add `adk-sales`, include ADK tests in configured checks. |
| `adk/src/adk_sales_workflow/` | Add typed result contracts, strict ingestion, chart validation/aggregation/rendering, and unit tests. |
| `adk/tests/test_stages.py` | Cover valid, partial, invalid, empty, and structural-failure cases; compare contracts with LangGraph. |
| `adk/README.md` | Document deterministic stages, commands, defaults, and no-LLM requirement. |

- [ ] Implement both standalone deterministic stages and their JSON-safe results.
- [ ] Verify stage contracts against existing LangGraph behavior.

### Phase 2: ADK graph, runner, and CLI
| File | What changes |
|---|---|
| `adk/src/adk_sales_workflow/nodes.py`, `workflow.py` | Add ADK nodes, invocation-scoped state, explicit skip/chart routes, and parent envelope assembly. |
| `adk/src/adk_sales_workflow/cli.py` | Implement `run`, `ingest`, and `chart`; path defaults/overrides; atomic-per-file outputs; stdout/stderr and exit behavior. |
| `adk/tests/test_workflow.py`, `test_cli.py` | Cover stage routing, exceptions, output preservation, CLI contracts, and invocation isolation. |
| `docs/adr/0001-adk-workflow-and-package-layout.md` | Record graph API and multi-root packaging decision. |

- [ ] Verify the chart stage runs once only for usable preparation and retains both child results.
- [ ] Build wheel and sdist; inspect contents and test all imports/entry points in a clean environment.
- [ ] If the backend changes, re-run the Phase 0 packaging checks and confirm the three existing LangGraph commands still work.

## Acceptance Criteria

- `uv run adk-sales run` processes the 500-row fixture, returns `completed`, and creates the offline HTML plus full parent JSON under `adk/outputs`.
- CLI path overrides work from another working directory; existing `sales-data`, `sales-chart`, and `sales-pipeline` commands remain usable after packaging changes.
- Invalid rows are quarantined; chartable partial data produces an annotated chart and warning status. Structural file failure or zero valid records skips charting and preserves existing artifacts.
- The workflow uses ADK graph routing and invocation-scoped JSON-safe state; stage results and parent error match the agreed envelope. Each stage also runs independently through its CLI subcommand.
- A two-node integration smoke test runs through ADK `Runner` on the pinned version, covering graph construction, routing, input handoff, and terminal output.
- No OpenAI calls or credentials are required. No run's stage data leaks into a later invocation.
- Wheel/sdist include all existing and ADK packages; CLI entry points import successfully. Tests, Pyright, and Ruff pass for ADK and existing code.

## Testing

- Exercise supplied clean CSV and synthetic partial, all-invalid, header-only, malformed, wrong-schema, duplicate-ID, multiline, and normalization cases.
- Assert exact price handling, date/catalog/quantity validation, issue provenance, row ordering, Decimal totals, chart labels/annotation, and offline HTML.
- Assert graph node order, explicit skip route, one chart call, state isolation, retained child results, and structured failures for thrown exceptions.
- Test all CLI subcommands, defaults/overrides, repository-root path resolution, compact stdout JSON, stderr traceback, exit codes, and artifact preservation/replacement.
- Inject HTML and JSON artifact-write failures separately. Return a structured `artifact_write_failed` result, print it to stdout, log the failed path/error to stderr, and exit 2. If the second replacement fails after the first succeeds, the already-replaced artifact may remain changed; the other artifact remains at its prior version.
- Compare ADK and LangGraph preparation/chart outputs on clean and representative partial/invalid fixtures (excluding run-specific metadata).
- Build and inspect wheel/sdist; install into a clean environment and smoke-test all four console commands.

## Logging

Use structured stderr logs with a per-invocation `run_id`. Do not log full CSVs, all records, full HTML, secrets, or credentials. DEBUG entries/exits include actual stage inputs and representative output values, not counts alone. No LLM or database events exist.

| Event | Level | Fields | Example |
|---|---|---|---|
| Workflow started | `info` | `run_id`, `csv_path`, `output_dir` | `{"event":"workflow_started","run_id":"adk-6f31","csv_path":"dataset/shared_sales_dataset.csv","output_dir":"adk/outputs"}` |
| Node entry | `debug` | `run_id`, `node`, actual arguments | `{"event":"node_entry","run_id":"adk-6f31","node":"ingest","args":{"csv_path":"dataset/shared_sales_dataset.csv"}}` |
| Node exit | `debug` | `run_id`, `node`, result preview, duration | `{"event":"node_exit","run_id":"adk-6f31","node":"ingest","return_preview":{"status":"completed","first_record":{"order_id":"ORD-0205","date":"2025-01-01","quantity":8,"unit_price":"89.00"}},"duration_ms":21.4}` |
| Row quarantined | `warning` | `run_id`, physical line, field, code, observed value | `{"event":"row_quarantined","run_id":"adk-6f31","line_number":4,"field":"unit_price","code":"invalid_unit_price_precision","observed_value":"39.999"}` |
| Chart skipped | `warning` | `run_id`, stage, code, reason | `{"event":"chart_skipped","run_id":"adk-6f31","stage":"preparation","code":"no_valid_records","reason":"Preparation produced zero valid sales orders"}` |
| Artifact write failed | `error` | `run_id`, artifact path, operation, exception type, message | `{"event":"artifact_write_failed","run_id":"adk-6f31","artifact_path":"adk/outputs/monthly_sales_amount.json","operation":"replace","exception_type":"PermissionError","message":"Permission denied"}` |
| Stage exception | `error` | `run_id`, stage, exception type, traceback | `{"event":"stage_exception","run_id":"adk-6f31","stage":"chart","exception_type":"RuntimeError","traceback":"RuntimeError: renderer unavailable"}` |
| Workflow finished | `info` | `run_id`, status, output path, exit code | `{"event":"workflow_finished","run_id":"adk-6f31","status":"completed_with_warnings","output_path":"adk/outputs/monthly_sales_amount.html","exit_code":0}` |

## Edge Cases

- Duplicate IDs: quarantine every row in each duplicate group, including the first occurrence.
- Header-only CSV: report empty input; do not invoke chart stage.
- Valid quoted multiline CSV: report the record's physical starting line.
- An exception after a prior stage completes retains its result; failed stage result is null. Do not promise rollback for unexpected side effects.
- Stage each artifact to a temporary sibling and replace atomically per file, not transactionally as a pair. A replacement failure returns parent `status: failed`, `error: {stage: "artifact_write", code: "artifact_write_failed", message: ...}`, stdout JSON, stderr diagnostic, and exit 2. If HTML replacement succeeds but JSON replacement fails, keep the successful HTML replacement and leave the prior JSON intact; do not claim rollback.
- Chart totals that cannot be converted to finite plot values fail before replacing output.

## Risks & Unknowns

- Current `uv_build` uses one `module-root`; verify its actual capability before migrating. If it cannot package both source roots, prove Hatchling wheel/sdist contents and installed CLI targets before the backend change and again before merging.
- Self-contained ADK rules duplicate LangGraph logic; parity tests are mandatory.
- ADK Workflow is a `BaseNode`, not a `BaseAgent`; expose stage commands through Runner roots, not agent-subagent wiring.

## Out of Scope

OpenAI/GPT-6 Luna, LLM-based validation/repair, dynamic chart selection, A2A serving, database sessions, persistent checkpoints, retries, concurrency, currency inference, and changes to LangGraph business logic.

## Docs to Update
