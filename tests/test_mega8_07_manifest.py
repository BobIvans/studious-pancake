from __future__ import annotations

import importlib
import inspect

from src.mega8_07.manifest import ALL_FUNCTIONS, CHILDREN, FUNCTION_COUNT, NF_IDS


def test_manifest_exact_scope_and_nf_sequence() -> None:
    assert tuple(CHILDREN) == tuple(range(271, 287))
    assert FUNCTION_COUNT == 64
    assert NF_IDS == tuple(range(769, 833))
    assert len(ALL_FUNCTIONS) == len(set(ALL_FUNCTIONS)) == 64


def test_every_nf_has_one_importable_child_owner() -> None:
    observed: set[str] = set()
    for child, (_, rows) in CHILDREN.items():
        module = importlib.import_module(f"src.mega8_07.pr{child}")
        for _, name in rows:
            assert callable(getattr(module, name))
            observed.add(name)
    assert observed == set(ALL_FUNCTIONS)


def test_mega807_modules_do_not_import_effectful_clients() -> None:
    banned = (
        "aiohttp",
        "requests",
        "solana.rpc",
        "solders.keypair",
        "src.submission",
        "subprocess",
    )
    for child in CHILDREN:
        module = importlib.import_module(f"src.mega8_07.pr{child}")
        source = inspect.getsource(module)
        for name in banned:
            assert f"import {name}" not in source
            assert f"from {name}" not in source
