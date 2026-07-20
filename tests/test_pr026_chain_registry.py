from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.chain_registry import (
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    NATIVE_SOL_MINT_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistry,
    ChainRegistryError,
    validate_pubkey,
)

ROOT = Path(__file__).resolve().parents[1]


def test_registry_contains_only_canonical_platform_constants() -> None:
    registry = ChainRegistry.load_default()
    expected = {
        "system_program": SYSTEM_PROGRAM_ADDRESS,
        "token_program": TOKEN_PROGRAM_ADDRESS,
        "token_2022_program": TOKEN_2022_PROGRAM_ADDRESS,
        "associated_token_program": ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
        "compute_budget_program": COMPUTE_BUDGET_PROGRAM_ADDRESS,
        "native_sol_mint": NATIVE_SOL_MINT_ADDRESS,
    }

    assert {entry.id: entry.address for entry in registry.entries} == expected
    assert registry.entry("token_2022_program").address == (
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
    )
    assert registry.entry("associated_token_program").address == (
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
    )


def test_packaged_and_operator_registry_copies_do_not_drift() -> None:
    operator_payload = json.loads(
        (ROOT / "config/chain_registry.json").read_text(encoding="utf-8")
    )
    packaged_payload = json.loads(
        (ROOT / "src/resources/chain_registry.json").read_text(encoding="utf-8")
    )
    assert operator_payload == packaged_payload


def test_marginfi_is_dynamic_and_has_no_current_looking_default() -> None:
    registry = ChainRegistry.load_default()
    marginfi = next(
        item for item in registry.dynamic_entries if item.id == "marginfi_program"
    )
    assert marginfi.config_path == "providers.marginfi.program_id"
    assert not hasattr(marginfi, "address")


def test_invalid_pubkeys_and_unregistered_programs_fail_closed() -> None:
    with pytest.raises(ChainRegistryError, match="non-base58"):
        validate_pubkey("not-a-solana-address")
    with pytest.raises(ChainRegistryError, match="exactly 32 bytes"):
        validate_pubkey("1111")

    registry = ChainRegistry.load_default()
    with pytest.raises(ChainRegistryError, match="not registered"):
        registry.validate_allowlisted_programs(
            ["Vote111111111111111111111111111111111111111"],
            cluster="mainnet-beta",
        )


def test_known_invalid_constants_are_removed_from_code_and_tests() -> None:
    forbidden = {
        "TokenzQdBNbLqP5VEh" + "fqASPWnGD1x1gUghStfV2hLwx",
        "TokenzQdBNbLqP5VEh" + "dkAS6EPZ5VK5jY6aXL7YYg9V",
        "ATokenGPvoter" + "11111111111111111111111111111111",
    }
    paths = [ROOT / "src", ROOT / "tests"]
    for root in paths:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                assert value not in text, f"forbidden constant remains in {path}"
