"""Parent orchestration contracts and child integration."""

import importlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import write_csv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableConfig
from sales_data_agent import graph as preparation_graph
from sales_pipeline_agent import graph
from sales_pipeline_agent.models import GraphInput

pipeline = importlib.import_module("sales_pipeline_agent.graph")


def test_shared_dataset(tmp_path: Path) -> None:
    output = tmp_path / "chart.html"
    inputs: GraphInput = {"output_path": str(output)}
    result = graph.invoke(inputs)
    assert set(result) == {"status", "preparation_result", "chart_result", "error"}
    assert result["status"] == "completed" and result["error"] is None
    assert result["preparation_result"] == preparation_graph.invoke({})
    assert result["preparation_result"]["report"]["valid_rows"] == 500
    assert result["chart_result"]["output_path"] == str(output)
    assert output.exists() and list(tmp_path.iterdir()) == [output]
    assert inputs == {"output_path": str(output)}


def test_partial_continues(tmp_path: Path, valid_row: dict[str, str]) -> None:
    csv = write_csv(
        tmp_path / "sales.csv",
        [valid_row, {**valid_row, "order_id": "bad", "quantity": "0"}],
    )
    result = graph.invoke(
        {"csv_path": str(csv), "output_path": str(tmp_path / "chart.html")}
    )
    assert result["status"] == "completed_with_warnings" and result["error"] is None
    assert result["preparation_result"] == preparation_graph.invoke(
        {"csv_path": str(csv)}
    )
    assert result["chart_result"]["quarantined_row_count"] == 1
    assert "Partial input: 1 rows quarantined" in (tmp_path / "chart.html").read_text()


@pytest.mark.parametrize("kind", ["missing", "empty", "rejected", "malformed"])
def test_preparation_failure_skips_chart(
    tmp_path: Path,
    valid_row: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    csv = tmp_path / "sales.csv"
    if kind == "empty":
        write_csv(csv, [])
    elif kind == "rejected":
        write_csv(csv, [{**valid_row, "quantity": "0"}])
    elif kind == "malformed":
        csv.write_text('order_id,date\n"unterminated')
    chart = Mock()
    monkeypatch.setattr(pipeline, "chart_graph", chart)
    output = tmp_path / "chart.html"
    output.write_text("previous")
    updates = list(
        graph.stream(
            {"csv_path": str(csv), "output_path": str(output)}, stream_mode="updates"
        )
    )
    assert [next(iter(update)) for update in updates] == ["prepare", "assemble"]
    result = updates[-1]["assemble"]
    assert result["status"] == "failed" and result["chart_result"] is None
    assert result["error"]["stage"] == "preparation"
    if kind in ("empty", "rejected"):
        assert result["error"]["code"] == "no_valid_records"
    else:
        assert (
            result["error"]["code"]
            == result["preparation_result"]["report"]["file_issues"][0]["code"]
        )
    chart.invoke.assert_not_called()
    assert output.read_text() == "previous"


def test_chart_failure_keeps_both_results(tmp_path: Path) -> None:
    target = tmp_path / "directory.html"
    target.mkdir()
    result = graph.invoke({"output_path": str(target)})
    assert (
        result["status"] == "failed"
        and result["preparation_result"]["status"] == "completed"
    )
    assert result["chart_result"]["status"] == "failed"
    assert result["error"] == {"stage": "chart", **result["chart_result"]["error"]}


@pytest.mark.parametrize("stage", ["preparation", "chart"])
def test_unexpected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
) -> None:
    child = Mock()
    child.invoke.side_effect = RuntimeError("secret-value-not-for-output")
    monkeypatch.setattr(
        pipeline,
        "preparation_graph" if stage == "preparation" else "chart_graph",
        child,
    )
    with caplog.at_level(logging.DEBUG, logger="sales_pipeline_agent"):
        result = graph.invoke({"output_path": str(tmp_path / "chart.html")})
    assert result["status"] == "failed"
    assert result["error"] == {
        "stage": stage,
        "code": "unexpected_stage_error",
        "message": f"Unexpected {stage} error: RuntimeError",
    }
    assert result["chart_result"] is None
    assert (result["preparation_result"] is None) == (stage == "preparation")
    event = next(
        json.loads(r.message)
        for r in caplog.records
        if json.loads(r.message)["event"] == "stage_exception"
    )
    assert (
        "RuntimeError" in event["traceback"]
        and "test_unexpected_exception" not in result["error"]["message"]
    )
    assert (
        "secret-value-not-for-output" not in json.dumps(result)
        and "secret-value-not-for-output" not in caplog.text
    )
    assert child.invoke.call_count == 1


def test_preparation_fallback_error(monkeypatch: pytest.MonkeyPatch) -> None:
    result = preparation_graph.invoke({"csv_path": "/does-not-exist.csv"})
    result["report"]["file_issues"] = []
    monkeypatch.setattr(
        pipeline, "preparation_graph", Mock(invoke=Mock(return_value=result))
    )
    parent = graph.invoke({})
    assert parent["preparation_result"] == result
    assert parent["error"]["code"] == "preparation_failed"


class Recorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self.starts: list[dict] = []

    def on_chain_start(self, serialized, inputs, **kwargs) -> None:
        self.starts.append(kwargs)


def test_config_callbacks_and_correlation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    callback = Recorder()
    metadata = {"caller": "test", "pipeline_run_id": "caller-supplied"}
    configurable = {"tenant": "example"}
    config: RunnableConfig = {
        "callbacks": [callback],
        "tags": ["pipeline-test"],
        "metadata": metadata,
        "configurable": configurable,
    }
    original_metadata, original_configurable = (
        deepcopy(metadata),
        deepcopy(configurable),
    )
    with caplog.at_level(logging.DEBUG):
        graph.invoke({"output_path": str(tmp_path / "chart.html")}, config=config)
    events = [
        json.loads(r.message)
        for r in caplog.records
        if r.name in ("sales_pipeline_agent", "sales_data_agent", "sales_chart_agent")
    ]
    ids = {e["pipeline_run_id"] for e in events}
    assert len(ids) == 1 and "caller-supplied" not in ids
    child_starts = [e for e in events if e["event"] == "agent_started"]
    assert len(child_starts) == 2 and len({e["run_id"] for e in child_starts}) == 2
    nested = [
        s
        for s in callback.starts
        if s.get("metadata", {}).get("pipeline_run_id") in ids
    ]
    assert nested and all("pipeline-test" in s.get("tags", []) for s in nested)
    assert all(s["metadata"].get("caller") == "test" for s in nested)
    forwarded = pipeline.child_config(config, next(iter(ids)))
    assert forwarded["configurable"] == {"tenant": "example"}
    assert any(s.get("parent_run_id") is not None for s in nested)
    assert metadata == original_metadata and configurable == original_configurable
    assert config["callbacks"] == [callback]
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="sales_data_agent"):
        preparation_graph.invoke({})
    assert all("pipeline_run_id" not in json.loads(r.message) for r in caplog.records)


def test_concurrent_graph_ids_are_isolated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def run(index: int):
        return graph.invoke({"output_path": str(tmp_path / f"chart-{index}.html")})

    with caplog.at_level(logging.INFO), ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, range(2)))
    assert all(result["status"] == "completed" for result in results)
    events = [
        json.loads(r.message) for r in caplog.records if r.name.startswith("sales_")
    ]
    ids = {event["pipeline_run_id"] for event in events}
    assert len(ids) == 2
    for pipeline_id in ids:
        related = [e for e in events if e["pipeline_run_id"] == pipeline_id]
        assert sum(e["event"] == "agent_started" for e in related) == 2
        assert sum(e["event"] == "pipeline_finished" for e in related) == 1


def test_traceback_excludes_source_literals(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("credential-literal-must-not-be-logged")

    monkeypatch.setattr(pipeline, "preparation_graph", Mock(invoke=fail))
    with caplog.at_level(logging.ERROR, logger="sales_pipeline_agent"):
        result = graph.invoke({})
    assert result["error"]["code"] == "unexpected_stage_error"
    assert "credential-literal-must-not-be-logged" not in caplog.text
    assert "RuntimeError" in caplog.text and "in fail" in caplog.text
