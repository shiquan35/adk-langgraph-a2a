"""One-command preparation and chart generation."""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import cast

from sales_pipeline_agent.graph import graph
from sales_pipeline_agent.models import EXIT_CODES, Result
from sales_pipeline_agent.observability import stderr_logging


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare sales CSV records and generate a monthly sales amount chart."
    )
    parser.add_argument(
        "--csv-path",
        help="CSV path relative to repository root; defaults to dataset/shared_sales_dataset.csv.",
    )
    parser.add_argument(
        "--output",
        help="HTML path relative to repository root; defaults to langgraph/outputs/monthly_sales_amount.html.",
    )
    args = parser.parse_args(argv)
    with stderr_logging():
        result = cast(
            Result,
            graph.invoke({"csv_path": args.csv_path, "output_path": args.output}),
        )
        payload = json.dumps(
            result, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        sys.stdout.write(payload + "\n")
        return EXIT_CODES[result["status"]]
