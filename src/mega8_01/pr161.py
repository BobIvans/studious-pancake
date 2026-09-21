"""PR-161 / NF-393..396: adversarial data-plane integrity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, require_non_negative_int, require_positive_int, require_text, sorted_unique


def validate_stream_payload_limits(
    source_id: str,
    body_bytes: int,
    json_depth: int,
    json_nodes: int,
    max_body_bytes: int,
    max_json_depth: int,
    max_json_nodes: int,
):
    source = require_text(source_id, "source_id")
    observed = (
        require_non_negative_int(body_bytes, "body_bytes"),
        require_non_negative_int(json_depth, "json_depth"),
        require_non_negative_int(json_nodes, "json_nodes"),
    )
    limits = (
        require_positive_int(max_body_bytes, "max_body_bytes"),
        require_positive_int(max_json_depth, "max_json_depth"),
        require_positive_int(max_json_nodes, "max_json_nodes"),
    )
    exceeded = any(value > limit for value, limit in zip(observed, limits, strict=True))
    payload = {"observed": observed, "limits": limits}
    if exceeded:
        return fail_closed(
            child="PR-161",
            nf="NF-393",
            action="validate_stream_payload_limits",
            subject_id=source,
            reason="MALFORMED_INPUT",
            payload=payload,
        )
    return artifact(
        child="PR-161",
        nf="NF-393",
        action="validate_stream_payload_limits",
        subject_id=source,
        payload=payload,
    )


def detect_data_poisoning_pattern(
    source_id: str,
    deviation_bps: int,
    repeated_identity_count: int,
    maximum_deviation_bps: int,
    maximum_repeat_count: int,
):
    source = require_text(source_id, "source_id")
    deviation = require_non_negative_int(deviation_bps, "deviation_bps")
    repeats = require_non_negative_int(repeated_identity_count, "repeated_identity_count")
    max_deviation = require_non_negative_int(maximum_deviation_bps, "maximum_deviation_bps")
    max_repeats = require_non_negative_int(maximum_repeat_count, "maximum_repeat_count")
    poisoned = deviation > max_deviation or repeats > max_repeats
    payload = {
        "deviation_bps": deviation,
        "repeated_identity_count": repeats,
        "poisoning_indicator": poisoned,
    }
    if poisoned:
        return fail_closed(
            child="PR-161",
            nf="NF-394",
            action="detect_data_poisoning_pattern",
            subject_id=source,
            reason="QUARANTINED_SOURCE",
            payload=payload,
        )
    return artifact(
        child="PR-161",
        nf="NF-394",
        action="detect_data_poisoning_pattern",
        subject_id=source,
        payload=payload,
    )


def quarantine_malformed_source(
    source_id: str,
    reason_codes: Sequence[str],
):
    source = require_text(source_id, "source_id")
    reasons = sorted_unique(reason_codes)
    if not reasons:
        return artifact(
            child="PR-161",
            nf="NF-395",
            action="quarantine_malformed_source",
            subject_id=source,
            payload={"quarantined": False, "reason_codes": ()},
        )
    return fail_closed(
        child="PR-161",
        nf="NF-395",
        action="quarantine_malformed_source",
        subject_id=source,
        reason="QUARANTINED_SOURCE",
        payload={"quarantined": True, "reason_codes": reasons},
    )


def replay_adversarial_ingest_suite(
    suite_id: str,
    case_results: Mapping[str, bool],
):
    sid = require_text(suite_id, "suite_id")
    checked = {
        require_text(case_id, "case_id"): bool(passed)
        for case_id, passed in case_results.items()
    }
    failed = tuple(sorted(case_id for case_id, passed in checked.items() if not passed))
    if not checked or failed:
        return fail_closed(
            child="PR-161",
            nf="NF-396",
            action="replay_adversarial_ingest_suite",
            subject_id=sid,
            reason="INSUFFICIENT_EVIDENCE",
            payload={"case_count": len(checked), "failed_cases": failed},
        )
    return artifact(
        child="PR-161",
        nf="NF-396",
        action="replay_adversarial_ingest_suite",
        subject_id=sid,
        payload={"case_count": len(checked), "failed_cases": ()},
    )
