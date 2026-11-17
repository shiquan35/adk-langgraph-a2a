"""Parity with the existing graphs and side-effect-free ADK stage behavior."""

import csv
from copy import deepcopy
from decimal import localcontext
from pathlib import Path
from typing import cast

import pytest
from adk_sales_workflow import chart, ingestion
from adk_sales_workflow.preparation.ingest import COLUMNS
from adk_sales_workflow.preparation.models import Result as PreparationResult
from adk_sales_workflow.visualization.models import ChartError
from sales_chart_agent.graph import graph as chart_graph
from sales_chart_agent.models import GraphInput as ChartInput
from sales_data_agent.graph import graph as preparation_graph

ROOT = Path(__file__).resolve().parents[2]


def write_source(path: Path, rows: list[list[str]]) -> str:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return str(path)


def row(order_id: str = "ORD-1", **changes: str) -> list[str]:
    values = {
        "order_id": order_id,
        "date": "2026-01-05",
        "product": "Wireless Mouse",
        "category": "Accessories",
        "region": "East",
        "quantity": "2",
        "unit_price": "39.90",
        **changes,
    }
    return [values[field] for field in COLUMNS]


def assert_chart_parity(
    source: object, tmp_path: Path, output_path: str | None = None
) -> dict:
    target = tmp_path / "unpublished" / "chart.html"
    requested = str(target) if output_path is None else output_path
    original = deepcopy(source)
    actual = chart.generate(source, requested)
    assert source == original
    assert not target.parent.exists()
    # The reference graph publishes only into its own disposable target.
    reference = chart_graph.invoke(
        cast(
            ChartInput,
            {
                "source_result": source,
                "output_path": (
                    str(tmp_path / "reference.html")
                    if output_path is None
                    else output_path
                ),
            },
        )
    )
    assert {k: v for k, v in actual.items() if k != "output_path"} == {
        k: v for k, v in reference.items() if k != "output_path"
    }
    if actual["status"] == "failed":
        assert actual["output_path"] is None
        assert reference["output_path"] is None
    else:
        assert actual["output_path"] == str(target.resolve())
        html = chart.render_document(actual)
        assert html == chart.render_document(actual)
        assert "Plotly.newPlot" in html
        assert "Monthly Sales Amount" in html
        assert "Order month" in html and "Sales amount" in html
        assert "<script src=" not in html
        partial = bool(actual["quarantined_row_count"])
        assert ("Partial input:" in html) == partial
        assert not target.parent.exists()
    return dict(actual)


def test_repository_roots_and_clean_dataset_parity(tmp_path: Path) -> None:
    assert ingestion.REPOSITORY_ROOT == ROOT
    assert chart.REPOSITORY_ROOT == ROOT
    assert (ROOT / "dataset/shared_sales_dataset.csv").is_file()
    actual = ingestion.prepare()
    assert actual == preparation_graph.invoke({})
    assert actual["status"] == "completed"
    result = assert_chart_parity(actual, tmp_path)
    assert result["status"] == "completed"
    assert (
        chart.resolve_output_path()
        == (ROOT / "adk/outputs/monthly_sales_amount.html").resolve()
    )


@pytest.mark.parametrize(
    "case",
    [
        "clean",
        "partial",
        "empty",
        "all_invalid",
        "missing",
        "malformed",
        "schema",
        "duplicate_header",
    ],
)
def test_synthetic_preparation_and_chart_parity(tmp_path: Path, case: str) -> None:
    path = tmp_path / "sales.csv"
    if case == "clean":
        write_source(
            path,
            [
                row("ORD-1", date="2026-03-20"),
                row("ORD-2", date="2025-12-31", quantity="3", unit_price="0.10"),
                row(" ORD-3 ", quantity=" 2.0 ", unit_price="0039.900"),
            ],
        )
    elif case == "partial":
        write_source(
            path,
            [
                row(" valid ", quantity="2.0", unit_price="039.900"),
                row("duplicate"),
                row(" duplicate "),
                row("bad-date", date="2026-02-30"),
                row("bad-price", unit_price="1.001"),
                row("unknown", product="NA", region="NULL"),
                row("multiline", product="Unknown\nProduct"),
            ],
        )
    elif case == "empty":
        write_source(path, [])
    elif case == "all_invalid":
        write_source(path, [row(quantity="0"), row("ORD-2", unit_price="NaN")])
    elif case == "malformed":
        write_source(path, [row(), ["too", "few"]])
    elif case == "schema":
        path.write_text("order_id,date\nORD-1,2026-01-05\n")
    elif case == "duplicate_header":
        path.write_text("order_id,order_id\n1,2\n")
    actual = ingestion.prepare(str(path))
    assert actual == preparation_graph.invoke({"csv_path": str(path)})
    result = assert_chart_parity(actual, tmp_path)
    if case == "partial":
        assert actual["report"]["valid_rows"] == 1
        assert actual["report"]["quarantined_rows"] == 6
        assert result["status"] == "completed_with_warnings"
        assert result["monthly_totals"] == [
            {"month": "2026-01", "sales_amount": "79.80"}
        ]
    if case == "clean":
        assert result["monthly_totals"] == [
            {"month": "2025-12", "sales_amount": "0.30"},
            {"month": "2026-01", "sales_amount": "79.80"},
            {"month": "2026-03", "sales_amount": "79.80"},
        ]


@pytest.mark.parametrize(
    "value",
    [None, [], {}, {"status": "failed"}, {"status": "other"}],
)
def test_invalid_envelope_parity(tmp_path: Path, value: object) -> None:
    assert_chart_parity(value, tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "2026-02-30"),
        ("quantity", True),
        ("unit_price", "NaN"),
        ("unit_price", "Infinity"),
        ("unit_price", "39.9"),
        ("product", ""),
    ],
)
def test_record_error_and_validated_counts_parity(
    tmp_path: Path, field: str, value: object
) -> None:
    source = ingestion.prepare(write_source(tmp_path / "sales.csv", [row()]))
    cast(dict[str, object], source["records"][0])[field] = value
    actual = assert_chart_parity(source, tmp_path)
    assert actual["status"] == "failed"
    assert actual["source_row_count"] == actual["valid_row_count"] == 1
    assert actual["quarantined_row_count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [("source_rows", 100), ("valid_rows", True), ("quarantined_rows", -1)],
)
def test_report_error_parity(tmp_path: Path, field: str, value: object) -> None:
    source = ingestion.prepare(write_source(tmp_path / "sales.csv", [row()]))
    cast(dict[str, object], source["report"])[field] = value
    actual = assert_chart_parity(source, tmp_path)
    assert actual["status"] == "failed"
    assert actual["source_row_count"] is None


@pytest.mark.parametrize("output_path", ["", "\x00", " "])
def test_invalid_output_path_parity(tmp_path: Path, output_path: str) -> None:
    source = ingestion.prepare(write_source(tmp_path / "sales.csv", [row()]))
    actual = assert_chart_parity(source, tmp_path, output_path)
    assert actual["error"]["code"] == "invalid_output_path"


def test_nonfinite_plot_error_parity(tmp_path: Path) -> None:
    source = ingestion.prepare(
        write_source(tmp_path / "sales.csv", [row(unit_price="1" + "0" * 310 + ".00")])
    )
    actual = assert_chart_parity(source, tmp_path)
    assert actual["error"]["code"] == "non_finite_plot_value"
    assert actual["monthly_totals"]


def test_exact_totals_with_restricted_decimal_context(tmp_path: Path) -> None:
    source = ingestion.prepare(
        write_source(
            tmp_path / "sales.csv",
            [
                row(unit_price="123456789012345678901234567890.12", quantity="3"),
                row("ORD-2", unit_price="0.10"),
            ],
        )
    )
    with localcontext() as context:
        context.prec = 3
        context.Emax = 1
        actual = assert_chart_parity(source, tmp_path)
    assert actual["monthly_totals"] == [
        {"month": "2026-01", "sales_amount": "370370367037037036703703703670.56"}
    ]


def test_generate_and_render_preserve_existing_target(tmp_path: Path) -> None:
    source: PreparationResult = ingestion.prepare(
        write_source(tmp_path / "sales.csv", [row()])
    )
    target = tmp_path / "chart.html"
    target.write_text("previous artifact")
    result = chart.generate(source, str(target))
    assert result["status"] == "completed"
    before = deepcopy(result)
    assert "Plotly.newPlot" in chart.render_document(result)
    assert result == before
    assert target.read_text() == "previous artifact"


def test_render_failure_returns_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ingestion.prepare(write_source(tmp_path / "sales.csv", [row()]))

    def fail_html(*args: object, **kwargs: object) -> str:
        raise ValueError("Rendering error")

    monkeypatch.setattr(chart.go.Figure, "to_html", fail_html)
    result = chart.generate(source, str(tmp_path / "chart.html"))
    assert result["status"] == "failed"
    assert result["output_path"] is None
    assert result["monthly_totals"] == [{"month": "2026-01", "sales_amount": "79.80"}]
    assert result["error"] == {
        "code": "render_failed",
        "message": "Unable to render chart: ValueError",
    }
    with pytest.raises(ChartError):
        chart.render_document(result)
    assert not (tmp_path / "chart.html").exists()
