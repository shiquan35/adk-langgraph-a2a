# ADR 0001: Google ADK Workflow and Package Layout

- **Status:** Accepted
- **Date:** 2026-11-17

## Context

The project already has deterministic sales-data and chart agents plus a LangGraph parent workflow. A separate Google ADK implementation is requested under `adk/`, using ADK's graph-based workflow API to sequence CSV preparation and chart generation. The installed Google ADK version is 2.14.1; its `Workflow` is a `BaseNode` graph API, while `SequentialAgent` is deprecated in favor of `Workflow`. Workflow nodes can route explicitly and communicate via node input/output and invocation session state. The repository currently uses `uv_build` with a single configured module root at `langgraph/src`; adding a module name does not include a sibling package from `adk/`.

## Decision

Use Google ADK's graph-based `Workflow` API with two deterministic `BaseNode` stages, connected by explicit route-controlled edges. The CSV stage produces a JSON-serializable prepared sales result, stores it under an invocation-scoped temporary state key, and routes to charting only when preparation succeeded and contains valid records. The chart stage consumes that structured result and stores its result for parent assembly. Run via ADK `Runner` with an in-memory session service. Expose a local `adk-sales` CLI with parent and standalone stage commands.

Keep ADK implementation, tests, and usage docs under `adk/`. Replace the current `uv_build` backend with Hatchling explicit wheel package selection, targeting the three existing packages under `langgraph/src` plus a new package at `adk/src/adk_sales_workflow`. Preserve existing standard console-script targets and add the ADK entry point. Build and inspect both wheel and sdist; install into a clean environment and verify every existing and new script/import before accepting the migration. This multi-root package configuration is proposed but has not yet been locally built.

Pin `google-adk >=2.14,<2.15`. The stages perform deterministic exact data work; do not configure OpenAI or GPT-6 Luna. Their CSV and chart rules mirror the established sales specifications, with parity tests comparing ADK and LangGraph outputs.

## Alternatives considered

- **Deprecated `SequentialAgent`:** Rejected because the installed ADK marks it deprecated in favor of the graph-based `Workflow` requested for this design.
- **Call existing LangGraph agent graphs from ADK nodes:** Rejected by the user in favor of a self-contained implementation under `adk/`, despite duplicated logic. Parity tests mitigate drift risk.
- **Keep `uv_build` and add the ADK package name:** Rejected because the current single `module-root` resolves all names under `langgraph/src`, not the sibling `adk/` directory.
- **Separate ADK distribution/workspace:** Rejected in favor of one project distribution and one `adk-sales` command.
- **LLM-driven agents:** Rejected because parsing, validation, exact Decimal aggregation, and rendering are deterministic; a model adds no required capability.

## Consequences

- Workflow execution uses ADK event/session machinery, but it does not persist beyond the in-memory CLI run.
- Explicit state writes are required; node outputs are not automatically copied to session state.
- The ADK API is version-constrained and needs deliberate upgrades.
- Root build configuration changes carry regression risk for existing LangGraph commands; wheel contents and installed entry points must be tested.
- Duplicated business logic can drift; parity tests are part of the acceptance criteria.
- Completed-with-warnings runs produce the partial chart/result and exit zero; failed runs exit two, emit a failure envelope, and preserve previous artifacts.
- Unexpected stage exceptions are represented in the parent error and logged to stderr with traceback while retaining any completed earlier-stage result.
- No model credentials or external LLM calls are needed.
