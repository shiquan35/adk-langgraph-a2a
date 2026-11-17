"""Exercise workflow routing and standalone nodes through the actual ADK Runner."""

import asyncio
import csv
import json
import logging
from collections.abc import AsyncGenerator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from adk_sales_workflow import ingestion, nodes, runtime
from adk_sales_workflow.models import Mode
from adk_sales_workflow.observability import (
    LOGGER,
    current_invocation_id,
    invocation_id,
    safe_preview,
    stderr_logging,
)
from adk_sales_workflow.preparation.ingest import COLUMNS
from adk_sales_workflow.workflow import build_workflow
from google.adk import Runner
from google.adk.sessions import InMemorySessionService


def source_file(tmp_path: Path, case: str = "clean") -> str:
    path = tmp_path / "sales.csv"
    if case == "missing":
        return str(path)
    rows = [
        [
            "private-order",
            "2026-02-05",
            "Wireless Mouse",
            "Accessories",
            "East",
            "2",
            "39.90",
        ],
        ["second", "2025-12-31", "Wireless Mouse", "Accessories", "East", "3", "0.10"],
    ]
    if case in ("partial", "all_invalid"):
        rows.append(
            [
                "invalid",
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
    elif case == "all_invalid":
        rows = rows[-1:]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return str(path)


@pytest.mark.parametrize(
    "case", ["clean", "partial", "empty", "all_invalid", "missing"]
)
def test_parent_routes_and_complete_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case: str,
) -> None:
    source = source_file(tmp_path, case)
    target = tmp_path / "unpublished" / "chart.html"
    expected = ingestion.prepare(source)
    prepare, generate = nodes.ingestion.prepare, nodes.chart.generate
    calls: list[str] = []

    def prepare_spy(csv_path: str | None = None) -> Any:
        calls.append("ingest")
        assert csv_path == source
        return prepare(csv_path)

    def chart_spy(source_result: object, output_path: str | None = None) -> Any:
        calls.append("chart")
        assert source_result == expected
        assert output_path == str(target)
        return generate(source_result, output_path)

    monkeypatch.setattr(nodes.ingestion, "prepare", prepare_spy)
    monkeypatch.setattr(nodes.chart, "generate", chart_spy)
    with caplog.at_level(logging.DEBUG, logger="adk_sales_workflow"):
        result = asyncio.run(
            runtime.execute("run", csv_path=source, output_path=str(target))
        )
    assert set(result) == {"status", "preparation_result", "chart_result", "error"}
    assert result["preparation_result"] == expected
    assert json.loads(json.dumps(result)) == result
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == LOGGER.name
    ]
    assert len({event["run_id"] for event in events}) == 1
    assert events[0]["event"] == "workflow_started"
    assert events[-1]["event"] == "execution_finished"
    assert "private-order" not in caplog.text
    assert "secret-product" not in caplog.text
    if case in ("clean", "partial"):
        assert calls == ["ingest", "chart"]
        assert result["error"] is None
        assert result["status"] == (
            "completed" if case == "clean" else "completed_with_warnings"
        )
        assert result["chart_result"]["monthly_totals"] == [
            {"month": "2025-12", "sales_amount": "0.30"},
            {"month": "2026-02", "sales_amount": "79.80"},
        ]
        assert result["chart_result"]["output_path"] == str(target.resolve())
    else:
        assert calls == ["ingest"]
        assert result["status"] == "failed"
        assert result["chart_result"] is None
        assert result["error"]["stage"] == "preparation"
        code = (
            expected["report"]["file_issues"][0]["code"]
            if case == "missing"
            else "no_valid_records"
        )
        assert result["error"]["code"] == code
        assert any(event["event"] == "chart_skipped" for event in events)
    assert [
        event["node"] for event in events if event["event"] == "node_entry"
    ] == calls + ["assemble"]
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "mode,stage",
    [
        ("run", "preparation"),
        ("run", "chart"),
        ("ingest", "preparation"),
        ("chart", "chart"),
    ],
)
def test_unexpected_stage_errors_still_finalize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: Mode,
    stage: str,
) -> None:
    source = source_file(tmp_path)
    prepared = ingestion.prepare(source)
    target = tmp_path / "never-created" / "chart.html"

    def explode(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("secret exception text")

    if stage == "preparation":
        monkeypatch.setattr(nodes.ingestion, "prepare", explode)
    else:
        monkeypatch.setattr(nodes.chart, "generate", explode)
    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        result = asyncio.run(
            runtime.execute(
                mode,
                csv_path=source,
                source_result=prepared,
                output_path=str(target),
            )
        )
    assert result["status"] == "failed"
    if mode == "run":
        assert result["error"] == {
            "stage": stage,
            "code": "unexpected_stage_error",
            "message": "RuntimeError",
        }
        assert result["chart_result"] is None
        assert result["preparation_result"] == (prepared if stage == "chart" else None)
    elif mode == "ingest":
        assert result["report"]["file_issues"][0]["code"] == "unexpected_stage_error"
    else:
        assert result["error"]["code"] == "unexpected_stage_error"
    assert "secret exception text" not in caplog.text
    exceptions = [
        json.loads(record.message)
        for record in caplog.records
        if '"stage_exception"' in record.message
    ]
    assert len(exceptions) == 1
    assert "explode" in exceptions[0]["traceback"]
    assert exceptions[0]["exception_type"] == "RuntimeError"
    assert not target.parent.exists()


def test_standalone_modes_and_isolation(tmp_path: Path) -> None:
    source = source_file(tmp_path, "partial")
    prepared = asyncio.run(runtime.execute("ingest", csv_path=source))
    assert prepared == ingestion.prepare(source)
    original = deepcopy(prepared)
    target = tmp_path / "unpublished" / "chart.html"
    chart = asyncio.run(
        runtime.execute("chart", source_result=prepared, output_path=str(target))
    )
    assert chart["status"] == "completed_with_warnings"
    assert prepared == original
    failed = asyncio.run(runtime.execute("chart", output_path=str(target)))
    assert failed["status"] == "failed"
    assert not target.parent.exists()


def test_expected_chart_failure_retains_both_children(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    result = asyncio.run(runtime.execute("run", csv_path=source, output_path=""))
    assert result["status"] == "failed"
    assert result["preparation_result"] == ingestion.prepare(source)
    assert result["chart_result"]["error"]["code"] == "invalid_output_path"
    assert result["error"]["stage"] == "chart"
    assert result["error"]["code"] == "invalid_output_path"


def test_real_runner_fresh_sessions_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services: list[InMemorySessionService] = []
    runners: list[Runner] = []
    run_ids: list[str] = []
    closed: list[Runner] = []

    class TrackingRunner(Runner):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            services.append(kwargs["session_service"])
            runners.append(self)

        async def close(self) -> None:
            closed.append(self)
            await super().close()

    create_session = InMemorySessionService.create_session

    async def track_session(self: InMemorySessionService, **kwargs: Any) -> Any:
        state = kwargs["state"]
        assert all(key.startswith("temp:") for key in state)
        run_ids.append(state["temp:run_id"])
        return await create_session(self, **kwargs)

    monkeypatch.setattr(runtime, "Runner", TrackingRunner)
    monkeypatch.setattr(InMemorySessionService, "create_session", track_session)
    source = source_file(tmp_path)
    asyncio.run(runtime.execute("ingest", csv_path=source))
    asyncio.run(runtime.execute("ingest", csv_path=source))
    assert services[0] is not services[1]
    assert run_ids[0] != run_ids[1]
    assert closed == runners

    async def fail_session(self: InMemorySessionService, **kwargs: Any) -> Any:
        raise RuntimeError("session failed")

    monkeypatch.setattr(InMemorySessionService, "create_session", fail_session)
    with pytest.raises(RuntimeError, match="session failed"):
        asyncio.run(runtime.execute("ingest", csv_path=source))
    assert closed == runners


def test_graph_builds_fresh_nodes() -> None:
    first, second = build_workflow(), build_workflow()
    assert first is not second
    first_nodes = (
        {edge.to_node.name: edge.to_node for edge in first.graph.edges}
        if first.graph
        else {}
    )
    second_nodes = (
        {edge.to_node.name: edge.to_node for edge in second.graph.edges}
        if second.graph
        else {}
    )
    assert set(first_nodes) == set(second_nodes) == {"ingest", "chart", "assemble"}
    assert all(first_nodes[name] is not second_nodes[name] for name in first_nodes)


def test_default_dataset_and_concurrent_invocations(tmp_path: Path) -> None:
    async def concurrent() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return await asyncio.gather(
            runtime.execute("run", output_path=str(tmp_path / "default.html")),
            runtime.execute("run", csv_path=str(tmp_path / "missing.csv")),
            runtime.execute("chart", source_result=None),
        )

    clean, missing, standalone = asyncio.run(concurrent())
    assert clean["status"] == "completed"
    assert clean["preparation_result"]["report"]["valid_rows"] == 500
    assert missing["status"] == "failed"
    assert missing["chart_result"] is None
    assert standalone["status"] == "failed"
    assert not (tmp_path / "default.html").exists()


def test_runner_closes_when_iteration_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    class BrokenRunner(Runner):
        async def run_async(self, **kwargs: Any) -> AsyncGenerator[Any, None]:
            raise RuntimeError("runner failed")
            yield

        async def close(self) -> None:
            closed.append(True)
            await super().close()

    monkeypatch.setattr(runtime, "Runner", BrokenRunner)
    with pytest.raises(RuntimeError, match="runner failed"):
        asyncio.run(runtime.execute("ingest"))
    assert closed == [True]


def test_scoped_logging_restores_root_and_dedicated_logger(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    root_before = (root.level, root.propagate, list(root.handlers))
    before = (LOGGER.level, LOGGER.propagate, list(LOGGER.handlers))
    with pytest.raises(RuntimeError), stderr_logging():
        from adk_sales_workflow.observability import log_event

        log_event(logging.INFO, "test", "run-1")
        raise RuntimeError("stop")
    assert json.loads(capsys.readouterr().err)["run_id"] == "run-1"
    assert (LOGGER.level, LOGGER.propagate, LOGGER.handlers) == before
    assert (root.level, root.propagate, root.handlers) == root_before
    assert safe_preview(None) == {"type": "NoneType"}


@pytest.mark.parametrize("failure", [None, "session", "iteration", "no_output"])
def test_cleanup_failure_preserves_execution_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str | None,
) -> None:
    original_close = Runner.close

    async def broken_close(self: Runner) -> None:
        await original_close(self)
        raise ValueError("private cleanup details")

    async def broken_session(self: InMemorySessionService, **kwargs: Any) -> Any:
        raise LookupError("original session error")

    async def broken_iteration(
        self: Runner, **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        if failure == "iteration":
            raise LookupError("original iteration error")
        return
        yield

    monkeypatch.setattr(Runner, "close", broken_close)
    if failure == "session":
        monkeypatch.setattr(InMemorySessionService, "create_session", broken_session)
    elif failure is not None:
        monkeypatch.setattr(Runner, "run_async", broken_iteration)
    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        if failure is None:
            result = asyncio.run(
                runtime.execute("ingest", csv_path=source_file(tmp_path))
            )
            assert result["status"] == "completed"
        elif failure == "no_output":
            with pytest.raises(RuntimeError, match="no terminal dictionary"):
                asyncio.run(runtime.execute("ingest"))
        else:
            with pytest.raises(LookupError, match=f"original {failure} error"):
                asyncio.run(runtime.execute("ingest"))
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == LOGGER.name
    ]
    assert len({event["run_id"] for event in events}) == 1
    cleanup = [event for event in events if event["event"] == "cleanup_failed"]
    assert len(cleanup) == 1
    assert cleanup[0]["exception_type"] == "ValueError"
    assert events[-1]["event"] == "execution_finished"
    assert "private cleanup details" not in caplog.text


def test_malformed_chart_values_are_not_logged_before_validation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source: dict[str, Any] = dict(ingestion.prepare(source_file(tmp_path)))
    secrets = {
        "date": "private-date@example.com",
        "quantity": "private-quantity@example.com",
        "unit_price": "private-price@example.com",
    }
    source["records"][0].update(secrets)
    source["status"] = "private-status@example.com"
    source["source_status"] = "private-source-status@example.com"
    source["source_row_count"] = "private-count@example.com"
    source["monthly_totals"] = [
        {
            "month": "private-month@example.com",
            "sales_amount": "private-total@example.com",
        }
    ]
    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        result = asyncio.run(runtime.execute("chart", source_result=source))
    assert result["status"] == "failed"
    assert "node_entry" in caplog.text
    assert "private-" not in caplog.text
    preview = safe_preview(source)
    records = preview["records"]
    assert isinstance(records, list)
    assert records[0] == {}
    assert preview["monthly_totals"] == [{}]
    assert "status" not in preview
    assert "source_status" not in preview
    assert "source_row_count" not in preview


def test_quarantine_logs_physical_lines_and_only_safe_observations(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = source_file(tmp_path)
    with Path(source).open("a", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerows(
            [
                [
                    "private-order\nsecond-line",
                    "2026-02-30",
                    "private-product",
                    "private-category",
                    "private-region",
                    "0",
                    "1.001",
                ],
                [
                    "private-other",
                    "private-date",
                    "Wireless Mouse",
                    "Accessories",
                    "East",
                    "private-quantity",
                    "private-price",
                ],
            ]
        )
    with caplog.at_level(logging.DEBUG, logger=LOGGER.name):
        result = asyncio.run(runtime.execute("ingest", csv_path=source))
    assert result["report"]["quarantined_rows"] == 2
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == LOGGER.name
    ]
    issues = [event for event in events if event["event"] == "quarantine_issue"]
    assert {issue["line_number"] for issue in issues} == {4, 6}
    assert {issue["code"] for issue in issues} == {
        "invalid_date",
        "unknown_product",
        "unknown_category",
        "unknown_region",
        "invalid_quantity",
        "invalid_unit_price",
        "invalid_unit_price_precision",
    }
    observed = {
        issue["field"]: issue["observed"] for issue in issues if "observed" in issue
    }
    assert observed == {"date": "2026-02-30", "quantity": "0", "unit_price": "1.001"}
    assert all("observed" not in issue for issue in issues if issue["line_number"] == 6)
    assert "private-" not in caplog.text
    assert "second-line" not in caplog.text
    assert len({event["run_id"] for event in events}) == 1


def test_invocation_id_scope_restores_and_runtime_reuses_context(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert current_invocation_id() is None
    with caplog.at_level(logging.INFO, logger=LOGGER.name), invocation_id() as outer:
        with pytest.raises(ValueError), invocation_id() as inner:
            assert inner != outer
            raise ValueError("restore context")
        assert current_invocation_id() == outer
        asyncio.run(runtime.execute("ingest", csv_path=source_file(tmp_path)))
    assert current_invocation_id() is None
    assert {
        json.loads(record.message)["run_id"]
        for record in caplog.records
        if record.name == LOGGER.name
    } == {outer}
