"""Helius provider adapters with the PR-199 authenticated ingress boundary."""

from . import delivery as _delivery
from .authenticated_ingress import (
    CredentialBinding,
    CredentialState,
    InboundRequestContext,
    IngressConnectionMetadata,
    IngressGatewayPolicy,
    IngressRejectReason,
    IngressRejected,
    authenticate_inbound_request,
    install_authenticated_ingress,
)

# Install before rebinding public names.  Python loads this package before a
# direct ``src.providers.helius.delivery`` import, so both import styles receive
# the same hardened class while the PR-188 implementation remains untouched.
install_authenticated_ingress(_delivery)

DeliveryDecision = _delivery.DeliveryDecision
DeliveryLimits = _delivery.DeliveryLimits
DeliveryOutcome = _delivery.DeliveryOutcome
FailedTransactionPolicy = _delivery.FailedTransactionPolicy
HeliusDeliveryConfig = _delivery.HeliusDeliveryConfig
HeliusDeliveryPlane = _delivery.HeliusDeliveryPlane
HeliusDeliveryStore = _delivery.HeliusDeliveryStore

from .rooted_recovery import (
    RecoveryOutcome,
    RecoveryPolicy,
    RecoveryStatus,
    RootedBackfillResult,
    RootedRecoveryStore,
    RootedRecoveryWorker,
    VerifiedProviderEvent,
)

__all__ = [
    "CredentialBinding",
    "CredentialState",
    "DeliveryDecision",
    "DeliveryLimits",
    "DeliveryOutcome",
    "FailedTransactionPolicy",
    "HeliusDeliveryConfig",
    "HeliusDeliveryPlane",
    "HeliusDeliveryStore",
    "InboundRequestContext",
    "IngressConnectionMetadata",
    "IngressGatewayPolicy",
    "IngressRejectReason",
    "IngressRejected",
    "RecoveryOutcome",
    "RecoveryPolicy",
    "RecoveryStatus",
    "RootedBackfillResult",
    "RootedRecoveryStore",
    "RootedRecoveryWorker",
    "VerifiedProviderEvent",
    "authenticate_inbound_request",
]
