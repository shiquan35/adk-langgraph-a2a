"""Structured, opt-in logging; never configure the caller's root logger."""

import json
import logging

LOGGER = logging.getLogger("sales_data_agent")
LOGGER.addHandler(logging.NullHandler())


def log_event(level: int, event: str, run_id: str, **fields: object) -> None:
    LOGGER.log(
        level,
        json.dumps({"event": event, "run_id": run_id, **fields}, ensure_ascii=False),
    )
