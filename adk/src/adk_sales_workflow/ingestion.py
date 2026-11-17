"""Read, validate, and assemble sales data without a graph runtime."""

from pathlib import Path

from .paths import repository_root
from .preparation.ingest import FileValidationError, read_csv
from .preparation.models import (
    Issue,
    Normalization,
    QuarantinedRow,
    Result,
    SalesRecord,
    Status,
)
from .preparation.validation import validate_rows

# ingestion.py -> adk_sales_workflow -> src -> adk -> repository root.
REPOSITORY_ROOT = repository_root()
DEFAULT_CSV = "dataset/shared_sales_dataset.csv"


def prepare(csv_path: str | None = None) -> Result:
    """Return the preparation envelope, including quarantines and file failures."""
    path = Path(csv_path if csv_path is not None else DEFAULT_CSV)
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    records: list[SalesRecord] = []
    quarantines: list[QuarantinedRow] = []
    changes: list[Normalization] = []
    file_issues: list[Issue] = []
    source_rows = 0
    status: Status = "completed"
    try:
        frame, lines = read_csv(path)
        records, quarantines, changes = validate_rows(frame, lines)
        source_rows = len(lines)
    except FileValidationError as exc:
        status = "failed"
        file_issues.append(exc.issue)
    else:
        if quarantines or source_rows == 0:
            status = "completed_with_errors"
        if source_rows == 0:
            file_issues.append(
                {
                    "code": "empty_dataset",
                    "message": "CSV has headers but no data records",
                }
            )
    return {
        "status": status,
        "records": records,
        "quarantined_rows": quarantines,
        "report": {
            "source_path": str(path),
            "source_rows": source_rows,
            "valid_rows": len(records),
            "quarantined_rows": len(quarantines),
            "normalization_change_count": len(changes),
            "normalization_changes": changes,
            "file_issues": file_issues,
        },
    }
