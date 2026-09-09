"""Canonical core-v1 provider/discovery -> exact-attempt materialization.

The materializer is deliberately sender-free.  It accepts only already-reviewed,
rooted provider/discovery evidence plus exact typed economic inputs and emits the
existing :class:`ExactAttemptRuntimeItem` contract.  A raw provider handoff is
never itself an executable attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Protocol, Sequence

from src.config.runtime import RuntimeConfig, RuntimeMode
from src.durability import AttemptKey
from src.economics.capital import CapitalCandidate
from src.economics.durable_reservations import WalletBalanceSnapshot
from src.paper_shadow.a2_exact_attempt_runtime import ExactAttemptRuntimeItem
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3ProviderEvidenceState,
)
from src.paper_shadow.exact_attempt_pr152 import (
    ExactAttemptRequest,
    ProviderExecutionEvidence,
)
from src.paper_shadow.atomic_vertical import AtomicVerticalCandidate
from src.planning.atomic_marginfi_jupiter import CapitalReservationEvidence

CORE_V1_PROFILE_ID = "core-marginfi-jupiter-v1"
CORE_V1_SCHEMA = "core-v1.exact-attempt-materialization.v1"
CORE_V1_BLOCKED_EXTERNAL = "CORE_V1_BLOCKED_EXTERNAL"


class CoreV1ExternalBlock(RuntimeError):
    """Required real provider/deployment evidence is unavailable."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be lowercase sha256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be lowercase sha256") from exc
    if value.lower() != value:
        raise ValueError(f"{label} must be lowercase sha256")


@dataclass(frozen=True, slots=True)
class CoreV1ReleaseProfile:
    """Immutable first-release scope; it grants no live capability."""

    profile_id: str
    strategy: str
    lender: str
    router: str
    cluster: str
    genesis_hash: str
    transport: str
    live_enabled: bool = False

    def __post_init__(self) -> None:
        expected = (
            self.profile_id == CORE_V1_PROFILE_ID,
            self.strategy == "circular_arbitrage",
            self.lender == "marginfi",
            self.router == "jupiter",
            self.transport in {"rpc", "rpc+jito"},
            self.live_enabled is False,
        )
        if not all(expected):
            raise ValueError("CORE_V1_PROFILE_SCOPE_MISMATCH")
        if not self.cluster.strip() or not self.genesis_hash.strip():
            raise ValueError("CORE_V1_CLUSTER_IDENTITY_REQUIRED")


class CoreV1CandidateFactory(Protocol):
    def __call__(
        self, reservation: CapitalReservationEvidence
    ) -> AtomicVerticalCandidate: ...


@dataclass(frozen=True, slots=True)
class CoreV1AttemptDraft:
    """Complete non-live inputs from one admitted discovery/provider observation."""

    profile_id: str
    release_id: str
    policy_bundle_hash: str
    source_delivery_id: str
    source_evidence_hash: str
    plan_hash: str
    attempt_generation: int
    capital_candidate: CapitalCandidate
    wallet_snapshot: WalletBalanceSnapshot
    provider_evidence: ProviderExecutionEvidence
    discovery_slot: int
    candidate_factory: Callable[[CapitalReservationEvidence], AtomicVerticalCandidate]

    def __post_init__(self) -> None:
        if self.profile_id != CORE_V1_PROFILE_ID:
            raise ValueError("CORE_V1_DRAFT_PROFILE_MISMATCH")
        for label, value in (
            ("release_id", self.release_id),
            ("source_delivery_id", self.source_delivery_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} is required")
        for label, value in (
            ("policy_bundle_hash", self.policy_bundle_hash),
            ("source_evidence_hash", self.source_evidence_hash),
            ("plan_hash", self.plan_hash),
        ):
            _require_sha256(value, label)
        if type(self.attempt_generation) is not int or self.attempt_generation < 1:
            raise ValueError("attempt_generation must be positive integer")
        if type(self.discovery_slot) is not int or self.discovery_slot < 0:
            raise ValueError("discovery_slot must be non-negative integer")

    @property
    def materialization_hash(self) -> str:
        return _hash_json(
            {
                "schema": CORE_V1_SCHEMA,
                "profile_id": self.profile_id,
                "release_id": self.release_id,
                "policy_bundle_hash": self.policy_bundle_hash,
                "source_delivery_id": self.source_delivery_id,
                "source_evidence_hash": self.source_evidence_hash,
                "plan_hash": self.plan_hash,
                "attempt_generation": self.attempt_generation,
                "candidate_id": self.capital_candidate.candidate_id,
                "provider_evidence_hash": self.provider_evidence.evidence_hash,
                "discovery_slot": self.discovery_slot,
            }
        )


class CoreV1AttemptMaterializer:
    """Fail-closed bridge into the existing exact-attempt runtime contract."""

    def __init__(
        self,
        config: RuntimeConfig,
        profile: CoreV1ReleaseProfile,
        *,
        release_id: str,
        policy_bundle_hash: str,
    ) -> None:
        if not release_id.strip():
            raise ValueError("CORE_V1_RELEASE_ID_REQUIRED")
        _require_sha256(policy_bundle_hash, "policy_bundle_hash")
        self.config = config
        self.profile = profile
        self.release_id = release_id
        self.policy_bundle_hash = policy_bundle_hash
        self._validate_static_scope()

    def _validate_static_scope(self) -> None:
        if self.profile.cluster != self.config.cluster.name:
            raise ValueError("CORE_V1_CLUSTER_NAME_MISMATCH")
        if self.profile.genesis_hash != self.config.cluster.genesis_hash:
            raise ValueError("CORE_V1_GENESIS_MISMATCH")
        if not self.config.providers.jupiter.enabled:
            raise ValueError("CORE_V1_JUPITER_DISABLED")
        if not self.config.providers.marginfi.enabled:
            raise ValueError("CORE_V1_MARGINFI_DISABLED")
        mode = self.config.strategies.circular_arbitrage
        if mode not in {RuntimeMode.PAPER, RuntimeMode.SHADOW}:
            raise ValueError("CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED")

    def materialize(self, draft: CoreV1AttemptDraft) -> ExactAttemptRuntimeItem:
        if type(draft) is not CoreV1AttemptDraft:
            raise TypeError("CORE_V1_CANONICAL_DRAFT_REQUIRED")
        if draft.release_id != self.release_id:
            raise ValueError("CORE_V1_RELEASE_DRIFT")
        if draft.policy_bundle_hash != self.policy_bundle_hash:
            raise ValueError("CORE_V1_POLICY_DRIFT")
        if draft.wallet_snapshot.cluster_genesis != self.profile.genesis_hash:
            raise ValueError("CORE_V1_WALLET_GENESIS_MISMATCH")
        if (
            self.config.wallet.public_key is not None
            and draft.wallet_snapshot.wallet_pubkey != self.config.wallet.public_key
        ):
            raise ValueError("CORE_V1_WALLET_IDENTITY_MISMATCH")
        blockers = draft.provider_evidence.blockers(
            now_ns=(
                draft.wallet_snapshot.captured_at_ns
                if draft.wallet_snapshot.captured_at_ns is not None
                else draft.provider_evidence.captured_at_ns
            ),
            discovery_slot=draft.discovery_slot,
        )
        if blockers:
            raise ValueError("CORE_V1_PROVIDER_EVIDENCE_BLOCKED:" + ",".join(blockers))
        attempt_key = AttemptKey(
            logical_opportunity_id=draft.capital_candidate.candidate_id,
            plan_hash=draft.plan_hash,
            generation=draft.attempt_generation,
        )
        prefix = draft.materialization_hash
        request = ExactAttemptRequest(
            attempt_key=attempt_key,
            capital_candidate=draft.capital_candidate,
            wallet_snapshot=draft.wallet_snapshot,
            provider_evidence=draft.provider_evidence,
            discovery_slot=draft.discovery_slot,
            candidate_factory=draft.candidate_factory,
            reserve_idempotency_key=f"core-v1:reserve:{prefix}",
            release_idempotency_key=f"core-v1:release:{prefix}",
            final_fee_idempotency_key=f"core-v1:final-fee:{prefix}",
        )
        return ExactAttemptRuntimeItem(
            request=request,
            attempt_generation=draft.attempt_generation,
            runtime_idempotency_key=f"core-v1:runtime:{prefix}",
        )


class CoreV1DraftSource(Protocol):
    def __call__(self) -> Sequence[CoreV1AttemptDraft]: ...


class CoreV1MaterializedBatchSource:
    """A3 source that emits exact items only; no raw handoff may pass through."""

    def __init__(
        self,
        materializer: CoreV1AttemptMaterializer,
        source: CoreV1DraftSource,
        *,
        max_items: int = 100,
    ) -> None:
        if type(max_items) is not int or not 1 <= max_items <= 1000:
            raise ValueError("max_items must be in [1, 1000]")
        self.materializer = materializer
        self.source = source
        self.max_items = max_items

    def __call__(self) -> A3ExactAttemptBatch:
        try:
            drafts = tuple(self.source())
        except CoreV1ExternalBlock as exc:
            reason = str(exc) or CORE_V1_BLOCKED_EXTERNAL
            evidence_hash = _hash_json({"schema": CORE_V1_SCHEMA, "reason": reason})
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(evidence_hash, False, (reason,))
            )
        if len(drafts) > self.max_items:
            reason = "CORE_V1_BATCH_LIMIT_EXCEEDED"
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(
                    _hash_json({"reason": reason}), False, (reason,)
                )
            )
        if not drafts:
            # An admitted, healthy producer with zero opportunities is NO_TRADE.
            evidence_hash = _hash_json(
                {
                    "schema": CORE_V1_SCHEMA,
                    "profile_id": self.materializer.profile.profile_id,
                    "release_id": self.materializer.release_id,
                    "items": [],
                }
            )
            return A3ExactAttemptBatch(A3ProviderEvidenceState(evidence_hash, True), ())
        try:
            items = tuple(self.materializer.materialize(draft) for draft in drafts)
        except (TypeError, ValueError) as exc:
            reason = str(exc) or "CORE_V1_MATERIALIZATION_FAILED"
            evidence_hash = _hash_json({"schema": CORE_V1_SCHEMA, "reason": reason})
            return A3ExactAttemptBatch(
                A3ProviderEvidenceState(evidence_hash, False, (reason,))
            )
        evidence_hash = _hash_json(
            {
                "schema": CORE_V1_SCHEMA,
                "profile_id": self.materializer.profile.profile_id,
                "release_id": self.materializer.release_id,
                "materializations": [draft.materialization_hash for draft in drafts],
            }
        )
        return A3ExactAttemptBatch(A3ProviderEvidenceState(evidence_hash, True), items)


class BlockedCoreV1DraftSource:
    """Explicit installed state when real core-v1 producer evidence is absent."""

    blocker = CORE_V1_BLOCKED_EXTERNAL

    def __call__(self) -> Sequence[CoreV1AttemptDraft]:
        raise CoreV1ExternalBlock(self.blocker)


__all__ = [
    "CORE_V1_BLOCKED_EXTERNAL",
    "CORE_V1_PROFILE_ID",
    "CoreV1AttemptDraft",
    "CoreV1ExternalBlock",
    "CoreV1AttemptMaterializer",
    "CoreV1DraftSource",
    "CoreV1MaterializedBatchSource",
    "CoreV1ReleaseProfile",
]
