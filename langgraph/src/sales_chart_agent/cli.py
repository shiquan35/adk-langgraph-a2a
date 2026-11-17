"""Console chart generation: one JSON result on stdout, logs on stderr."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast
from uuid import uuid4

from sales_data_agent.ingest import REPOSITORY_ROOT

from sales_chart_agent.graph import graph
from sales_chart_agent.models import EXIT_CODES, Result, failure_result
from sales_chart_agent.observability import LOGGER, log_event


def reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON numeric constant: {value}")


def load_source(value: str) -> object:
    path = Path(value)
    path = (path if path.is_absolute() else REPOSITORY_ROOT / path).resolve()
    return json.loads(
        path.read_text(encoding="utf-8"), parse_constant=reject_json_constant
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a monthly sales amount HTML chart from Agent 1 JSON."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Agent 1 JSON file (relative paths resolve from the repository root).",
    )
    parser.add_argument(
        "--output",
        help="HTML output path; defaults to langgraph/outputs/monthly_sales_amount.html.",
    )
    args = parser.parse_args(argv)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    previous_level, previous_propagate = LOGGER.level, LOGGER.propagate
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    try:
        result: Result
        load_failed = True
        try:
            source = load_source(args.input)
        except OSError as exc:
            result = failure_result(
                "input_read_failed",
                f"Unable to read input: {exc.strerror or type(exc).__name__}",
            )
        except (ValueError, UnicodeError, RuntimeError) as exc:
            result = failure_result(
                "invalid_input_json", f"Unable to parse input: {type(exc).__name__}"
            )
        else:
            load_failed = False
            result = cast(
                Result,
                graph.invoke({"source_result": source, "output_path": args.output}),
            )
        if load_failed and result["error"] is not None:
            run_id = uuid4().hex
            log_event(
                logging.ERROR,
                "input_failed",
                run_id,
                input_path=args.input,
                **result["error"],
            )
            log_event(
                logging.INFO,
                "agent_finished",
                run_id,
                **result,
                exit_code=EXIT_CODES[result["status"]],
            )
        # Serialize completely before writing; ASCII escapes handle lone surrogates.
        payload = json.dumps(
            result, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        )
        sys.stdout.write(payload + "\n")
        return EXIT_CODES[result["status"]]
    finally:
        LOGGER.removeHandler(handler)
        handler.close()
        LOGGER.setLevel(previous_level)
        LOGGER.propagate = previous_propagate
