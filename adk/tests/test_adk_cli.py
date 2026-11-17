"""CLI contracts and per-file publication failures, using the real ADK Runner."""

import csv
import json
import logging
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from adk_sales_workflow import artifacts, chart, cli, ingestion, runtime
from adk_sales_workflow.observability import LOGGER, current_invocation_id
from adk_sales_workflow.preparation.ingest import COLUMNS


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use a fake repository and unrelated CWD without a shared conftest."""
    root = tmp_path / "repository"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(ingestion, "REPOSITORY_ROOT", root)
    monkeypatch.chdir(elsewhere)
    return root


def write_csv(root: Path, case: str = "clean") -> Path:
    path = root / ingestion.DEFAULT_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    if case == "missing":
        return path
    rows = [
        [
            "private-order",
            "2026-02-05",
            "Wireless Mouse",
            "Accessories",
            "East",
            "2",
            "39.90",
        ]
    ]
    if case in ("partial", "all_invalid"):
        rows.append(
            [
                "private-invalid",
                "2026-02-30",
                "secret-product",
                "Accessories",
                "East",
                "0",
                "NaN",
            ]
        )
    if case == "empty":
        rows = []
    if case == "all_invalid":
        rows = rows[-1:]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return path


def invoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *args: str,
) -> tuple[int, dict[str, Any], str, str]:
    monkeypatch.setattr(sys, "argv", ["adk-sales", *args])
    code = cli.main()
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    result = json.loads(captured.out)
    assert captured.out == artifacts.serialize(result) + "\n"
    assert captured.out.isascii()
    assert "private-order" not in captured.err
    assert "secret-product" not in captured.err
    assert "private-invalid" not in captured.err
    return code, result, captured.out, captured.err


@pytest.mark.parametrize(
    "case", ["clean", "partial", "missing", "empty", "all_invalid"]
)
def test_run_relative_defaults_and_failures(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    source = write_csv(repository, case)
    code, result, stdout, stderr = invoke(monkeypatch, capsys, "run")
    output = repository / "adk/outputs"
    assert result["preparation_result"] == ingestion.prepare(str(source))
    assert "workflow_started" in stderr
    events = [json.loads(line) for line in stderr.splitlines()]
    assert len({event["run_id"] for event in events}) == 1
    assert events[-1]["event"] == "workflow_finished"
    assert events[-1]["status"] == result["status"]
    assert events[-1]["exit_code"] == code
    assert current_invocation_id() is None
    if case in ("clean", "partial"):
        assert code == 0
        assert result["status"] == (
            "completed" if case == "clean" else "completed_with_warnings"
        )
        html_path = output / cli.HTML_NAME
        assert result["chart_result"]["output_path"] == str(html_path)
        assert (output / cli.JSON_NAME).read_text() == stdout.rstrip("\n")
        document = html_path.read_text()
        assert "plotly.js" in document
        assert "Monthly Sales Amount" in document
        if case == "partial":
            assert "Partial input: 1 rows quarantined" in document
    else:
        assert code == 2
        assert result["status"] == "failed"
        assert result["chart_result"] is None
        assert not output.exists()


@pytest.mark.parametrize(
    "case", ["clean", "partial", "empty", "all_invalid", "missing"]
)
@pytest.mark.parametrize("save", [False, True])
def test_ingest_optional_full_result(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
    save: bool,
) -> None:
    source = write_csv(repository, case)
    args = ["ingest", "--csv-path", ingestion.DEFAULT_CSV]
    if save:
        args += ["--output", "saved/prepared.json"]
    code, result, stdout, _ = invoke(monkeypatch, capsys, *args)
    assert result == ingestion.prepare(str(source))
    assert code == (2 if case == "missing" else 0)
    destination = repository / "saved/prepared.json"
    if save:
        assert destination.read_text() == stdout.rstrip("\n")
    else:
        assert not destination.exists()
    assert not (repository / "adk/outputs").exists()


@pytest.mark.parametrize("case", ["clean", "partial"])
def test_chart_json_input_and_relative_output(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    prepared = ingestion.prepare(str(write_csv(repository, case)))
    input_path = repository / "prepared.json"
    input_path.write_text(artifacts.serialize(prepared))
    code, result, stdout, _ = invoke(
        monkeypatch,
        capsys,
        "chart",
        "--input",
        "prepared.json",
        "--output-dir",
        "charts",
    )
    assert code == 0
    assert "chart_result" not in result
    assert result == chart.generate(
        prepared, str(repository / "charts" / cli.HTML_NAME)
    )
    assert (repository / "charts" / cli.JSON_NAME).read_text() == stdout.rstrip("\n")
    assert json.loads(input_path.read_text()) == prepared


@pytest.mark.parametrize(
    "content,expected",
    [
        (None, "input_read_failed"),
        ("{secret", "invalid_json"),
        ("\ufffd", "invalid_json"),
        ("null", "invalid_source_envelope"),
    ],
)
def test_chart_input_errors_preserve_existing_files(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str | None,
    expected: str,
) -> None:
    if content is not None:
        (repository / "input.json").write_text(content)
    output = repository / "adk/outputs"
    output.mkdir(parents=True)
    (output / cli.HTML_NAME).write_text("old html")
    (output / cli.JSON_NAME).write_text("old json")
    code, result, _, stderr = invoke(
        monkeypatch, capsys, "chart", "--input", "input.json"
    )
    assert code == 2
    assert result["status"] == "failed"
    assert result["error"]["code"] == expected
    assert result["output_path"] is None
    assert "secret" not in stderr
    assert (output / cli.HTML_NAME).read_text() == "old html"
    assert (output / cli.JSON_NAME).read_text() == "old json"


@pytest.mark.parametrize("mode", ["run", "chart"])
@pytest.mark.parametrize("failed_name", [cli.HTML_NAME, cli.JSON_NAME])
def test_replace_failure_old_files_or_mixed_state(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    failed_name: str,
) -> None:
    prepared = ingestion.prepare(str(write_csv(repository)))
    (repository / "prepared.json").write_text(artifacts.serialize(prepared))
    output = repository / "published"
    output.mkdir()
    html_path, json_path = output / cli.HTML_NAME, output / cli.JSON_NAME
    html_path.write_text("old html")
    json_path.write_text("old json")
    expected_child = chart.generate(prepared, str(html_path))
    original_child = deepcopy(expected_child)
    replace = artifacts.os.replace
    replacements: list[str] = []

    def fail_replace(source: Any, destination: Any) -> None:
        # Both complete siblings must exist before the first replacement.
        if not replacements:
            staged = list(output.glob(".*.tmp"))
            assert len(staged) == 2
            json_temporary = next(path for path in staged if cli.JSON_NAME in path.name)
            saved = json.loads(json_temporary.read_text())
            assert saved["status"] == "completed"
            assert (
                saved["chart_result"] == expected_child
                if mode == "run"
                else saved == expected_child
            )
        replacements.append(Path(destination).name)
        if Path(destination).name == failed_name:
            raise OSError("private exception data")
        replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", fail_replace)
    args = [mode, "--output-dir", "published"]
    if mode == "chart":
        args += ["--input", "prepared.json"]
    code, result, _, stderr = invoke(monkeypatch, capsys, *args)
    assert code == 2
    assert result["status"] == "failed"
    assert result["error"]["code"] == "artifact_write_failed"
    assert current_invocation_id() is None
    assert str(output / failed_name) in result["error"]["message"]
    assert "private exception data" not in stderr
    assert "private exception data" not in result["error"]["message"]
    events = [json.loads(line) for line in stderr.splitlines()]
    assert len({event["run_id"] for event in events}) == 1
    assert len(events[0]["run_id"]) == 32
    assert any(event["event"] == "artifact_write_failed" for event in events)
    assert any(event["event"] == "execution_finished" for event in events)
    assert events[-1] == {
        "event": "workflow_finished",
        "run_id": events[0]["run_id"],
        "mode": mode,
        "status": "failed",
        "output_path": (
            str(html_path) if mode == "run" or failed_name == cli.JSON_NAME else None
        ),
        "exit_code": 2,
    }
    if mode == "run":
        assert result["error"]["stage"] == "artifact_write"
        assert result["preparation_result"] == prepared
        assert result["chart_result"] == original_child
    else:
        assert result["output_path"] == (
            str(html_path) if failed_name == cli.JSON_NAME else None
        )
        assert result["monthly_totals"] == expected_child["monthly_totals"]
    assert json_path.read_text() == "old json"
    if failed_name == cli.JSON_NAME:
        assert replacements == [cli.HTML_NAME, cli.JSON_NAME]
        assert "Monthly Sales Amount" in html_path.read_text()
    else:
        assert replacements == [cli.HTML_NAME]
        assert html_path.read_text() == "old html"
    assert sorted(path.name for path in output.iterdir()) == sorted(
        [cli.HTML_NAME, cli.JSON_NAME]
    )


def test_ingest_save_failure_is_new_envelope(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepared = ingestion.prepare(str(write_csv(repository, "partial")))
    destination = repository / "saved.json"
    destination.write_text("old json")

    def fail_replace(*args: Any) -> None:
        raise PermissionError("private exception data")

    monkeypatch.setattr(artifacts.os, "replace", fail_replace)
    code, result, _, _ = invoke(monkeypatch, capsys, "ingest", "--output", "saved.json")
    assert code == 2
    assert result["status"] == "failed"
    assert result["records"] == prepared["records"]
    assert result["quarantined_rows"] == prepared["quarantined_rows"]
    assert result["report"]["file_issues"][-1]["code"] == "artifact_write_failed"
    assert destination.read_text() == "old json"
    assert not list(repository.glob(".*.tmp"))


@pytest.mark.parametrize("failure", ["render", "serialize", "stage"])
def test_prepublication_failure_changes_neither_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    prepared = ingestion.prepare(str(write_csv(tmp_path)))
    html_path, json_path = tmp_path / cli.HTML_NAME, tmp_path / cli.JSON_NAME
    child = chart.generate(prepared, str(html_path))
    html_path.write_text("old html")
    json_path.write_text("old json")
    result: dict[str, Any] = dict(child)
    if failure == "render":

        def fail_render(*args: Any) -> str:
            raise ValueError("private data")

        monkeypatch.setattr(chart, "render_document", fail_render)
    elif failure == "serialize":
        result["non_finite"] = float("nan")
    else:
        stage = artifacts._stage

        def fail_stage(path: Path, content: str, pending: list[Path]) -> Path:
            temporary = stage(path, content, pending)
            if path == json_path:
                raise OSError("private data")
            return temporary

        monkeypatch.setattr(artifacts, "_stage", fail_stage)
    with pytest.raises(artifacts.ArtifactWriteError) as caught:
        artifacts.publish_chart(result, child, html_path, json_path)
    assert not caught.value.html_replaced
    assert html_path.read_text() == "old html"
    assert json_path.read_text() == "old json"
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("mode", ["run", "chart", "ingest"])
def test_unexpected_runtime_failure_scoped_logs(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    (repository / "prepared.json").write_text("{}")
    before = (LOGGER.level, LOGGER.propagate, list(LOGGER.handlers))
    root = logging.getLogger()
    root_before = (root.level, root.propagate, list(root.handlers))

    async def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("private exception data")

    monkeypatch.setattr(runtime, "execute", explode)
    args = [mode] + (["--input", "prepared.json"] if mode == "chart" else [])
    code, result, _, stderr = invoke(monkeypatch, capsys, *args)
    assert code == 2
    issue = result["report"]["file_issues"][0] if mode == "ingest" else result["error"]
    assert issue["code"] == "unexpected_stage_error"
    assert "stage_exception" in stderr
    assert "private exception data" not in stderr
    events = [json.loads(line) for line in stderr.splitlines()]
    assert len({event["run_id"] for event in events}) == 1
    assert len(events[0]["run_id"]) == 32
    assert events[-1]["event"] == "workflow_finished"
    assert events[-1]["status"] == "failed"
    assert events[-1]["exit_code"] == 2
    assert (LOGGER.level, LOGGER.propagate, LOGGER.handlers) == before
    assert (root.level, root.propagate, root.handlers) == root_before


@pytest.mark.parametrize("args", [[], ["chart"], ["run", "--unknown"]])
def test_argparse_required_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["adk-sales", *args])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2
    assert not capsys.readouterr().out
