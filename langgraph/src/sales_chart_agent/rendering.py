"""Offline Plotly charts with replace-on-success filesystem semantics."""

import math
import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

import plotly.graph_objects as go
from sales_data_agent.ingest import REPOSITORY_ROOT

from sales_chart_agent.models import ChartError, MonthlyTotal

DEFAULT_OUTPUT = "langgraph/outputs/monthly_sales_amount.html"


def resolve_output_path(value: str | None) -> Path:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ChartError(
            "invalid_output_path", "Output path must be a non-empty string"
        )
    path = Path(value if value is not None else DEFAULT_OUTPUT)
    return (path if path.is_absolute() else REPOSITORY_ROOT / path).resolve()


def build_figure(totals: list[MonthlyTotal], quarantined_rows: int) -> go.Figure:
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
            customdata=[[total["month"], total["sales_amount"]] for total in totals],
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
    return figure


def render_html(totals: list[MonthlyTotal], quarantined_rows: int, path: Path) -> None:
    temporary: Path | None = None
    try:
        figure = build_figure(totals, quarantined_rows)
        html = figure.to_html(
            full_html=True, include_plotlyjs=True, config={"responsive": True}
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        os.replace(temporary, path)
    except ChartError:
        raise
    except OSError as exc:
        raise ChartError(
            "html_write_failed", f"Unable to write chart: {exc.strerror or str(exc)}"
        ) from exc
    except Exception as exc:
        raise ChartError(
            "render_failed", f"Unable to render chart: {type(exc).__name__}"
        ) from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
