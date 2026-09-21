"""PR-151 / NF-353..356: current-head delta qualification."""

from __future__ import annotations

from collections.abc import Sequence

from .common import artifact, fail_closed, require_git_sha, require_non_negative_int, sorted_unique


def capture_head_delta(
    base_sha: str,
    current_sha: str,
    changed_paths: Sequence[str],
    observed_at_ms: int,
    validity_ms: int,
):
    base = require_git_sha(base_sha, "base_sha")
    current = require_git_sha(current_sha, "current_sha")
    observed = require_non_negative_int(observed_at_ms, "observed_at_ms")
    validity = require_non_negative_int(validity_ms, "validity_ms")
    paths = sorted_unique(changed_paths)
    return artifact(
        child="PR-151",
        nf="NF-353",
        action="capture_head_delta",
        subject_id=current,
        payload={"base_sha": base, "current_sha": current, "changed_paths": paths},
        valid_from_ms=observed,
        valid_until_ms=observed + validity,
    )


def invalidate_stale_evidence(
    evidence_head_sha: str,
    current_head_sha: str,
    evidence_valid_until_ms: int,
    now_ms: int,
):
    evidence_head = require_git_sha(evidence_head_sha, "evidence_head_sha")
    current = require_git_sha(current_head_sha, "current_head_sha")
    valid_until = require_non_negative_int(evidence_valid_until_ms, "evidence_valid_until_ms")
    now = require_non_negative_int(now_ms, "now_ms")
    stale = evidence_head != current or now > valid_until
    if stale:
        return fail_closed(
            child="PR-151",
            nf="NF-354",
            action="invalidate_stale_evidence",
            subject_id=current,
            reason="STALE_EVIDENCE",
            payload={
                "evidence_head_sha": evidence_head,
                "current_head_sha": current,
                "expired": now > valid_until,
            },
            valid_from_ms=now,
            valid_until_ms=now,
        )
    return artifact(
        child="PR-151",
        nf="NF-354",
        action="invalidate_stale_evidence",
        subject_id=current,
        payload={"evidence_head_sha": evidence_head, "expired": False},
        valid_from_ms=now,
        valid_until_ms=valid_until,
    )


def replay_impacted_qualifications(
    delta_hash: str,
    qualification_ids: Sequence[str],
    impacted_paths: Sequence[str],
):
    qualifications = sorted_unique(qualification_ids)
    paths = sorted_unique(impacted_paths)
    return artifact(
        child="PR-151",
        nf="NF-355",
        action="replay_impacted_qualifications",
        subject_id=delta_hash,
        payload={"qualification_ids": qualifications, "impacted_paths": paths},
    )


def publish_delta_qualification(
    head_sha: str,
    replay_hashes: Sequence[str],
    unresolved_blockers: Sequence[str],
):
    head = require_git_sha(head_sha, "head_sha")
    replays = sorted_unique(replay_hashes)
    blockers = sorted_unique(unresolved_blockers)
    if blockers:
        return fail_closed(
            child="PR-151",
            nf="NF-356",
            action="publish_delta_qualification",
            subject_id=head,
            reason="INSUFFICIENT_EVIDENCE",
            payload={"replay_hashes": replays, "blockers": blockers},
        )
    return artifact(
        child="PR-151",
        nf="NF-356",
        action="publish_delta_qualification",
        subject_id=head,
        payload={"replay_hashes": replays, "blockers": ()},
    )
