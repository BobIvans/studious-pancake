#!/usr/bin/env python3
"""Verify the MPR-CLOSE-05 isolated signer authorization boundary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_05_isolated_signer_jito_canary import (  # noqa: E402
    NonceReplayCache,
    authorize_exact_message,
    evaluate_mpr_close_05_evidence,
    sample_ready_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="fail when the boundary is not ready")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    evidence = sample_ready_evidence(canary_requested=False)
    report = evaluate_mpr_close_05_evidence(evidence)
    replay_cache = NonceReplayCache()
    auth_result = "passed"
    try:
        authorize_exact_message(
            evidence.signer,
            message_bytes=b"not-the-fixture-message",
            replay_cache=replay_cache,
            now_ns=200,
        )
        auth_result = "failed_open"
    except ValueError:
        auth_result = "fail_closed_on_mutation"

    payload = {
        "schema_version": report.schema_version,
        "state": report.state.value,
        "blockers": [blocker.__dict__ for blocker in report.blockers],
        "signer_allowed": report.signer_allowed,
        "sender_allowed": report.sender_allowed,
        "unrestricted_live_available": report.unrestricted_live_available,
        "bounded_canary_default_off": report.bounded_canary_default_off,
        "exact_message_mutation_check": auth_result,
        "evidence_hash": report.evidence_hash,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-CLOSE-05 isolated signer boundary: {payload['state']}")

    failed_open = auth_result != "fail_closed_on_mutation"
    if args.strict and (report.blockers or failed_open or report.signer_allowed):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
