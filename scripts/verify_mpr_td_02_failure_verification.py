#!/usr/bin/env python3
"""Verify the canonical failure, retry, deadline, and cancellation contract."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.errors import (  # noqa: E402
    Ambiguity,
    ErrorEnvelope,
    FailureCategory,
    ResultState,
    UnknownReasonCode,
    reason,
)
from src.errors.deadline import Deadline  # noqa: E402
from src.errors.retry import decide  # noqa: E402
from src.errors.supervision import supervise  # noqa: E402


async def _cancellation_propagates() -> bool:
    async def cancelled() -> None:
        raise asyncio.CancelledError

    try:
        await supervise(cancelled(), correlation_id="c", operation_id="o")
    except asyncio.CancelledError:
        return True
    return False


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    registry = json.loads(
        (ROOT / "src/resources/reason_code_registry.json").read_text(encoding="utf-8")
    )
    codes = [str(item["reason_code"]) for item in registry.get("reason_codes", [])]
    if not codes or len(codes) != len(set(codes)):
        errors.append("reason-code registry is empty or contains duplicates")
    exercised_codes: list[str] = []
    for index, code in enumerate(codes):
        definition = reason(code)
        try:
            payload = ErrorEnvelope(
                code,
                f"correlation-{index}",
                f"operation-{index}",
            ).to_dict()
            json.dumps(payload, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            errors.append(f"reason code {code} failed envelope serialization: {exc}")
            continue
        if payload["reason_code"] != code:
            errors.append(f"reason code {code} serialized as another code")
            continue
        if payload["category"] != definition.category.value:
            errors.append(f"reason code {code} serialized with wrong category")
            continue
        exercised_codes.append(code)
    if len(exercised_codes) != len(codes):
        errors.append("not every reason code crossed the envelope boundary")
    try:
        reason("UNREGISTERED_REASON")
    except UnknownReasonCode:
        unknown_rejected = True
    else:
        unknown_rejected = False
        errors.append("unknown reason code was accepted")
    envelope = ErrorEnvelope(
        "PROVIDER_TRANSIENT_TIMEOUT",
        "correlation",
        "operation",
        safe_context={"provider_id": "fixture"},
    )
    if "exception" in json.dumps(envelope.to_dict()).lower():
        errors.append("safe envelope exposed raw exception material")
    retry = decide(
        operation_class="safe_read",
        category=FailureCategory.PROVIDER_TRANSIENT,
        attempt=0,
        remaining_seconds=1.0,
    )
    ambiguous = decide(
        operation_class="non_idempotent_submission",
        category=FailureCategory.PROVIDER_TRANSIENT,
        attempt=0,
        remaining_seconds=1.0,
        ambiguity=Ambiguity.POSSIBLE_EFFECT,
    )
    if not retry.allowed:
        errors.append("safe typed transient read was not retryable")
    if ambiguous.allowed or ambiguous.terminal_state != "ambiguous":
        errors.append("ambiguous non-idempotent effect was retryable")
    clock_value = [10.0]
    deadline = Deadline.after(5.0, clock=lambda: clock_value[0])
    child = deadline.child(20.0)
    if child.expires_at > deadline.expires_at:
        errors.append("child deadline extended parent budget")
    cancellation = asyncio.run(_cancellation_propagates())
    if not cancellation:
        errors.append("cancellation was swallowed")
    required_manifests = (
        "config/broad_exception_boundary_allowlist.json",
        "config/cancellation_shield_allowlist.json",
        "config/verification_invariant_manifest.json",
        "config/verification_profiles.json",
        "config/fuzz_targets.json",
        "config/mutation_policy.json",
        "config/flake_detection_policy.json",
    )
    missing = [path for path in required_manifests if not (ROOT / path).is_file()]
    if missing:
        errors.append(f"missing verification manifests: {missing!r}")
    return {
        "schema_version": "mpr-td-02.failure-verification-evidence.v1",
        "accepted": not errors,
        "active_reason_code_count": len(codes),
        "exercised_reason_code_count": len(exercised_codes),
        "exercised_reason_codes": exercised_codes,
        "unknown_reason_code_rejected": unknown_rejected,
        "typed_retry_allowed": retry.allowed,
        "ambiguous_retry_denied": not ambiguous.allowed,
        "cancellation_propagates": cancellation,
        "sender_free": True,
        "production_ready": False,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    evidence = build_evidence()
    print(
        json.dumps(evidence, indent=2, sort_keys=True)
        if args.as_json
        else ("PASS" if evidence["accepted"] else "FAIL")
    )
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
