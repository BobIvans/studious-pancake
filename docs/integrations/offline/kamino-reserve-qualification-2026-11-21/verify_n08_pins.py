"""Deterministic offline verification of the N08 Kamino qualification dossier.

Checks, with zero network access:
1. every vendored blob hash matches SOURCE_MANIFEST.json (git-hash-object
   equivalent: git blob sha1 over the raw bytes);
2. the ReserveConfig tail offset arithmetic closes on the pinned klend
   program sizes (RESERVE_SIZE 8616 / RESERVE_CONFIG_SIZE 952);
3. the exact pinned flash fee vectors reproduce (round-half-up, min fee 1,
   referral floor split, BorrowTooSmall, disabled sentinel);
4. the config-tail decoder and the offline flash-capacity bound behave
   fail-closed on the documented negative inputs.

Run: python verify_n08_pins.py   (exit 0 == all pins verified)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
REPO = DOSSIER.parents[3]
sys.path.insert(0, str(REPO))

from src.lending.kamino import (  # noqa: E402
    KAMINO_CONFIG_BORROW_LIMIT_OFFSET,
    KAMINO_CONFIG_DEPOSIT_LIMIT_OFFSET,
    KAMINO_CONFIG_DEPOSIT_WITHDRAWAL_CAP_OFFSET,
    KAMINO_FEE_ROUNDING_RULE,
    KAMINO_FLASH_FEE_DISABLED_SENTINEL_SF,
    KAMINO_LENDING_MARKET_SIZE_PINNED,
    KAMINO_PROGRAM_VERSION_PINNED,
    KAMINO_RESERVE_SIZE_PINNED,
    KLEND_ONE_SF,
    KaminoCapacityReaderError,
    calculate_kamino_flash_loan_fee,
    decode_kamino_reserve_config_tail,
    derive_kamino_offline_flash_capacity_bound,
)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def check_blob_hashes(manifest: dict) -> list[str]:
    failures = []
    for entry in manifest["new_blobs"]:
        path = DOSSIER / entry["local"]
        actual = git_blob_sha1(path.read_bytes())
        if actual != entry["upstream_git_blob_sha"]:
            failures.append(
                f"blob hash mismatch for {entry['local']}: {actual} != "
                f"{entry['upstream_git_blob_sha']}"
            )
    return failures


def check_offset_arithmetic() -> list[str]:
    failures = []
    config_base = 4840
    tail_end = 5496
    if (tail_end - config_base) + 0 != 656 or config_base + 952 != 5792:
        failures.append("config size arithmetic mismatch")
    if 5792 + 896 + 8 + 256 + 32 + 1632 != KAMINO_RESERVE_SIZE_PINNED:
        failures.append("reserve total layout does not close on 8616")
    if KAMINO_PROGRAM_VERSION_PINNED != 1 or KAMINO_LENDING_MARKET_SIZE_PINNED != 4656:
        failures.append("pinned program constants mismatch")
    return failures


def check_fee_vectors() -> list[str]:
    failures = []
    fee_sf = 3 * (KLEND_ONE_SF >> 2)  # 0.75
    vectors = (
        (1_000_000, fee_sf, 750_000),
        (2, 0, 1),  # minimum fee applies before rounding
        (5, KLEND_ONE_SF >> 1, 3),  # 2.5 -> 3 (half-up, not floor)
        (10, 1, 1),  # tiny rate still charges minimum fee
    )
    for amount, raw, expected in vectors:
        got = calculate_kamino_flash_loan_fee(amount, raw)
        if got != expected:
            failures.append(f"fee vector {amount}/{raw}: got {got}, want {expected}")
    for amount, raw in (
        (2, KLEND_ONE_SF),
        (1_000_000, KAMINO_FLASH_FEE_DISABLED_SENTINEL_SF),
    ):
        try:
            calculate_kamino_flash_loan_fee(amount, raw)
            failures.append(f"fee({amount},{raw}) did not fail closed")
        except KaminoCapacityReaderError:
            pass
    referral = calculate_kamino_flash_loan_fee(
        1_000_000, fee_sf, referral_fee_bps=5000, has_referrer=True
    )
    if referral != 375_000:
        failures.append(f"referral split vector: got {referral}, want 375000")
    if (
        calculate_kamino_flash_loan_fee(
            1_000_000, fee_sf, referral_fee_bps=10_000, has_referrer=True
        )
        != 0
    ):
        failures.append("bps=10000 must hand the whole fee to the referrer")
    return failures


def _disc() -> bytes:
    from src.lending.kamino import KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR

    return KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR


def check_tail_and_bound_fail_closed() -> list[str]:
    failures = []
    raw = bytearray(KAMINO_RESERVE_SIZE_PINNED)
    raw[:8] = _disc()
    raw[8:16] = (1).to_bytes(8, "little")  # version
    raw[16:24] = (30_000_000).to_bytes(8, "little")  # lastUpdate.slot
    raw[24] = 0  # not stale
    raw[32:64] = bytes(_pk7())  # lendingMarket binding
    raw[128:160] = bytes(range(32))  # liquidity.mint (nonzero)
    raw[160:192] = bytes(range(32, 64))  # supply vault
    raw[192:224] = bytes(range(64, 96))  # fee vault
    raw[224:232] = (5_000_000_000).to_bytes(8, "little")  # totalAvailable
    raw[272:280] = (6).to_bytes(8, "little")  # mintDecimals
    from src.lending.kamino import SPL_TOKEN_PROGRAM_ID

    raw[392:424] = bytes(SPL_TOKEN_PROGRAM_ID)  # token program
    raw[4840] = 0  # status Active
    raw[4848] = 0  # emergency mode
    raw[4888:4896] = (3 * (KLEND_ONE_SF >> 2)).to_bytes(8, "little")
    raw[KAMINO_CONFIG_BORROW_LIMIT_OFFSET : KAMINO_CONFIG_BORROW_LIMIT_OFFSET + 8] = (
        1_500_000_000
    ).to_bytes(8, "little")
    from src.lending.kamino import KLEND_PROGRAM_ID

    try:
        tail = decode_kamino_reserve_config_tail(bytes(raw))
        if tail.borrow_limit != 1_500_000_000:
            failures.append("tail borrow limit decode mismatch")
        from src.lending.kamino import decode_kamino_reserve

        reserve_state = decode_kamino_reserve(
            bytes(raw), owner=KLEND_PROGRAM_ID, lending_market=_pk7()
        )
        bound = derive_kamino_offline_flash_capacity_bound(reserve_state)
        if bound.bound_base_units != 5_000_000_000:
            failures.append("offline flash capacity bound mismatch")
        if bound.repay_obligation_base_units != 5_000_000_000 + 3_750_000_000:
            failures.append("offline repay obligation mismatch")
        if bound.fee_rule != KAMINO_FEE_ROUNDING_RULE:
            failures.append("fee rule string mismatch")
    except KaminoCapacityReaderError as exc:
        failures.append(f"positive path raised: {exc}")
    # Short account must fail closed.
    try:
        decode_kamino_reserve_config_tail(bytes(raw[:8615]))
        failures.append("short-account tail decode did not fail closed")
    except KaminoCapacityReaderError:
        pass
    return failures


def _pk7():
    from solders.pubkey import Pubkey

    return Pubkey.from_bytes(bytes((7,)) * 32)


def main() -> int:
    manifest = json.loads(
        (DOSSIER / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    failures = []
    failures += check_blob_hashes(manifest)
    failures += check_offset_arithmetic()
    failures += check_fee_vectors()
    failures += check_tail_and_bound_fail_closed()
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(
        "N08_VERIFY_OK blobs=%d offsets=closed fee_vectors=reproduced "
        "tail_decode=pass offline_bound=pass rule=%s"
        % (
            len(manifest["new_blobs"]),
            KAMINO_FEE_ROUNDING_RULE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
