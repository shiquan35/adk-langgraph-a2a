"""Composable three-node graph with explicit file-failure routing."""

import logging
from time import perf_counter
from typing import Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from sales_data_agent.ingest import FileValidationError, read_csv, resolve_csv_path
from sales_data_agent.models import GraphInput, GraphState, Report, Result, Status
from sales_data_agent.observability import log_event
from sales_data_agent.validation import validate_rows


def read_and_check(state: GraphState) -> GraphState:
    started = perf_counter()
    run_id = uuid4().hex
    path = resolve_csv_path(state.get("csv_path"))
    log_event(logging.INFO, "agent_started", run_id, csv_path=str(path))
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="read_and_check",
        args={"csv_path": str(path)},
    )
    update: GraphState = {
        "run_id": run_id,
        "source_path": str(path),
        "file_error": None,
    }
    try:
        update["frame"], update["line_numbers"] = read_csv(path)
    except FileValidationError as exc:
        update["file_error"] = exc.issue
        log_event(
            logging.ERROR, "file_failure", run_id, source_path=str(path), **exc.issue
        )
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="read_and_check",
        return_preview={"source_path": str(path), "file_error": update["file_error"]},
        duration_ms=(perf_counter() - started) * 1000,
    )
    return update


def route_file(state: GraphState) -> Literal["validate", "assemble"]:
    return "assemble" if state.get("file_error") is not None else "validate"


def validate(state: GraphState) -> GraphState:
    started = perf_counter()
    run_id = state.get("run_id")
    frame = state.get("frame")
    lines = state.get("line_numbers")
    assert run_id is not None and frame is not None and lines is not None
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="validate",
        args={"source_path": state.get("source_path"), "columns": list(frame.columns)},
    )
    records, quarantines, changes = validate_rows(frame, lines)
    for change in changes:
        log_event(logging.DEBUG, "normalization", run_id, **change)
    for row in quarantines:
        for issue in row["issues"]:
            field = issue.get("field", "")
            details = {
                **issue,
                "line_number": row["line_number"],
                "observed_value": row["raw_values"].get(field),
            }
            log_event(logging.WARNING, "row_rejected", run_id, **details)
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="validate",
        return_preview={
            "valid_rows": len(records),
            "quarantined_lines": [row["line_number"] for row in quarantines],
        },
        duration_ms=(perf_counter() - started) * 1000,
    )
    return {
        "records": records,
        "quarantined_rows": quarantines,
        "normalization_changes": changes,
    }


def assemble(state: GraphState) -> GraphState:
    started = perf_counter()
    run_id = state.get("run_id")
    source_path = state.get("source_path")
    assert run_id is not None and source_path is not None
    log_event(
        logging.DEBUG,
        "node_entry",
        run_id,
        node="assemble",
        args={"source_path": source_path, "file_error": state.get("file_error")},
    )
    error = state.get("file_error")
    records = state.get("records", []) if error is None else []
    quarantines = state.get("quarantined_rows", []) if error is None else []
    changes = state.get("normalization_changes", []) if error is None else []
    source_rows = len(state.get("line_numbers", [])) if error is None else 0
    file_issues = [error] if error is not None else []
    status: Status = "failed" if error is not None else "completed"
    if error is None and (quarantines or source_rows == 0):
        status = "completed_with_errors"
        if source_rows == 0:
            file_issues.append(
                {
                    "code": "empty_dataset",
                    "message": "CSV has headers but no data records",
                }
            )
    report: Report = {
        "source_path": source_path,
        "source_rows": source_rows,
        "valid_rows": len(records),
        "quarantined_rows": len(quarantines),
        "normalization_change_count": len(changes),
        "normalization_changes": changes,
        "file_issues": file_issues,
    }
    log_event(
        logging.DEBUG,
        "node_exit",
        run_id,
        node="assemble",
        return_preview={
            "status": status,
            "report": {
                "source_path": source_path,
                "valid_rows": len(records),
                "file_issues": file_issues,
            },
        },
        duration_ms=(perf_counter() - started) * 1000,
    )
    log_event(
        logging.INFO,
        "agent_finished",
        run_id,
        status=status,
        source_path=source_path,
        source_rows=source_rows,
        valid_rows=len(records),
        quarantined_rows=len(quarantines),
        exit_code={"completed": 0, "completed_with_errors": 1, "failed": 2}[status],
        file_issues=file_issues,
    )
    return {
        "status": status,
        "records": records,
        "quarantined_rows": quarantines,
        "report": report,
    }


def build_graph():
    builder = StateGraph(GraphState, input_schema=GraphInput, output_schema=Result)
    builder.add_node("read", read_and_check)
    builder.add_node("validate", validate)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "read")
    builder.add_conditional_edges("read", route_file)
    builder.add_edge("validate", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile()


graph = build_graph()
