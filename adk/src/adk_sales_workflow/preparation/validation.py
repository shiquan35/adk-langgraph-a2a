"""Deterministic business checks, exact decimal parsing, and cleanup audit."""

import re
from datetime import date
from decimal import Decimal
from typing import cast

import pandas as pd

from .ingest import COLUMNS
from .models import Issue, Normalization, QuarantinedRow, SalesRecord

PRODUCT_CATEGORIES = {
    "Mechanical Keyboard": "Accessories",
    "Laptop Stand": "Accessories",
    "USB-C Hub": "Accessories",
    "Wireless Mouse": "Accessories",
    "Headphones": "Audio",
    "Desktop Speaker": "Audio",
    "27-inch Monitor": "Displays",
    "Webcam": "Electronics",
}
REGIONS = {"East", "North", "South", "West"}
DECIMAL_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


def validate_rows(
    frame: pd.DataFrame, line_numbers: list[int]
) -> tuple[list[SalesRecord], list[QuarantinedRow], list[Normalization]]:
    """Validate every row independently; quarantine every duplicated ID."""
    records: list[SalesRecord] = []
    quarantines: list[QuarantinedRow] = []
    changes: list[Normalization] = []
    duplicate_mask = frame["order_id"].str.strip().duplicated(keep=False).tolist()
    for index, values in enumerate(frame.itertuples(index=False, name=None)):
        raw: dict[str, str] = dict(
            zip(COLUMNS, cast(tuple[str, ...], values), strict=True)
        )
        normalized: dict[str, str | int] = {}
        line = line_numbers[index]
        issues: list[Issue] = []

        def reject(
            field: str, code: str, message: str, row_issues: list[Issue] = issues
        ) -> None:
            row_issues.append({"field": field, "code": code, "message": message})

        def assign(
            field: str,
            value: str | int,
            row_values: dict[str, str | int] = normalized,
            raw_values: dict[str, str] = raw,
            line_number: int = line,
        ) -> None:
            previous = row_values.get(field, raw_values[field])
            row_values[field] = value
            if previous != value:
                changes.append(
                    {
                        "line_number": line_number,
                        "field": field,
                        "original_value": str(previous),
                        "normalized_value": value,
                    }
                )

        for field, value in raw.items():
            assign(field, value.strip())
            if not value.strip():
                reject(field, "missing_value", f"{field} is required")
        text = {field: str(value) for field, value in normalized.items()}

        if text["order_id"] and duplicate_mask[index]:
            reject(
                "order_id",
                "duplicate_order_id",
                "Order ID occurs more than once after trimming",
            )
        if text["date"]:
            try:
                if not ISO_DATE.fullmatch(text["date"]):
                    raise ValueError
                date.fromisoformat(text["date"])
            except ValueError:
                reject(
                    "date",
                    "invalid_date",
                    "Expected a real calendar date in YYYY-MM-DD format",
                )

        for field, catalog in (
            ("product", set(PRODUCT_CATEGORIES)),
            ("category", set(PRODUCT_CATEGORIES.values())),
            ("region", REGIONS),
        ):
            if text[field] and text[field] not in catalog:
                reject(field, f"unknown_{field}", f"Unknown {field}: {text[field]}")
        if (
            text["product"] in PRODUCT_CATEGORIES
            and text["category"] in PRODUCT_CATEGORIES.values()
            and PRODUCT_CATEGORIES[text["product"]] != text["category"]
        ):
            reject(
                "category",
                "product_category_mismatch",
                f"{text['product']} belongs to {PRODUCT_CATEGORIES[text['product']]}",
            )

        for field in ("quantity", "unit_price"):
            value = text[field]
            if not value:
                continue
            if not DECIMAL_TEXT.fullmatch(value):
                reject(
                    field,
                    f"invalid_{field}",
                    "Expected a positive number in plain decimal notation",
                )
                continue
            number = Decimal(value)
            if not number.is_finite() or number <= 0:
                reject(field, f"invalid_{field}", "Expected a finite positive value")
            elif field == "quantity":
                if number != number.to_integral_value():
                    reject(field, "invalid_quantity", "Quantity must be a whole number")
                else:
                    assign(field, int(number))
            else:
                # Inspect text rather than context-limited Decimal arithmetic.
                fraction = value.partition(".")[2]
                if any(digit != "0" for digit in fraction[2:]):
                    reject(
                        field,
                        "invalid_unit_price_precision",
                        "Unit price must be exactly representable to cents without rounding",
                    )
                else:
                    integer = value.partition(".")[0].lstrip("0") or "0"
                    assign(field, f"{integer}.{fraction[:2].ljust(2, '0')}")
        if issues:
            quarantines.append(
                {"line_number": line, "raw_values": raw, "issues": issues}
            )
        else:
            records.append(cast(SalesRecord, normalized))
    return records, quarantines, changes
