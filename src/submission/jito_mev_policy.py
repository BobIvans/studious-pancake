"""PR-130 Jito unbundling and uncle-bandit protection policy.

The policy is intentionally transport-local and side-effect free. It gives the
canonical sender/release gates a deterministic way to prove that first-live Jito
submission does not rely on a standalone tip transaction or multi-transaction
bundle atomicity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .permit_bound import TransportKind

PR130_JITO_MEV_POLICY_SCHEMA_VERSION = "pr130.jito-mev-policy.v1"
PR130_FIRST_PRODUCTION_POLICY = "one-transaction-same-message-tip"


class JitoMevProtectionState(StrEnum):
    """Review state for one Jito payload policy evaluation."""

    NOT_JITO = "not_jito"
    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class JitoMevProtectionPolicy:
    """Static PR-130 policy for the first production Jito vertical."""

    schema_version: str = PR130_JITO_MEV_POLICY_SCHEMA_VERSION
    first_production_policy: str = PR130_FIRST_PRODUCTION_POLICY
    allow_multi_transaction_bundle: bool = False
    require_tip_in_primary_transaction: bool = True
    require_static_tip_account: bool = True
    bundle_status_is_settlement_proof: bool = False
    require_explicit_settlement_reconciliation: bool = True
    jitodontfront_policy_reviewed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "first_production_policy": self.first_production_policy,
            "allow_multi_transaction_bundle": self.allow_multi_transaction_bundle,
            "require_tip_in_primary_transaction": (
                self.require_tip_in_primary_transaction
            ),
            "require_static_tip_account": self.require_static_tip_account,
            "bundle_status_is_settlement_proof": self.bundle_status_is_settlement_proof,
            "require_explicit_settlement_reconciliation": (
                self.require_explicit_settlement_reconciliation
            ),
            "jitodontfront_policy_reviewed": self.jitodontfront_policy_reviewed,
        }


@dataclass(frozen=True, slots=True)
class JitoMevProtectionReadiness:
    """Deterministic PR-130 readiness result for one payload shape."""

    state: JitoMevProtectionState
    transport: TransportKind
    transaction_count: int
    tip_transaction_index: int | None
    bundle_only: bool
    tip_account_static: bool
    bundle_ack_treated_as_settlement: bool
    blockers: tuple[str, ...]
    policy: JitoMevProtectionPolicy

    @property
    def ready(self) -> bool:
        return self.state is JitoMevProtectionState.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.policy.schema_version,
            "state": self.state.value,
            "transport": self.transport.value,
            "transaction_count": self.transaction_count,
            "tip_transaction_index": self.tip_transaction_index,
            "bundle_only": self.bundle_only,
            "tip_account_static": self.tip_account_static,
            "bundle_ack_treated_as_settlement": self.bundle_ack_treated_as_settlement,
            "blockers": list(self.blockers),
            "policy": self.policy.to_dict(),
        }


def evaluate_pr130_jito_mev_policy(
    *,
    transport: TransportKind,
    transaction_count: int,
    tip_transaction_index: int | None,
    bundle_only: bool,
    tip_account_static: bool,
    bundle_ack_treated_as_settlement: bool,
    policy: JitoMevProtectionPolicy | None = None,
) -> JitoMevProtectionReadiness:
    """Evaluate the first-live Jito payload shape without network access."""

    active_policy = policy or JitoMevProtectionPolicy()
    if transaction_count <= 0:
        raise ValueError("transaction_count must be positive")
    if tip_transaction_index is not None and tip_transaction_index < 0:
        raise ValueError("tip_transaction_index must be non-negative when present")

    if transport is TransportKind.RPC:
        return JitoMevProtectionReadiness(
            JitoMevProtectionState.NOT_JITO,
            transport,
            transaction_count,
            tip_transaction_index,
            bundle_only,
            tip_account_static,
            bundle_ack_treated_as_settlement,
            (),
            active_policy,
        )

    blockers: list[str] = []
    if (
        transport is TransportKind.JITO_BUNDLE
        and not active_policy.allow_multi_transaction_bundle
    ):
        blockers.append("MULTI_TRANSACTION_JITO_BUNDLE_DISABLED_FOR_PR130")
    if transaction_count != 1:
        blockers.append("JITO_PAYLOAD_MUST_CONTAIN_EXACTLY_ONE_TRANSACTION")
    if tip_transaction_index is None:
        blockers.append("JITO_TIP_MISSING")
    elif tip_transaction_index >= transaction_count:
        blockers.append("JITO_TIP_INDEX_OUT_OF_RANGE")
    elif (
        active_policy.require_tip_in_primary_transaction
        and tip_transaction_index != 0
    ):
        blockers.append("STANDALONE_TIP_TRANSACTION_FORBIDDEN")
    if active_policy.require_static_tip_account and not tip_account_static:
        blockers.append("JITO_TIP_ACCOUNT_MUST_BE_STATIC_NO_ALT")
    if (
        bundle_ack_treated_as_settlement
        or active_policy.bundle_status_is_settlement_proof
    ):
        blockers.append("JITO_BUNDLE_STATUS_NOT_SETTLEMENT_PROOF")

    return JitoMevProtectionReadiness(
        JitoMevProtectionState.BLOCKED if blockers else JitoMevProtectionState.READY,
        transport,
        transaction_count,
        tip_transaction_index,
        bundle_only,
        tip_account_static,
        bundle_ack_treated_as_settlement,
        tuple(blockers),
        active_policy,
    )


__all__ = [
    "JitoMevProtectionPolicy",
    "JitoMevProtectionReadiness",
    "JitoMevProtectionState",
    "PR130_FIRST_PRODUCTION_POLICY",
    "PR130_JITO_MEV_POLICY_SCHEMA_VERSION",
    "evaluate_pr130_jito_mev_policy",
]
