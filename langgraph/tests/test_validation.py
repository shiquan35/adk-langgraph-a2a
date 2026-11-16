"""Business rules and audit outcomes."""

import pandas as pd
import pytest
from sales_data_agent.validation import validate_rows


@pytest.mark.parametrize(
    "price,expected",
    [
        ("39.9", "39.90"),
        ("39.900", "39.90"),
        ("0.01", "0.01"),
        ("123456789012345678901234567890.00", "123456789012345678901234567890.00"),
    ],
)
def test_exact_prices(valid_row: dict[str, str], price: str, expected: str) -> None:
    valid_row["unit_price"] = price
    records, rejected, _ = validate_rows(pd.DataFrame([valid_row]), [2])
    assert rejected == []
    assert records[0]["unit_price"] == expected


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("unit_price", "39.999", "invalid_unit_price_precision"),
        ("unit_price", "0.00", "invalid_unit_price"),
        ("unit_price", "NaN", "invalid_unit_price"),
        ("unit_price", "Infinity", "invalid_unit_price"),
        ("unit_price", "-1", "invalid_unit_price"),
        ("unit_price", "$1.00", "invalid_unit_price"),
        ("quantity", "1.5", "invalid_quantity"),
        ("quantity", "0", "invalid_quantity"),
        ("quantity", "1e2", "invalid_quantity"),
        ("date", "2025-02-30", "invalid_date"),
        ("date", "01/02/2025", "invalid_date"),
        ("date", "20250101", "invalid_date"),
        ("product", "unknown", "unknown_product"),
        ("category", "audio", "unknown_category"),
        ("category", "Displays", "product_category_mismatch"),
        ("region", "NA", "unknown_region"),
        ("order_id", "  ", "missing_value"),
    ],
)
def test_invalid_values(
    valid_row: dict[str, str], field: str, value: str, code: str
) -> None:
    valid_row[field] = value
    records, rejected, _ = validate_rows(pd.DataFrame([valid_row]), [12])
    assert not records
    assert rejected[0]["line_number"] == 12
    assert rejected[0]["raw_values"][field] == value
    assert code in [issue["code"] for issue in rejected[0]["issues"]]


def test_trim_integer_conversion_and_audit(valid_row: dict[str, str]) -> None:
    valid_row.update(order_id=" ORD-1 ", quantity="3.0", unit_price="39.900")
    records, rejected, changes = validate_rows(pd.DataFrame([valid_row]), [2])
    assert not rejected
    assert records[0]["order_id"] == "ORD-1"
    assert records[0]["quantity"] == 3
    assert {
        "line_number": 2,
        "field": "order_id",
        "original_value": " ORD-1 ",
        "normalized_value": "ORD-1",
    } in changes
    assert {
        "line_number": 2,
        "field": "quantity",
        "original_value": "3.0",
        "normalized_value": 3,
    } in changes


def test_all_duplicates_and_all_issues(valid_row: dict[str, str]) -> None:
    rows = [
        valid_row,
        {**valid_row, "order_id": " ORD-1 ", "date": "bad", "quantity": "bad"},
        {**valid_row, "order_id": "ord-1"},
    ]
    records, rejected, _ = validate_rows(pd.DataFrame(rows), [2, 3, 4])
    assert [record["order_id"] for record in records] == ["ord-1"]
    assert [row["line_number"] for row in rejected] == [2, 3]
    assert {issue["code"] for issue in rejected[1]["issues"]} == {
        "duplicate_order_id",
        "invalid_date",
        "invalid_quantity",
    }


def test_missing_all_fields(valid_row: dict[str, str]) -> None:
    rows = [{field: "" for field in valid_row}]
    records, rejected, _ = validate_rows(pd.DataFrame(rows), [2])
    assert not records
    assert len(rejected[0]["issues"]) == 7
