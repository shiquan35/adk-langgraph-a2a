"""Structured, opt-in logging; never configure the caller's root logger."""

import json
import logging

from langgraph.config import get_config

LOGGER = logging.getLogger("sales_data_agent")
LOGGER.addHandler(logging.NullHandler())


def log_event(level: int, event: str, run_id: str, **fields: object) -> None:
    try:
        pipeline_id = get_config().get("metadata", {}).get("pipeline_run_id")
    except RuntimeError:
        pipeline_id = None
    if isinstance(pipeline_id, str):
        fields["pipeline_run_id"] = pipeline_id
    LOGGER.log(
        level,
        json.dumps({"event": event, "run_id": run_id, **fields}, ensure_ascii=False),
    )
