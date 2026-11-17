"""Public runtime and parent-result contracts."""

from typing import Literal, TypedDict

from .preparation.models import Result as PreparationResult
from .visualization.models import Result as ChartResult

Mode = Literal["run", "ingest", "chart"]
Stage = Literal["preparation", "chart", "artifact_write"]
Status = Literal["completed", "completed_with_warnings", "failed"]


class Error(TypedDict):
    stage: Stage
    code: str
    message: str


class Result(TypedDict):
    status: Status
    preparation_result: PreparationResult | None
    chart_result: ChartResult | None
    error: Error | None
