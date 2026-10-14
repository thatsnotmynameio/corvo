from importlinter.cli import lint_imports


def test_import_contracts() -> None:
    """The contracts of [tool.importlinter] in pyproject.toml hold."""
    assert lint_imports(no_cache=True) == 0
