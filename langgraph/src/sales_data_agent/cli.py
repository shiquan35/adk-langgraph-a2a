"""Console trigger: one JSON envelope on stdout, diagnostic JSON on stderr."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from sales_data_agent.graph import graph
from sales_data_agent.models import Status
from sales_data_agent.observability import LOGGER

EXIT_CODES: dict[Status, int] = {
    "completed": 0,
    "completed_with_errors": 1,
    "failed": 2,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and prepare sales CSV records with LangGraph."
    )
    parser.add_argument(
        "--csv-path",
        help="CSV path (relative to the repository root); defaults to the shared dataset.",
    )
    args = parser.parse_args(argv)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    previous_level = LOGGER.level
    previous_propagate = LOGGER.propagate
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    try:
        result = graph.invoke({"csv_path": args.csv_path})
        json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False)
        sys.stdout.write("\n")
        return EXIT_CODES[result["status"]]
    finally:
        LOGGER.removeHandler(handler)
        handler.close()
        LOGGER.setLevel(previous_level)
        LOGGER.propagate = previous_propagate
