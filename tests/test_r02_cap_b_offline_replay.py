"""R02-CAP-B offline replay: pinned dossier integrity + negative replay matrix.

Replays the reader against the pinned offline pack
(docs/roadmap/r02-capacity-recovery-2026-10-08/): the vendor manifest blob
hashes, the structural prefix probe shipped with the pack, and a typed
negative replay matrix. Zero network; every account byte is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from solders.pubkey import Pubkey

from src.lending.kamino import (
    KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR,
    KAMINO_RESERVE_PINNED_FIELDS,
    KAMINO_RESERVE_PINNED_PREFIX_LEN,
    KLEND_ONE_SF,
    KLEND_PROGRAM_ID,
    KLEND_SDK_UPSTREAM_COMMIT,
    READER_EXECUTION_AUTHORITY,
    SPL_TOKEN_PROGRAM_ID,
    KaminoCapacityReaderError,
    KaminoCapacityRejectionCode,
    decode_kamino_reserve,
    observe_kamino_reserve_capacity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OFFLINE_ROOT = REPO_ROOT / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes((seed,)) * 32)


def _values() -> dict[str, bytes]:
    return {
        "version": (0).to_bytes(8, "little"),
        "last_update_slot": (30_100_000).to_bytes(8, "little"),
        "last_update_stale": (0).to_bytes(1, "little"),
        "last_update_price_status": (1).to_bytes(1, "little"),
        "last_update_pad": bytes(2),
        "last_update_timestamp": (1_764_100_000).to_bytes(4, "little"),
        "lending_market": bytes(_pk(7)),
        "farm_collateral": bytes(_pk(41)),
        "farm_debt": bytes(_pk(42)),
        "liquidity_mint": bytes(_pk(3)),
        "liquidity_supply_vault": bytes(_pk(9)),
        "liquidity_fee_vault": bytes(_pk(10)),
        "total_available_amount": (7_500_000_000).to_bytes(8, "little"),
        "borrowed_amount_sf": (1_250_000_000 * KLEND_ONE_SF).to_bytes(16, "little"),
        "market_price_sf": (1).to_bytes(16, "little"),
        "market_price_last_updated_ts": (1_764_099_000).to_bytes(8, "little"),
        "mint_decimals": (9).to_bytes(8, "little"),
        "deposit_limit_crossed_ts": (0).to_bytes(8, "little"),
        "borrow_limit_crossed_ts": (0).to_bytes(8, "little"),
        "cumulative_borrow_rate_bsf": (3).to_bytes(8, "little") + bytes(24),
        "accumulated_protocol_fees_sf": (0).to_bytes(16, "little"),
        "accumulated_referrer_fees_sf": (0).to_bytes(16, "little"),
        "pending_referrer_fees_sf": (0).to_bytes(16, "little"),
        "absolute_referral_rate_sf": (0).to_bytes(16, "little"),
        "liquidity_token_program": bytes(SPL_TOKEN_PROGRAM_ID),
        "rewards_amount_available": (0).to_bytes(8, "little"),
        "liquidity_padding2": bytes(400),
        "liquidity_padding3": bytes(512),
        "reserve_liquidity_padding": bytes(1200),
        "collateral_mint": bytes(_pk(43)),
        "collateral_mint_total_supply": (9_000_000_000).to_bytes(8, "little"),
        "collateral_supply_vault": bytes(_pk(44)),
        "collateral_padding1": bytes(512),
        "collateral_padding2": bytes(512),
        "reserve_collateral_padding": bytes(1200),
        "config_status": (0).to_bytes(1, "little"),
        "config_padding_deprecated_asset_tier": (0).to_bytes(1, "little"),
        "config_host_fixed_interest_rate_bps": (0).to_bytes(2, "little"),
        "config_min_deleveraging_bonus_bps": (0).to_bytes(2, "little"),
        "config_block_ctoken_usage": (0).to_bytes(1, "little"),
        "config_early_repay_remaining_interest_pct": (0).to_bytes(1, "little"),
        "config_emergency_mode": (0).to_bytes(1, "little"),
        "config_interest_rate_basis": (0).to_bytes(1, "little"),
        "config_reserved1": bytes(3),
        "config_protocol_order_execution_fee_pct": (0).to_bytes(1, "little"),
        "config_protocol_take_rate_pct": (0).to_bytes(1, "little"),
        "config_protocol_liquidation_fee_pct": (0).to_bytes(1, "little"),
        "config_loan_to_value_pct": (75).to_bytes(1, "little"),
        "config_liquidation_threshold_pct": (85).to_bytes(1, "little"),
        "config_min_liquidation_bonus_bps": (0).to_bytes(2, "little"),
        "config_max_liquidation_bonus_bps": (0).to_bytes(2, "little"),
        "config_bad_debt_liquidation_bonus_bps": (0).to_bytes(2, "little"),
        "config_deleveraging_margin_call_period_secs": (0).to_bytes(8, "little"),
        "config_deleveraging_threshold_decrease_bps_per_day": (0).to_bytes(8, "little"),
        "config_origination_fee_sf": (0).to_bytes(8, "little"),
        "config_flash_loan_fee_sf": (KLEND_ONE_SF >> 1).to_bytes(8, "little"),
        "config_fees_padding": bytes(8),
    }


def _reserve_bytes(values: dict[str, bytes], *, tail_len: int = 2816) -> bytes:
    raw = bytearray(KAMINO_RESERVE_PINNED_PREFIX_LEN + tail_len)
    raw[:8] = KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR
    for name, (offset, size) in KAMINO_RESERVE_PINNED_FIELDS.items():
        chunk = values[name]
        assert len(chunk) == size, name
        raw[offset : offset + size] = chunk
    return bytes(raw)


def _vault_bytes(mint: Pubkey, authority: Pubkey, amount: int) -> bytes:
    raw = bytearray(165)
    raw[0:32] = bytes(mint)
    raw[32:64] = bytes(authority)
    raw[64:72] = amount.to_bytes(8, "little")
    raw[108] = 1
    return bytes(raw)


def _observation(values: dict[str, bytes] | None = None):
    resolved = values if values is not None else _values()
    reserve_bytes = _reserve_bytes(resolved)
    return (
        observe_kamino_reserve_capacity(
            reserve_bytes=reserve_bytes,
            reserve_owner=KLEND_PROGRAM_ID,
            reserve_address=_pk(8),
            lending_market=_pk(7),
            supply_vault_bytes=_vault_bytes(_pk(3), _pk(7), 8_000_000_000),
            supply_vault_address=_pk(9),
            supply_vault_owner_program=SPL_TOKEN_PROGRAM_ID,
            reviewed_mint=_pk(3),
        ),
        reserve_bytes,
    )


def test_offline_pack_verifier_passes_without_network() -> None:
    verifier = _load_module(OFFLINE_ROOT / "verify_offline.py", "r02_verify_offline")
    result = verifier.validate()
    assert result["status"] == "OFFLINE_REFERENCE_INTEGRITY_PASS"
    assert result["live_readers_qualified"] == 0
    assert result["network_requests"] == 0
    assert result["execution_authority"] == "NONE"
    assert result["kamino_prefix_bytes"] == 280


def test_vendor_manifest_pins_klend_sdk_vendored_files() -> None:
    manifest = json.loads(
        (OFFLINE_ROOT / "VENDOR_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["kamino_package_version"] == "13.0.2"

    def git_blob_sha(raw: bytes) -> str:
        return hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()

    kamino_entries = [
        entry
        for entry in manifest["entries"]
        if entry["local_path"].startswith("offline/vendor/kamino/")
    ]
    assert len(kamino_entries) >= 8
    for entry in kamino_entries:
        raw = (OFFLINE_ROOT.parent / entry["local_path"]).read_bytes()
        assert git_blob_sha(raw) == entry["upstream_git_blob_sha"], entry["local_path"]
        assert len(raw) == entry["bytes"]
        assert entry["upstream_commit_sha"] == KLEND_SDK_UPSTREAM_COMMIT
        assert entry["license_label"].startswith("MIT")
        assert entry["reference_only"] is True


def test_prefix_probe_decoder_agrees_with_full_reader() -> None:
    probe = _load_module(OFFLINE_ROOT / "probe_structural.py", "r02_probe_structural")
    values = _values()
    reserve_bytes = _reserve_bytes(values)
    account = {
        "owner": str(KLEND_PROGRAM_ID),
        "executable": False,
        "data": [base64.b64encode(reserve_bytes).decode("ascii"), "base64"],
    }
    structural = probe.decode_captured_account(account, "kamino")
    assert structural["status"] == "STRUCTURAL_ONLY_NOT_FLASH_CAPACITY"
    assert structural["qualified_edges"] == []
    assert structural["sign_enabled"] is False
    assert structural["send_enabled"] is False
    assert structural["execution_authority"] == "NONE"

    observation, _ = _observation(values)
    prefix = structural["structural"]
    assert int(prefix["total_available_amount"]) == (
        observation.raw_total_available_amount
    )
    assert int(prefix["mint_decimals"]) == observation.mint_decimals
    assert prefix["mint"] == observation.mint
    assert prefix["supply_vault"] == str(observation.supply_vault.address)
    assert prefix["fee_vault"] == str(_pk(10))
    assert prefix["lending_market"] == observation.lending_market
    assert int(prefix["last_update_slot"]) == observation.last_update.slot
    assert int(prefix["last_update_stale"]) == observation.last_update.stale
    assert int(prefix["borrowed_amount_sf"]) == observation.raw_borrowed_amount_sf


def test_offline_replay_receipt_is_deterministic_and_typed() -> None:
    observation, _ = _observation()
    record = observation.evidence_record()
    replayed = json.dumps(record, sort_keys=True, separators=(",", ":"))
    assert json.loads(replayed)["evidence_sha256"] == observation.evidence_digest
    again, _ = _observation()
    assert again.evidence_digest == observation.evidence_digest
    assert record["decoder_identity"] == "kamino.klend.reserve.capacity-reader.v1"
    assert record["execution_authority"] == "NONE"
    assert record["sign_enabled"] is False
    assert record["send_enabled"] is False
    assert record["status"] == "BLOCKED_LIVE_STATE"
    assert (
        record["flash_instruction_pair"]["borrow"] == "flash_borrow_reserve_liquidity"
    )
    assert record["flash_instruction_pair"]["repay"] == "flash_repay_reserve_liquidity"
    assert record["flash_instruction_pair"]["obligation_account_required"] is False
    fee = record["observation"]["flash_loan_fee_rational"]
    assert fee == {"numerator": 1, "denominator": 2}
    assert observation.flash_loan_fee_rational == Fraction(1, 2)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("bad_discriminator", "R02CAPB_RESERVE_UNKNOWN_DISCRIMINATOR"),
        ("truncated", "R02CAPB_RESERVE_TRUNCATED_LAYOUT"),
        ("stale_last_update", "R02CAPB_RESERVE_LAST_UPDATE_STALE"),
        ("unknown_config_status", "R02CAPB_RESERVE_CONFIG_STATUS_UNKNOWN"),
        ("emergency_mode", "R02CAPB_RESERVE_EMERGENCY_MODE_NONZERO"),
        ("wrong_owner", "R02CAPB_RESERVE_OWNER_MISMATCH"),
        ("wrong_market", "R02CAPB_RESERVE_MARKET_BINDING_MISMATCH"),
        ("zero_mint", "R02CAPB_RESERVE_ZERO_MINT"),
        ("unknown_token_program", "R02CAPB_VAULT_TOKEN_PROGRAM_MISMATCH"),
    ],
)
def test_negative_replay_matrix_fails_closed(mutation: str, expected_code: str) -> None:
    values = _values()
    owner = KLEND_PROGRAM_ID
    market = _pk(7)
    if mutation == "bad_discriminator":
        raw = bytearray(_reserve_bytes(values))
        raw[3] ^= 0xFF
        reserve_bytes = bytes(raw)
    elif mutation == "truncated":
        reserve_bytes = _reserve_bytes(values)[: KAMINO_RESERVE_PINNED_PREFIX_LEN - 8]
    elif mutation == "stale_last_update":
        values["last_update_stale"] = (1).to_bytes(1, "little")
        reserve_bytes = _reserve_bytes(values)
    elif mutation == "unknown_config_status":
        values["config_status"] = (2).to_bytes(1, "little")
        reserve_bytes = _reserve_bytes(values)
    elif mutation == "emergency_mode":
        values["config_emergency_mode"] = (1).to_bytes(1, "little")
        reserve_bytes = _reserve_bytes(values)
    elif mutation == "wrong_owner":
        owner = _pk(60)
        reserve_bytes = _reserve_bytes(values)
    elif mutation == "wrong_market":
        market = _pk(61)
        reserve_bytes = _reserve_bytes(values)
    elif mutation == "zero_mint":
        values["liquidity_mint"] = bytes(32)
        reserve_bytes = _reserve_bytes(values)
    else:
        values["liquidity_token_program"] = bytes(_pk(55))
        reserve_bytes = _reserve_bytes(values)
    with pytest.raises(KaminoCapacityReaderError, match=expected_code):
        decode_kamino_reserve(reserve_bytes, owner=owner, lending_market=market)


def test_unrooted_observation_never_claims_chain_position() -> None:
    observation, _ = _observation()
    record = observation.evidence_record()
    assert record["observation"]["slot"] is None
    assert record["observation"]["slot_rooted"] is False
    assert record["observation"]["slot_provenance"] == "OFFLINE_FIXTURE_NOT_ROOTED"
    blockers = set(record["observation"]["blockers"])
    assert blockers == {
        KaminoCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
        KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value,
    }
    assert READER_EXECUTION_AUTHORITY == "NONE"
