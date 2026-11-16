"""Opt-in structured logs; no root logger or stdout configuration."""

import json
import logging

from langgraph.config import get_config

LOGGER = logging.getLogger("sales_chart_agent")
LOGGER.addHandler(logging.NullHandler())


def log_event(level: int, event: str, run_id: str, **fields: object) -> None:
    if not LOGGER.isEnabledFor(level):
        return
    try:
        pipeline_id = get_config().get("metadata", {}).get("pipeline_run_id")
    except RuntimeError:
        pipeline_id = None
    if isinstance(pipeline_id, str):
        fields["pipeline_run_id"] = pipeline_id
    try:
        message = json.dumps(
            {"event": event, "run_id": run_id, **fields}, allow_nan=False
        )
    except (TypeError, ValueError, OverflowError):
        message = json.dumps(
            {
                "event": event,
                "run_id": run_id,
                "diagnostic_error": "Unserializable diagnostic values",
            }
        )
    LOGGER.log(level, message)
