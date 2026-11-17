"""Structured pipeline events and temporarily scoped CLI stderr handlers."""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

LOGGER = logging.getLogger("sales_pipeline_agent")
LOGGER.addHandler(logging.NullHandler())
LOGGER_NAMES = ("sales_pipeline_agent", "sales_data_agent", "sales_chart_agent")
_CLI_LOGGING_LOCK = RLock()


def log_event(level: int, event: str, pipeline_run_id: str, **fields: object) -> None:
    if not LOGGER.isEnabledFor(level):
        return
    LOGGER.log(
        level,
        json.dumps(
            {"event": event, "pipeline_run_id": pipeline_run_id, **fields},
            ensure_ascii=True,
            allow_nan=False,
        ),
    )


@contextmanager
def stderr_logging() -> Iterator[None]:
    # Logger configuration is process-global: overlapping CLI scopes must serialize.
    with _CLI_LOGGING_LOCK, _stderr_logging_scope():
        yield


@contextmanager
def _stderr_logging_scope() -> Iterator[None]:
    """Restore precisely the settings we change, even after processing fails."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    saved = [
        (
            logging.getLogger(name),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
            list(logging.getLogger(name).handlers),
        )
        for name in LOGGER_NAMES
    ]
    try:
        for logger, level, _, _ in saved:
            debug_enabled = logger.isEnabledFor(logging.DEBUG)
            for existing in list(logger.handlers):
                logger.removeHandler(existing)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
            logger.propagate = False
        yield
    finally:
        for logger, level, propagate, handlers in saved:
            logger.removeHandler(handler)
            for existing in handlers:
                logger.addHandler(existing)
            logger.setLevel(level)
            logger.propagate = propagate
        handler.close()
