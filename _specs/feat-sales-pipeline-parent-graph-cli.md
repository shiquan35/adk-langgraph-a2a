# Sales Pipeline Parent Graph and CLI

> 🌿 **Branch:** `feat/sales-pipeline-parent-graph-cli` · 📅 **Date:** 2026-11-16

## Problem & Solution

**Problem:** Preparing the shared sales dataset and generating its chart currently requires separate CLI invocations with an intermediate JSON file, or hand-written Python composition. There is no parent workflow with a unified outcome and correlated stage diagnostics.

**Solution:** Add a parent LangGraph and `sales-pipeline` command that invoke the two existing compiled graphs sequentially in memory, route unusable preparation results away from chart generation, and return both child results in one JSON envelope.

## Decisions

| Type | Decision | Choice | Why |
|---|---|---|---|
| Constraint | Existing agents | Reuse `sales_data_agent.graph` and `sales_chart_agent.graph`; preserve standalone commands and child result contracts | Avoid duplicating validation, aggregation, and rendering |
| Constraint | Project scope | Python 3.11+, uv; feature source/tests/docs under `langgraph/`; root packaging changes only in `pyproject.toml` and `uv.lock`, apart from this plan | Preserve the existing package layout; leave `a2a/` and `adk/` untouched |
| Choice | Parent structure | Wrapper nodes invoke each compiled child graph in process | Adapt dissimilar schemas without merging child internal states |
| Choice | CLI | `uv run sales-pipeline [--csv-path PATH] [--output PATH]` | A single command, with the existing defaults and overrides |
| Choice | Partial preparation | Continue when valid records exist; propagate a warning outcome | Keep the chart agent's established partial-data behavior |
| Choice | Unusable preparation | Skip chart when Agent 1 fails or returns zero valid records | Avoid unnecessary work and preserve the existing HTML |
| Choice | Result | Parent envelope retains both unmodified child results and a stage-qualified error | Preserve quarantines, normalization audit, and chart provenance |
| Choice | Exceptions | Catch unexpected `Exception` at child invocation boundaries; return structured stage failure and log traceback | Keep machine-readable failure output without hiding debugging evidence |
| Choice | Execution | One sequential attempt per stage; forward LangGraph execution configuration | Retain callbacks/tracing without introducing retries or persistence |
| Choice | Correlation | Shared `pipeline_run_id` in parent/child events; retain each child's `run_id` | Trace the complete run without changing public child results |

## Architecture

```text
sales-pipeline [--csv-path PATH] [--output PATH]
                         |
                         v
                  Parent StateGraph
                         |
                         v
              [prepare: invoke Agent 1]
                 |                  |
      usable records                failed / no records / exception
                 |                  |
                 v                  |
        [chart: invoke Agent 2]     |
                 |                  |
                 +--------+---------+
                          v
                  [assemble result] --> END
                          |
                  one JSON line stdout
                  diagnostics stderr
```

- Parent package: `langgraph/src/sales_pipeline_agent/`. Add it to the existing uv `module-name` list; keep `module-root = "langgraph/src"`.
- Export compiled `graph`; `graph.invoke({})` uses Agent 1's `dataset/shared_sales_dataset.csv` and Agent 2's `langgraph/outputs/monthly_sales_amount.html` defaults. Delegate path resolution to the children: relative paths resolve from repository root.
- `prepare` calls Agent 1 with `csv_path`; `chart` calls Agent 2 with `{source_result: preparation_result, output_path}`. Never invoke child CLIs or serialize intermediate records to disk.
- Wrapper nodes accept `RunnableConfig`, forward callbacks/tags/configurable settings, and copy/merge metadata with the parent-generated `pipeline_run_id`. Never mutate the caller's config or reuse its callback-manager objects by global storage.
- Generate the pipeline ID once per invocation in the first node, retain it in private state, and explicitly forward it to child configuration. Extend both child logging helpers to read optional `pipeline_run_id` from current LangGraph configuration metadata; omit it outside pipeline execution. No parent-package import from a child is needed.
- The CLI temporarily enables structured stderr logging on the parent and both child loggers. Restore handlers, levels, and propagation in `finally`; never configure the root logger. Programmatic graph use does not configure handlers.

## Code Shape

- `GraphInput`: optional `csv_path: str | None`, `output_path: str | None`.
- `Result`: exactly `status`, `preparation_result`, `chart_result`, `error`.
  - `status`: `completed | completed_with_warnings | failed`.
  - `preparation_result`: Agent 1 `Result`, or null if its invocation raised.
  - `chart_result`: Agent 2 `Result`, or null if skipped or its invocation raised.
  - `error`: null on clean/warning completion; otherwise `{stage: "preparation" | "chart", code: str, message: str}`.
- Private state holds inputs, `pipeline_run_id`, nullable child results, and any stage error. Public output excludes internal state and tracing metadata.
- `graph.py`: `build_graph()`, compiled `graph`, preparation/chart wrapper nodes, conditional preparation routing, and result assembly.
- `models.py`: typed input/state/result/error shapes and parent exit mapping. `observability.py`: parent JSON events and scoped CLI logger configuration. `cli.py:main`: argument parsing, invocation, serialization, and exit mapping.

## Validation Rules

- Delegate CSV validation to Agent 1 and source-envelope/chart validation to Agent 2; do not normalize, repair, or rewrite their results.
- Preparation status `failed`: skip chart, set parent `failed`, copy the first `report.file_issues` issue's code/message into a preparation-stage error; fall back to `preparation_failed` if no issue exists.
- Preparation with no valid records: skip chart and return preparation-stage `no_valid_records`, even if Agent 1 returned `completed_with_errors` and `empty_dataset`.
- Preparation `completed` or `completed_with_errors` with records: invoke chart exactly once.
- Chart `completed` maps to parent `completed`; chart `completed_with_warnings` maps to parent `completed_with_warnings`; chart `failed` maps to parent `failed` with its error code/message and stage `chart`.
- An unexpected child `Exception` maps to `unexpected_stage_error` for that stage, with a concise safe message naming the exception type. Preserve any earlier result; the throwing stage's result is null. Do not catch `BaseException`, `KeyboardInterrupt`, or `SystemExit`.
- CLI exits: `0` completed, `1` completed with warnings, `2` failed. After successful argument parsing, processing failures use the parent envelope; argparse help/usage errors retain normal behavior.
- Serialize the entire result as compact, ASCII-escaped, standards-compliant JSON before writing one newline-terminated stdout record. All diagnostics, including tracebacks, go to stderr.

## Implementation Plan

### Phase 1: Parent orchestration and correlated diagnostics

| File | What changes |
|---|---|
| `pyproject.toml` | Add `sales_pipeline_agent` to uv's packaged modules; no new dependencies. |
| `uv.lock` | Synchronize project metadata if changed by uv. |
| `langgraph/src/sales_pipeline_agent/__init__.py` | Export compiled parent graph. |
| `langgraph/src/sales_pipeline_agent/models.py` | Define typed input/state/result/error and exit mapping. |
| `langgraph/src/sales_pipeline_agent/graph.py` | Invoke child graphs, forward config, route failures, and assemble results. |
| `langgraph/src/sales_pipeline_agent/observability.py` | Parent structured logging and scoped multi-logger CLI configuration. |
| `langgraph/src/sales_data_agent/observability.py` | Add optional pipeline metadata correlation; preserve standalone logging behavior. |
| `langgraph/src/sales_chart_agent/observability.py` | Add the same optional correlation without altering standalone results. |
| `langgraph/tests/test_sales_pipeline_graph.py` | Exercise routing, retained child results, config forwarding, and log correlation. |

- [ ] Implement the parent graph and correlation without duplicating child business logic.
- [ ] Verify clean/partial/no-data/failure/exception outcomes and input/config isolation.
- [ ] Typecheck and run focused graph tests before proceeding.

### Phase 2: Combined CLI and usage

| File | What changes |
|---|---|
| `pyproject.toml` | Register `sales-pipeline = "sales_pipeline_agent.cli:main"`. |
| `uv.lock` | Refresh project metadata if necessary. |
| `langgraph/src/sales_pipeline_agent/cli.py` | Parse optional paths, invoke parent graph, emit JSON, and map exit codes. |
| `langgraph/tests/test_sales_pipeline_cli.py` | Subprocess and repeated-call tests for streams, paths, statuses, and logger restoration. |
| `langgraph/README.md` | Document one-command usage, parent graph API/result, defaults, errors, and correlated logging. |

- [ ] Add the command while retaining `sales-data` and `sales-chart`.
- [ ] Test help, default dataset, overrides, and all exit outcomes; document parent composition.
- [ ] Run full suite, typechecking, lint, formatting checks for touched Python files, and locked uv sync.

## Acceptance Criteria

- `uv run sales-pipeline` processes the shared 500-row dataset and generates the default offline HTML with parent `completed`, both child results present, null error, and exit 0.
- Path overrides work; repository-root-relative behavior matches the existing commands. Parent API supports the same defaults and returns the same envelope as the CLI.
- Partial valid data generates a visibly partial chart, retains all preparation quarantines/audit entries, and returns parent warning status with exit 1.
- Failed or zero-record preparation never invokes the chart stage; result has null `chart_result` and stage-qualified error, exits 2, and leaves existing HTML unchanged.
- A chart failure retains the complete preparation result and chart failure result; an unexpected exception retains earlier results and sets the throwing stage's result to null.
- Parent orchestration adds no intermediate JSON file, browser launch, extra retries, or child-result modifications.
- Parent and both children emit the same `pipeline_run_id`; child `run_id` values remain intact. Callbacks/tracing receive forwarded configuration, and caller config/logger settings remain unchanged after successful or failed runs.
- CLI emits one compact JSON line to stdout; parent/child diagnostics and unexpected-exception traceback evidence remain on stderr. Existing standalone commands/tests continue to work.
- Full pytest suite, Pyright, Ruff lint/format checks for touched code, and `uv sync --locked` pass.

## Testing

- End-to-end graph and CLI tests on the supplied dataset, writing HTML only into temporary directories except a redirected temporary default-output test.
- Synthetic CSVs: clean, partial, all rows rejected, header-only, missing/unreadable file, malformed CSV. Assert full parent status/error shape and exact retention of each child result.
- Inject preparation/chart exceptions; verify stage/code/message, earlier-result retention, stderr traceback, chart-stage bypass, and no fabricated child result.
- Assert stage order and one invocation per child; inspect parent updates to verify conditional routing. This orchestration behavior warrants boundary-call assertions in addition to result assertions.
- Forward a test callback and metadata/tags through the parent; verify nested child execution, one shared pipeline ID, distinct child run IDs, no caller-config mutation, and no correlation leakage into a later standalone invocation.
- Test CLI flags/help/defaults, invocation from another working directory, compact JSON/ASCII escaping, exit codes, existing-output preservation on expected child failures, repeated invocations, and handler/level/propagation restoration including exceptions.

## Logging

Use structured JSON with `pipeline_run_id` on every pipeline event and correlated child event. Parent logs identify stages and actual path/error/aggregate values, not just counts. DEBUG node entry/exit logs capture safe argument/result previews and duration; do not dump prepared rows, quarantines, full HTML, secrets, or PII. Traceback evidence belongs in a structured stderr event (formatted traceback text), not the parent result or stdout. No LLM/DB calls exist. No alert/dashboard integration is included.

| Event | Level | Fields | Example |
|---|---|---|---|
| Pipeline started | `info` | `pipeline_run_id`, effective input/output paths | `{"event":"pipeline_started","pipeline_run_id":"pipeline-a81f","csv_path":"dataset/shared_sales_dataset.csv","output_path":"langgraph/outputs/monthly_sales_amount.html"}` |
| Node entry | `debug` | `pipeline_run_id`, `node`, `args` | `{"event":"node_entry","pipeline_run_id":"pipeline-a81f","node":"prepare","args":{"csv_path":"dataset/shared_sales_dataset.csv"}}` |
| Node exit | `debug` | `pipeline_run_id`, `node`, `return_preview`, `duration_ms` | `{"event":"node_exit","pipeline_run_id":"pipeline-a81f","node":"chart","return_preview":{"status":"completed","monthly_totals":[{"month":"2026-01","sales_amount":"79.80"}]},"duration_ms":42.3}` |
| Chart skipped | `warning` | `pipeline_run_id`, `stage`, `code`, `message` | `{"event":"chart_skipped","pipeline_run_id":"pipeline-a81f","stage":"preparation","code":"no_valid_records","message":"Preparation returned no valid records"}` |
| Stage exception | `error` | `pipeline_run_id`, `stage`, exception type, formatted traceback | `{"event":"stage_exception","pipeline_run_id":"pipeline-a81f","stage":"chart","exception_type":"RuntimeError","traceback":"RuntimeError: renderer unavailable"}` |
| Correlated child event | existing level | existing fields plus `pipeline_run_id` | `{"event":"agent_started","run_id":"child-d42b","pipeline_run_id":"pipeline-a81f","csv_path":"dataset/shared_sales_dataset.csv"}` |
| Pipeline finished | `info` | `pipeline_run_id`, status, chart path, error, exit | `{"event":"pipeline_finished","pipeline_run_id":"pipeline-a81f","status":"completed_with_warnings","output_path":"/tmp/sales-chart.html","error":null,"exit_code":1}` |

## Edge Cases

- Agent 1's header-only outcome is partial completion, not failure; the parent must still skip chart generation and return `no_valid_records`.
- If chart generation returns a failed result, preserve it; if it raises before returning, use null. Do not confuse these cases.
- A child might raise after a filesystem side effect. Do not promise rollback for unexpected exceptions; normal chart write failures retain Agent 2's existing atomic-write guarantees.
- Correlation is invocation-scoped, including programmatic runs; concurrent pipeline invocations must not share IDs or alter global logging state outside the CLI's temporary setup.

## Risks & Unknowns

- No root `INDEX.md` exists; index-based documentation discovery is skipped and Docs to Update is empty. The usage-guide change is explicitly listed in Phase 2.
- Returning the full preparation result makes stdout large; explicitly accepted to retain auditability. Logging uses previews instead.
- Configuration forwarding must preserve LangGraph callback nesting; verify with a callback test rather than assuming dictionary copying is sufficient.
- No unresolved product decisions remain. Keep the existing no-Git instruction: do not create branches or commits during implementation unless separately authorized; phases are logical commit-sized checkpoints.

## Out of Scope

- Changes to sales-domain terminology, validation rules, chart design, child result schemas, A2A/ADK integration, LLM orchestration, concurrency between stages, retries, added timeouts, streaming CLI, checkpoints/resume, intermediate result persistence, and browser opening.

## Docs to Update
