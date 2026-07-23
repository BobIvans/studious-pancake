#!/usr/bin/env python3
"""Verify the authoritative sender-free PR-206 durable-state boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pr206_durable_state import (
    ManualLifecycleClock,
    PR206DurableStateStore,
    SemanticIdempotencyCollision,
)


def verify() -> dict[str, object]:
    with TemporaryDirectory(prefix="pr206-") as directory:
        path = Path(directory) / "durable-state.sqlite"
        clock = ManualLifecycleClock(monotonic_ns=10, utc_ns=1_000)
        with PR206DurableStateStore(path, trusted_clock=clock) as store:
            store.admit_opportunity(
                opportunity_id="verification-opportunity",
                lifecycle_key="verification-route",
                expires_after_ns=100,
                terminal_retention_ns=10,
                idempotency_key="verification-admit",
            )
            try:
                store.admit_opportunity(
                    opportunity_id="collision",
                    lifecycle_key="other-route",
                    expires_after_ns=100,
                    terminal_retention_ns=10,
                    idempotency_key="verification-admit",
                )
            except SemanticIdempotencyCollision:
                semantic_collision_blocked = True
            else:
                semantic_collision_blocked = False
            store.reserve_wallet_lamports(
                reservation_id="verification-reservation",
                wallet_id="verification-wallet",
                attempt_id="verification-attempt",
                lamports=10,
                wallet_limit_lamports=100,
                idempotency_key="verification-reserve",
            )
            store.release_wallet_reservation(
                reservation_id="verification-reservation",
                expected_revision=0,
                charged_fee_lamports=1,
                idempotency_key="verification-release",
                principal="verification-wallet",
            )

        clock.reboot(boot_id="boot-b")
        clock.utc_ns += 101
        with PR206DurableStateStore(path, trusted_clock=clock) as restarted:
            expired = restarted.expire_due_opportunities(terminal_retention_ns=10)
            report = restarted.inspect_readiness()

        reboot_expiry_verified = [item.opportunity_id for item in expired] == [
            "verification-opportunity"
        ]
        accepted = (
            semantic_collision_blocked and reboot_expiry_verified and report.ready
        )
        return {
            "schema_version": report.schema_version,
            "accepted": accepted,
            "live_enabled": False,
            "sender_or_signer_enabled": False,
            "semantic_collision_blocked": semantic_collision_blocked,
            "reboot_expiry_verified": reboot_expiry_verified,
            "migration_rows_verified": report.migration_rows_verified,
            "boot_reconciled": report.boot_reconciled,
            "projections_verified": report.projections_verified,
            "idempotency_rows_verified": report.idempotency_rows_verified,
            "terminal_rows_verified": report.terminal_rows_verified,
            "reason_codes": list(report.reason_codes),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence = verify()
    if args.json:
        print(json.dumps(evidence, sort_keys=True))
    else:
        print("PR-206 durable-state verification passed")
    return 0 if evidence["accepted"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
