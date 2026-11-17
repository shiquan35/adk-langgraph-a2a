"""CLI streams, exit codes, input paths, and logging isolation."""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sales_chart_agent.cli import main
from sales_chart_agent.observability import LOGGER
from sales_data_agent.graph import graph as preparation_graph


@pytest.fixture
def source_json(tmp_path: Path) -> Path:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(preparation_graph.invoke({})))
    return path


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = str(Path(sys.executable).parent / "sales-chart")
    return subprocess.run(
        [command, *args], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("partial,exit_code", [(False, 0), (True, 1)])
def test_cli_generated_chart(
    source_json: Path, tmp_path: Path, partial: bool, exit_code: int
) -> None:
    if partial:
        value = json.loads(source_json.read_text())
        value["status"] = "completed_with_errors"
        value["quarantined_rows"] = [
            {
                "line_number": 2,
                "raw_values": {"quantity": "0"},
                "issues": [{"code": "invalid_quantity", "message": "Not positive"}],
            }
        ]
        value["report"]["source_rows"] += 1
        value["report"]["quarantined_rows"] = 1
        source_json.write_text(json.dumps(value))
    path = tmp_path / "output" / "chart.html"
    completed = run_cli(
        "--input", str(source_json), "--output", str(path), cwd=tmp_path
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == exit_code
    assert result["status"] == ("completed_with_warnings" if partial else "completed")
    assert result["valid_row_count"] == 500
    assert result["output_path"] == str(path)
    assert len(completed.stdout.splitlines()) == 1
    assert (
        completed.stdout
        == json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    assert path.exists()
    events = [json.loads(line) for line in completed.stderr.splitlines()]
    assert events[-1]["event"] == "agent_finished"


@pytest.mark.parametrize(
    "text,code",
    [
        ("{", "invalid_input_json"),
        ("NaN", "invalid_input_json"),
        ("[]", "invalid_source_envelope"),
        ('{"status":"failed"}', "source_failed"),
    ],
)
def test_cli_invalid_json_or_source(tmp_path: Path, text: str, code: str) -> None:
    source = tmp_path / "input.json"
    source.write_text(text)
    path = tmp_path / "chart.html"
    path.write_bytes(b"previous")
    completed = run_cli("--input", str(source), "--output", str(path))
    result = json.loads(completed.stdout)
    assert completed.returncode == 2 and result["error"]["code"] == code
    assert result["output_path"] is None and path.read_bytes() == b"previous"


@pytest.mark.parametrize("is_directory", [False, True])
def test_cli_unreadable_input(tmp_path: Path, is_directory: bool) -> None:
    path = tmp_path if is_directory else tmp_path / "missing.json"
    completed = run_cli("--input", str(path), "--output", str(tmp_path / "chart.html"))
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error"]["code"] == "input_read_failed"


def test_cli_help_and_missing_input() -> None:
    help_result = run_cli("--help")
    assert (
        help_result.returncode == 0
        and "--input" in help_result.stdout
        and "--output" in help_result.stdout
    )
    usage = run_cli()
    assert usage.returncode == 2 and not usage.stdout and "--input" in usage.stderr


def test_cli_relative_input_output_and_default(
    source_json: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Redirect the repository constant to a temporary repository, not the cwd.
    from sales_chart_agent import cli, rendering

    monkeypatch.setattr(cli, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(rendering, "REPOSITORY_ROOT", tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["--input", source_json.name]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["output_path"] == str(
        tmp_path / "langgraph/outputs/monthly_sales_amount.html"
    )
    assert main(["--input", source_json.name, "--output", "custom/chart.html"]) == 0
    assert json.loads(capsys.readouterr().out)["output_path"] == str(
        tmp_path / "custom/chart.html"
    )


def test_cli_render_failure(source_json: Path, tmp_path: Path) -> None:
    path = tmp_path / "directory.html"
    path.mkdir()
    result = run_cli("--input", str(source_json), "--output", str(path))
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "html_write_failed"
    assert path.is_dir()


def test_cli_restores_logger_settings(
    source_json: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    handlers, level, propagate = list(LOGGER.handlers), LOGGER.level, LOGGER.propagate
    root_handlers = list(logging.getLogger().handlers)
    for _ in range(2):
        assert (
            main(
                ["--input", str(source_json), "--output", str(tmp_path / "chart.html")]
            )
            == 0
        )
        streams = capsys.readouterr()
        events = [json.loads(line) for line in streams.err.splitlines()]
        assert sum(e["event"] == "agent_finished" for e in events) == 1
        assert (
            LOGGER.handlers == handlers
            and LOGGER.level == level
            and LOGGER.propagate == propagate
        )
        assert logging.getLogger().handlers == root_handlers


def test_agent1_to_agent2_in_memory(tmp_path: Path) -> None:
    from sales_chart_agent import graph

    result = graph.invoke(
        {
            "source_result": preparation_graph.invoke({}),
            "output_path": str(tmp_path / "chart.html"),
        }
    )
    assert result["status"] == "completed" and result["valid_row_count"] == 500
    assert result["monthly_totals"] and result["error"] is None


def test_cli_lone_surrogate_emits_complete_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"status":"\\ud800"}')
    completed = run_cli("--input", str(path))
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["error"]["code"] == "invalid_source_status"


def test_malformed_source_has_single_finish_event(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[]")
    completed = run_cli("--input", str(path))
    events = [json.loads(line) for line in completed.stderr.splitlines()]
    assert sum(e["event"] == "agent_finished" for e in events) == 1
