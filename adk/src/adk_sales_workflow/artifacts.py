"""Stage complete artifacts before publishing them atomically, one file at a time."""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import chart
from .visualization.models import Result as ChartResult


class ArtifactWriteError(Exception):
    """Safe publication context, including whether HTML was already replaced."""

    def __init__(self, path: Path, *, html_replaced: bool = False) -> None:
        super().__init__(f"Unable to publish artifact: {path}")
        self.path = path
        self.html_replaced = html_replaced


def serialize(result: Mapping[str, Any]) -> str:
    """Use exactly the same strict, compact encoding for stdout and saved JSON."""
    return json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _stage(path: Path, content: str, pending: list[Path]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        # Track before writing/closing, both of which may fail.
        pending.append(temporary)
        stream.write(content)
    return temporary


def _cleanup(pending: list[Path]) -> None:
    for path in pending:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Cleanup must not hide the original publication failure.
            pass


def save_result(result: Mapping[str, Any], path: Path) -> str:
    """Save a full preparation envelope, including an ordinary failed result."""
    pending: list[Path] = []
    try:
        text = serialize(result)
        temporary = _stage(path, text, pending)
        os.replace(temporary, path)
        return text
    except Exception as exc:
        raise ArtifactWriteError(path) from exc
    finally:
        _cleanup(pending)


def publish_chart(
    result: Mapping[str, Any],
    chart_result: ChartResult,
    html_path: Path,
    json_path: Path,
) -> str:
    """Render/serialize/stage both files before replacing HTML and then JSON.

    This is deliberately not a pair transaction. A JSON replacement failure
    leaves new HTML beside the previous JSON; callers must report that failure
    only on stdout, not attempt a second JSON publication or roll back HTML.
    """
    pending: list[Path] = []
    active_path = html_path
    html_replaced = False
    try:
        document = chart.render_document(chart_result)
        active_path = json_path
        text = serialize(result)
        active_path = html_path
        html_temporary = _stage(html_path, document, pending)
        active_path = json_path
        json_temporary = _stage(json_path, text, pending)
        active_path = html_path
        os.replace(html_temporary, html_path)
        html_replaced = True
        active_path = json_path
        os.replace(json_temporary, json_path)
        return text
    except Exception as exc:
        raise ArtifactWriteError(active_path, html_replaced=html_replaced) from exc
    finally:
        _cleanup(pending)
