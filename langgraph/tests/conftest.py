"""Small source CSV fixtures, independent of production parsing."""

import csv
from pathlib import Path

import pytest


@pytest.fixture
def valid_row() -> dict[str, str]:
    return {
        "order_id": "ORD-1",
        "date": "2025-01-01",
        "product": "Headphones",
        "category": "Audio",
        "region": "North",
        "quantity": "3",
        "unit_price": "119.0",
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "order_id",
                "date",
                "product",
                "category",
                "region",
                "quantity",
                "unit_price",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path
