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
from typing import Protocol, Sequence

from src.config.runtime import RuntimeConfig, RuntimeMode
from src.durability import AttemptKey
from src.economics.capital import CapitalCandidate
from src.economics.durable_reservations import WalletBalanceSnapshot
from src.paper_shadow.a2_exact_attempt_runtime import ExactAttemptRuntimeItem
from src.lending.financing import (
    FINANCING_CONTRACT_VERSION,
    FinancingEvidence,
    validate_financing_binding,
)
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3ProviderEvidenceState,
)
from src.paper_shadow.exact_attempt_pr152 import (
    CandidateFactory,
    ExactAttemptRequest,
    ProviderExecutionEvidence,
)

CORE_V1_PROFILE_ID = "core-marginfi-jupiter-v1"
CORE_V1_LEGACY_SCHEMA = "core-v1.exact-attempt-materialization.v1"
CORE_V1_SCHEMA = "core-v1.exact-attempt-materialization.v2"
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
    """Immutable lender-bound profile; the historical profile remains exact."""

    profile_id: str
    strategy: str
    lender: str
    router: str
    cluster: str
    genesis_hash: str
    transport: str
    live_enabled: bool = False
    profile_generation: int = 1
    financing_contract_version: str = FINANCING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.lender.strip():
            raise ValueError("CORE_V1_PROFILE_IDENTITY_REQUIRED")
        expected = (
            self.strategy == "circular_arbitrage",
            self.router == "jupiter",
            self.transport in {"rpc", "rpc+jito"},
            self.live_enabled is False,
            type(self.profile_generation) is int and self.profile_generation >= 1,
            self.financing_contract_version == FINANCING_CONTRACT_VERSION,
        )
        if not all(expected):
            raise ValueError("CORE_V1_PROFILE_SCOPE_MISMATCH")
        if self.profile_id == CORE_V1_PROFILE_ID:
            if self.lender != "marginfi":
                raise ValueError("CORE_V1_LEGACY_PROFILE_LENDER_MISMATCH")
            if self.profile_generation != 1:
                raise ValueError("CORE_V1_LEGACY_PROFILE_GENERATION_MISMATCH")
        if not self.cluster.strip() or not self.genesis_hash.strip():
            raise ValueError("CORE_V1_CLUSTER_IDENTITY_REQUIRED")


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
    candidate_factory: CandidateFactory
    profile_generation: int = 1
    financing_evidence: FinancingEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("CORE_V1_DRAFT_PROFILE_REQUIRED")
        if type(self.profile_generation) is not int or self.profile_generation < 1:
            raise ValueError("profile_generation must be positive integer")
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
                "profile_generation": self.profile_generation,
                "financing_evidence_digest": (
                    None
                    if self.financing_evidence is None
                    else self.financing_evidence.digest
                ),
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
        if (
            self.profile.lender == "marginfi"
            and not self.config.providers.marginfi.enabled
        ):
            raise ValueError("CORE_V1_MARGINFI_DISABLED")
        mode = self.config.strategies.circular_arbitrage
        if mode not in {RuntimeMode.PAPER, RuntimeMode.SHADOW}:
            raise ValueError("CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED")

    def materialize(self, draft: CoreV1AttemptDraft) -> ExactAttemptRuntimeItem:
        if type(draft) is not CoreV1AttemptDraft:
            raise TypeError("CORE_V1_CANONICAL_DRAFT_REQUIRED")
        if draft.profile_id != self.profile.profile_id:
            raise ValueError("CORE_V1_DRAFT_PROFILE_MISMATCH")
        if draft.profile_generation != self.profile.profile_generation:
            raise ValueError("CORE_V1_PROFILE_GENERATION_MISMATCH")
        if draft.financing_evidence is not None:
            validate_financing_binding(
                lender_id=self.profile.lender,
                deployment_generation=self.profile.profile_generation,
                evidence=draft.financing_evidence,
            )
        elif self.profile.lender != "marginfi" or self.profile.profile_generation != 1:
            raise ValueError("CORE_V1_FINANCING_EVIDENCE_REQUIRED")
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
        if self.profile.lender != "marginfi":
            if draft.provider_evidence.financing_lender != self.profile.lender:
                raise ValueError("CORE_V1_PROVIDER_FINANCING_LENDER_MISMATCH")
            if draft.provider_evidence.financing_program_hash is None:
                raise ValueError("CORE_V1_PROVIDER_FINANCING_PROGRAM_HASH_REQUIRED")
            if draft.financing_evidence is None:
                raise ValueError("CORE_V1_FINANCING_EVIDENCE_REQUIRED")
            if (
                draft.provider_evidence.financing_program_hash
                != draft.financing_evidence.evidence_sha256
            ):
                raise ValueError("CORE_V1_PROVIDER_FINANCING_PROGRAM_HASH_MISMATCH")
        elif draft.provider_evidence.financing_lender is not None:
            raise ValueError("CORE_V1_LEGACY_PROVIDER_FINANCING_IDENTITY_FORBIDDEN")
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


def _batch_profile_identity(profile: object) -> tuple[str, int, str]:
    profile_id = getattr(profile, "profile_id", None)
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("CORE_V1_BATCH_PROFILE_IDENTITY_REQUIRED")
    generation = getattr(profile, "profile_generation", None)
    lender = getattr(profile, "lender", None)
    if profile_id == CORE_V1_PROFILE_ID:
        if generation is None:
            generation = 1
        if lender is None:
            lender = "marginfi"
    if type(generation) is not int or generation < 1:
        raise ValueError("CORE_V1_BATCH_PROFILE_GENERATION_REQUIRED")
    if not isinstance(lender, str) or not lender.strip():
        raise ValueError("CORE_V1_BATCH_LENDER_REQUIRED")
    return profile_id, generation, lender


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
        profile_id, profile_generation, lender = _batch_profile_identity(
            self.materializer.profile
        )
        if not drafts:
            evidence_hash = _hash_json(
                {
                    "schema": CORE_V1_SCHEMA,
                    "profile_id": profile_id,
                    "profile_generation": profile_generation,
                    "lender": lender,
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
                "profile_id": profile_id,
                "profile_generation": profile_generation,
                "lender": lender,
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
    "CORE_V1_LEGACY_SCHEMA",
    "CORE_V1_PROFILE_ID",
    "CoreV1AttemptDraft",
    "CoreV1ExternalBlock",
    "CoreV1AttemptMaterializer",
    "CoreV1DraftSource",
    "CoreV1MaterializedBatchSource",
    "CoreV1ReleaseProfile",
]
