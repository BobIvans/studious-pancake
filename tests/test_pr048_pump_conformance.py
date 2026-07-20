from __future__ import annotations

import copy

import pytest

from src.venues.pump import (
    PumpAdapter,
    PumpContractManifest,
    PumpFamily,
    PumpManifestStatus,
    PumpProvenanceError,
    RawAccount,
    ReasonCode,
    manifest_shadow_errors,
)


pytestmark = pytest.mark.unit

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"


def _u64(value: int) -> bytes:
    return value.to_bytes(8, "little")


def _bonding_curve_data(*, discriminator: bytes | None = None) -> bytes:
    quote_mint = bytes(range(32))
    body = b"".join(
        (
            _u64(1_000_000),
            _u64(2_000_000),
            _u64(900_000),
            _u64(1_800_000),
            _u64(1_000_000_000),
            b"\x00",
            bytes([7]) * 32,
            b"\x00",
            b"\x00",
            quote_mint,
        )
    )
    return (discriminator or bytes.fromhex("17b7f83760d8ac60")) + body + b"tail"


def test_manifest_pins_official_idl_blob_sha_and_denies_live() -> None:
    manifest = PumpContractManifest.load()

    assert manifest.live_capability == "DENIED_SHADOW_ONLY"
    assert manifest.shadow_errors() == ()

    bonding = manifest.by_family(PumpFamily.BONDING_CURVE)
    pumpswap = manifest.by_family(PumpFamily.PUMPSWAP)
    assert bonding is not None
    assert pumpswap is not None
    assert bonding.source.status == PumpManifestStatus.OFFICIAL_PINNED_SHADOW.value
    assert bonding.idl_git_blob_sha == "062e66f032bb9f295353b573be3400070bd55e5b"
    assert pumpswap.idl_git_blob_sha == "a654b6f924c8e5458ba9b38c9e13a3980f5e9518"
    assert "buy" in bonding.instruction_discriminators
    assert "sell" in bonding.instruction_discriminators


def test_placeholder_manifest_is_not_shadow_eligible() -> None:
    raw = copy.deepcopy(PumpContractManifest.load().raw)
    raw["families"][0]["status"] = "ENABLED_SHADOW"
    raw["families"][0]["idl_git_blob_sha"] = "fixture-pinned-pump-idl-sha"
    raw["families"][0]["upstream_commit"] = "main@implementation-time"

    manifest = PumpContractManifest(raw)

    errors = manifest_shadow_errors(raw)
    assert any("status=ENABLED_SHADOW" in error for error in errors)
    assert any("idl_git_blob_sha_not_40_hex" in error for error in errors)

    bonding = manifest.by_family(PumpFamily.BONDING_CURVE)
    assert bonding is not None
    with pytest.raises(PumpProvenanceError):
        bonding.validate_shadow_ready()


def test_default_adapter_decodes_official_bonding_curve_layout_with_tail() -> None:
    adapter = PumpAdapter()
    account = RawAccount(
        address="curve",
        owner=PUMP_PROGRAM,
        data=_bonding_curve_data(),
        executable=False,
        slot=123,
    )

    decoded = adapter.decode_account(PumpFamily.BONDING_CURVE, account)

    assert decoded.virtual_base_reserves == 1_000_000
    assert decoded.virtual_quote_reserves == 2_000_000
    assert decoded.real_base_reserves == 900_000
    assert decoded.real_quote_reserves == 1_800_000
    assert decoded.complete is False
    assert decoded.quote_mint == bytes(range(32)).hex()


def test_wrong_owner_and_discriminator_fail_closed() -> None:
    adapter = PumpAdapter()
    account = RawAccount(
        address="curve",
        owner=PUMPSWAP_PROGRAM,
        data=_bonding_curve_data(),
        executable=False,
        slot=123,
    )

    with pytest.raises(ValueError, match=ReasonCode.PUMP_OWNER_MISMATCH.value):
        adapter.decode_account(PumpFamily.BONDING_CURVE, account)

    bad_discriminator = RawAccount(
        address="curve",
        owner=PUMP_PROGRAM,
        data=_bonding_curve_data(discriminator=b"12345678"),
        executable=False,
        slot=123,
    )
    with pytest.raises(ValueError, match=ReasonCode.PUMP_DISCRIMINATOR_MISMATCH.value):
        adapter.decode_account(PumpFamily.BONDING_CURVE, bad_discriminator)


def test_instruction_discriminator_comes_from_pinned_idl_not_local_hash() -> None:
    manifest = PumpContractManifest.load()
    bonding = manifest.by_family(PumpFamily.BONDING_CURVE)
    assert bonding is not None

    assert bonding.instruction_discriminators["buy"] == bytes(
        [102, 6, 61, 18, 1, 218, 235, 234]
    )
    assert bonding.instruction_discriminators["sell"] == bytes(
        [51, 230, 133, 164, 1, 127, 131, 173]
    )
