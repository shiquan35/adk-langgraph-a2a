"""Execute real ADK nodes with a fresh ephemeral session for every call."""

import logging
from time import perf_counter
from typing import Any
from uuid import uuid4

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import BaseNode

from .models import Mode
from .nodes import ChartNode, IngestNode
from .observability import current_invocation_id, log_event, safe_preview
from .workflow import build_workflow

APP_NAME = "adk_sales_workflow"
USER_ID = "local"


async def execute(
    mode: Mode,
    *,
    csv_path: str | None = None,
    source_result: Any = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Return the terminal parent/preparation/chart envelope; never publish files."""
    node: BaseNode
    if mode == "run":
        node = build_workflow()
        terminal_name = "assemble"
    elif mode == "ingest":
        node = IngestNode(name="ingest")
        terminal_name = node.name
    elif mode == "chart":
        node = ChartNode(name="chart")
        terminal_name = node.name
    else:
        raise ValueError(f"Unsupported execution mode: {mode}")
    run_id = current_invocation_id() or uuid4().hex
    initial_state: dict[str, Any] = {
        "temp:run_id": run_id,
        "temp:csv_path": csv_path,
        "temp:source_result": source_result,
        "temp:output_path": output_path,
        "temp:preparation_result": None,
        "temp:chart_result": None,
        "temp:error": None,
    }
    service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, node=node, session_service=service)
    started = perf_counter()
    terminal_output: dict[str, Any] | None = None
    log_event(logging.INFO, "workflow_started", run_id, mode=mode)
    try:
        session = await service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=run_id,
            state=initial_state,
        )
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            # ADK may omit temp keys from persisted session state. Seed the
            # invocation as well, so only this invocation owns the handoff.
            state_delta=initial_state,
        ):
            if (
                event.node_info is not None
                and event.node_info.name == terminal_name
                and isinstance(event.output, dict)
            ):
                terminal_output = event.output
        if terminal_output is None:
            raise RuntimeError("ADK execution produced no terminal dictionary output")
        return terminal_output
    finally:
        try:
            await runner.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask execution
            log_event(
                logging.ERROR,
                "cleanup_failed",
                run_id,
                exception_type=type(exc).__name__,
            )
        finally:
            log_event(
                logging.INFO,
                "execution_finished",
                run_id,
                mode=mode,
                result=safe_preview(terminal_output),
                duration_ms=(perf_counter() - started) * 1000,
            )
