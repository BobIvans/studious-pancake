"""Offline import smoke tests for ingest modules."""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import src.ingest

pytestmark = pytest.mark.unit


def ingest_module_names() -> list[str]:
    return sorted(
        module.name
        for module in pkgutil.iter_modules(src.ingest.__path__, prefix="src.ingest.")
        if not module.ispkg and not module.name.endswith(".jito_executor.py")
    )


@pytest.mark.parametrize("module_name", ingest_module_names())
def test_ingest_module_imports_without_runtime_side_effects(module_name: str) -> None:
    """Every src.ingest module must import without network access or runtime state."""
    importlib.import_module(module_name)
