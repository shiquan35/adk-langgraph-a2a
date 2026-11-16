"""One sequential parent workflow around the two existing compiled graphs."""

import logging
import traceback
from time import perf_counter
from typing import Literal, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sales_chart_agent import graph as chart_graph
from sales_chart_agent.models import Result as ChartResult
from sales_chart_agent.rendering import DEFAULT_OUTPUT
from sales_data_agent import graph as preparation_graph
from sales_data_agent.ingest import DEFAULT_CSV
from sales_data_agent.models import Result as PreparationResult

from sales_pipeline_agent.models import (
    EXIT_CODES,
    Error,
    GraphInput,
    GraphState,
    Result,
    Stage,
    Status,
)
from sales_pipeline_agent.observability import log_event


def child_config(config: RunnableConfig, pipeline_id: str) -> RunnableConfig:
    return {
        **config,
        "metadata": {**config.get("metadata", {}), "pipeline_run_id": pipeline_id},
    }


def unexpected_error(stage: Stage, pipeline_id: str, exc: Exception) -> Error:
    # Tracebacks contain stack locations and exception type, not arbitrary secret-bearing messages.
    stack = "".join(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        for frame in traceback.extract_tb(exc.__traceback__)
    )
    log_event(
        logging.ERROR,
        "stage_exception",
        pipeline_id,
        stage=stage,
        exception_type=type(exc).__name__,
        traceback=stack + type(exc).__name__,
    )
    return {
        "stage": stage,
        "code": "unexpected_stage_error",
        "message": f"Unexpected {stage} error: {type(exc).__name__}",
    }


def prepare(state: GraphState, config: RunnableConfig) -> GraphState:
    started = perf_counter()
    pipeline_id = uuid4().hex
    csv_path = state.get("csv_path")
    log_event(
        logging.INFO,
        "pipeline_started",
        pipeline_id,
        csv_path=csv_path if csv_path is not None else DEFAULT_CSV,
        output_path=(
            state.get("output_path")
            if state.get("output_path") is not None
            else DEFAULT_OUTPUT
        ),
    )
    log_event(
        logging.DEBUG,
        "node_entry",
        pipeline_id,
        node="prepare",
        args={"csv_path": csv_path},
    )
    update: GraphState = {
        "pipeline_run_id": pipeline_id,
        "preparation_result": None,
        "chart_result": None,
        "error": None,
    }
    try:
        result = cast(
            PreparationResult,
            preparation_graph.invoke(
                {"csv_path": csv_path}, config=child_config(config, pipeline_id)
            ),
        )
        update["preparation_result"] = result
        if result["status"] == "failed":
            issues = result["report"]["file_issues"]
            issue = (
                issues[0]
                if issues
                else {"code": "preparation_failed", "message": "Preparation failed"}
            )
            update["error"] = {
                "stage": "preparation",
                "code": issue["code"],
                "message": issue["message"],
            }
        elif not result["records"]:
            update["error"] = {
                "stage": "preparation",
                "code": "no_valid_records",
                "message": "Preparation returned no valid records",
            }
    except (
        Exception
    ) as exc:  # noqa: BLE001 - public stage boundary returns the required failure envelope
        update["preparation_result"] = None
        update["error"] = unexpected_error("preparation", pipeline_id, exc)
    if update.get("error") is not None:
        log_event(
            logging.WARNING,
            "chart_skipped",
            pipeline_id,
            **cast(Error, update.get("error")),
        )
    result_preview = update.get("preparation_result")
    log_event(
        logging.DEBUG,
        "node_exit",
        pipeline_id,
        node="prepare",
        return_preview={
            "status": result_preview["status"] if result_preview else None,
            "source_path": (
                result_preview["report"]["source_path"] if result_preview else None
            ),
            "error": update.get("error"),
        },
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def route_preparation(state: GraphState) -> Literal["chart", "assemble"]:
    return "assemble" if state.get("error") is not None else "chart"


def chart(state: GraphState, config: RunnableConfig) -> GraphState:
    started = perf_counter()
    pipeline_id = state.get("pipeline_run_id")
    source = state.get("preparation_result")
    assert pipeline_id is not None and source is not None
    log_event(
        logging.DEBUG,
        "node_entry",
        pipeline_id,
        node="chart",
        args={
            "source_status": source["status"],
            "source_path": source["report"]["source_path"],
            "output_path": state.get("output_path"),
        },
    )
    update: GraphState = {"chart_result": None, "error": None}
    try:
        result = cast(
            ChartResult,
            chart_graph.invoke(
                {"source_result": source, "output_path": state.get("output_path")},
                config=child_config(config, pipeline_id),
            ),
        )
        update["chart_result"] = result
        if result["status"] == "failed":
            error = result["error"] or {
                "code": "chart_failed",
                "message": "Chart generation failed",
            }
            update["error"] = {
                "stage": "chart",
                "code": error["code"],
                "message": error["message"],
            }
    except (
        Exception
    ) as exc:  # noqa: BLE001 - public stage boundary returns the required failure envelope
        update["chart_result"] = None
        update["error"] = unexpected_error("chart", pipeline_id, exc)
    chart_result = update.get("chart_result")
    log_event(
        logging.DEBUG,
        "node_exit",
        pipeline_id,
        node="chart",
        return_preview={
            "status": chart_result["status"] if chart_result else None,
            "output_path": chart_result["output_path"] if chart_result else None,
            "monthly_totals": chart_result["monthly_totals"] if chart_result else [],
            "error": update.get("error"),
        },
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def assemble(state: GraphState) -> GraphState:
    started = perf_counter()
    pipeline_id = state.get("pipeline_run_id")
    assert pipeline_id is not None
    chart_result = state.get("chart_result")
    error = state.get("error")
    log_event(
        logging.DEBUG,
        "node_entry",
        pipeline_id,
        node="assemble",
        args={
            "chart_status": chart_result["status"] if chart_result else None,
            "error": error,
        },
    )
    status: Status = (
        "failed"
        if error is not None
        else cast(Status, chart_result["status"] if chart_result else "failed")
    )
    result: Result = {
        "status": status,
        "preparation_result": state.get("preparation_result"),
        "chart_result": chart_result,
        "error": error,
    }
    preview = {
        "status": status,
        "output_path": chart_result["output_path"] if chart_result else None,
        "error": error,
    }
    log_event(
        logging.DEBUG,
        "node_exit",
        pipeline_id,
        node="assemble",
        return_preview=preview,
        duration_ms=(perf_counter() - started) * 1000,
    )
    log_event(
        logging.INFO,
        "pipeline_finished",
        pipeline_id,
        **preview,
        exit_code=EXIT_CODES[status],
    )
    return cast(GraphState, dict(result))


def build_graph():
    builder = StateGraph(GraphState, input_schema=GraphInput, output_schema=Result)
    builder.add_node("prepare", prepare)
    builder.add_node("chart", chart)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", route_preparation)
    builder.add_edge("chart", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile()


graph = build_graph()
