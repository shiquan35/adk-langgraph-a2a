# ADK Sales CSV-to-Chart Workflow

> Status: Design agreed; implementation not started.

## Problem and solution

Build a local two-stage sales workflow using Google ADK. The first deterministic stage prepares the sales CSV; the second validates the prepared result and renders a monthly sales amount chart. A graph-based ADK `Workflow` coordinates both stages in sequence, passing a structured result through invocation-scoped state. The workflow skips chart generation when preparation fails or yields no valid records.

This is a distinct implementation under `adk/`; the existing LangGraph implementation remains unchanged. The ADK stages are self-contained copies/adaptations of the existing deterministic business rules and must remain behaviorally aligned with those rules. Add parity tests to detect drift.

## Domain language

Use the root glossary terms in `CONTEXT.md`: sales order, order ID, product, product category, sales region, order date, unit price, sales amount, and monthly sales amount. The stage handoff is a **prepared sales result**: accepted sales orders, quarantined rows, and preparation report, including status and provenance.

Do not infer currency or call sales amount revenue. Use `quantity × unit_price` and exact decimal arithmetic.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Runtime | ADK version | Pin `google-adk >=2.14,<2.15` | The installed 2.14.1 Workflow graph API was verified; avoid unreviewed API drift. |
| Orchestration | Parent | Use Google ADK's graph-based `Workflow`, not deprecated `SequentialAgent` | It is the requested graph API and supports explicit route-controlled stage flow. |
| Stages | Agent model | Two deterministic ADK `BaseNode` stages, ingestion and charting | Both stages perform exact data operations; no LLM is necessary. |
| Model | OpenAI | No OpenAI/GPT-6 Luna configuration or calls | The workflow is deterministic; avoid an unnecessary model dependency/configuration. |
| Code boundary | Feature files | Implementation, tests, and ADK documentation under `adk/` | Keep ADK implementation distinct from LangGraph. |
| Packaging | CLI | Register `adk-sales` and package ADK modules alongside the LangGraph packages | The root build configuration must be changed from `uv_build` to a backend/layout that supports both source roots. Validate built wheel contents and imports. |
| CLI | Commands | `adk-sales run`, `adk-sales ingest`, `adk-sales chart` | Support the parent and independently executable stages. |
| Workflow | State | Store complete JSON-serializable preparation and chart envelopes in temporary, invocation-scoped state keys | Preserve provenance while preventing results leaking between runs. |
| Runner | Session | Use ADK `Runner` with an in-memory session service | Keep local CLI runs ephemeral and use ADK's supported node invocation path. |
| Input | CSV path | Default to `dataset/shared_sales_dataset.csv`; optional `--csv-path` override | Fast default run plus fixture/user path support. |
| Output | Location | Default to `adk/outputs`; optional `--output-dir` override | Keep generated files under the ADK feature by default. |
| Output | Names | `monthly_sales_amount.html` and `monthly_sales_amount.json` | Consistent chart name with adjacent machine-readable result. |
| Output | Writes | Replace each artifact atomically only on chart success | Avoid truncating existing files on expected failures. Atomicity is per file; pairwise transaction is not promised. |
| Path resolution | Relative paths | Resolve CSV, preparation JSON, and output directory relative to repository root | Consistent with existing sales CLIs. |
| CLI result | Workflow | Full parent envelope is written to JSON artifact and identical compact JSON is printed to stdout | Preserve both stage results and enable shell integrations. |
| CLI result | Ingest | Full preparation JSON to stdout; optionally save it with an output option; no file by default | Pipe-friendly and supports standalone chart execution without mandatory intermediate files. |
| CLI result | Chart | Read a saved preparation-result JSON; write HTML and chart-result JSON in output directory | Independently execute stage two using the same contract. |
| Failure | File input | Unreadable, malformed, or schema-invalid CSV fails preparation as a whole | Follow the established strict file-level contract. |
| Failure | Invalid rows | Quarantine bad rows; continue charting valid rows with a warning | Preserve useful records without hiding partial coverage. |
| Failure | No records | Zero valid records fails the workflow and skips charting | Empty data cannot produce a meaningful chart. |
| Exit | Workflow | 0 for completed or completed-with-warnings; 2 for failure | Warnings remain successful for automation, as selected. |
| Docs | Architecture | Add ADK README details, a feature design spec, and an ADR for the graph API/package-layout choice | Keep a durable record of meaningful API and build trade-offs. |

## Data contracts

### Preparation stage

Use the existing CSV rules and result shape from `_specs/feat-sales-csv-agent-cli.md`:

- Exact case-sensitive seven-field schema: `order_id`, `date`, `product`, `category`, `region`, `quantity`, `unit_price`; any header order is allowed.
- Strict CSV parsing, duplicate/header/schema/record-width validation before row processing; file-level failures return no records.
- Valid quoted multiline CSV records are supported and quarantines preserve starting physical line numbers.
- Trim surrounding whitespace, retain normalization audit, preserve literal `NA`, and collect all row issues.
- Validate catalog labels/product-category pairs, positive integer quantity, canonical real ISO date, unique trimmed case-sensitive order IDs (quarantine all duplicate group members), and positive exact-cent `Decimal` unit price without rounding.
- Result retains valid records in source order, quarantined rows/issues, counts, source path, and normalization report.

### Chart stage

Use the existing chart rules from `_specs/feat-monthly-sales-amount-chart-agent.md`:

- Accept the complete prepared-result mapping; validate statuses, counts, arrays, and record shape before rendering.
- Reject failed/unknown/contradictory status, zero records, malformed records, invalid dates, quantities, or noncanonical decimal prices; do not silently drop records.
- Do not repeat product/category/region catalog validation.
- Aggregate `quantity × unit_price` by order-date calendar month with `Decimal`, chronologically; omit months without orders.
- Render an offline-capable interactive Plotly HTML titled “Monthly Sales Amount”, axes “Order month” and “Sales amount”, no currency symbol. Partial results show “Partial input: N rows quarantined”.
- Exact decimal strings in the result are authoritative; plot numeric values must be finite.

### Parent result

Use the existing parent fields: `status`, `preparation_result`, `chart_result`, and `error`. Status is `completed`, `completed_with_warnings`, or `failed`. Preserve complete child results; chart result is null when skipped or when the stage raises before returning. Error has stage (`preparation` or `chart`), stable code, and concise message. Failures still emit the parent JSON to stdout and must not replace prior artifacts.

## ADK graph behavior

- Use ADK `Workflow` with deterministic ingestion and chart `BaseNode`s and explicit route edges. Ingestion sets `ctx.route` to chart or assembly based on successful, non-empty preparation. Declare both routes explicitly; lack of route match is not an implicit skip.
- Chart receives the preparation envelope as structured node input and stores its result in state. Both paths lead to result assembly.
- Use complete envelopes in temporary state keys, not prose summaries. Node output and session state are separate: explicitly set state for handoff/result assembly.
- Each stage can be run as the root node of its own ADK `Runner` from the standalone subcommands; the CLI wraps JSON/file operations and status mapping.
- Runner uses one in-memory session per invocation. No database, LLM, retries, or persistent checkpoints.

## CLI

- `adk-sales run [--csv-path PATH] [--output-dir DIR]`: sequential workflow; outputs HTML and full parent JSON on successful charting, compact parent JSON stdout; failure JSON stdout and preserves previous artifacts.
- `adk-sales ingest [--csv-path PATH] [--output PATH]`: preparation JSON stdout, optionally saved to path.
- `adk-sales chart --input PREPARATION.json [--output-dir DIR]`: validates prepared result and writes HTML plus chart-result JSON; prints chart result JSON.
- Relative paths resolve from repository root. Diagnostics go to stderr. After argparse succeeds, processing failures use machine-readable JSON.
- All three commands exit 0 for completed or completed-with-warnings results and 2 for failures.
- Unexpected stage exceptions become stage-qualified failure envelopes and traceback logs on stderr; preserve any earlier child result.
- A chartable partial result is successful for artifact purposes: write the annotated chart and warning result, atomically per file.

## Testing and verification

- Add ADK tests under `adk/tests`; update pytest discovery and Pyright include as needed, and run Ruff against `adk/` explicitly.
- Test clean shared dataset (500 rows), synthetic partial/all-invalid data, empty/header-only data, malformed CSV/schema, duplicate IDs, normalization, multiline provenance, and strict decimal behavior.
- Test graph route/order, one invocation per stage, skip chart on preparation failure/empty data, both child results retained, complete JSON-safe state, and invocation isolation.
- Parity-test ADK stage outputs against existing LangGraph agents on the shared CSV and representative invalid/partial fixtures.
- Test standalone ingest stdout/optional file and chart input JSON/output behavior; test paths from a different working directory.
- Test artifact safety, compact stdout JSON, stderr diagnostics, and exit codes.
- Build the wheel and inspect that all existing LangGraph modules and the ADK CLI target are included/importable after installation. Run locked sync, tests, Pyright, and Ruff.

## Risks and open notes

- The codebase currently uses `uv_build` with a single module root at `langgraph/src`; adding a module name does not package modules located under sibling `adk/`. The selected shared-backend approach requires careful migration and wheel verification to avoid breaking existing `sales-data`, `sales-chart`, and `sales-pipeline` entry points.
- Proposed package approach: Hatchling with explicit wheel package paths for the three existing `langgraph/src/*_agent` packages and a new `adk/src/adk_sales_workflow` package; keep standard console-script metadata. Build and inspect both wheel and sdist, then install in a clean environment and verify every script/import. This is a design recommendation, not yet tested by a local build.
- ADK changes quickly; the selected version range and lockfile need to be maintained deliberately.
- Copying deterministic business logic creates drift risk; parity tests are required.

## Out of scope

OpenAI/GPT-6 Luna, LLM-based validation or repair, dynamic chart selection, A2A serving, database sessions, persistent checkpoint/resume, retries, concurrency, currency inference, and changes to the existing LangGraph feature.
