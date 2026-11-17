"""Repository discovery stays independent of the installed package location."""

from pathlib import Path

import pytest
from adk_sales_workflow import paths


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate both discovery origins from the real checkout."""
    monkeypatch.delenv("ADK_SALES_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    module = tmp_path / "site-packages/adk_sales_workflow/paths.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(module))
    root = tmp_path / "repository"
    (root / "dataset").mkdir(parents=True)
    (root / "dataset/shared_sales_dataset.csv").touch()
    (root / "pyproject.toml").touch()
    return root


@pytest.mark.parametrize("relative", [False, True])
def test_environment_override_takes_precedence(
    repository: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    configured = repository.parent / "configured"
    configured.mkdir()
    monkeypatch.chdir(repository)
    value = "../configured" if relative else str(configured)
    monkeypatch.setenv("ADK_SALES_ROOT", value)

    assert paths.repository_root() == configured.resolve()


def test_environment_override_expands_home(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(repository.parent))
    monkeypatch.setenv("ADK_SALES_ROOT", "~/repository")

    assert paths.repository_root() == repository.resolve()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_environment_override_does_not_fall_back(
    repository: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    configured = repository.parent / kind
    if kind == "file":
        configured.touch()
    monkeypatch.chdir(repository)
    monkeypatch.setenv("ADK_SALES_ROOT", str(configured))

    with pytest.raises(
        ValueError, match="^ADK_SALES_ROOT must name an existing directory$"
    ):
        paths.repository_root()


@pytest.mark.parametrize("nested", [False, True])
def test_discovers_repository_from_cwd(
    repository: Path, monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    cwd = repository / "nested/working" if nested else repository
    cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)

    assert paths.repository_root() == repository.resolve()


def test_discovers_repository_from_module_location(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = repository / "adk/src/adk_sales_workflow/paths.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(module))

    assert paths.repository_root() == repository.resolve()


@pytest.mark.parametrize("marker", ["both", "dataset", "project"])
def test_missing_repository_requires_explicit_root(
    repository: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    if marker in ("both", "dataset"):
        (repository / "dataset/shared_sales_dataset.csv").unlink()
    if marker in ("both", "project"):
        (repository / "pyproject.toml").unlink()
    monkeypatch.chdir(repository)

    with pytest.raises(
        ValueError, match="^Cannot locate sales repository; set ADK_SALES_ROOT$"
    ):
        paths.repository_root()
