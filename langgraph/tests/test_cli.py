"""End-to-end installed console command behavior."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write_csv
from sales_data_agent.ingest import COLUMNS, REPOSITORY_ROOT

CONSOLE = Path(sys.executable).parent / "sales-data"


def test_help() -> None:
    command = subprocess.run(
        [str(CONSOLE), "--help"], capture_output=True, text=True, check=False
    )
    assert command.returncode == 0
    assert "--csv-path" in command.stdout


def test_default_and_relative_paths(tmp_path: Path) -> None:
    for args in ([], ["--csv-path", "dataset/shared_sales_dataset.csv"]):
        command = subprocess.run(
            [str(CONSOLE), *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert command.returncode == 0
        result = json.loads(command.stdout)
        assert len(result["records"]) == 500
        assert result["report"]["source_path"] == str(
            REPOSITORY_ROOT / "dataset/shared_sales_dataset.csv"
        )
        assert all("run_id" in json.loads(line) for line in command.stderr.splitlines())
        assert "agent_started" in command.stderr and "agent_finished" in command.stderr


@pytest.mark.parametrize(
    "kind,exit_code,status",
    [
        ("clean", 0, "completed"),
        ("invalid", 1, "completed_with_errors"),
        ("empty", 1, "completed_with_errors"),
        ("missing", 2, "failed"),
        ("malformed", 2, "failed"),
    ],
)
def test_absolute_path_and_exit_codes(
    tmp_path: Path, valid_row: dict[str, str], kind: str, exit_code: int, status: str
) -> None:
    path = tmp_path / "input.csv"
    if kind == "clean":
        write_csv(path, [valid_row])
    elif kind == "invalid":
        write_csv(path, [{**valid_row, "quantity": "bad"}])
    elif kind == "empty":
        write_csv(path, [])
    elif kind == "malformed":
        path.write_text(",".join(COLUMNS) + "\nbad,row\n")
    command = subprocess.run(
        [str(CONSOLE), "--csv-path", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert command.returncode == exit_code
    assert json.loads(command.stdout)["status"] == status
    if kind == "invalid":
        assert "invalid_quantity" in command.stderr


def test_usage_error() -> None:
    command = subprocess.run(
        [str(CONSOLE), "--unknown"], capture_output=True, text=True, check=False
    )
    assert command.returncode == 2
    assert command.stdout == ""
    assert "unrecognized arguments" in command.stderr
