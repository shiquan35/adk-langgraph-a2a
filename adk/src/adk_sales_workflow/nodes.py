"""Deterministic ADK nodes around the side-effect-free child stages."""

import logging
from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any, cast

from google.adk.agents.context import Context
from google.adk.workflow import BaseNode

from . import chart, ingestion
from .models import Error, Result, Stage
from .observability import log_event, log_exception, safe_observed, safe_preview
from .preparation.models import Result as PreparationResult
from .visualization.models import Result as ChartResult
from .visualization.models import failure_result


def state_value(ctx: Context, key: str) -> Any:
    """ADK's state getter is dynamically typed, including absent/null values."""
    return ctx.state.get(key)


def unexpected_error(ctx: Context, stage: Stage, exc: Exception) -> Error:
    error: Error = {
        "stage": stage,
        "code": "unexpected_stage_error",
        "message": type(exc).__name__,
    }
    ctx.state["temp:error"] = error
    log_exception(str(state_value(ctx, "temp:run_id")), stage, exc)
    return error


def node_log(ctx: Context, event: str, **fields: object) -> None:
    log_event(
        logging.DEBUG,
        event,
        str(state_value(ctx, "temp:run_id")),
        node=ctx.node.name if ctx.node else None,
        **fields,
    )


class IngestNode(BaseNode):
    async def _run_impl(
        self, *, ctx: Context, node_input: Any
    ) -> AsyncGenerator[Any, None]:
        started = perf_counter()
        csv_path: str | None = state_value(ctx, "temp:csv_path")
        node_log(ctx, "node_entry", args={"csv_path": csv_path})
        ctx.state["temp:preparation_result"] = None
        ctx.state["temp:error"] = None
        ctx.route = "skip"
        try:
            result = ingestion.prepare(csv_path)
            ctx.state["temp:preparation_result"] = result
            for row in result["quarantined_rows"]:
                for issue in row["issues"]:
                    field = issue.get("field")
                    details: dict[str, object] = {
                        "line_number": row["line_number"],
                        "code": issue["code"],
                        "field": field,
                    }
                    observed = safe_observed(
                        field or "", row["raw_values"].get(field or "")
                    )
                    if observed is not None:
                        details["observed"] = observed
                    log_event(
                        logging.WARNING,
                        "quarantine_issue",
                        str(state_value(ctx, "temp:run_id")),
                        **details,
                    )
            if result["status"] == "failed":
                issues = result["report"]["file_issues"]
                issue = (
                    issues[0]
                    if issues
                    else {
                        "code": "preparation_failed",
                        "message": "Preparation failed",
                    }
                )
                ctx.state["temp:error"] = {
                    "stage": "preparation",
                    "code": issue["code"],
                    "message": issue["message"],
                }
            elif not result["records"]:
                ctx.state["temp:error"] = {
                    "stage": "preparation",
                    "code": "no_valid_records",
                    "message": "Preparation returned no valid records",
                }
            else:
                ctx.route = "chart"
        except (
            Exception
        ) as exc:  # noqa: BLE001 - child boundary must emit a failure envelope
            ctx.state["temp:preparation_result"] = None
            error = unexpected_error(ctx, "preparation", exc)
            # A non-null output is required for downstream routing/finalization.
            # Preserve the preparation contract even for standalone execution.
            result: PreparationResult = {
                "status": "failed",
                "records": [],
                "quarantined_rows": [],
                "report": {
                    "source_path": csv_path or ingestion.DEFAULT_CSV,
                    "source_rows": 0,
                    "valid_rows": 0,
                    "quarantined_rows": 0,
                    "normalization_change_count": 0,
                    "normalization_changes": [],
                    "file_issues": [
                        {"code": error["code"], "message": error["message"]}
                    ],
                },
            }
        if ctx.route == "skip":
            skip_error = state_value(ctx, "temp:error") or {}
            log_event(
                logging.WARNING,
                "chart_skipped",
                str(state_value(ctx, "temp:run_id")),
                code=skip_error.get("code"),
                reason="Preparation failed or produced no valid sales orders",
            )
        node_log(
            ctx,
            "node_exit",
            return_preview=safe_preview(result),
            duration_ms=(perf_counter() - started) * 1000,
        )
        yield result


class ChartNode(BaseNode):
    async def _run_impl(
        self, *, ctx: Context, node_input: Any
    ) -> AsyncGenerator[Any, None]:
        started = perf_counter()
        source = state_value(ctx, "temp:preparation_result")
        if source is None:
            source = state_value(ctx, "temp:source_result")
        output_path: str | None = state_value(ctx, "temp:output_path")
        node_log(
            ctx,
            "node_entry",
            args={"source_result": safe_preview(source), "output_path": output_path},
        )
        ctx.state["temp:chart_result"] = None
        ctx.state["temp:error"] = None
        try:
            result = chart.generate(source, output_path)
            ctx.state["temp:chart_result"] = result
            if result["status"] == "failed":
                error = result["error"] or {
                    "code": "chart_failed",
                    "message": "Chart generation failed",
                }
                ctx.state["temp:error"] = {"stage": "chart", **error}
        except (
            Exception
        ) as exc:  # noqa: BLE001 - child boundary must emit a failure envelope
            ctx.state["temp:chart_result"] = None
            unexpected = unexpected_error(ctx, "chart", exc)
            result = failure_result(unexpected["code"], unexpected["message"])
        node_log(
            ctx,
            "node_exit",
            return_preview=safe_preview(result),
            duration_ms=(perf_counter() - started) * 1000,
        )
        yield result


class AssembleNode(BaseNode):
    async def _run_impl(
        self, *, ctx: Context, node_input: Any
    ) -> AsyncGenerator[Any, None]:
        started = perf_counter()
        preparation: PreparationResult | None = state_value(
            ctx, "temp:preparation_result"
        )
        chart_result: ChartResult | None = state_value(ctx, "temp:chart_result")
        error: Error | None = state_value(ctx, "temp:error")
        node_log(
            ctx,
            "node_entry",
            args={
                "preparation_result": safe_preview(preparation),
                "chart_result": safe_preview(chart_result),
            },
        )
        result: Result = {
            "status": (
                "failed"
                if error is not None or chart_result is None
                else chart_result["status"]
            ),
            "preparation_result": preparation,
            "chart_result": chart_result,
            "error": error,
        }
        node_log(
            ctx,
            "node_exit",
            return_preview={"status": result["status"]},
            duration_ms=(perf_counter() - started) * 1000,
        )
        yield cast(dict[str, Any], result)
