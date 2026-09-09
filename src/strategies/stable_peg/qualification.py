"""Fail-closed qualification policy for MPR-2622."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .models import CandidateClass, PegReferenceEvidence, Reason, StableAssetEvidence, StablePegCandidate, StablePegError, canonical_digest, strict_int

@dataclass(frozen=True, slots=True)
class PegRiskPolicy:
    now_ns: int
    max_age_ns: int
    max_confidence_ratio_ppm: int
    max_reference_disagreement_ppm: int
    pyth_generation: str

    def __post_init__(self) -> None:
        strict_int(self.now_ns, field="now_ns")
        strict_int(self.max_age_ns, field="max_age_ns", minimum=1)
        strict_int(self.max_confidence_ratio_ppm, field="max_confidence_ratio_ppm")
        strict_int(self.max_reference_disagreement_ppm, field="max_reference_disagreement_ppm")
        if not self.pyth_generation:
            raise StablePegError("pyth_generation required")


def validate_assets(assets: Iterable[StableAssetEvidence]) -> tuple[str, ...]:
    blockers: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        if asset.mint in seen:
            raise StablePegError("duplicate mint evidence")
        seen.add(asset.mint)
        if not asset.executable_allowed:
            blockers.append(Reason.ASSET_UNQUALIFIED)
    return tuple(sorted(set(blockers)))


def _scaled_ratio_ppm(n: int, d: int) -> int:
    if d <= 0:
        return 1_000_000_000
    return (n * 1_000_000 + d - 1) // d


def validate_references(refs: Iterable[PegReferenceEvidence], policy: PegRiskPolicy) -> tuple[str, ...]:
    refs_t = tuple(refs)
    blockers: list[str] = []
    normalized: list[tuple[int, int]] = []
    for ref in refs_t:
        if policy.now_ns < ref.publish_time_ns or policy.now_ns - ref.publish_time_ns > policy.max_age_ns or not ref.fresh:
            blockers.append(Reason.REFERENCE_STALE)
        if not ref.confidence_ok or _scaled_ratio_ppm(ref.confidence, abs(ref.price)) > policy.max_confidence_ratio_ppm:
            blockers.append(Reason.REFERENCE_CONFIDENCE_WIDE)
        normalized.append((ref.price, ref.exponent))
    for i, (p1, e1) in enumerate(normalized):
        for p2, e2 in normalized[i + 1:]:
            common = min(e1, e2)
            a = p1 * (10 ** (e1 - common))
            b = p2 * (10 ** (e2 - common))
            denom = max(abs(a), abs(b), 1)
            if _scaled_ratio_ppm(abs(a - b), denom) > policy.max_reference_disagreement_ppm:
                blockers.append(Reason.REFERENCE_DISAGREEMENT)
    return tuple(sorted(set(blockers)))

@dataclass(frozen=True, slots=True)
class QualificationArtifact:
    schema: str
    status: str
    source_commit: str
    release_id: str
    config_digest: str
    policy_digest: str
    candidate_hash: str
    blockers: tuple[str, ...]
    live_enabled: bool
    release_claim_allowed: bool
    production_ready: bool
    artifact_digest: str


def qualify(*, candidate: StablePegCandidate, assets: Iterable[StableAssetEvidence], references: Iterable[PegReferenceEvidence], policy: PegRiskPolicy, source_commit: str, release_id: str, config_digest: str, policy_digest: str) -> QualificationArtifact:
    blockers = sorted(set(candidate.blockers + validate_assets(assets) + validate_references(references, policy)))
    status = "VERIFIED_OFFLINE" if candidate.classification in {CandidateClass.CANDIDATE, CandidateClass.RECORDED_OFFLINE} and not blockers else "BLOCKED_INTEGRATION"
    if candidate.classification == CandidateClass.RECORDED_OFFLINE and not blockers:
        status = "RECORDED_OFFLINE"
    payload = {
        "schema": "mpr2622.stable-peg-qualification.v1",
        "status": status,
        "source_commit": source_commit,
        "release_id": release_id,
        "config_digest": config_digest,
        "policy_digest": policy_digest,
        "candidate_hash": candidate.candidate_hash,
        "blockers": blockers,
        "live_enabled": False,
        "release_claim_allowed": False,
        "production_ready": False,
    }
    return QualificationArtifact(**payload, artifact_digest=canonical_digest("mpr2622.qualification.v1", payload))
