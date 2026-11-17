"""Safe JSON events; stderr configuration is scoped to an explicit CLI call."""

import json
import logging
import re
import sys
import traceback
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from uuid import uuid4

LOGGER = logging.getLogger("adk_sales_workflow")
LOGGER.addHandler(logging.NullHandler())
_CLI_LOGGING_LOCK = RLock()
_INVOCATION_ID: ContextVar[str | None] = ContextVar("adk_run_id", default=None)
_STATUSES = {"completed", "completed_with_errors", "completed_with_warnings", "failed"}


def current_invocation_id() -> str | None:
    return _INVOCATION_ID.get()


@contextmanager
def invocation_id() -> Iterator[str]:
    """Give one CLI invocation an ID, restoring any enclosing scope on exit."""
    run_id = uuid4().hex
    token = _INVOCATION_ID.set(run_id)
    try:
        yield run_id
    finally:
        _INVOCATION_ID.reset(token)


def safe_observed(field: str, value: object) -> str | int | None:
    """Permit only bounded ASCII numeric/date values, even before validation."""
    if field in ("date", "month"):
        if isinstance(value, str) and re.fullmatch(r"[0-9-]{1,10}", value):
            return value
    elif field in ("quantity", "unit_price", "sales_amount"):
        if type(value) is int and value.bit_length() <= 256:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9.+-]{1,80}", value):
            return value
    return None


def _safe_fields(
    value: Mapping[object, object], keys: tuple[str, ...]
) -> dict[str, object]:
    return {
        key: observed
        for key in keys
        if (observed := safe_observed(key, value.get(key))) is not None
    }


def log_event(level: int, event: str, run_id: str, **fields: object) -> None:
    if LOGGER.isEnabledFor(level):
        LOGGER.log(
            level,
            json.dumps(
                {**fields, "event": event, "run_id": run_id},
                ensure_ascii=True,
                allow_nan=False,
            ),
        )


def safe_preview(value: object) -> dict[str, object]:
    """Never include raw/quarantined rows, order IDs, or arbitrary text fields."""
    if not isinstance(value, Mapping):
        return {"type": type(value).__name__}
    preview: dict[str, object] = {}
    for key in ("status", "source_status"):
        item = value.get(key)
        if item is None or (isinstance(item, str) and item in _STATUSES):
            preview[key] = item
    for key in (
        "source_row_count",
        "valid_row_count",
        "quarantined_row_count",
    ):
        item = value.get(key)
        if item is None or type(item) is int:
            preview[key] = item
    report = value.get("report")
    if isinstance(report, Mapping):
        preview["counts"] = {
            key: report.get(key)
            for key in ("source_rows", "valid_rows", "quarantined_rows")
            if isinstance(report.get(key), int)
        }
    records = value.get("records")
    if isinstance(records, list):
        preview["records"] = [
            _safe_fields(item, ("date", "quantity", "unit_price"))
            for item in records[:3]
            if isinstance(item, Mapping)
        ]
    totals = value.get("monthly_totals")
    if isinstance(totals, list):
        preview["monthly_totals"] = [
            _safe_fields(item, ("month", "sales_amount"))
            for item in totals[:12]
            if isinstance(item, Mapping)
        ]
    return preview


def log_exception(run_id: str, stage: str, exc: Exception) -> None:
    # Keep stack locations and exception type, excluding messages/source lines
    # that could contain arbitrary input or credentials.
    stack = "".join(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        for frame in traceback.extract_tb(exc.__traceback__)
    )
    log_event(
        logging.ERROR,
        "stage_exception",
        run_id,
        stage=stage,
        exception_type=type(exc).__name__,
        traceback=stack + type(exc).__name__,
    )


@contextmanager
def stderr_logging() -> Iterator[None]:
    """Temporarily attach one dedicated handler, without touching root logging."""
    with _CLI_LOGGING_LOCK:
        level, propagate, handlers = (
            LOGGER.level,
            LOGGER.propagate,
            list(LOGGER.handlers),
        )
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        try:
            debug = LOGGER.isEnabledFor(logging.DEBUG)
            for existing in handlers:
                LOGGER.removeHandler(existing)
            LOGGER.addHandler(handler)
            LOGGER.setLevel(logging.DEBUG if debug else logging.INFO)
            LOGGER.propagate = False
            yield
        finally:
            LOGGER.removeHandler(handler)
            for existing in handlers:
                LOGGER.addHandler(existing)
            LOGGER.setLevel(level)
            LOGGER.propagate = propagate
            handler.close()
