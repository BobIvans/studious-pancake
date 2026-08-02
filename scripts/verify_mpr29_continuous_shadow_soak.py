#!/usr/bin/env python3
"""Verify MPR-29 continuous installed paper/shadow soak evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.release_gate.mpr29_continuous_shadow_soak import (  # noqa: E402
    MAX_P95_LATENCY_MS,
    MIN_CYCLE_COUNT,
    MIN_PROVIDER_SNAPSHOT_COUNT,
    MPR29_EVIDENCE_KIND,
    MPR29_ID,
    MPR29_SCHEMA_VERSION,
    bundle_from_mapping,
    evaluate_mpr29_soak,
    signed_artifact_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate MPR-29 default-off continuous soak evidence."
    )
    parser.add_argument(
        "--evidence",
        default=None,
        help="optional JSON evidence bundle to evaluate",
    )
    parser.add_argument(
        "--signed-artifact-output",
        default=None,
        help="optional path to write the MPR-31-compatible signed artifact payload",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _static_contract() -> dict[str, object]:
    return {
        "schema_version": MPR29_SCHEMA_VERSION,
        "mpr_id": MPR29_ID,
        "evidence_kind": MPR29_EVIDENCE_KIND,
        "minimum_cycles": MIN_CYCLE_COUNT,
        "minimum_provider_snapshots": MIN_PROVIDER_SNAPSHOT_COUNT,
        "max_p95_latency_ms": MAX_P95_LATENCY_MS,
        "installed_artifact_required": True,
        "source_checkout_allowed": False,
        "live_enabled": False,
        "signer_loaded": False,
        "sender_loaded": False,
        "production_ready": False,
        "long_soak_manual_or_scheduled": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.evidence:
        payload = _static_contract()
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                "MPR29_CONTINUOUS_SOAK: "
                "contract=default-off installed-artifact-required "
                "live=false signer=false sender=false"
            )
        return 0

    path = Path(args.evidence)
    if not path.is_absolute():
        path = ROOT / path
    bundle = bundle_from_mapping(json.loads(path.read_text(encoding="utf-8")))
    decision = evaluate_mpr29_soak(bundle)
    payload = decision.to_dict()
    if args.signed_artifact_output:
        output = Path(args.signed_artifact_output)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(signed_artifact_payload(bundle), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        payload["signed_artifact_output"] = str(output)
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "MPR29_CONTINUOUS_SOAK: "
            f"accepted={str(decision.accepted).lower()} "
            f"status={decision.status.value} "
            f"reasons={len(decision.reason_codes)} "
            "live=false signer=false sender=false"
        )
    return 0 if decision.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
