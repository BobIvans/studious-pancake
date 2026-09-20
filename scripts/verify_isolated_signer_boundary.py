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
    deployment_dir = ROOT / "deployment" / "signer"
    attestation = json.loads(
        (deployment_dir / "artifact-attestation.json").read_text(encoding="utf-8")
    )
    capabilities = json.loads(
        (deployment_dir / "capabilities.json").read_text(encoding="utf-8")
    )
    deployment_blockers = []
    if attestation["base_image_digest"] is None:
        deployment_blockers.append("SIGNER_BASE_IMAGE_DIGEST_MISSING")
    if attestation["artifact_digest"] is None:
        deployment_blockers.append("SIGNER_IMAGE_DIGEST_MISSING")
    if attestation["artifact_signature"] is None:
        deployment_blockers.append("SIGNER_IMAGE_SIGNATURE_MISSING")
    if attestation["isolated_keystore_attestation"] is None:
        deployment_blockers.append("ISOLATED_KEYSTORE_ATTESTATION_MISSING")
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
        "state": "blocked" if deployment_blockers else report.state.value,
        "blockers": [blocker.__dict__ for blocker in report.blockers]
        + [
            {"code": code, "message": "materialized external evidence is absent"}
            for code in deployment_blockers
        ],
        "signer_allowed": report.signer_allowed,
        "sender_allowed": report.sender_allowed,
        "unrestricted_live_available": report.unrestricted_live_available,
        "bounded_canary_default_off": report.bounded_canary_default_off,
        "exact_message_mutation_check": auth_result,
        "evidence_hash": report.evidence_hash,
        "artifact_attestation_blocker": attestation["blocker"],
        "artifact_signed": attestation["artifact_signature"] is not None,
        "isolated_keystore_attested": (
            attestation["isolated_keystore_attestation"] is not None
        ),
        "signer_status_only": capabilities["status_only"],
        "network_egress": capabilities["network_egress"],
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"MPR-CLOSE-05 isolated signer boundary: {payload['state']}")

    failed_open = auth_result != "fail_closed_on_mutation"
    unsafe_deployment = any(
        (
            attestation["signer_allowed"],
            attestation["canary_allowed"],
            not capabilities["status_only"],
            bool(capabilities["network_egress"]),
            capabilities["private_key_loader"],
        )
    )
    if args.strict and (
        report.blockers or failed_open or report.signer_allowed or unsafe_deployment
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
