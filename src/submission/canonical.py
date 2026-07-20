"""Canonical permit-bound RPC/Jito sender facade for roadmap PR-063.

The PR-045 transport implementations remain the low-level mechanism. This
module provides the single supported composition boundary: one configured
transport, one one-use permit issuer, one sender, and one conservative status
report. It never falls back from Jito to RPC (or the reverse) and never grants
automatic resubmission after a request may have been dispatched.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
import time
from typing import Callable

from .permit_bound import (
    AsyncJsonHttpTransport,
    ErrorDisposition,
    JitoSender,
    JitoUuidAuth,
    LivePermitIssuer,
    LiveSubmissionPolicy,
    RpcSender,
    Sender,
    SignedPayload,
    SubmissionAck,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionPermit,
    SubmissionState,
    SubmissionStatusClient,
    TransportKind,
)


class JitoCredentialMode(StrEnum):
    """Explicit Jito credential contract.

    ``DEFAULT`` is the current public/default Block Engine mode and emits no
    authentication header. ``UUID`` is an explicitly configured credentialed
    mode and requires ``x-jito-auth`` evidence.
    """

    DEFAULT = "default"
    UUID = "uuid"


@dataclass(frozen=True, slots=True)
class CanonicalSenderConfig:
    """Configuration for exactly one canonical permit-bound sender."""

    transport: TransportKind
    rpc_endpoint: str
    jito_base_url: str | None = None
    jito_credential_mode: JitoCredentialMode = JitoCredentialMode.DEFAULT
    jito_uuid_auth: JitoUuidAuth | None = None
    compile_time_enabled: bool = False
    config_enabled: bool = False
    commitment: str = "confirmed"
    skip_preflight: bool = False
    max_retries: int = 0
    timeout_seconds: float = 8.0
    jito_bundle_only: bool = True

    def __post_init__(self) -> None:
        if not self.rpc_endpoint:
            raise ValueError("rpc_endpoint is required for status reconciliation")
        if self.transport is TransportKind.RPC:
            if self.jito_base_url is not None or self.jito_uuid_auth is not None:
                raise ValueError("RPC transport cannot carry Jito configuration")
            if self.jito_credential_mode is not JitoCredentialMode.DEFAULT:
                raise ValueError("RPC transport cannot select a Jito credential mode")
            return
        if self.jito_base_url is None:
            raise ValueError("Jito transport requires jito_base_url")
        if self.jito_credential_mode is JitoCredentialMode.UUID:
            if self.jito_uuid_auth is None:
                raise ValueError("Jito UUID mode requires jito_uuid_auth")
        elif self.jito_uuid_auth is not None:
            raise ValueError("Jito default mode must not emit UUID credentials")

    def live_policy(self) -> LiveSubmissionPolicy:
        """Build the sole PR-045 policy used by this canonical facade."""

        return LiveSubmissionPolicy(
            compile_time_enabled=self.compile_time_enabled,
            config_enabled=self.config_enabled,
            allowed_transports=(self.transport,),
            commitment=self.commitment,
            skip_preflight=self.skip_preflight,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            require_jito_uuid_auth=(
                self.jito_credential_mode is JitoCredentialMode.UUID
            ),
            jito_bundle_only=self.jito_bundle_only,
        )


@dataclass(frozen=True, slots=True)
class CanonicalStatusReport:
    """Conservative status result with an explicit no-resubmit invariant."""

    state: SubmissionState
    observations: tuple[SubmissionObservation, ...]
    authoritative_source: str
    ambiguous: bool
    automatic_resubmit_allowed: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError("canonical status report requires observations")
        if self.automatic_resubmit_allowed:
            raise ValueError("PR-063 forbids automatic duplicate submission")


class CanonicalPermitBoundSender:
    """Single public sender facade with no transport fallback."""

    def __init__(
        self,
        config: CanonicalSenderConfig,
        http: AsyncJsonHttpTransport,
        *,
        issuer: LivePermitIssuer | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.config = config
        expected_policy = config.live_policy()
        self.issuer = issuer or LivePermitIssuer(expected_policy, clock_ns=clock_ns)
        if self.issuer.policy.fingerprint != expected_policy.fingerprint:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "canonical sender policy does not match the supplied permit issuer",
            )
        self.status_client = SubmissionStatusClient(
            http,
            rpc_endpoint=config.rpc_endpoint,
            jito_base_url=config.jito_base_url,
            jito_auth=config.jito_uuid_auth,
            timeout_seconds=config.timeout_seconds,
            clock_ns=clock_ns,
        )
        self._sender: Sender
        if config.transport is TransportKind.RPC:
            self._sender = RpcSender(
                config.rpc_endpoint,
                http,
                self.issuer,
                clock_ns=clock_ns,
            )
        else:
            if config.jito_base_url is None:  # narrowed by CanonicalSenderConfig
                raise AssertionError("Jito base URL was not validated")
            self._sender = JitoSender(
                config.jito_base_url,
                http,
                self.issuer,
                auth=config.jito_uuid_auth,
                clock_ns=clock_ns,
            )

    async def submit(
        self,
        permit: SubmissionPermit,
        signed_payload: SignedPayload,
        message_hash: str,
    ) -> SubmissionAck:
        if permit.transport is not self.config.transport:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "permit transport differs from the canonical sender transport",
            )
        return await self._sender.submit(permit, signed_payload, message_hash)

    async def poll_once(
        self,
        ack: SubmissionAck,
        *,
        current_block_height: int,
        last_valid_block_height: int,
    ) -> CanonicalStatusReport:
        """Poll the configured path once without submitting or falling back."""

        signature = await self.status_client.signature_statuses(
            ack,
            current_block_height=current_block_height,
            last_valid_block_height=last_valid_block_height,
        )
        observations: list[SubmissionObservation] = [signature]
        if self.config.transport is not TransportKind.RPC and ack.bundle_id:
            observations.append(await self.status_client.jito_inflight_status(ack))
            observations.append(await self.status_client.jito_bundle_status(ack))
        return consolidate_submission_observations(
            self.config.transport,
            observations,
        )


def consolidate_submission_observations(
    transport: TransportKind,
    observations: Sequence[SubmissionObservation],
) -> CanonicalStatusReport:
    """Reduce status evidence while treating Solana signatures as authority.

    Jito evidence can strengthen diagnostics but cannot overrule a missing or
    conflicting Solana signature result. Every post-submit report blocks
    automatic resubmission; proven expiry/failure still requires a fresh permit
    and an explicit durable lifecycle decision.
    """

    values = tuple(observations)
    if not values:
        raise ValueError("at least one submission observation is required")
    solana = tuple(item for item in values if item.source.startswith("solana."))
    if len(solana) != 1:
        raise ValueError(
            "exactly one aggregate Solana signature observation is required"
        )
    if transport is TransportKind.RPC and any(
        item.source.startswith("jito.") for item in values
    ):
        raise ValueError("RPC status report cannot contain Jito observations")

    signature = solana[0]
    jito_states = {item.state for item in values if item.source.startswith("jito.")}
    state = signature.state
    ambiguous = False
    reason = signature.reason or "Solana signature status is authoritative"

    if signature.state is SubmissionState.LANDED:
        if SubmissionState.FAILED in jito_states:
            state = SubmissionState.UNKNOWN
            ambiguous = True
            reason = "Jito failure conflicts with landed Solana signature evidence"
    elif signature.state is SubmissionState.FAILED:
        if SubmissionState.LANDED in jito_states:
            state = SubmissionState.UNKNOWN
            ambiguous = True
            reason = "Jito landing conflicts with failed Solana signature evidence"
    elif signature.state is SubmissionState.EXPIRED:
        if jito_states.intersection(
            {SubmissionState.ACCEPTED, SubmissionState.LANDED, SubmissionState.UNKNOWN}
        ):
            state = SubmissionState.UNKNOWN
            ambiguous = True
            reason = "expiry conflicts with unresolved Jito evidence"
    elif signature.state is SubmissionState.ACCEPTED:
        ambiguous = SubmissionState.FAILED in jito_states
        if ambiguous:
            state = SubmissionState.UNKNOWN
            reason = "pending Solana signature conflicts with Jito failure evidence"
    else:
        state = SubmissionState.UNKNOWN
        ambiguous = True
        reason = "signature state is missing or indeterminate"

    return CanonicalStatusReport(
        state=state,
        observations=values,
        authoritative_source=signature.source,
        ambiguous=ambiguous,
        automatic_resubmit_allowed=False,
        reason=reason,
    )


__all__ = [
    "CanonicalPermitBoundSender",
    "CanonicalSenderConfig",
    "CanonicalStatusReport",
    "JitoCredentialMode",
    "consolidate_submission_observations",
]
