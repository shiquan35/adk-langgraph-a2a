"""Parent workflow contracts; child results are retained unchanged."""

from typing import Literal, TypedDict

from sales_chart_agent.models import Result as ChartResult
from sales_data_agent.models import Result as PreparationResult

Status = Literal["completed", "completed_with_warnings", "failed"]
Stage = Literal["preparation", "chart"]
EXIT_CODES: dict[Status, int] = {
    "completed": 0,
    "completed_with_warnings": 1,
    "failed": 2,
}


class Error(TypedDict):
    stage: Stage
    code: str
    message: str


class GraphInput(TypedDict, total=False):
    csv_path: str | None
    output_path: str | None


class Result(TypedDict):
    status: Status
    preparation_result: PreparationResult | None
    chart_result: ChartResult | None
    error: Error | None


class GraphState(TypedDict, total=False):
    csv_path: str | None
    output_path: str | None
    pipeline_run_id: str
    preparation_result: PreparationResult | None
    chart_result: ChartResult | None
    error: Error | None
    status: Status
