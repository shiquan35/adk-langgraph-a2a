"""Combined CLI subprocess and logging-restoration tests."""

import importlib
import json
import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import write_csv
from sales_pipeline_agent.cli import main
from sales_pipeline_agent.observability import LOGGER_NAMES


def run_cli(*args: str, cwd: Path | None = None):
    command = str(Path(sys.executable).parent / "sales-pipeline")
    return subprocess.run(
        [command, *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def test_default_csv_subprocess(tmp_path: Path) -> None:
    output = tmp_path / "chart.html"
    completed = run_cli("--output", str(output), cwd=tmp_path)
    result = json.loads(completed.stdout)
    assert completed.returncode == 0 and result["status"] == "completed"
    assert result["preparation_result"]["report"]["valid_rows"] == 500
    assert result["chart_result"]["output_path"] == str(output)
    assert (
        completed.stdout
        == json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n"
    )
    events = [json.loads(line) for line in completed.stderr.splitlines()]
    assert len({e["pipeline_run_id"] for e in events}) == 1
    assert sum(e["event"] == "agent_started" for e in events) == 2
    assert events[-1]["event"] == "pipeline_finished"


def test_existing_stdout_handler_and_debug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    logger = logging.getLogger("sales_pipeline_agent")
    handler = logging.StreamHandler(sys.stdout)
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        assert main(["--output", str(tmp_path / "chart.html")]) == 0
        streams = capsys.readouterr()
        assert len(streams.out.splitlines()) == 1
        assert json.loads(streams.out)["status"] == "completed"
        events = [json.loads(line) for line in streams.err.splitlines()]
        assert any(e["event"] == "node_entry" for e in events)
        assert handler in logger.handlers and logger.level == logging.DEBUG
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()


def test_logging_scopes_serialize() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sales_pipeline_agent.observability import stderr_logging

    started, entered = Event(), Event()
    logger = logging.getLogger("sales_pipeline_agent")
    original = (list(logger.handlers), logger.level, logger.propagate)

    def other_scope() -> None:
        started.set()
        with stderr_logging():
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with stderr_logging():
            future = executor.submit(other_scope)
            assert started.wait(5)
            assert not entered.is_set()
        future.result(timeout=5)
    assert entered.is_set()
    assert (list(logger.handlers), logger.level, logger.propagate) == original


@pytest.mark.parametrize(
    "kind,exit_code",
    [("clean", 0), ("partial", 1), ("empty", 2), ("rejected", 2), ("missing", 2)],
)
def test_cli_outcomes(
    tmp_path: Path, valid_row: dict[str, str], kind: str, exit_code: int
) -> None:
    csv = tmp_path / "sales.csv"
    rows = [valid_row]
    if kind == "partial":
        rows.append({**valid_row, "order_id": "invalid", "quantity": "0"})
    elif kind == "empty":
        rows = []
    elif kind == "rejected":
        rows = [{**valid_row, "quantity": "0"}]
    if kind != "missing":
        write_csv(csv, rows)
    output = tmp_path / "chart.html"
    output.write_text("previous")
    completed = run_cli("--csv-path", str(csv), "--output", str(output))
    result = json.loads(completed.stdout)
    assert completed.returncode == exit_code
    assert result["preparation_result"] is not None
    if exit_code == 2:
        assert result["chart_result"] is None and output.read_text() == "previous"
    else:
        assert result["chart_result"] is not None and result["error"] is None


def test_cli_chart_failure(tmp_path: Path) -> None:
    completed = run_cli("--output", str(tmp_path))
    result = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert result["preparation_result"]["status"] == "completed"
    assert result["chart_result"]["status"] == "failed"
    assert result["error"]["stage"] == "chart"


def test_help_and_usage() -> None:
    completed = run_cli("--help")
    assert (
        completed.returncode == 0
        and "--csv-path" in completed.stdout
        and "--output" in completed.stdout
    )
    invalid = run_cli("--invalid")
    assert (
        invalid.returncode == 2
        and not invalid.stdout
        and "unrecognized" in invalid.stderr
    )


def test_defaults_and_relative_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valid_row: dict[str, str],
) -> None:
    ingest = importlib.import_module("sales_data_agent.ingest")
    rendering = importlib.import_module("sales_chart_agent.rendering")
    monkeypatch.setattr(ingest, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(rendering, "REPOSITORY_ROOT", tmp_path)
    (tmp_path / "dataset").mkdir()
    write_csv(tmp_path / "dataset/shared_sales_dataset.csv", [valid_row])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["chart_result"]["output_path"] == str(
        tmp_path / "langgraph/outputs/monthly_sales_amount.html"
    )
    assert (
        main(
            [
                "--csv-path",
                "dataset/shared_sales_dataset.csv",
                "--output",
                "custom/chart.html",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["chart_result"]["output_path"] == str(
        tmp_path / "custom/chart.html"
    )


@pytest.mark.parametrize("fail", [False, True])
def test_logger_restoration_and_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail: bool,
) -> None:
    pipeline = importlib.import_module("sales_pipeline_agent.graph")
    if fail:
        monkeypatch.setattr(
            pipeline,
            "chart_graph",
            Mock(invoke=Mock(side_effect=RuntimeError("private exception detail"))),
        )
    loggers = [logging.getLogger(name) for name in LOGGER_NAMES] + [logging.getLogger()]
    before = [
        (list(logger.handlers), logger.level, logger.propagate) for logger in loggers
    ]
    for _ in range(2):
        assert main(["--output", str(tmp_path / "chart.html")]) == (2 if fail else 0)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        events = [json.loads(line) for line in captured.err.splitlines()]
        assert sum(e["event"] == "pipeline_finished" for e in events) == 1
        if fail:
            assert result["error"]["code"] == "unexpected_stage_error"
            assert any("RuntimeError" in e.get("traceback", "") for e in events)
        assert [
            (list(logger.handlers), logger.level, logger.propagate)
            for logger in loggers
        ] == before
