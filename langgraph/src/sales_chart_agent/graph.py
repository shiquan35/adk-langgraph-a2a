"""Deterministic chart graph: validate, aggregate, render, assemble."""

import logging
from collections.abc import Mapping
from time import perf_counter
from typing import Literal, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from sales_chart_agent.aggregation import aggregate_monthly
from sales_chart_agent.models import (
    EXIT_CODES,
    ChartError,
    GraphInput,
    GraphState,
    Result,
    Status,
)
from sales_chart_agent.observability import log_event
from sales_chart_agent.rendering import render_html, resolve_output_path
from sales_chart_agent.validation import validate_source


def validate(state: GraphState) -> GraphState:
    run_id = uuid4().hex
    started = perf_counter()
    source = state.get("source_result")
    raw_status = source.get("status") if isinstance(source, Mapping) else None
    source_status = raw_status if isinstance(raw_status, str) else None
    requested = state.get("output_path")
    preview: dict[str, object] = {}
    raw_records = source.get("records") if isinstance(source, Mapping) else None
    if (
        isinstance(raw_records, list)
        and raw_records
        and isinstance(raw_records[0], Mapping)
    ):
        first = raw_records[0]
        # Inspect numeric/date inputs only; never dump arbitrary record text.
        for field in ("date", "quantity", "unit_price"):
            value = first.get(field)
            if type(value) is int or (
                isinstance(value, str)
                and len(value) <= 32
                and all(c in "0123456789-." for c in value)
            ):
                preview[field] = value
    log_event(
        logging.INFO,
        "agent_started",
        run_id,
        source_status=source_status,
        output_path=requested if isinstance(requested, str) else None,
    )
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="validate_input",
        args={
            "source_status": source_status,
            "output_path": requested if isinstance(requested, str) else None,
            "record_preview": preview,
        },
    )
    update: GraphState = {
        "run_id": run_id,
        "source_status": source_status,
        "requested_output": requested,
        "output_path": None,
        "monthly_totals": [],
        "error": None,
        "source_row_count": None,
        "valid_row_count": None,
        "quarantined_row_count": None,
    }
    try:
        validated = validate_source(source)
        update.update(
            records=validated.records,
            source_row_count=validated.source_rows,
            valid_row_count=len(validated.records),
            quarantined_row_count=validated.quarantined_rows,
        )
    except ChartError as exc:
        update["error"] = exc.error
        counts = exc.details.get("validated_counts")
        if isinstance(counts, dict):
            update.update(
                source_row_count=counts["source_rows"],
                valid_row_count=counts["valid_rows"],
                quarantined_row_count=counts["quarantined_rows"],
            )
        log_event(logging.WARNING, "input_rejected", run_id, **exc.error, **exc.details)
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="validate_input",
        return_preview={
            "source_status": source_status,
            "error": update["error"],
            "record_preview": [
                {
                    "date": r["date"],
                    "quantity": r["quantity"],
                    "unit_price": r["unit_price"],
                }
                for r in update.get("records", [])[:1]
            ],
        },
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def aggregate(state: GraphState) -> GraphState:
    started = perf_counter()
    records = state.get("records")
    run_id = state.get("run_id")
    assert records is not None and run_id is not None
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="aggregate_monthly",
        args={
            "record_preview": [
                {
                    "date": r["date"],
                    "quantity": r["quantity"],
                    "unit_price": r["unit_price"],
                }
                for r in records[:1]
            ]
        },
    )
    update: GraphState = {}
    try:
        update["monthly_totals"] = aggregate_monthly(records)
    except (ArithmeticError, ValueError) as exc:
        update["error"] = {
            "code": "aggregation_failed",
            "message": f"Unable to aggregate: {type(exc).__name__}",
        }
        log_event(logging.ERROR, "aggregation_failed", run_id, **update["error"])
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="aggregate_monthly",
        return_preview=update,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def render(state: GraphState) -> GraphState:
    started = perf_counter()
    run_id = state.get("run_id")
    totals = state.get("monthly_totals")
    assert run_id is not None and totals is not None
    requested = state.get("requested_output")
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="render_html",
        args={
            "output_path": requested if isinstance(requested, str) else None,
            "monthly_totals": totals,
            "quarantined_rows": state.get("quarantined_row_count"),
        },
    )
    update: GraphState = {"output_path": None}
    try:
        path = resolve_output_path(requested)
        render_html(totals, state.get("quarantined_row_count") or 0, path)
        update["output_path"] = str(path)
    except ChartError as exc:
        update["error"] = exc.error
        log_event(
            logging.ERROR,
            "render_failed",
            run_id,
            output_path=requested if isinstance(requested, str) else None,
            **exc.error,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        update["error"] = {
            "code": "invalid_output_path",
            "message": f"Unable to resolve output: {type(exc).__name__}",
        }
        log_event(
            logging.ERROR,
            "render_failed",
            run_id,
            output_path=requested if isinstance(requested, str) else None,
            **update["error"],
        )
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="render_html",
        return_preview=update,
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def route_validation(state: GraphState) -> Literal["aggregate", "assemble"]:
    return "assemble" if state.get("error") else "aggregate"


def route_aggregation(state: GraphState) -> Literal["render", "assemble"]:
    return "assemble" if state.get("error") else "render"


def assemble(state: GraphState) -> GraphState:
    started = perf_counter()
    run_id = state.get("run_id")
    assert run_id is not None
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="assemble",
        args={
            "error": state.get("error"),
            "output_path": state.get("output_path"),
            "source_status": state.get("source_status"),
        },
    )
    status: Status = (
        "failed"
        if state.get("error")
        else (
            "completed_with_warnings"
            if state.get("source_status") == "completed_with_errors"
            else "completed"
        )
    )
    result: Result = {
        "status": status,
        "output_path": state.get("output_path"),
        "monthly_totals": state.get("monthly_totals", []),
        "source_status": state.get("source_status"),
        "source_row_count": state.get("source_row_count"),
        "valid_row_count": state.get("valid_row_count"),
        "quarantined_row_count": state.get("quarantined_row_count"),
        "error": state.get("error"),
    }
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="assemble",
        return_preview=result,
        duration_ms=(perf_counter() - started) * 1000,
    )
    log_event(
        logging.INFO, "agent_finished", run_id, **result, exit_code=EXIT_CODES[status]
    )
    return cast(GraphState, dict(result))


def build_graph():
    builder = StateGraph(GraphState, input_schema=GraphInput, output_schema=Result)
    builder.add_node("validate", validate)
    builder.add_node("aggregate", aggregate)
    builder.add_node("render", render)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "validate")
    builder.add_conditional_edges("validate", route_validation)
    builder.add_conditional_edges("aggregate", route_aggregation)
    builder.add_edge("render", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile()


graph = build_graph()
