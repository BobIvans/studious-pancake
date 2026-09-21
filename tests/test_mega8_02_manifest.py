from __future__ import annotations

import importlib
import inspect

from src.mega8_02.manifest import ALL_FUNCTIONS, CHILDREN, FUNCTION_COUNT, NF_IDS


def test_manifest_exact_scope_and_nf_sequence() -> None:
    assert tuple(CHILDREN) == tuple(range(163, 186))
    assert FUNCTION_COUNT == 92
    assert NF_IDS == tuple(range(401, 493))
    assert len(ALL_FUNCTIONS) == len(set(ALL_FUNCTIONS)) == 92


def test_every_nf_has_one_importable_child_owner() -> None:
    observed: set[str] = set()
    for child, (_, rows) in CHILDREN.items():
        module = importlib.import_module(f"src.mega8_02.pr{child}")
        for _, name in rows:
            symbol = getattr(module, name)
            assert callable(symbol)
            observed.add(name)
    assert observed == set(ALL_FUNCTIONS)


def test_mega802_modules_are_sender_free_by_import_surface() -> None:
    banned = ("aiohttp", "requests", "solders", "solana.rpc", "submission")
    for child in CHILDREN:
        module = importlib.import_module(f"src.mega8_02.pr{child}")
        source = inspect.getsource(module)
        for name in banned:
            assert f"import {name}" not in source
            assert f"from {name}" not in source
