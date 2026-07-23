"""MEGA-PR-02 V5 finalized-message evidence contract.

This module is additive and live-disabled. It defines the fail-closed contract that
V5 requires before permit issuance or signer authorization may trust an exact
message: one hardened compiler/finalizer authority, rooted inputs, causal slot
ordering, final compute-budget/landing-cost binding, post-final blockhash
viability and mandatory raw snapshots for all economically relevant writable
accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Final

_HASH: Final = re.compile(r"^[0-9a-f]{64}$")
PROTOCOL_WIRE_SIZE_LIMIT_BYTES: Final = 1232
HARDENED_COMPILER_ID: Final = "HardenedExactCompiler"


class FinalizedMessageStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class FinalizedMessageReason(str, Enum):
    READY = "ready"
    UNHARDENED_COMPILER = "unhardened_compiler"
    ALT_METADATA_NOT_RAW_DERIVED = "alt_metadata_not_raw_derived"
    ALT_DEACTIVATED = "alt_deactivated"
    WIRE_SIZE_LIMIT_EXCEEDED = "wire_size_limit_exceeded"
    INPUT_PROVENANCE_MISSING = "input_provenance_missing"
    MIN_CONTEXT_SLOT_ZERO = "min_context_slot_zero"
    SLOT_REGRESSION = "slot_regression"
    PROVIDER_OR_FORK_DRIFT = "provider_or_fork_drift"
    BLOCKHASH_NOT_FINAL_VALID = "blockhash_not_final_valid"
    BLOCKHASH_MARGIN_INSUFFICIENT = "blockhash_margin_insufficient"
    COMPUTE_BUDGET_NOT_FINALIZED = "compute_budget_not_finalized"
    COMPUTE_BUDGET_NOT_BOUND_TO_MESSAGE = "compute_budget_not_bound_to_message"
    MONITORED_ACCOUNT_MISSING = "monitored_account_missing"
    DOWNSTREAM_EVIDENCE_HASH_MISMATCH = "downstream_evidence_hash_mismatch"


@dataclass(frozen=True, slots=True)
class RootedInputEvidence:
    provider_id: str
    genesis_hash: str
    quote_slot: int
    market_slot: int
    oracle_slot: int
    alt_slot: int
    root_slot: int
    quote_hash: str
    market_hash: str
    oracle_hash: str

    def __post_init__(self) -> None:
        for name in ("provider_id",):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in ("genesis_hash", "quote_hash", "market_hash", "oracle_hash"):
            _require_hash(getattr(self, name), name)
        for name in ("quote_slot", "market_slot", "oracle_slot", "alt_slot", "root_slot"):
            _require_positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class AltTableEvidence:
    table_address: str
    owner: str
    raw_hash: str
    resolved_slot: int
    extension_slot: int
    deactivation_slot: int | None
    authority_hash: str
    addresses_hash: str
    genesis_hash: str
    metadata_source: str

    def __post_init__(self) -> None:
        for name in ("table_address", "owner", "metadata_source"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        for name in ("raw_hash", "authority_hash", "addresses_hash", "genesis_hash"):
            _require_hash(getattr(self, name), name)
        _require_positive(self.resolved_slot, "resolved_slot")
        _require_non_negative(self.extension_slot, "extension_slot")
        if self.deactivation_slot is not None:
            _require_non_negative(self.deactivation_slot, "deactivation_slot")

    @property
    def fingerprint(self) -> str:
        return _hash_json(_plain(self))

    @property
    def raw_derived(self) -> bool:
        return self.metadata_source == "on_chain_raw_bytes"


@dataclass(frozen=True, slots=True)
class ComputeBudgetFinalization:
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    loaded_account_data_size_limit_bytes: int
    landing_cost_cap_lamports: int
    final_observation_slot: int
    priority_fee_hash: str
    policy_hash: str
    emitted_compute_unit_limit_instructions: int
    emitted_compute_unit_price_instructions: int
    emitted_loaded_data_limit_instructions: int

    def __post_init__(self) -> None:
        for name in (
            "compute_unit_limit",
            "loaded_account_data_size_limit_bytes",
            "landing_cost_cap_lamports",
            "final_observation_slot",
        ):
            _require_positive(getattr(self, name), name)
        _require_non_negative(
            self.compute_unit_price_micro_lamports,
            "compute_unit_price_micro_lamports",
        )
        for name in ("priority_fee_hash", "policy_hash"):
            _require_hash(getattr(self, name), name)
        for name in (
            "emitted_compute_unit_limit_instructions",
            "emitted_compute_unit_price_instructions",
            "emitted_loaded_data_limit_instructions",
        ):
            _require_non_negative(getattr(self, name), name)

    @property
    def fingerprint(self) -> str:
        return _hash_json(_plain(self))

    @property
    def emits_exactly_one_policy(self) -> bool:
        return (
            self.emitted_compute_unit_limit_instructions == 1
            and self.emitted_compute_unit_price_instructions == 1
            and self.emitted_loaded_data_limit_instructions == 1
        )


@dataclass(frozen=True, slots=True)
class CompiledMessageFingerprint:
    compiler_id: str
    compiler_policy_hash: str
    plan_hash: str
    message_hash: str
    blockhash: str
    blockhash_source_slot: int
    alt_fingerprints: tuple[str, ...]
    static_account_hash: str
    instruction_hash: str
    wire_size_bytes: int
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    loaded_account_data_size_limit_bytes: int
    compute_budget_fingerprint: str
    generated_by_exact_simulation: bool

    def __post_init__(self) -> None:
        if not self.compiler_id or not self.blockhash:
            raise ValueError("compiler_id and blockhash are required")
        for name in (
            "compiler_policy_hash",
            "plan_hash",
            "message_hash",
            "static_account_hash",
            "instruction_hash",
            "compute_budget_fingerprint",
        ):
            _require_hash(getattr(self, name), name)
        for fingerprint in self.alt_fingerprints:
            _require_hash(fingerprint, "alt_fingerprint")
        for name in (
            "blockhash_source_slot",
            "wire_size_bytes",
            "compute_unit_limit",
            "loaded_account_data_size_limit_bytes",
        ):
            _require_positive(getattr(self, name), name)
        _require_non_negative(
            self.compute_unit_price_micro_lamports,
            "compute_unit_price_micro_lamports",
        )

    @property
    def hardened(self) -> bool:
        return self.compiler_id == HARDENED_COMPILER_ID and self.generated_by_exact_simulation


@dataclass(frozen=True, slots=True)
class CausalEvidenceTimeline:
    provider_id: str
    genesis_hash: str
    validation_slot: int
    provisional_simulation_slot: int
    compute_finalization_slot: int
    final_simulation_slot: int
    fee_quote_slot: int
    blockhash_check_slot: int
    validation_hash: str
    provisional_simulation_hash: str
    final_simulation_hash: str
    fee_quote_hash: str
    blockhash_check_hash: str

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        _require_hash(self.genesis_hash, "genesis_hash")
        for name in (
            "validation_slot",
            "provisional_simulation_slot",
            "compute_finalization_slot",
            "final_simulation_slot",
            "fee_quote_slot",
            "blockhash_check_slot",
        ):
            _require_positive(getattr(self, name), name)
        for name in (
            "validation_hash",
            "provisional_simulation_hash",
            "final_simulation_hash",
            "fee_quote_hash",
            "blockhash_check_hash",
        ):
            _require_hash(getattr(self, name), name)

    @property
    def monotonic(self) -> bool:
        slots = (
            self.validation_slot,
            self.provisional_simulation_slot,
            self.compute_finalization_slot,
            self.final_simulation_slot,
            self.fee_quote_slot,
            self.blockhash_check_slot,
        )
        return all(left <= right for left, right in zip(slots, slots[1:]))


@dataclass(frozen=True, slots=True)
class FinalBlockhashEvidence:
    blockhash: str
    checked_at_slot: int
    current_block_height: int
    last_valid_block_height: int
    remaining_height_margin: int
    is_blockhash_valid: bool
    response_hash: str

    def __post_init__(self) -> None:
        if not self.blockhash:
            raise ValueError("blockhash is required")
        _require_hash(self.response_hash, "response_hash")
        for name in (
            "checked_at_slot",
            "current_block_height",
            "last_valid_block_height",
            "remaining_height_margin",
        ):
            _require_positive(getattr(self, name), name)

    @property
    def remaining_height(self) -> int:
        return self.last_valid_block_height - self.current_block_height


@dataclass(frozen=True, slots=True)
class MandatoryAccountDerivation:
    payer: str
    writable_accounts: frozenset[str]
    token_accounts: frozenset[str]
    temporary_accounts: frozenset[str]
    protocol_vaults: frozenset[str]
    protocol_banks: frozenset[str]
    margin_accounts: frozenset[str]
    oracle_accounts: frozenset[str]
    cleanup_recipients: frozenset[str]
    caller_extra_accounts: frozenset[str]
    returned_raw_snapshot_accounts: frozenset[str]

    def __post_init__(self) -> None:
        if not self.payer:
            raise ValueError("payer is required")

    @property
    def mandatory_accounts(self) -> frozenset[str]:
        return frozenset(
            {self.payer}
            | set(self.writable_accounts)
            | set(self.token_accounts)
            | set(self.temporary_accounts)
            | set(self.protocol_vaults)
            | set(self.protocol_banks)
            | set(self.margin_accounts)
            | set(self.oracle_accounts)
            | set(self.cleanup_recipients)
        )

    @property
    def requested_accounts(self) -> frozenset[str]:
        return frozenset(set(self.mandatory_accounts) | set(self.caller_extra_accounts))

    @property
    def missing_raw_snapshots(self) -> tuple[str, ...]:
        return tuple(sorted(self.mandatory_accounts - self.returned_raw_snapshot_accounts))


@dataclass(frozen=True, slots=True)
class HardenedFinalizedMessageEvidence:
    rooted_inputs: RootedInputEvidence
    compiled_message: CompiledMessageFingerprint
    alt_tables: tuple[AltTableEvidence, ...]
    compute_budget: ComputeBudgetFinalization
    timeline: CausalEvidenceTimeline
    final_blockhash: FinalBlockhashEvidence
    monitored_accounts: MandatoryAccountDerivation
    min_context_slot: int
    permit_issuer_evidence_hash: str
    signer_authorization_evidence_hash: str

    def __post_init__(self) -> None:
        _require_positive(self.min_context_slot, "min_context_slot")
        _require_hash(self.permit_issuer_evidence_hash, "permit_issuer_evidence_hash")
        _require_hash(
            self.signer_authorization_evidence_hash,
            "signer_authorization_evidence_hash",
        )

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "rooted_inputs": _plain(self.rooted_inputs),
                "compiled_message": _plain(self.compiled_message),
                "alt_tables": _plain(self.alt_tables),
                "compute_budget": _plain(self.compute_budget),
                "timeline": _plain(self.timeline),
                "final_blockhash": _plain(self.final_blockhash),
                "monitored_accounts": _plain(self.monitored_accounts),
                "min_context_slot": self.min_context_slot,
            }
        )


@dataclass(frozen=True, slots=True)
class FinalizedMessageQualification:
    status: FinalizedMessageStatus
    reason: FinalizedMessageReason
    evidence_hash: str | None
    diagnostic: str

    @property
    def ready(self) -> bool:
        return self.status == FinalizedMessageStatus.READY


class HardenedFinalizedMessageAuthority:
    """Verify V5 exact-message integrity before downstream authorization."""

    def verify(
        self,
        evidence: HardenedFinalizedMessageEvidence,
    ) -> FinalizedMessageQualification:
        reason = self._first_blocker(evidence)
        if reason is not None:
            return FinalizedMessageQualification(
                FinalizedMessageStatus.BLOCKED,
                reason,
                None,
                reason.value,
            )
        return FinalizedMessageQualification(
            FinalizedMessageStatus.READY,
            FinalizedMessageReason.READY,
            evidence.evidence_hash,
            "hardened finalized message evidence is internally consistent",
        )

    def _first_blocker(
        self,
        evidence: HardenedFinalizedMessageEvidence,
    ) -> FinalizedMessageReason | None:
        if not evidence.compiled_message.hardened:
            return FinalizedMessageReason.UNHARDENED_COMPILER
        if evidence.compiled_message.wire_size_bytes > PROTOCOL_WIRE_SIZE_LIMIT_BYTES:
            return FinalizedMessageReason.WIRE_SIZE_LIMIT_EXCEEDED
        if not self._rooted_input_slots_present(evidence.rooted_inputs):
            return FinalizedMessageReason.INPUT_PROVENANCE_MISSING
        if evidence.min_context_slot <= 0:
            return FinalizedMessageReason.MIN_CONTEXT_SLOT_ZERO
        if not evidence.timeline.monotonic:
            return FinalizedMessageReason.SLOT_REGRESSION
        if not self._same_provider_and_fork(evidence):
            return FinalizedMessageReason.PROVIDER_OR_FORK_DRIFT
        alt_reason = self._alt_reason(evidence)
        if alt_reason is not None:
            return alt_reason
        compute_reason = self._compute_reason(evidence)
        if compute_reason is not None:
            return compute_reason
        blockhash_reason = self._blockhash_reason(evidence)
        if blockhash_reason is not None:
            return blockhash_reason
        if evidence.monitored_accounts.missing_raw_snapshots:
            return FinalizedMessageReason.MONITORED_ACCOUNT_MISSING
        if not self._downstream_hashes_match(evidence):
            return FinalizedMessageReason.DOWNSTREAM_EVIDENCE_HASH_MISMATCH
        return None

    @staticmethod
    def _rooted_input_slots_present(rooted: RootedInputEvidence) -> bool:
        return (
            rooted.quote_slot > 0
            and rooted.market_slot > 0
            and rooted.oracle_slot > 0
            and rooted.alt_slot > 0
            and rooted.root_slot >= max(
                rooted.quote_slot,
                rooted.market_slot,
                rooted.oracle_slot,
                rooted.alt_slot,
            )
        )

    @staticmethod
    def _same_provider_and_fork(evidence: HardenedFinalizedMessageEvidence) -> bool:
        return (
            evidence.rooted_inputs.provider_id == evidence.timeline.provider_id
            and evidence.rooted_inputs.genesis_hash == evidence.timeline.genesis_hash
            and all(
                alt.genesis_hash == evidence.rooted_inputs.genesis_hash
                for alt in evidence.alt_tables
            )
        )

    @staticmethod
    def _alt_reason(
        evidence: HardenedFinalizedMessageEvidence,
    ) -> FinalizedMessageReason | None:
        compiled_alts = set(evidence.compiled_message.alt_fingerprints)
        observed_alts = {alt.fingerprint for alt in evidence.alt_tables}
        if compiled_alts != observed_alts:
            return FinalizedMessageReason.ALT_METADATA_NOT_RAW_DERIVED
        for alt in evidence.alt_tables:
            if not alt.raw_derived:
                return FinalizedMessageReason.ALT_METADATA_NOT_RAW_DERIVED
            if alt.deactivation_slot is not None and alt.deactivation_slot <= evidence.min_context_slot:
                return FinalizedMessageReason.ALT_DEACTIVATED
        return None

    @staticmethod
    def _compute_reason(
        evidence: HardenedFinalizedMessageEvidence,
    ) -> FinalizedMessageReason | None:
        compute = evidence.compute_budget
        message = evidence.compiled_message
        if not compute.emits_exactly_one_policy:
            return FinalizedMessageReason.COMPUTE_BUDGET_NOT_FINALIZED
        if (
            message.compute_unit_limit != compute.compute_unit_limit
            or message.compute_unit_price_micro_lamports
            != compute.compute_unit_price_micro_lamports
            or message.loaded_account_data_size_limit_bytes
            != compute.loaded_account_data_size_limit_bytes
            or message.compute_budget_fingerprint != compute.fingerprint
        ):
            return FinalizedMessageReason.COMPUTE_BUDGET_NOT_BOUND_TO_MESSAGE
        if compute.final_observation_slot < evidence.timeline.compute_finalization_slot:
            return FinalizedMessageReason.COMPUTE_BUDGET_NOT_FINALIZED
        return None

    @staticmethod
    def _blockhash_reason(
        evidence: HardenedFinalizedMessageEvidence,
    ) -> FinalizedMessageReason | None:
        blockhash = evidence.final_blockhash
        if (
            blockhash.blockhash != evidence.compiled_message.blockhash
            or not blockhash.is_blockhash_valid
            or blockhash.checked_at_slot < evidence.timeline.final_simulation_slot
        ):
            return FinalizedMessageReason.BLOCKHASH_NOT_FINAL_VALID
        if blockhash.remaining_height < blockhash.remaining_height_margin:
            return FinalizedMessageReason.BLOCKHASH_MARGIN_INSUFFICIENT
        return None

    @staticmethod
    def _downstream_hashes_match(evidence: HardenedFinalizedMessageEvidence) -> bool:
        return (
            evidence.permit_issuer_evidence_hash == evidence.evidence_hash
            and evidence.signer_authorization_evidence_hash == evidence.evidence_hash
        )


def finalized_message_evidence_hash(
    evidence_without_downstream_hashes: HardenedFinalizedMessageEvidence,
) -> str:
    """Return the canonical hash consumed by permit issuer and signer."""
    return evidence_without_downstream_hashes.evidence_hash


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (frozenset, set)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    return value


def _hash_json(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_hash(value: str, name: str) -> None:
    if not _HASH.fullmatch(value):
        raise ValueError(f"{name} must be lower-case sha256")


def _require_positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "AltTableEvidence",
    "CausalEvidenceTimeline",
    "CompiledMessageFingerprint",
    "ComputeBudgetFinalization",
    "FinalBlockhashEvidence",
    "FinalizedMessageQualification",
    "FinalizedMessageReason",
    "FinalizedMessageStatus",
    "HARDENED_COMPILER_ID",
    "HardenedFinalizedMessageAuthority",
    "HardenedFinalizedMessageEvidence",
    "MandatoryAccountDerivation",
    "PROTOCOL_WIRE_SIZE_LIMIT_BYTES",
    "RootedInputEvidence",
    "finalized_message_evidence_hash",
]
