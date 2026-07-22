"""PR-063 canonical RPC/Jito sender consolidation.

This module is a narrow composition boundary around the PR-045 permit-bound
sender.  It selects exactly one submission transport, exposes the current
Jito/RPC route contract as reviewable constants, and converts status
observations into durable follow-up instructions that never auto-resubmit an
already submitted payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json

from src.execution.models import ExecutionState

from .jito_mev_policy import (
    JitoMevProtectionPolicy,
    evaluate_pr130_jito_mev_policy,
)
from .permit_bound import (
    AsyncJsonHttpTransport,
    ErrorDisposition,
    JitoSender,
    JitoUuidAuth,
    LivePermitIssuer,
    LiveSubmissionPolicy,
    RpcSender,
    Sender,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionState,
    SubmissionStatusClient,
    TransportKind,
    resubmission_decision,
)

DEFAULT_JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf"
JITO_SINGLE_TRANSACTION_PATH = "/api/v1/transactions"
JITO_BUNDLE_PATH = "/api/v1/bundles"
JITO_INFLIGHT_STATUS_PATH = "/api/v1/getInflightBundleStatuses"
JITO_BUNDLE_STATUS_PATH = "/api/v1/getBundleStatuses"
JITO_TIP_ACCOUNTS_PATH = "/api/v1/getTipAccounts"
SOLANA_SIGNATURE_STATUS_METHOD = "getSignatureStatuses"
PR130_JITO_MEV_POLICY = JitoMevProtectionPolicy()


class JitoCredentialMode(StrEnum):
    """Supported Block Engine auth modes."""

    NO_AUTH = "no_auth"
    UUID = "uuid"


class CanonicalFollowupAction(StrEnum):
    """Next operator action after submission status reconciliation."""

    RECORD_LANDING = "record_landing"
    RECONCILE_WITHOUT_RESEND = "reconcile_without_resend"
    REVIEWED_REBUILD_NEW_PERMIT = "reviewed_rebuild_new_permit"


@dataclass(frozen=True, slots=True)
class CanonicalFollowup:
    """Durable status target and resend policy for one observation."""

    action: CanonicalFollowupAction
    durable_state: ExecutionState
    requires_new_permit: bool
    reason: str

    @property
    def resend_same_payload_allowed(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class CanonicalEndpointRoute:
    """Reviewable endpoint/method contract for one polling or submission route."""

    transport: TransportKind | None
    name: str
    path_or_method: str
    requires_jito: bool = False


CANONICAL_STATUS_ROUTES: tuple[CanonicalEndpointRoute, ...] = (
    CanonicalEndpointRoute(
        None, "solana-signature-status", SOLANA_SIGNATURE_STATUS_METHOD
    ),
    CanonicalEndpointRoute(
        TransportKind.JITO_SINGLE,
        "jito-inflight-status",
        JITO_INFLIGHT_STATUS_PATH,
        requires_jito=True,
    ),
    CanonicalEndpointRoute(
        TransportKind.JITO_BUNDLE,
        "jito-bundle-status",
        JITO_BUNDLE_STATUS_PATH,
        requires_jito=True,
    ),
    CanonicalEndpointRoute(
        None,
        "jito-tip-accounts",
        JITO_TIP_ACCOUNTS_PATH,
        requires_jito=True,
    ),
)


@dataclass(frozen=True, slots=True)
class CanonicalSenderSettings:
    """Single-transport sender settings."""

    transport: TransportKind
    rpc_endpoint: str
    jito_base_url: str = DEFAULT_JITO_BLOCK_ENGINE_URL
    jito_credential_mode: JitoCredentialMode = JitoCredentialMode.NO_AUTH
    jito_uuid: str | None = field(default=None, repr=False)
    compile_time_enabled: bool = False
    config_enabled: bool = False
    commitment: str = "confirmed"
    skip_preflight: bool = False
    max_retries: int = 0
    timeout_seconds: float = 8.0
    jito_bundle_only: bool = True
    allow_transport_fallback: bool = False
    allow_duplicate_submission: bool = False

    def __post_init__(self) -> None:
        if self.allow_transport_fallback:
            raise SubmissionError(
                SubmissionErrorCode.LIVE_GATE_CLOSED,
                ErrorDisposition.FATAL,
                "canonical sender cannot be configured with transport fallback",
            )
        if self.allow_duplicate_submission:
            raise SubmissionError(
                SubmissionErrorCode.RESUBMIT_FORBIDDEN,
                ErrorDisposition.FATAL,
                "canonical sender cannot allow duplicate submission",
            )
        if self.transport is TransportKind.RPC:
            if self.jito_credential_mode is not JitoCredentialMode.NO_AUTH:
                raise SubmissionError(
                    SubmissionErrorCode.AUTH_INVALID,
                    ErrorDisposition.FATAL,
                    "RPC transport must not carry Jito credential mode",
                )
            if self.jito_uuid is not None:
                raise SubmissionError(
                    SubmissionErrorCode.AUTH_INVALID,
                    ErrorDisposition.FATAL,
                    "RPC transport must not carry Jito UUID material",
                )
        elif self.transport in {TransportKind.JITO_SINGLE, TransportKind.JITO_BUNDLE}:
            if (
                self.transport is TransportKind.JITO_BUNDLE
                and (self.compile_time_enabled or self.config_enabled)
            ):
                raise SubmissionError(
                    SubmissionErrorCode.LIVE_GATE_CLOSED,
                    ErrorDisposition.FATAL,
                    "PR-130 first production Jito policy requires one "
                    "transaction via JITO_SINGLE; multi-transaction bundles "
                    "remain disabled until unbundling chaos evidence exists",
                )
            if (
                self.jito_credential_mode is JitoCredentialMode.UUID
                and not self.jito_uuid
            ):
                raise SubmissionError(
                    SubmissionErrorCode.AUTH_INVALID,
                    ErrorDisposition.FATAL,
                    "Jito UUID credential mode requires a UUID value",
                )
            if (
                self.jito_credential_mode is JitoCredentialMode.NO_AUTH
                and self.jito_uuid
            ):
                raise SubmissionError(
                    SubmissionErrorCode.AUTH_INVALID,
                    ErrorDisposition.FATAL,
                    "Jito UUID value requires explicit UUID credential mode",
                )
        else:
            raise SubmissionError(
                SubmissionErrorCode.PERMIT_INVALID,
                ErrorDisposition.FATAL,
                "unsupported canonical sender transport",
            )

    @property
    def uses_jito(self) -> bool:
        return self.transport in {TransportKind.JITO_SINGLE, TransportKind.JITO_BUNDLE}

    @property
    def require_jito_uuid_auth(self) -> bool:
        return self.uses_jito and self.jito_credential_mode is JitoCredentialMode.UUID

    def live_policy(self) -> LiveSubmissionPolicy:
        return LiveSubmissionPolicy(
            compile_time_enabled=self.compile_time_enabled,
            config_enabled=self.config_enabled,
            allowed_transports=(self.transport,),
            commitment=self.commitment,
            skip_preflight=self.skip_preflight,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            require_jito_uuid_auth=self.require_jito_uuid_auth,
            jito_bundle_only=self.jito_bundle_only,
        )

    def jito_auth(self) -> JitoUuidAuth | None:
        if (
            not self.uses_jito
            or self.jito_credential_mode is JitoCredentialMode.NO_AUTH
        ):
            return None
        if self.jito_uuid is None:
            raise SubmissionError(
                SubmissionErrorCode.AUTH_INVALID,
                ErrorDisposition.FATAL,
                "Jito UUID credential mode requires a UUID value",
            )
        return JitoUuidAuth.parse(self.jito_uuid)

    def pr130_jito_mev_protection(self) -> dict[str, object] | None:
        if not self.uses_jito:
            return None
        transaction_count = 1
        if self.transport is TransportKind.JITO_BUNDLE:
            transaction_count = 2
        evaluation = evaluate_pr130_jito_mev_policy(
            transport=self.transport,
            transaction_count=transaction_count,
            tip_transaction_index=0,
            bundle_only=self.jito_bundle_only,
            tip_account_static=True,
            bundle_ack_treated_as_settlement=False,
            policy=PR130_JITO_MEV_POLICY,
        )
        return evaluation.to_dict()

    def redacted_manifest(self) -> dict[str, object]:
        auth = self.jito_auth()
        return {
            "transport": self.transport.value,
            "rpc_endpoint": self.rpc_endpoint,
            "jito_base_url": self.jito_base_url if self.uses_jito else None,
            "jito_credential_mode": self.jito_credential_mode.value,
            "jito_uuid_fingerprint": auth.fingerprint if auth is not None else None,
            "allowed_transports": [self.transport.value],
            "transport_fallback_allowed": False,
            "duplicate_submission_allowed": False,
            "jito_mev_protection": self.pr130_jito_mev_protection(),
            "status_routes": [
                {
                    "name": route.name,
                    "path_or_method": route.path_or_method,
                    "requires_jito": route.requires_jito,
                }
                for route in canonical_status_routes(self.transport)
            ],
        }

    @property
    def endpoint_fingerprint(self) -> str:
        return _hash_json(self.redacted_manifest())


@dataclass(frozen=True, slots=True)
class CanonicalSubmissionStack:
    """Exactly one sender plus its matching issuer and status client."""

    sender: Sender
    issuer: LivePermitIssuer
    status_client: SubmissionStatusClient
    transport: TransportKind
    endpoint_fingerprint: str
    duplicate_submission_allowed: bool = False
    transport_fallback_allowed: bool = False


def build_canonical_submission_stack(
    settings: CanonicalSenderSettings,
    http: AsyncJsonHttpTransport,
    *,
    issuer: LivePermitIssuer | None = None,
) -> CanonicalSubmissionStack:
    """Build one permit-bound sender and one status client."""

    policy = settings.live_policy()
    active_issuer = issuer if issuer is not None else LivePermitIssuer(policy)
    if active_issuer.policy.fingerprint != policy.fingerprint:
        raise SubmissionError(
            SubmissionErrorCode.PERMIT_INVALID,
            ErrorDisposition.FATAL,
            "injected issuer policy does not match canonical sender settings",
        )
    jito_auth = settings.jito_auth()
    if settings.transport is TransportKind.RPC:
        sender: Sender = RpcSender(settings.rpc_endpoint, http, active_issuer)
        jito_base_url = None
    else:
        sender = JitoSender(
            settings.jito_base_url,
            http,
            active_issuer,
            auth=jito_auth,
        )
        jito_base_url = settings.jito_base_url
    status_client = SubmissionStatusClient(
        http,
        rpc_endpoint=settings.rpc_endpoint,
        jito_base_url=jito_base_url,
        jito_auth=jito_auth,
        timeout_seconds=settings.timeout_seconds,
    )
    return CanonicalSubmissionStack(
        sender=sender,
        issuer=active_issuer,
        status_client=status_client,
        transport=settings.transport,
        endpoint_fingerprint=settings.endpoint_fingerprint,
    )


def canonical_status_routes(
    transport: TransportKind,
) -> tuple[CanonicalEndpointRoute, ...]:
    """Return the status/tip routes needed for one selected transport."""

    if transport is TransportKind.RPC:
        return (CANONICAL_STATUS_ROUTES[0],)
    if transport is TransportKind.JITO_SINGLE:
        return (
            CANONICAL_STATUS_ROUTES[0],
            CANONICAL_STATUS_ROUTES[1],
            CANONICAL_STATUS_ROUTES[3],
        )
    if transport is TransportKind.JITO_BUNDLE:
        return CANONICAL_STATUS_ROUTES
    raise SubmissionError(
        SubmissionErrorCode.PERMIT_INVALID,
        ErrorDisposition.FATAL,
        "unsupported canonical status transport",
    )


def canonical_followup_for_observation(
    observation: SubmissionObservation,
) -> CanonicalFollowup:
    """Translate a status observation into a durable no-auto-resubmit action."""

    decision = resubmission_decision(observation)
    if observation.state is SubmissionState.LANDED:
        action = CanonicalFollowupAction.RECORD_LANDING
    elif decision.allowed:
        action = CanonicalFollowupAction.REVIEWED_REBUILD_NEW_PERMIT
    else:
        action = CanonicalFollowupAction.RECONCILE_WITHOUT_RESEND
    return CanonicalFollowup(
        action=action,
        durable_state=_durable_target(observation.state),
        requires_new_permit=decision.requires_new_permit,
        reason=decision.reason,
    )


def _durable_target(state: SubmissionState) -> ExecutionState:
    if state is SubmissionState.LANDED:
        return ExecutionState.LANDED
    if state is SubmissionState.ACCEPTED:
        return ExecutionState.PENDING
    if state in {
        SubmissionState.UNKNOWN,
        SubmissionState.EXPIRED,
        SubmissionState.FAILED,
    }:
        return ExecutionState.RECONCILING
    raise AssertionError("unhandled submission state")


def _hash_json(value: object) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "CANONICAL_STATUS_ROUTES",
    "DEFAULT_JITO_BLOCK_ENGINE_URL",
    "JITO_BUNDLE_PATH",
    "JITO_BUNDLE_STATUS_PATH",
    "JITO_INFLIGHT_STATUS_PATH",
    "JITO_SINGLE_TRANSACTION_PATH",
    "JITO_TIP_ACCOUNTS_PATH",
    "PR130_JITO_MEV_POLICY",
    "SOLANA_SIGNATURE_STATUS_METHOD",
    "CanonicalEndpointRoute",
    "CanonicalFollowup",
    "CanonicalFollowupAction",
    "CanonicalSenderSettings",
    "CanonicalSubmissionStack",
    "JitoCredentialMode",
    "build_canonical_submission_stack",
    "canonical_followup_for_observation",
    "canonical_status_routes",
]
