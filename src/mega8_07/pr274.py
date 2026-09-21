"""PR-274 / CACHE-02: immutable generation-aware state slices."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import EvidenceBinding, Mega807Error, StateSlice, stable_hash


def publish_immutable_state_slice(
    *,
    slice_id: str,
    generation: str,
    payload: Mapping[str, int | str],
    evidence: EvidenceBinding,
    now: int,
) -> StateSlice:
    evidence.assert_usable(now=now)
    digest = stable_hash(
        "mega8-07-state-slice",
        {
            "slice_id": slice_id,
            "generation": generation,
            "payload": dict(sorted(payload.items())),
            "evidence": evidence.identity,
        },
    )
    return StateSlice(
        slice_id,
        generation,
        digest,
        evidence.identity,
        dict(payload),
    )


def subscribe_edge_cache(
    slices: Sequence[StateSlice], *, allowed_generations: Sequence[str]
) -> tuple[StateSlice, ...]:
    allowed = set(allowed_generations)
    return tuple(
        sorted(
            (item for item in slices if item.generation in allowed),
            key=lambda item: (item.generation, item.slice_id),
        )
    )


def validate_cache_generation(
    state_slice: StateSlice, *, expected_generation: str
) -> bool:
    if state_slice.generation != expected_generation:
        raise Mega807Error("CACHE_GENERATION_MISMATCH")
    expected = stable_hash(
        "mega8-07-state-slice",
        {
            "slice_id": state_slice.slice_id,
            "generation": state_slice.generation,
            "payload": dict(sorted(state_slice.payload.items())),
            "evidence": state_slice.evidence_identity,
        },
    )
    if expected != state_slice.content_sha256:
        raise Mega807Error("CACHE_CONTENT_HASH_MISMATCH")
    return True


def revoke_stale_cache(
    slices: Sequence[StateSlice], *, current_generation: str
) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.slice_id
            for item in slices
            if item.generation != current_generation
        )
    )
