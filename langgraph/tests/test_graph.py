"""Public graph envelopes and conditional failure routing."""

import json
import logging
from pathlib import Path

import pytest
from conftest import write_csv
from sales_data_agent.graph import build_graph, graph
from sales_data_agent.ingest import REPOSITORY_ROOT


def test_shared_dataset() -> None:
    result = graph.invoke({})
    assert result["status"] == "completed"
    assert len(result["records"]) == 500
    assert result["records"][0]["order_id"] == "ORD-0205"
    assert result["records"][0]["quantity"] == 8
    assert result["records"][0]["unit_price"] == "89.00"
    assert result["quarantined_rows"] == []
    assert result["report"]["source_rows"] == 500
    assert set(result) == {"status", "records", "quarantined_rows", "report"}
    json.dumps(result, allow_nan=False)


def test_partial_and_all_invalid(tmp_path: Path, valid_row: dict[str, str]) -> None:
    invalid = {**valid_row, "order_id": "bad", "quantity": "0"}
    path = write_csv(tmp_path / "input.csv", [valid_row, invalid])
    result = graph.invoke({"csv_path": str(path)})
    assert result["status"] == "completed_with_errors"
    assert result["report"]["valid_rows"] == 1
    assert result["report"]["quarantined_rows"] == 1
    write_csv(path, [invalid])
    result = graph.invoke({"csv_path": str(path)})
    assert result["status"] == "completed_with_errors"
    assert result["records"] == []


def test_failed_route_skips_validation(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("bad,header\na,b\n")
    updates = list(build_graph().stream({"csv_path": str(path)}, stream_mode="updates"))
    assert [next(iter(update)) for update in updates] == ["read", "assemble"]
    result = graph.invoke({"csv_path": str(path)})
    assert result["status"] == "failed"
    assert result["records"] == result["quarantined_rows"] == []
    assert result["report"]["file_issues"][0]["code"] == "schema_mismatch"


def test_header_only(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "empty.csv", [])
    result = graph.invoke({"csv_path": str(path)})
    assert result["status"] == "completed_with_errors"
    assert result["report"]["file_issues"][0]["code"] == "empty_dataset"


def test_relative_default_path() -> None:
    result = graph.invoke({"csv_path": "dataset/shared_sales_dataset.csv"})
    assert result["report"]["source_path"] == str(
        REPOSITORY_ROOT / "dataset/shared_sales_dataset.csv"
    )


def test_multiline_quarantine(tmp_path: Path, valid_row: dict[str, str]) -> None:
    path = write_csv(
        tmp_path / "multi.csv",
        [
            {**valid_row, "product": "bad\nproduct"},
            {**valid_row, "order_id": "ORD-2", "quantity": "bad"},
        ],
    )
    result = graph.invoke({"csv_path": str(path)})
    assert [row["line_number"] for row in result["quarantined_rows"]] == [2, 4]
    assert result["quarantined_rows"][0]["raw_values"]["product"] == "bad\nproduct"


def test_structured_logging(
    tmp_path: Path, valid_row: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_csv(tmp_path / "bad.csv", [{**valid_row, "quantity": "bad"}])
    with caplog.at_level(logging.DEBUG, logger="sales_data_agent"):
        graph.invoke({"csv_path": str(path)})
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "sales_data_agent"
    ]
    assert len({event["run_id"] for event in events}) == 1
    rejection = next(event for event in events if event["event"] == "row_rejected")
    assert rejection["field"] == "quantity"
    assert rejection["code"] == "invalid_quantity"
    assert rejection["observed_value"] == "bad"
    finish = next(event for event in events if event["event"] == "agent_finished")
    assert finish["source_rows"] == finish["quarantined_rows"] == 1
    assert finish["exit_code"] == 1
    assert {event["node"] for event in events if event["event"] == "node_entry"} == {
        "read_and_check",
        "validate",
        "assemble",
    }
    assert {event["node"] for event in events if event["event"] == "node_exit"} == {
        "read_and_check",
        "validate",
        "assemble",
    }
    assert all("raw_values" not in event and "records" not in event for event in events)
