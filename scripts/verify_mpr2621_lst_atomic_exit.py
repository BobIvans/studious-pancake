#!/usr/bin/env python3
"""Static/focused verifier for MPR-2621's sender-free LST authority."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr2621_lst_atomic_exit import IMMEDIATE_SOL_EXIT_MECHANISMS, Mechanism


BANNED_REACHABILITY = (
    "aiohttp",
    "Keypair",
    "jito",
    "sendTransaction",
    "send_raw_transaction",
    "send_bundle",
    "lst_unstake_arbitrage",
    "lst_route_aggregator",
)


def main() -> int:
    module = ROOT / "src" / "mpr2621_lst_atomic_exit.py"
    tests = ROOT / "tests" / "test_mpr2621_lst_atomic_exit.py"
    legacy = ROOT / "src" / "ingest" / "lst_unstake_arbitrage.py"
    source = module.read_text(encoding="utf-8")
    blockers: list[str] = []

    for token in BANNED_REACHABILITY:
        if token in source:
            blockers.append(f"BANNED_QUALIFIED_REACHABILITY:{token}")

    delayed = {
        Mechanism.STAKE_ACCOUNT_WITHDRAW,
        Mechanism.STAKE_ACCOUNT_DEACTIVATION,
        Mechanism.LST_TO_LST_POOL_SWAP,
        Mechanism.PROTOCOL_DEPOSIT_SOL_FOR_LST,
    }
    if delayed.intersection(IMMEDIATE_SOL_EXIT_MECHANISMS):
        blockers.append("DELAYED_OR_NON_EXIT_MECHANISM_MARKED_IMMEDIATE")

    if not tests.is_file():
        blockers.append("FOCUSED_TESTS_MISSING")
    if not legacy.is_file():
        blockers.append("LEGACY_INVENTORY_MISSING")

    payload = {
        "schema_version": "mpr-2621.verification.v1",
        "accepted_main_baseline": "d23f82e20d10345926742352739b1a6ca3f7a859",
        "mpr2620_status": "RESERVED_PREDECESSOR_UNOBSERVED",
        "mpr2621_status": "NEW_PROPOSED_EXTENSION",
        "legacy_lst_executor_reused": False,
        "circular_arbitrage_profile_modified": False,
        "liquidation_profile_modified": False,
        "sender_allowed": False,
        "signer_allowed": False,
        "live_enabled": False,
        "auto_merge_allowed": False,
        "immediate_exit_mechanisms": sorted(item.value for item in IMMEDIATE_SOL_EXIT_MECHANISMS),
        "blockers": sorted(blockers),
        "verified_offline": not blockers,
        "real_shadow_qualified": False,
        "canary_eligible": False,
        "production_qualified": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
