"""PR-156 / NF-373..376: calibrated time and timestamp uncertainty."""

from __future__ import annotations

from collections.abc import Sequence

from .common import artifact, fail_closed, require_non_negative_int, require_text


def calibrate_monotonic_clock(
    clock_id: str,
    wall_elapsed_ms: int,
    monotonic_elapsed_ms: int,
    max_error_ms: int,
):
    cid = require_text(clock_id, "clock_id")
    wall = require_non_negative_int(wall_elapsed_ms, "wall_elapsed_ms")
    mono = require_non_negative_int(monotonic_elapsed_ms, "monotonic_elapsed_ms")
    max_error = require_non_negative_int(max_error_ms, "max_error_ms")
    error = abs(wall - mono)
    if error > max_error:
        return fail_closed(
            child="PR-156",
            nf="NF-373",
            action="calibrate_monotonic_clock",
            subject_id=cid,
            reason="TEMPORALLY_AMBIGUOUS",
            payload={"clock_error_ms": error, "max_error_ms": max_error},
        )
    return artifact(
        child="PR-156",
        nf="NF-373",
        action="calibrate_monotonic_clock",
        subject_id=cid,
        payload={"clock_error_ms": error, "max_error_ms": max_error},
    )


def estimate_source_latency(
    source_id: str,
    source_time_ms: int,
    receive_time_ms: int,
    available_time_ms: int,
):
    source = require_text(source_id, "source_id")
    source_time = require_non_negative_int(source_time_ms, "source_time_ms")
    receive_time = require_non_negative_int(receive_time_ms, "receive_time_ms")
    available_time = require_non_negative_int(available_time_ms, "available_time_ms")
    if source_time > receive_time or receive_time > available_time:
        return fail_closed(
            child="PR-156",
            nf="NF-374",
            action="estimate_source_latency",
            subject_id=source,
            reason="TEMPORALLY_AMBIGUOUS",
            payload={
                "source_time_ms": source_time,
                "receive_time_ms": receive_time,
                "available_time_ms": available_time,
            },
        )
    return artifact(
        child="PR-156",
        nf="NF-374",
        action="estimate_source_latency",
        subject_id=source,
        payload={
            "source_to_receive_ms": receive_time - source_time,
            "receive_to_available_ms": available_time - receive_time,
            "source_to_available_ms": available_time - source_time,
        },
    )


def propagate_timestamp_uncertainty(
    frame_id: str,
    uncertainty_components_ms: Sequence[int],
):
    fid = require_text(frame_id, "frame_id")
    components = tuple(
        require_non_negative_int(value, "uncertainty_ms")
        for value in uncertainty_components_ms
    )
    total = sum(components)
    return artifact(
        child="PR-156",
        nf="NF-375",
        action="propagate_timestamp_uncertainty",
        subject_id=fid,
        payload={"components_ms": components, "total_uncertainty_ms": total},
    )


def reject_temporally_ambiguous_frame(
    frame_id: str,
    total_uncertainty_ms: int,
    maximum_uncertainty_ms: int,
):
    fid = require_text(frame_id, "frame_id")
    total = require_non_negative_int(total_uncertainty_ms, "total_uncertainty_ms")
    maximum = require_non_negative_int(maximum_uncertainty_ms, "maximum_uncertainty_ms")
    if total > maximum:
        return fail_closed(
            child="PR-156",
            nf="NF-376",
            action="reject_temporally_ambiguous_frame",
            subject_id=fid,
            reason="TEMPORALLY_AMBIGUOUS",
            payload={"total_uncertainty_ms": total, "maximum_uncertainty_ms": maximum},
        )
    return artifact(
        child="PR-156",
        nf="NF-376",
        action="reject_temporally_ambiguous_frame",
        subject_id=fid,
        payload={"total_uncertainty_ms": total, "maximum_uncertainty_ms": maximum},
    )
