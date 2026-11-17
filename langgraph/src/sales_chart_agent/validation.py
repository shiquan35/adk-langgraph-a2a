"""Validate the source envelope without repairing records or repeating catalogs."""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from sales_data_agent.models import SalesRecord

from sales_chart_agent.models import ChartError, ValidatedSource

DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
PRICE_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
TEXT_FIELDS = ("order_id", "product", "category", "region")


def validate_source(value: object) -> ValidatedSource:
    if not isinstance(value, Mapping):
        raise ChartError("invalid_source_envelope", "Source result must be a mapping")
    status = value.get("status")
    if status == "failed":
        raise ChartError("source_failed", "Agent 1 failed; no chart can be generated")
    if status not in ("completed", "completed_with_errors"):
        raise ChartError("invalid_source_status", "Unknown or missing Agent 1 status")
    records = value.get("records")
    quarantines = value.get("quarantined_rows")
    report = value.get("report")
    if not isinstance(records, list) or not isinstance(quarantines, list):
        raise ChartError(
            "invalid_source_envelope", "Source records and quarantines must be arrays"
        )
    if not isinstance(report, Mapping):
        raise ChartError("invalid_source_envelope", "Source report must be a mapping")
    counts: dict[str, int] = {}
    for field in ("source_rows", "valid_rows", "quarantined_rows"):
        count = report.get(field)
        if type(count) is not int or count < 0:
            raise ChartError(
                "invalid_source_report",
                f"report.{field} must be a non-negative integer",
            )
        counts[field] = count
    if (
        len(records) != counts["valid_rows"]
        or len(quarantines) != counts["quarantined_rows"]
        or counts["source_rows"] != counts["valid_rows"] + counts["quarantined_rows"]
    ):
        raise ChartError(
            "inconsistent_source_report",
            "Source arrays and report counts do not agree",
            records_length=len(records),
            quarantines_length=len(quarantines),
            reported_counts=counts,
        )
    if (status == "completed" and quarantines) or (
        status == "completed_with_errors" and records and not quarantines
    ):
        raise ChartError(
            "inconsistent_source_status",
            "Source status contradicts its quarantine count",
        )
    if not records:
        raise ChartError("no_valid_records", "Source has no valid records to chart")
    try:
        validated = [
            validate_record(record, index) for index, record in enumerate(records, 1)
        ]
    except ChartError as exc:
        exc.details["validated_counts"] = counts
        raise
    return ValidatedSource(
        status=cast(Literal["completed", "completed_with_errors"], status),
        records=validated,
        source_rows=counts["source_rows"],
        quarantined_rows=counts["quarantined_rows"],
    )


def validate_record(value: object, index: int) -> SalesRecord:
    if not isinstance(value, Mapping):
        raise ChartError(
            "invalid_record", "Record must be a mapping", record_index=index
        )
    for field in TEXT_FIELDS:
        text = value.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ChartError(
                "invalid_record",
                f"{field} must be non-empty text",
                record_index=index,
                field=field,
            )
    day = value.get("date")
    if not isinstance(day, str) or DATE_PATTERN.fullmatch(day) is None:
        raise ChartError(
            "invalid_date",
            "Date must be exactly YYYY-MM-DD",
            record_index=index,
            field="date",
        )
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise ChartError(
            "invalid_date",
            "Date must be a real calendar date",
            record_index=index,
            field="date",
            observed_value=day,
        ) from exc
    quantity = value.get("quantity")
    if type(quantity) is not int or quantity <= 0:
        raise ChartError(
            "invalid_quantity",
            "Quantity must be a positive integer, not a boolean",
            record_index=index,
            field="quantity",
        )
    price = value.get("unit_price")
    if (
        not isinstance(price, str)
        or PRICE_PATTERN.fullmatch(price) is None
        or Decimal(price) <= 0
    ):
        raise ChartError(
            "invalid_unit_price",
            "Price must be a positive canonical two-decimal string",
            record_index=index,
            field="unit_price",
            value_type=type(price).__name__,
            value_length=len(price) if isinstance(price, str) else None,
        )
    # Copy just the public record fields; never mutate the supplied envelope.
    return cast(
        SalesRecord,
        {
            field: value[field]
            for field in (*TEXT_FIELDS, "date", "quantity", "unit_price")
        },
    )
