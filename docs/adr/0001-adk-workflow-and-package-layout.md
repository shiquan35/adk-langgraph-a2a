# ADR 0001: Google ADK Workflow and Package Layout

- **Status:** Implemented (clean-installed distribution verified)
- **Date:** 2026-11-17

## Context

The project has deterministic sales-data and chart agents plus a LangGraph parent workflow. The separate ADK implementation under `adk/` uses Google ADK 2.14's graph-based `Workflow`/`BaseNode` API rather than deprecated `SequentialAgent`. The former `uv_build` configuration had one module root at `langgraph/src`; adding a module name could not include the sibling ADK package.

## Decision

Use deterministic preparation and chart `BaseNode` stages with explicit route-controlled edges and a final assembly node. Preparation stores its structured result in invocation-scoped `temp:` shared state and routes to charting only for non-failed, nonempty data. Charting stores its result for assembly. Each execution uses ADK `Runner` with a fresh `InMemorySessionService` session; initial temporary state is also seeded through the invocation's `state_delta`. The runner is closed after execution; no state persists across calls.

Keep implementation, tests, and usage docs under `adk/`. The actual backend is now Hatchling, with explicit wheel selection of the three packages under `langgraph/src` and `adk/src/adk_sales_workflow`. Existing console-script targets are preserved and `adk-sales` is configured in [pyproject.toml](../../pyproject.toml). Wheel and sdist have been built and inspected, proving the multi-root layout; a clean-installed wheel also passed the end-to-end ADK dataset run and all four command help checks.

Constrain `google-adk>=2.14,<2.15`. No LLM or model credentials are used. Preparation, validation, exact decimal aggregation, and rendering logic is copied into the self-contained ADK package rather than calling LangGraph graphs; parity tests mitigate drift.

Expose `uv run adk-sales run`, `uv run adk-sales ingest --output adk/outputs/prepared.json`, and `uv run adk-sales chart --input adk/outputs/prepared.json`. Relative paths are repository-root-relative. CSV input defaults to [dataset/shared_sales_dataset.csv](../../dataset/shared_sales_dataset.csv); `run`/`chart` default to HTML and JSON named `monthly_sales_amount` under `adk/outputs`. Standalone commands return their preparation/chart envelopes; the parent returns `{status, preparation_result, chart_result, error}`. Full command options and child shapes are documented in [adk/README.md](../../adk/README.md).

## Alternatives considered

- **Deprecated `SequentialAgent`:** Rejected because the installed ADK marks it deprecated in favor of the graph-based `Workflow` requested for this design.
- **Call existing LangGraph agent graphs from ADK nodes:** Rejected by the user in favor of a self-contained implementation under `adk/`, despite duplicated logic. Parity tests mitigate drift risk.
- **Keep `uv_build` and add the ADK package name:** Rejected because the former single `module-root` resolved all names under `langgraph/src`, not the sibling `adk/` directory.
- **Separate ADK distribution/workspace:** Rejected in favor of one project distribution and one `adk-sales` command.
- **LLM-driven agents:** Rejected because parsing, validation, exact Decimal aggregation, and rendering are deterministic; a model adds no required capability.

## Consequences

- Explicit temporary-state writes are required; yielded outputs alone do not populate shared state. ADK upgrades require deliberate verification.
- The CLI emits one compact JSON envelope to stdout and diagnostics to stderr. `completed`, preparation's `completed_with_errors`, and chart/parent's `completed_with_warnings` all exit 0; failures exit 2. Failed or empty preparation skips charting and fails the parent.
- Chart generation checks rendering but never publishes files; `output_path` denotes an intended destination. The CLI publisher stages both complete files, then atomically replaces HTML followed by JSON. There is no pair transaction: failure before publication or at the first replacement preserves old files, but failure at the second replacement may leave new HTML with old JSON. Report `artifact_write_failed` on stdout without rollback or a second JSON publication; retain parent child results unchanged.
- Unexpected stage exceptions are logged with traceback to stderr and represented in the parent error while retaining earlier completed results; skipped or unexpectedly interrupted children are null.
- Repository-relative defaults use `ADK_SALES_ROOT` when set, otherwise checkout discovery from cwd and module ancestors. Outside a checkout, clean-installed wheel users must set `ADK_SALES_ROOT`; repository execution alone cannot certify this behavior. Clean-installed end-to-end execution and command help checks have now succeeded.

## Implementation evidence

- [Runner smoke test](../../adk/tests/test_adk_workflow_smoke.py) exercises the real `Workflow`, conditional route, node input, and `temp:` state handoff through `Runner`.
- [Workflow tests](../../adk/tests/test_adk_workflow.py) cover parent/standalone execution, routing, exceptions, cleanup, and concurrent isolated sessions. [Stage parity tests](../../adk/tests/test_adk_stages.py) compare copied logic against LangGraph. [CLI tests](../../adk/tests/test_adk_cli.py) cover envelope shapes, paths, exit codes, and staged-publication failures including mixed versions.
- Local verification before the path-discovery tests: 238 regression tests passed; `uv run ruff check adk` and `uv run ruff format --check adk` passed. Run `uv run pytest -q adk/tests` for focused checks or `uv run pytest -q` for the current full regression total.
- Wheel metadata identifies Hatchling 1.33.0; wheel and sdist inspection confirms all four package roots. Clean-installed wheel verification, reported by the main verification run, succeeded outside the checkout with `ADK_SALES_ROOT` set: the supplied dataset completed the ADK workflow end-to-end, and `adk-sales`, `sales-data`, `sales-chart`, and `sales-pipeline` help checks passed, exercising their entry-point imports.
