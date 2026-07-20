"""Authoritative multi-source status consolidation for canonical PR-063 sender.

The merged ``canonical_sender`` module remains the only sender composition API.
This module hardens its post-submit evidence path: Solana signature status is
canonical, Jito status is supplementary, ambiguity never triggers a resend, and
proven expiry/failure can only request a reviewed rebuild with a new permit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .canonical_sender import (
    CanonicalFollowup,
    CanonicalSubmissionStack,
    canonical_followup_for_observation,
)
from .permit_bound import (
    ErrorDisposition,
    SubmissionAck,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionState,
    TransportKind,
)


@dataclass(frozen=True, slots=True)
class CanonicalStatusReport:
    """One conservative status decision across Solana and optional Jito evidence."""

    state: SubmissionState
    observations: tuple[SubmissionObservation, ...]
    followup: CanonicalFollowup
    authoritative_source: str
    ambiguous: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError("canonical status report requires observations")
        if not self.authoritative_source.startswith("solana."):
            raise ValueError("canonical status authority must be a Solana source")

    @property
    def automatic_resubmit_allowed(self) -> bool:
        """PR-063 never resubmits a possibly dispatched payload automatically."""

        return False

    @property
    def resend_same_payload_allowed(self) -> bool:
        return False


def consolidate_canonical_observations(
    transport: TransportKind,
    observations: Sequence[SubmissionObservation],
) -> CanonicalStatusReport:
    """Consolidate status evidence without letting Jito overrule Solana.

    Exactly one aggregate Solana signature observation is required. Jito
    observations may improve diagnostics for a Jito transport, but only Solana
    can prove transaction landing or an on-chain failure. Missing or conflicting
    non-final evidence remains ambiguous and routes to reconciliation.
    """

    values = tuple(observations)
    if not values:
        raise ValueError("at least one submission observation is required")

    solana = tuple(item for item in values if item.source.startswith("solana."))
    if len(solana) != 1:
        raise ValueError(
            "exactly one aggregate Solana signature observation is required"
        )
    jito = tuple(item for item in values if item.source.startswith("jito."))
    unknown_sources = tuple(
        item.source
        for item in values
        if not item.source.startswith(("solana.", "jito."))
    )
    if unknown_sources:
        raise ValueError("status observations contain an unsupported source")
    if transport is TransportKind.RPC and jito:
        raise ValueError("RPC status evidence cannot contain Jito observations")

    signature = solana[0]
    jito_states = {item.state for item in jito}
    state = signature.state
    ambiguous = signature.state is SubmissionState.UNKNOWN
    reason = signature.reason or "Solana signature status is authoritative"

    # Confirmed/finalized signature evidence and explicit on-chain errors are
    # authoritative even when provider caches disagree.
    if signature.state is SubmissionState.LANDED:
        reason = "Solana signature evidence proves landing"
    elif signature.state is SubmissionState.FAILED:
        reason = "Solana signature evidence proves an on-chain failure"
    elif signature.state is SubmissionState.EXPIRED:
        if jito_states.intersection(
            {SubmissionState.ACCEPTED, SubmissionState.LANDED, SubmissionState.UNKNOWN}
        ):
            state = SubmissionState.UNKNOWN
            ambiguous = True
            reason = "expiry conflicts with unresolved Jito delivery evidence"
        else:
            reason = "blockhash expiry is proven with no contradictory Jito evidence"
    elif signature.state is SubmissionState.ACCEPTED:
        if jito_states.intersection(
            {SubmissionState.FAILED, SubmissionState.EXPIRED}
        ):
            state = SubmissionState.UNKNOWN
            ambiguous = True
            reason = "processed Solana signature conflicts with Jito failure evidence"
        else:
            reason = "signature is observed but not yet confirmed"
    else:
        state = SubmissionState.UNKNOWN
        ambiguous = True
        if SubmissionState.LANDED in jito_states:
            reason = "Jito reports landing but Solana signature proof is unavailable"
        elif SubmissionState.FAILED in jito_states:
            reason = "Jito reports failure while Solana signature state is indeterminate"
        else:
            reason = "Solana signature state is missing or indeterminate"

    effective = signature
    if state is not signature.state or reason != signature.reason:
        effective = SubmissionObservation(
            state=state,
            source="canonical.status-consolidation",
            observed_at_ns=max(item.observed_at_ns for item in values),
            slot=signature.slot,
            confirmation_status=signature.confirmation_status,
            reason=reason,
        )

    return CanonicalStatusReport(
        state=state,
        observations=values,
        followup=canonical_followup_for_observation(effective),
        authoritative_source=signature.source,
        ambiguous=ambiguous,
        reason=reason,
    )


async def poll_canonical_status_once(
    stack: CanonicalSubmissionStack,
    ack: SubmissionAck,
    *,
    current_block_height: int,
    last_valid_block_height: int,
) -> CanonicalStatusReport:
    """Poll bounded official status routes once without sending or falling back."""

    if ack.transport is not stack.transport:
        raise SubmissionError(
            SubmissionErrorCode.IDENTITY_MISMATCH,
            ErrorDisposition.FATAL,
            "ack transport differs from the canonical submission stack",
        )

    observations: list[SubmissionObservation] = [
        await stack.status_client.signature_statuses(
            ack,
            current_block_height=current_block_height,
            last_valid_block_height=last_valid_block_height,
        )
    ]
    if stack.transport is not TransportKind.RPC and ack.bundle_id:
        observations.append(await stack.status_client.jito_inflight_status(ack))
        observations.append(await stack.status_client.jito_bundle_status(ack))

    return consolidate_canonical_observations(stack.transport, observations)


__all__ = [
    "CanonicalStatusReport",
    "consolidate_canonical_observations",
    "poll_canonical_status_once",
]
