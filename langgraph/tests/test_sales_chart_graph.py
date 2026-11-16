"""Observable chart contract, arithmetic, and filesystem guarantees."""

import importlib
import json
import logging
from copy import deepcopy
from decimal import localcontext
from pathlib import Path
from typing import cast

import pytest
from sales_chart_agent.aggregation import aggregate_monthly
from sales_chart_agent.graph import graph
from sales_chart_agent.models import GraphInput
from sales_chart_agent.rendering import build_figure, resolve_output_path
from sales_data_agent.models import SalesRecord


def record(
    day: str = "2026-01-05", price: str = "39.90", quantity: int = 2
) -> SalesRecord:
    return {
        "order_id": "ORD001",
        "date": day,
        "product": "Wireless Mouse",
        "category": "Accessories",
        "region": "East",
        "quantity": quantity,
        "unit_price": price,
    }


def source(records: list[SalesRecord] | None = None, partial: bool = False) -> dict:
    rows = [record()] if records is None else records
    quarantines = (
        [
            {
                "line_number": 3,
                "raw_values": {"quantity": "0"},
                "issues": [{"code": "invalid_quantity", "message": "Not positive"}],
            }
        ]
        if partial
        else []
    )
    return {
        "status": "completed_with_errors" if partial else "completed",
        "records": rows,
        "quarantined_rows": quarantines,
        "report": {
            "source_path": "/sales.csv",
            "source_rows": len(rows) + len(quarantines),
            "valid_rows": len(rows),
            "quarantined_rows": len(quarantines),
            "normalization_change_count": 0,
            "normalization_changes": [],
            "file_issues": [],
        },
    }


def invoke(value: object, path: Path):
    return graph.invoke({"source_result": value, "output_path": str(path)})


@pytest.mark.parametrize("partial", [False, True])
def test_clean_and_partial_html(tmp_path: Path, partial: bool) -> None:
    value = source(
        [record("2026-03-20"), record(), record("2025-12-31", "0.10", 3)], partial
    )
    original = deepcopy(value)
    path = tmp_path / "new" / "chart.html"
    result = invoke(value, path)
    assert result == {
        "status": "completed_with_warnings" if partial else "completed",
        "output_path": str(path.resolve()),
        "monthly_totals": [
            {"month": "2025-12", "sales_amount": "0.30"},
            {"month": "2026-01", "sales_amount": "79.80"},
            {"month": "2026-03", "sales_amount": "79.80"},
        ],
        "source_status": value["status"],
        "source_row_count": 4 if partial else 3,
        "valid_row_count": 3,
        "quarantined_row_count": 1 if partial else 0,
        "error": None,
    }
    assert value == original
    html = path.read_text()
    assert (
        "Monthly Sales Amount" in html
        and "Order month" in html
        and "Sales amount" in html
    )
    assert "Plotly.newPlot" in html
    assert "<script src=" not in html
    assert ("Partial input: 1 rows quarantined" in html) == partial
    assert not list(path.parent.glob("*.tmp"))


def test_figure_axis_hover_and_missing_months() -> None:
    figure = build_figure(
        [
            {"month": "2026-01", "sales_amount": "79.80"},
            {"month": "2026-03", "sales_amount": "0.10"},
        ],
        0,
    ).to_plotly_json()
    assert figure["layout"]["xaxis"] == {
        "title": {"text": "Order month"},
        "type": "date",
        "tickformat": "%Y-%m",
    }
    assert figure["layout"]["yaxis"]["title"]["text"] == "Sales amount"
    trace = figure["data"][0]
    assert trace["x"] == ["2026-01-01", "2026-03-01"]
    assert trace["y"] == [79.8, 0.1]
    assert trace["customdata"] == [["2026-01", "79.80"], ["2026-03", "0.10"]]
    assert trace["mode"] == "lines+markers"
    assert "customdata[1]" in trace["hovertemplate"]


def test_decimal_totals_ignore_ambient_precision() -> None:
    with localcontext() as context:
        context.prec = 3
        rows = [
            record(price="123456789012345678901234567890.12", quantity=3),
            record(price="0.10"),
        ]
        assert aggregate_monthly(rows) == [
            {"month": "2026-01", "sales_amount": "370370367037037036703703703670.56"}
        ]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("order_id", " ", "invalid_record"),
        ("product", "", "invalid_record"),
        ("category", None, "invalid_record"),
        ("region", 1, "invalid_record"),
        ("date", "2026-1-05", "invalid_date"),
        ("date", "2026-02-30", "invalid_date"),
        ("date", "2026-01-05T00:00:00", "invalid_date"),
        ("date", "20260105", "invalid_date"),
        ("quantity", True, "invalid_quantity"),
        ("quantity", 0, "invalid_quantity"),
        ("quantity", -1, "invalid_quantity"),
        ("quantity", 2.0, "invalid_quantity"),
        ("unit_price", "39.9", "invalid_unit_price"),
        ("unit_price", "39.900", "invalid_unit_price"),
        ("unit_price", "0.00", "invalid_unit_price"),
        ("unit_price", "-1.00", "invalid_unit_price"),
        ("unit_price", "NaN", "invalid_unit_price"),
        ("unit_price", "Infinity", "invalid_unit_price"),
        ("unit_price", "1.001", "invalid_unit_price"),
        ("unit_price", " 1.00", "invalid_unit_price"),
        ("unit_price", "1e2", "invalid_unit_price"),
        ("unit_price", 39.9, "invalid_unit_price"),
        ("unit_price", float("nan"), "invalid_unit_price"),
    ],
)
def test_invalid_record_fails_whole_input(
    tmp_path: Path, field: str, value: object, code: str
) -> None:
    envelope = source([record(), record()])
    envelope["records"][1][field] = value
    path = tmp_path / "chart.html"
    path.write_bytes(b"previous chart")
    result = invoke(envelope, path)
    assert result["status"] == "failed" and result["error"]["code"] == code
    assert result["output_path"] is None and result["monthly_totals"] == []
    assert path.read_bytes() == b"previous chart"


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("source_rows", 100, "inconsistent_source_report"),
        ("valid_rows", 95, "inconsistent_source_report"),
        ("quarantined_rows", 5, "inconsistent_source_report"),
        ("source_rows", -1, "invalid_source_report"),
        ("valid_rows", True, "invalid_source_report"),
        ("quarantined_rows", 0.0, "invalid_source_report"),
    ],
)
def test_report_invariants(
    tmp_path: Path, field: str, value: object, code: str
) -> None:
    envelope = source()
    envelope["report"][field] = value
    result = invoke(envelope, tmp_path / "chart.html")
    assert result["error"]["code"] == code
    assert result["source_row_count"] is None
    assert not (tmp_path / "chart.html").exists()


@pytest.mark.parametrize("partial", [False, True])
def test_status_count_contradictions(tmp_path: Path, partial: bool) -> None:
    envelope = source(partial=partial)
    envelope["status"] = "completed" if partial else "completed_with_errors"
    assert (
        invoke(envelope, tmp_path / "chart.html")["error"]["code"]
        == "inconsistent_source_status"
    )


@pytest.mark.parametrize(
    "value,code",
    [
        (None, "invalid_source_envelope"),
        ([], "invalid_source_envelope"),
        ({}, "invalid_source_status"),
        ({"status": "failed"}, "source_failed"),
        ({"status": "other"}, "invalid_source_status"),
        ({"status": "completed", "records": None}, "invalid_source_envelope"),
        (source([]), "no_valid_records"),
        (source([], True), "no_valid_records"),
    ],
)
def test_invalid_envelopes(tmp_path: Path, value: object, code: str) -> None:
    result = invoke(value, tmp_path / "chart.html")
    assert result["status"] == "failed" and result["error"]["code"] == code


def test_does_not_repeat_catalog_validation(tmp_path: Path) -> None:
    envelope = source()
    envelope["records"][0]["product"] = "New Product"
    assert invoke(envelope, tmp_path / "chart.html")["status"] == "completed"


def test_render_error_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendering = importlib.import_module("sales_chart_agent.rendering")
    path = tmp_path / "chart.html"
    path.write_bytes(b"previous")

    def fail_replace(*args: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(rendering.os, "replace", fail_replace)
    result = invoke(source(), path)
    assert (
        result["error"]["code"] == "html_write_failed" and result["output_path"] is None
    )
    assert result["monthly_totals"] == [{"month": "2026-01", "sales_amount": "79.80"}]
    assert path.read_bytes() == b"previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chart.html"]


def test_nonfinite_plot_value_preserves_file(tmp_path: Path) -> None:
    path = tmp_path / "chart.html"
    path.write_bytes(b"previous")
    result = invoke(source([record(price="1" + "0" * 310 + ".00")]), path)
    assert result["error"]["code"] == "non_finite_plot_value"
    assert result["output_path"] is None and path.read_bytes() == b"previous"


def test_overwrite_and_path_defaults(tmp_path: Path) -> None:
    path = tmp_path / "chart.html"
    path.write_text("old")
    assert invoke(source(), path)["status"] == "completed"
    assert path.read_text() != "old"
    assert resolve_output_path(None).name == "monthly_sales_amount.html"
    assert resolve_output_path(
        "langgraph/outputs/monthly_sales_amount.html"
    ) == resolve_output_path(None)
    assert resolve_output_path(str(path)) == path


def test_logging_is_opt_in_and_json(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="sales_chart_agent"):
        invoke(source(), tmp_path / "chart.html")
    events = [
        json.loads(r.message) for r in caplog.records if r.name == "sales_chart_agent"
    ]
    assert len({e["run_id"] for e in events}) == 1
    assert {e["node"] for e in events if e["event"] == "node_entry"} == {
        "validate_input",
        "aggregate_monthly",
        "render_html",
        "assemble",
    }
    assert events[-1]["monthly_totals"] == [
        {"month": "2026-01", "sales_amount": "79.80"}
    ]


def test_missing_graph_source_returns_failure(tmp_path: Path) -> None:
    result = graph.invoke(
        cast(GraphInput, {"output_path": str(tmp_path / "chart.html")})
    )
    assert result["status"] == "failed"


@pytest.mark.parametrize("value", ["", "\x00", float("nan"), {}])
def test_invalid_output_returns_failure(value: object) -> None:
    result = graph.invoke(
        cast(GraphInput, {"source_result": source(), "output_path": value})
    )
    assert result["status"] == "failed" and result["output_path"] is None


def test_plotly_failure_preserves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendering = importlib.import_module("sales_chart_agent.rendering")
    path = tmp_path / "chart.html"
    path.write_text("previous")

    def fail_figure(*args: object) -> None:
        raise ValueError("Rendering error")

    monkeypatch.setattr(rendering, "build_figure", fail_figure)
    result = invoke(source(), path)
    assert result["error"]["code"] == "render_failed"
    assert path.read_text() == "previous"


def test_decimal_exponent_context_isolated() -> None:
    with localcontext() as context:
        context.Emax = 1
        assert aggregate_monthly([record(price="100.00")]) == [
            {"month": "2026-01", "sales_amount": "200.00"}
        ]


def test_record_failure_retains_validated_counts(tmp_path: Path) -> None:
    result = invoke(source([record("2026-02-30")]), tmp_path / "chart.html")
    assert result["status"] == "failed"
    assert (
        result["source_row_count"],
        result["valid_row_count"],
        result["quarantined_row_count"],
    ) == (1, 1, 0)


def test_rejected_price_diagnostics_are_scrubbed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    envelope = source()
    envelope["records"][0]["unit_price"] = "private@example.com"
    with caplog.at_level(logging.DEBUG, logger="sales_chart_agent"):
        invoke(envelope, tmp_path / "chart.html")
    assert "private@example.com" not in caplog.text
    assert '"value_length": 19' in caplog.text


def test_logging_unserializable_values_do_not_abort(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sales_chart_agent.observability import log_event

    with caplog.at_level(logging.DEBUG, logger="sales_chart_agent"):
        log_event(logging.DEBUG, "diagnostic", "test-run", invalid=object())
    assert (
        json.loads(caplog.records[-1].message)["diagnostic_error"]
        == "Unserializable diagnostic values"
    )
