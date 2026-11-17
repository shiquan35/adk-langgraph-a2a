"""Locate a sales checkout independently of editable or wheel installation."""

import os
from pathlib import Path


def repository_root() -> Path:
    """Use explicit configuration, then discover a checkout from cwd/source.

    A wheel cannot infer an unrelated checkout's location. Outside one, callers
    must set ADK_SALES_ROOT; never silently resolve paths into site-packages.
    """
    configured = os.environ.get("ADK_SALES_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("ADK_SALES_ROOT must name an existing directory")
        return root
    for location in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for root in (location, *location.parents):
            if (root / "dataset/shared_sales_dataset.csv").is_file() and (
                root / "pyproject.toml"
            ).is_file():
                return root
    message = "Cannot locate sales repository; set ADK_SALES_ROOT"
    raise ValueError(message)
