"""Opt-in structured logs; no root logger or stdout configuration."""

import json
import logging

LOGGER = logging.getLogger("sales_chart_agent")
LOGGER.addHandler(logging.NullHandler())


def log_event(level: int, event: str, run_id: str, **fields: object) -> None:
    if not LOGGER.isEnabledFor(level):
        return
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
