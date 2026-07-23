#!/usr/bin/env python3
"""Independently verify PR-205 asymmetric release qualification evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
EXIT_BLOCKED = 3
EXIT_ERROR = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--run", required=True, help="relative run JSON path")
    parser.add_argument("--claim", required=True, help="relative claim JSON path")
    parser.add_argument("--claim-envelope", required=True)
    parser.add_argument("--profile-policy", required=True)
    parser.add_argument("--profile-policy-envelope", required=True)
    parser.add_argument("--trust-registry", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--policy-bundle-hash", required=True)
    parser.add_argument("--release-digest", required=True)
    parser.add_argument("--evaluated-at", default=None)
    parser.add_argument("--output", default=None)
    return parser


def _write(payload: dict[str, object], output: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        from src.release_gate.asymmetric_qualification import (
            profile_policy_from_dict,
            read_json_object_under_root,
            release_claim_from_dict,
            signed_envelope_from_dict,
            trust_registry_from_dict,
            verify_asymmetric_qualification,
        )

        artifact_root = Path(args.artifact_root)
        run_payload = read_json_object_under_root(artifact_root, args.run)
        claim = release_claim_from_dict(
            read_json_object_under_root(artifact_root, args.claim)
        )
        claim_envelope = signed_envelope_from_dict(
            read_json_object_under_root(artifact_root, args.claim_envelope)
        )
        profile_policy = profile_policy_from_dict(
            read_json_object_under_root(artifact_root, args.profile_policy)
        )
        profile_policy_envelope = signed_envelope_from_dict(
            read_json_object_under_root(artifact_root, args.profile_policy_envelope)
        )
        trust_registry = trust_registry_from_dict(
            read_json_object_under_root(artifact_root, args.trust_registry)
        )
        evaluated_at = (
            datetime.fromisoformat(args.evaluated_at)
            if args.evaluated_at
            else datetime.now(timezone.utc)
        )
        result = verify_asymmetric_qualification(
            run_payload=run_payload,
            claim=claim,
            claim_envelope=claim_envelope,
            profile_policy=profile_policy,
            profile_policy_envelope=profile_policy_envelope,
            trust_registry=trust_registry,
            evaluated_at=evaluated_at,
            expected_environment=args.environment,
            expected_source_commit=args.source_commit,
            expected_policy_bundle_hash=args.policy_bundle_hash,
            expected_release_digest=args.release_digest,
        )
        _write(result.to_dict(), args.output)
        return 0 if result.release_claim_allowed else EXIT_BLOCKED
    except (OSError, TypeError, ValueError) as exc:
        _write(
            {
                "schema_version": "pr205.asymmetric-release-verification-error.v1",
                "release_claim_allowed": False,
                "error_type": type(exc).__name__,
                "reason": str(exc),
            },
            args.output,
        )
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
