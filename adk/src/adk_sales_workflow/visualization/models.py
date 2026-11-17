"""Public JSON chart contracts, independent of graph frameworks."""

from dataclasses import dataclass
from typing import Literal, TypedDict

from ..preparation.models import SalesRecord

Status = Literal["completed", "completed_with_warnings", "failed"]
EXIT_CODES: dict[Status, int] = {
    "completed": 0,
    "completed_with_warnings": 1,
    "failed": 2,
}


class Error(TypedDict):
    code: str
    message: str


class MonthlyTotal(TypedDict):
    month: str
    sales_amount: str


class Result(TypedDict):
    status: Status
    output_path: str | None
    monthly_totals: list[MonthlyTotal]
    source_status: str | None
    source_row_count: int | None
    valid_row_count: int | None
    quarantined_row_count: int | None
    error: Error | None


@dataclass(frozen=True)
class ValidatedSource:
    status: Literal["completed", "completed_with_errors"]
    records: list[SalesRecord]
    source_rows: int
    quarantined_rows: int


class ChartError(Exception):
    """Expected processing failure with safe, structured diagnostic context."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.error: Error = {"code": code, "message": message}
        self.details = details


def failure_result(code: str, message: str) -> Result:
    """Build a failure envelope when input cannot reach chart generation."""
    return {
        "status": "failed",
        "output_path": None,
        "monthly_totals": [],
        "source_status": None,
        "source_row_count": None,
        "valid_row_count": None,
        "quarantined_row_count": None,
        "error": {"code": code, "message": message},
    }
