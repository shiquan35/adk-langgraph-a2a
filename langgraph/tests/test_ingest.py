"""Structure and physical provenance precede Pandas interpretation."""

from pathlib import Path

import pytest
from conftest import write_csv
from sales_data_agent.ingest import COLUMNS, FileValidationError, read_csv


def test_multiline_and_following_record(
    tmp_path: Path, valid_row: dict[str, str]
) -> None:
    path = write_csv(
        tmp_path / "rows.csv",
        [{**valid_row, "order_id": "first\norder"}, {**valid_row, "order_id": "NA"}],
    )
    frame, lines = read_csv(path)
    assert lines == [2, 4]
    assert frame["order_id"].tolist() == ["first\norder", "NA"]


@pytest.mark.parametrize(
    "contents,code",
    [
        ("order_id,order_id\na,b\n", "duplicate_header"),
        ("order_id,date\na,b\n", "schema_mismatch"),
        (",".join(COLUMNS) + ",extra\n", "schema_mismatch"),
        (",".join(COLUMNS) + "\na,b\n", "malformed_csv"),
        (",".join(COLUMNS) + "\na,b,c,d,e,f,g,h\n", "malformed_csv"),
        (",".join(COLUMNS) + '\n"unterminated\n', "malformed_csv"),
        (",".join(COLUMNS) + "\n\n", "malformed_csv"),
        ("", "schema_mismatch"),
    ],
)
def test_structure_failure(tmp_path: Path, contents: str, code: str) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(contents)
    with pytest.raises(FileValidationError) as caught:
        read_csv(path)
    assert caught.value.issue["code"] == code
    assert caught.value.issue.get("line_number") in (1, 2)


def test_reordered_headers(tmp_path: Path, valid_row: dict[str, str]) -> None:
    columns = list(reversed(COLUMNS))
    path = tmp_path / "reordered.csv"
    path.write_text(
        ",".join(columns) + "\n" + ",".join(valid_row[key] for key in columns) + "\n"
    )
    frame, _ = read_csv(path)
    assert list(frame.columns) == list(COLUMNS)
    assert frame.iloc[0]["order_id"] == "ORD-1"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileValidationError) as caught:
        read_csv(tmp_path / "missing.csv")
    assert caught.value.issue["code"] == "file_not_found"
