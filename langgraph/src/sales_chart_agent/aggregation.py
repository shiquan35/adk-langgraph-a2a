"""Exact monthly Decimal totals, independent of the ambient decimal context."""

from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext

from sales_data_agent.models import SalesRecord

from sales_chart_agent.models import MonthlyTotal


def aggregate_monthly(records: list[SalesRecord]) -> list[MonthlyTotal]:
    # Enough significant digits for every product and their sum, including cents.
    precision = (
        max(
            len(str(record["quantity"])) + len(record["unit_price"])
            for record in records
        )
        + len(str(len(records)))
        + 2
    )
    with localcontext(Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN)):
        totals: dict[str, Decimal] = {}
        for record in records:
            month = record["date"][:7]
            amount = Decimal(record["quantity"]) * Decimal(record["unit_price"])
            totals[month] = totals.get(month, Decimal(0)) + amount
        return [
            {"month": month, "sales_amount": format(totals[month], ".2f")}
            for month in sorted(totals)
        ]
