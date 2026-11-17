"""Typed public preparation contract, independent of graph frameworks."""

from typing import Literal, NotRequired, TypedDict

Status = Literal["completed", "completed_with_errors", "failed"]


class Issue(TypedDict):
    code: str
    message: str
    field: NotRequired[str]
    line_number: NotRequired[int]


class SalesRecord(TypedDict):
    order_id: str
    date: str
    product: str
    category: str
    region: str
    quantity: int
    unit_price: str


class QuarantinedRow(TypedDict):
    line_number: int
    raw_values: dict[str, str]
    issues: list[Issue]


class Normalization(TypedDict):
    line_number: int
    field: str
    original_value: str
    normalized_value: str | int


class Report(TypedDict):
    source_path: str
    source_rows: int
    valid_rows: int
    quarantined_rows: int
    normalization_change_count: int
    normalization_changes: list[Normalization]
    file_issues: list[Issue]


class Result(TypedDict):
    status: Status
    records: list[SalesRecord]
    quarantined_rows: list[QuarantinedRow]
    report: Report
