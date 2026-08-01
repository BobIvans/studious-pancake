"""Cross-slot policy applied to PR-004 rooted observations."""

from dataclasses import dataclass


class CoherenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RootedStateEvidence:
    kind: str
    slot: int
    rooted_slot: int
    genesis_hash: str
    commitment: str
    fork_hash: str
    endpoint_identity: str
    min_context_slot: int | None


@dataclass(frozen=True, slots=True)
class CrossSlotPolicy:
    genesis_hash: str
    maximum_slot_skew: int = 2
    maximum_age_slots: int = 64
    commitment: str = "finalized"


def require_coherent(
    evidence: tuple[RootedStateEvidence, ...],
    *,
    policy: CrossSlotPolicy,
    current_root: int,
) -> str:
    required = {"reserve", "oracle", "mint", "alt", "blockhash", "protocol"}
    if {x.kind for x in evidence} != required:
        raise CoherenceError("incomplete state evidence set")
    if any(x.min_context_slot is None for x in evidence):
        raise CoherenceError("missing minContextSlot")
    if any(x.genesis_hash != policy.genesis_hash for x in evidence):
        raise CoherenceError("mixed or wrong genesis")
    if any(x.commitment != policy.commitment for x in evidence):
        raise CoherenceError("mixed or wrong commitment")
    if len({x.fork_hash for x in evidence}) != 1:
        raise CoherenceError("mixed fork")
    if len({x.endpoint_identity for x in evidence}) < 2:
        raise CoherenceError("rooted quorum requires independent endpoints")
    slots = [x.slot for x in evidence]
    if any(x.slot > x.rooted_slot or x.rooted_slot > current_root for x in evidence):
        raise CoherenceError("future or unrooted evidence")
    if current_root - min(slots) > policy.maximum_age_slots:
        raise CoherenceError("stale evidence")
    if max(slots) - min(slots) > policy.maximum_slot_skew:
        raise CoherenceError("cross-slot skew exceeded")
    if any(
        x.min_context_slot > x.slot for x in evidence if x.min_context_slot is not None
    ):
        raise CoherenceError("response predates minContextSlot")
    from hashlib import sha256

    return sha256(
        "|".join(
            f"{x.kind}:{x.slot}:{x.endpoint_identity}"
            for x in sorted(evidence, key=lambda v: v.kind)
        ).encode()
    ).hexdigest()
