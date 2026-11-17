"""Public JSON contracts and private chart graph state."""

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from sales_data_agent.models import SalesRecord

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


class GraphInput(TypedDict):
    # Runtime validation also accepts malformed JSON values to return an envelope.
    source_result: object
    output_path: NotRequired[str | None]


class GraphState(TypedDict, total=False):
    source_result: object
    requested_output: str | None
    output_path: str | None
    run_id: str
    records: list[SalesRecord]
    monthly_totals: list[MonthlyTotal]
    source_status: str | None
    source_row_count: int | None
    valid_row_count: int | None
    quarantined_row_count: int | None
    error: Error | None
    status: Status


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
    """The CLI uses the same envelope when input cannot reach the graph."""
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
