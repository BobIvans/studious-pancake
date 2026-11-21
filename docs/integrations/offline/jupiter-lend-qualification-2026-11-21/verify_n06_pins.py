"""Deterministic offline verification of the N06 Jupiter Lend dossier.

No upstream bytes are vendored (BSL-1.1 / no-license upstreams), so this
checks the pinned fact set that the owner module carries, with zero network
access:
1. the pinned IDL blob hashes still equal the module constants;
2. the UserBorrowPosition offset arithmetic closes on 112 bytes (packed);
3. the exact flashloan fee vectors reproduce (ceil scale 1e4, max 50,
   min amount 1000);
4. the gap list carries exactly the pinned cleared/remaining split.

Run: python verify_n06_pins.py   (exit 0 == all pins verified)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
REPO = DOSSIER.parents[3]
sys.path.insert(0, str(REPO))

from src.lending.jupiter_lend import (  # noqa: E402
    JUPITER_FLASHLOAN_FEE_MAX,
    JUPITER_FLASHLOAN_FEE_SCALE,
    JUPITER_FLASHLOAN_MIN_AMOUNT,
    JUPITER_LEND_FLASHLOAN_IDL_BLOB,
    JUPITER_LEND_LIQUIDITY_IDL_BLOB,
    JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT,
    JUPITER_TOKEN_DECIMALS_MAX,
    JUPITER_TOKEN_DECIMALS_MIN,
    JUPITER_UBP_DEBT_CEILING_OFFSET,
    JUPITER_UBP_MAX_DEBT_CEILING_OFFSET,
    JUPITER_UBP_STATUS_OFFSET,
    JUPITER_USER_BORROW_POSITION_LEN,
    _UNPINNED_CAPACITY_GAPS,
    calculate_jupiter_flashloan_fee,
)
from solders.pubkey import Pubkey  # noqa: E402


def check_blob_pins(manifest: dict) -> list[str]:
    failures = []
    base = manifest["qualification_base"]
    if base["flashloan_idl_blob"] != JUPITER_LEND_FLASHLOAN_IDL_BLOB:
        failures.append("flashloan IDL blob pin mismatch")
    if base["liquidity_idl_blob"] != JUPITER_LEND_LIQUIDITY_IDL_BLOB:
        failures.append("liquidity IDL blob pin mismatch")
    if base["program_source_commit"] != "626b177f235224bc5d074d39439cd2558f542886":
        failures.append("program source commit pin mismatch")
    return failures


def check_position_layout() -> list[str]:
    failures = []
    # packed layout: every field abuts the previous one
    expected_last = JUPITER_UBP_STATUS_OFFSET
    if JUPITER_UBP_MAX_DEBT_CEILING_OFFSET + 8 != JUPITER_UBP_STATUS_OFFSET:
        failures.append("max_debt_ceiling/status abutment broken")
    if expected_last != 111 or JUPITER_USER_BORROW_POSITION_LEN != 112:
        failures.append("UserBorrowPosition total length mismatch")
    if JUPITER_UBP_DEBT_CEILING_OFFSET != 73:
        failures.append("debt ceiling offset mismatch")
    return failures


def check_fee_vectors() -> list[str]:
    failures = []
    vectors = (
        (1_000_000, 5, 500),
        (1_000_000, 50, 5_000),
        (1_000_003, 5, 501),  # ceil: 500.0015 -> 501
        (1_000, 0, 0),
    )
    for amount, fee_raw, expected in vectors:
        got = calculate_jupiter_flashloan_fee(amount, fee_raw)
        if got != expected:
            failures.append(
                f"fee vector {amount}/{fee_raw}: got {got}, want {expected}"
            )
    for amount, fee_raw in ((999, 0), (1_000, JUPITER_FLASHLOAN_FEE_MAX + 1), (0, 0)):
        try:
            calculate_jupiter_flashloan_fee(amount, fee_raw)
            failures.append(f"fee({amount},{fee_raw}) did not fail closed")
        except Exception:
            pass
    return failures


def check_gap_split() -> list[str]:
    cleared = {
        "UTILIZATION_SCALE_UNPINNED",
        "FLASH_BORROW_POSITION_DEBT_CEILING_UNDECODED",
        "FEE_ROUNDING_RULE_UNPINNED",
    }
    failures = []
    for gap in cleared:
        if gap in _UNPINNED_CAPACITY_GAPS:
            failures.append(f"cleared gap {gap} still present")
    for gap in (
        "MAX_UTILIZATION_SEMANTICS_UNPINNED",
        "EXCHANGE_PRICE_VALUATION_UNAUDITED",
        "TOTAL_CLAIM_SEMANTICS_UNPINNED",
        "VAULT_AUTHORITY_BINDING_UNPROVEN",
        "MIN_OPERATE_AMOUNT_ENFORCEMENT_UNPINNED",
        "FLASH_BORROW_POSITION_STATUS_SEMANTICS_UNPINNED",
    ):
        if gap not in _UNPINNED_CAPACITY_GAPS:
            failures.append(f"remaining gap {gap} missing")
    if JUPITER_FLASHLOAN_FEE_SCALE != 10_000 or JUPITER_FLASHLOAN_FEE_MAX != 50:
        failures.append("fee scale/max pins mismatch")
    if (JUPITER_TOKEN_DECIMALS_MIN, JUPITER_TOKEN_DECIMALS_MAX) != (2, 9):
        failures.append("token decimals bounds mismatch")
    return failures


def main() -> int:
    manifest = json.loads(
        (DOSSIER / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    failures = []
    failures += check_blob_pins(manifest)
    failures += check_position_layout()
    failures += check_fee_vectors()
    failures += check_gap_split()
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(
        "N06_VERIFY_OK blob_pins=matched position_layout=closed "
        "fee_vectors=reproduced gaps=coherent rule=U128_MUL_DIV_CEIL_SCALE_1E4_MAX_50"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
