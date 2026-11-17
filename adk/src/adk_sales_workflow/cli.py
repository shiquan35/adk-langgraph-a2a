"""Repository-relative CLI for real ADK execution and artifact publication."""

import argparse
import asyncio
import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from . import artifacts, ingestion, runtime
from .models import Mode
from .observability import (
    current_invocation_id,
    invocation_id,
    log_event,
    log_exception,
    stderr_logging,
)
from .visualization.models import Result as ChartResult
from .visualization.models import failure_result

DEFAULT_OUTPUT_DIR = "adk/outputs"
HTML_NAME = "monthly_sales_amount.html"
JSON_NAME = "monthly_sales_amount.json"
SUCCESS_STATUSES = {"completed", "completed_with_errors", "completed_with_warnings"}


def _resolve(value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else ingestion.REPOSITORY_ROOT / path).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adk-sales")
    commands = parser.add_subparsers(dest="mode", required=True)
    run = commands.add_parser("run", help="Prepare sales data and publish a chart")
    run.add_argument("--csv-path", default=ingestion.DEFAULT_CSV)
    run.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ingest = commands.add_parser("ingest", help="Prepare sales data as JSON")
    ingest.add_argument("--csv-path", default=ingestion.DEFAULT_CSV)
    ingest.add_argument("--output")
    chart = commands.add_parser("chart", help="Chart a prepared sales JSON result")
    chart.add_argument("--input", required=True)
    chart.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser


def _unexpected(mode: Mode, csv_path: str | None, exc: Exception) -> dict[str, Any]:
    stage = "chart" if mode == "chart" else "preparation"
    log_exception(current_invocation_id() or "cli", stage, exc)
    issue = {"code": "unexpected_stage_error", "message": type(exc).__name__}
    if mode == "run":
        return {
            "status": "failed",
            "preparation_result": None,
            "chart_result": None,
            "error": {"stage": stage, **issue},
        }
    if mode == "chart":
        return dict(failure_result(issue["code"], issue["message"]))
    return {
        "status": "failed",
        "records": [],
        "quarantined_rows": [],
        "report": {
            "source_path": csv_path,
            "source_rows": 0,
            "valid_rows": 0,
            "quarantined_rows": 0,
            "normalization_change_count": 0,
            "normalization_changes": [],
            "file_issues": [issue],
        },
    }


def _artifact_failure(
    mode: Mode,
    result: dict[str, Any],
    exc: artifacts.ArtifactWriteError,
) -> dict[str, Any]:
    # Never mutate successful children retained in a parent result.
    log_event(
        logging.ERROR,
        "artifact_write_failed",
        current_invocation_id() or "cli",
        artifact_path=str(exc.path),
        exception_type=type(exc.__cause__).__name__,
        message=str(exc),
        html_replaced=exc.html_replaced,
    )
    failed = deepcopy(result)
    failed["status"] = "failed"
    issue = {"code": "artifact_write_failed", "message": str(exc)}
    if mode == "ingest":
        failed["report"]["file_issues"].append(issue)
    elif mode == "run":
        failed["error"] = {"stage": "artifact_write", **issue}
    else:
        failed["error"] = issue
        if not exc.html_replaced:
            failed["output_path"] = None
    return failed


def _process(args: argparse.Namespace) -> dict[str, Any]:
    mode = cast(Mode, args.mode)
    csv_path: str | None = None
    try:
        if mode in ("run", "ingest"):
            csv_path = str(_resolve(args.csv_path))
        source: Any = None
        if mode == "chart":
            input_path = _resolve(args.input)
            try:
                text = input_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return dict(
                    failure_result(
                        "input_read_failed", f"Unable to read input: {input_path}"
                    )
                )
            try:
                source = json.loads(text)
            except (ValueError, RecursionError):
                return dict(
                    failure_result("invalid_json", f"Invalid JSON input: {input_path}")
                )
        output_dir = _resolve(args.output_dir) if mode != "ingest" else None
        html_path = output_dir / HTML_NAME if output_dir is not None else None
        result = asyncio.run(
            runtime.execute(
                mode,
                csv_path=csv_path,
                source_result=source,
                output_path=str(html_path) if html_path is not None else None,
            )
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary must emit a failure envelope
        return _unexpected(mode, csv_path, exc)

    try:
        if mode == "ingest" and args.output is not None:
            artifacts.save_result(result, _resolve(args.output))
        elif mode != "ingest" and result["status"] in SUCCESS_STATUSES:
            assert output_dir is not None and html_path is not None
            child = result["chart_result"] if mode == "run" else result
            artifacts.publish_chart(
                result,
                cast(ChartResult, child),
                html_path,
                output_dir / JSON_NAME,
            )
    except artifacts.ArtifactWriteError as exc:
        return _artifact_failure(mode, result, exc)
    except (OSError, ValueError, RuntimeError):
        # Path resolution can fail before the writer has a destination.
        path = Path(cast(str, args.output if mode == "ingest" else args.output_dir))
        return _artifact_failure(mode, result, artifacts.ArtifactWriteError(path))
    return result


def main() -> int:
    """Emit one compact JSON envelope after argparse, with warnings successful."""
    args = _parser().parse_args()
    with invocation_id() as run_id, stderr_logging():
        result = _process(args)
        try:
            text = artifacts.serialize(result)
        except (TypeError, ValueError, RecursionError) as exc:
            result = _unexpected(cast(Mode, args.mode), None, exc)
            text = artifacts.serialize(result)
        exit_code = 0 if result["status"] in SUCCESS_STATUSES else 2
        child = result.get("chart_result") if args.mode == "run" else result
        output_path = child.get("output_path") if isinstance(child, dict) else None
        if args.mode == "ingest" and args.output is not None:
            output_path = args.output
        log_event(
            logging.INFO,
            "workflow_finished",
            run_id,
            mode=args.mode,
            status=result["status"],
            output_path=output_path,
            exit_code=exit_code,
        )
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
