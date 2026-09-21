"""PR-155 / NF-369..372: provider consensus and source quarantine."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, require_non_negative_int, require_sha256, require_text


def _checked_samples(samples: Mapping[str, str]) -> dict[str, str]:
    checked: dict[str, str] = {}
    for provider, state_hash in samples.items():
        checked[require_text(provider, "provider")] = require_sha256(
            state_hash, "state_hash"
        )
    return checked


def collect_provider_consensus_sample(
    sample_id: str,
    provider_state_hashes: Mapping[str, str],
):
    sid = require_text(sample_id, "sample_id")
    samples = _checked_samples(provider_state_hashes)
    if len(samples) < 2:
        return fail_closed(
            child="PR-155",
            nf="NF-369",
            action="collect_provider_consensus_sample",
            subject_id=sid,
            reason="INSUFFICIENT_EVIDENCE",
            payload={"provider_count": len(samples)},
        )
    return artifact(
        child="PR-155",
        nf="NF-369",
        action="collect_provider_consensus_sample",
        subject_id=sid,
        payload={"provider_state_hashes": dict(sorted(samples.items()))},
    )


def score_source_disagreement(
    sample_id: str,
    provider_state_hashes: Mapping[str, str],
):
    sid = require_text(sample_id, "sample_id")
    samples = _checked_samples(provider_state_hashes)
    counts = Counter(samples.values())
    majority_hash, majority_count = counts.most_common(1)[0] if counts else ("", 0)
    disagreeing = tuple(
        sorted(provider for provider, state_hash in samples.items() if state_hash != majority_hash)
    )
    return artifact(
        child="PR-155",
        nf="NF-370",
        action="score_source_disagreement",
        subject_id=sid,
        payload={
            "provider_count": len(samples),
            "majority_count": majority_count,
            "majority_hash": majority_hash,
            "disagreeing_providers": disagreeing,
        },
    )


def quarantine_byzantine_source(
    provider_id: str,
    disagreements: int,
    observations: int,
    threshold_bps: int,
):
    provider = require_text(provider_id, "provider_id")
    bad = require_non_negative_int(disagreements, "disagreements")
    total = require_non_negative_int(observations, "observations")
    threshold = require_non_negative_int(threshold_bps, "threshold_bps")
    if bad > total or threshold > 10_000:
        return fail_closed(
            child="PR-155",
            nf="NF-371",
            action="quarantine_byzantine_source",
            subject_id=provider,
            reason="INCONSISTENT_STATE",
        )
    rate_bps = 0 if total == 0 else (bad * 10_000) // total
    if total == 0 or rate_bps > threshold:
        return fail_closed(
            child="PR-155",
            nf="NF-371",
            action="quarantine_byzantine_source",
            subject_id=provider,
            reason="QUARANTINED_SOURCE",
            payload={"disagreement_bps": rate_bps, "threshold_bps": threshold},
        )
    return artifact(
        child="PR-155",
        nf="NF-371",
        action="quarantine_byzantine_source",
        subject_id=provider,
        payload={"disagreement_bps": rate_bps, "threshold_bps": threshold},
    )


def reconstruct_consensus_state(
    sample_id: str,
    provider_state_hashes: Mapping[str, str],
    minimum_quorum: int,
):
    sid = require_text(sample_id, "sample_id")
    samples = _checked_samples(provider_state_hashes)
    quorum = require_non_negative_int(minimum_quorum, "minimum_quorum")
    counts = Counter(samples.values())
    majority_hash, count = counts.most_common(1)[0] if counts else ("", 0)
    if quorum == 0 or count < quorum:
        return fail_closed(
            child="PR-155",
            nf="NF-372",
            action="reconstruct_consensus_state",
            subject_id=sid,
            reason="INCONSISTENT_STATE",
            payload={"majority_count": count, "minimum_quorum": quorum},
        )
    supporters: Sequence[str] = tuple(
        sorted(provider for provider, value in samples.items() if value == majority_hash)
    )
    return artifact(
        child="PR-155",
        nf="NF-372",
        action="reconstruct_consensus_state",
        subject_id=sid,
        payload={
            "consensus_state_hash": majority_hash,
            "supporters": supporters,
            "minimum_quorum": quorum,
        },
    )
