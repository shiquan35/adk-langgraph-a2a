# Building agents using Google ADK

## Sales CSV-to-chart workflow

The planned ADK example is a deterministic two-stage workflow: CSV preparation produces a prepared sales result, then chart generation validates that result and writes an offline monthly sales amount chart. The graph-based Google ADK `Workflow` will coordinate the two independently executable stages. Invalid rows are quarantined; chartable partial data produces a warning chart; failed or empty preparation skips charting.

No LLM is required or configured. In particular, OpenAI/GPT-6 Luna is not used: strict CSV validation, exact decimal aggregation, and chart rendering are deterministic operations.

See the [ADK sales workflow design](../_specs/feat-adk-sales-workflow.md) and [ADR 0001](../docs/adr/0001-adk-workflow-and-package-layout.md) for the agreed contract, CLI plan, API-version decision, package-layout risk, and verification plan. **Implementation is not started yet.**
