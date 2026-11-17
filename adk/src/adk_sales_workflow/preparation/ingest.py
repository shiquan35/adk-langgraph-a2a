"""Strict structural preflight before Pandas can reinterpret CSV input."""

import csv
from pathlib import Path

import pandas as pd

from .models import Issue

COLUMNS = (
    "order_id",
    "date",
    "product",
    "category",
    "region",
    "quantity",
    "unit_price",
)
# This module is one level deeper than the public stage modules.
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CSV = "dataset/shared_sales_dataset.csv"


class FileValidationError(Exception):
    def __init__(self, issue: Issue) -> None:
        self.issue = issue
        super().__init__(issue["message"])


def resolve_csv_path(csv_path: str | None = None) -> Path:
    path = Path(csv_path if csv_path is not None else DEFAULT_CSV)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def read_csv(path: Path) -> tuple[pd.DataFrame, list[int]]:
    """Return raw strings and record-start lines; never silently skip a record."""
    rows: list[list[str]] = []
    lines: list[int] = []
    start_line = 1
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, [])
            if len(header) != len(set(header)):
                raise FileValidationError(
                    {
                        "code": "duplicate_header",
                        "message": "Duplicate CSV headers",
                        "line_number": 1,
                    }
                )
            if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
                raise FileValidationError(
                    {
                        "code": "schema_mismatch",
                        "message": f"Expected exactly {list(COLUMNS)}, got {header}",
                        "line_number": 1,
                    }
                )
            while True:
                start_line = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                if len(row) != len(header):
                    raise FileValidationError(
                        {
                            "code": "malformed_csv",
                            "message": f"Expected {len(header)} fields, got {len(row)}",
                            "line_number": start_line,
                        }
                    )
                rows.append(row)
                lines.append(start_line)
    except FileNotFoundError as exc:
        raise FileValidationError(
            {"code": "file_not_found", "message": "CSV file does not exist"}
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise FileValidationError(
            {"code": "file_unreadable", "message": str(exc)}
        ) from exc
    except csv.Error as exc:
        raise FileValidationError(
            {"code": "malformed_csv", "message": str(exc), "line_number": start_line}
        ) from exc
    return pd.DataFrame(rows, columns=header, dtype=object).loc[:, list(COLUMNS)], lines
