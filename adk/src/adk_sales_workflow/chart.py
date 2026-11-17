"""Generate chart results and offline HTML without publishing any files."""

import math
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import plotly.graph_objects as go

from .paths import repository_root
from .visualization.aggregation import aggregate_monthly
from .visualization.models import ChartError, Result
from .visualization.validation import validate_source

# chart.py -> adk_sales_workflow -> src -> adk -> repository root.
REPOSITORY_ROOT = repository_root()
DEFAULT_OUTPUT = "adk/outputs/monthly_sales_amount.html"


def resolve_output_path(value: str | None = None) -> Path:
    """Resolve an intended destination without creating or opening it."""
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ChartError(
            "invalid_output_path", "Output path must be a non-empty string"
        )
    path = Path(value if value is not None else DEFAULT_OUTPUT)
    return (path if path.is_absolute() else REPOSITORY_ROOT / path).resolve()


def generate(source_result: object, output_path: str | None = None) -> Result:
    """Validate, aggregate, and check rendering; leave publication to the caller.

    A successful output_path is the intended absolute destination, not evidence
    of a published file. HTML is available separately through render_document.
    Rendering is checked here to preserve the chart stage's error contract.
    Filesystem write errors belong to the caller's artifact publication step.
    """
    raw_status = (
        source_result.get("status") if isinstance(source_result, Mapping) else None
    )
    result: Result = {
        "status": "failed",
        "output_path": None,
        "monthly_totals": [],
        "source_status": raw_status if isinstance(raw_status, str) else None,
        "source_row_count": None,
        "valid_row_count": None,
        "quarantined_row_count": None,
        "error": None,
    }
    try:
        validated = validate_source(source_result)
    except ChartError as exc:
        result["error"] = exc.error
        counts = exc.details.get("validated_counts")
        if isinstance(counts, dict):
            counts = cast(dict[str, int], counts)
            result["source_row_count"] = counts["source_rows"]
            result["valid_row_count"] = counts["valid_rows"]
            result["quarantined_row_count"] = counts["quarantined_rows"]
        return result
    result["source_row_count"] = validated.source_rows
    result["valid_row_count"] = len(validated.records)
    result["quarantined_row_count"] = validated.quarantined_rows
    try:
        result["monthly_totals"] = aggregate_monthly(validated.records)
    except (ArithmeticError, ValueError) as exc:
        result["error"] = {
            "code": "aggregation_failed",
            "message": f"Unable to aggregate: {type(exc).__name__}",
        }
        return result
    try:
        path = resolve_output_path(output_path)
    except ChartError as exc:
        result["error"] = exc.error
        return result
    except (OSError, ValueError, RuntimeError) as exc:
        result["error"] = {
            "code": "invalid_output_path",
            "message": f"Unable to resolve output: {type(exc).__name__}",
        }
        return result
    result["status"] = (
        "completed_with_warnings"
        if validated.status == "completed_with_errors"
        else "completed"
    )
    result["output_path"] = str(path)
    try:
        render_document(result)
    except ChartError as exc:
        result["status"] = "failed"
        result["output_path"] = None
        result["error"] = exc.error
    return result


def render_document(result: Result) -> str:
    """Return self-contained HTML; never write, create directories, or mutate.

    Raises ChartError on rendering failures or an already-failed result.
    A fixed div ID makes repeated rendering of the same result deterministic.
    """
    if result["status"] == "failed" or result["error"] is not None:
        error = result["error"]
        if error is not None:
            raise ChartError(error["code"], error["message"])
        raise ChartError("render_failed", "Cannot render a failed chart result")
    try:
        totals = result["monthly_totals"]
        values = [float(total["sales_amount"]) for total in totals]
        if not all(math.isfinite(value) for value in values):
            raise ChartError(
                "non_finite_plot_value",
                "A monthly total cannot be plotted as a finite number",
            )
        figure = go.Figure(
            go.Scatter(
                x=[total["month"] + "-01" for total in totals],
                y=values,
                mode="lines+markers",
                name="Sales amount",
                customdata=[
                    [total["month"], total["sales_amount"]] for total in totals
                ],
                hovertemplate="Order month: %{customdata[0]}<br>Sales amount: %{customdata[1]}<extra></extra>",
                line={"color": "#2563eb", "width": 3},
                marker={"size": 8},
            )
        )
        figure.update_layout(
            title="Monthly Sales Amount",
            template="plotly_white",
            xaxis={"title": "Order month", "type": "date", "tickformat": "%Y-%m"},
            yaxis={"title": "Sales amount", "tickformat": ",.2f"},
            font={"family": "Arial, sans-serif"},
            margin={"t": 100},
        )
        quarantined_rows = result["quarantined_row_count"] or 0
        if quarantined_rows:
            figure.add_annotation(
                text=f"Partial input: {quarantined_rows} rows quarantined",
                xref="paper",
                yref="paper",
                x=0,
                y=1.12,
                showarrow=False,
                font={"color": "#b45309"},
            )
        return figure.to_html(
            full_html=True,
            include_plotlyjs=True,
            config={"responsive": True},
            div_id="adk-monthly-sales-amount",
        )
    except ChartError:
        raise
    except Exception as exc:
        raise ChartError(
            "render_failed", f"Unable to render chart: {type(exc).__name__}"
        ) from exc
