"""Core-v1 raw-finalized -> MPR-2610 economic-ledger producer.

The producer does not own persistence and cannot submit a transaction.  A
caller supplies immutable raw finalized evidence to an approved decoder; this
module derives repayment/economic-completeness decisions, invokes the existing
MPR-2610 classifier, and hands one deterministic commit command to the existing
durable lifecycle/capital owner.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Protocol

from src.execution.finalized_economic_ledger import (
    AttemptEconomicLineage,
    EconomicPosting,
    FinalizedEconomicInput,
    FinalizedEconomicLedger,
    FinalizedEconomicOutcome,
    classify_finalized_economics,
)

CORE_V1_FINALIZED_SCHEMA = "core-v1.finalized-settlement-producer.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _strict_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a non-bool integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be sha256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be sha256") from exc
    return value


@dataclass(frozen=True, slots=True)
class DecodedCoreV1FinalizedEvidence:
    """Strict output of the approved raw transaction/protocol decoder."""

    attempt_id: str
    attempt_generation: int
    message_hash: str
    signed_transaction_digest: str
    primary_signature: str
    confirmation_status: str
    finalized_slot: int
    release_hash: str
    config_hash: str
    policy_hash: str
    cluster_genesis_hash: str
    raw_evidence_hash: str
    meta_err: object | None
    payer_pre_lamports: int | None
    payer_post_lamports: int | None
    meta_fee_lamports: int | None
    marginfi_liability_pre_base_units: int | None
    marginfi_liability_post_base_units: int | None
    marginfi_required_repayment_base_units: int | None
    marginfi_observed_repayment_base_units: int | None
    postings: tuple[EconomicPosting, ...]
    decode_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.attempt_id.strip() or not self.primary_signature.strip():
            raise ValueError("attempt/signature identity required")
        _strict_int(self.attempt_generation, "attempt_generation", minimum=1)
        _strict_int(self.finalized_slot, "finalized_slot", minimum=0)
        for hash_label, hash_value in (
            ("message_hash", self.message_hash),
            ("signed_transaction_digest", self.signed_transaction_digest),
            ("release_hash", self.release_hash),
            ("config_hash", self.config_hash),
            ("policy_hash", self.policy_hash),
            ("cluster_genesis_hash", self.cluster_genesis_hash),
            ("raw_evidence_hash", self.raw_evidence_hash),
        ):
            _sha256(hash_value, hash_label)
        if not self.confirmation_status.strip():
            raise ValueError("confirmation_status required")
        pairs = (
            (self.payer_pre_lamports, self.payer_post_lamports, "payer balances"),
            (
                self.marginfi_liability_pre_base_units,
                self.marginfi_liability_post_base_units,
                "MarginFi liability",
            ),
        )
        for left, right, pair_label in pairs:
            if (left is None) != (right is None):
                raise ValueError(f"{pair_label} must be paired")
            if left is not None:
                _strict_int(left, f"{pair_label}.pre", minimum=0)
                _strict_int(right, f"{pair_label}.post", minimum=0)
        for amount_label, amount_value in (
            ("meta_fee_lamports", self.meta_fee_lamports),
            (
                "marginfi_required_repayment",
                self.marginfi_required_repayment_base_units,
            ),
            (
                "marginfi_observed_repayment",
                self.marginfi_observed_repayment_base_units,
            ),
        ):
            if amount_value is not None:
                _strict_int(amount_value, amount_label, minimum=0)
        if any(not isinstance(item, str) or not item for item in self.decode_blockers):
            raise ValueError("decode blockers must be non-empty strings")

    @property
    def marginfi_repayment_proven(self) -> bool:
        values = (
            self.marginfi_liability_pre_base_units,
            self.marginfi_liability_post_base_units,
            self.marginfi_required_repayment_base_units,
            self.marginfi_observed_repayment_base_units,
        )
        if any(value is None for value in values):
            return False
        liability_pre, liability_post, required, observed = values
        assert liability_pre is not None
        assert liability_post is not None
        assert required is not None
        assert observed is not None
        return liability_post <= liability_pre and observed >= required

    @property
    def economics_complete(self) -> bool:
        if self.decode_blockers:
            return False
        if self.confirmation_status.strip().lower() != "finalized":
            return False
        if self.meta_err is None and not self.marginfi_repayment_proven:
            return False
        return bool(self.postings)


class CoreV1RawFinalizedDecoder(Protocol):
    """Approved decoder of immutable getTransaction/protocol evidence."""

    decoder_identity: str

    def decode(self, raw: Mapping[str, Any]) -> DecodedCoreV1FinalizedEvidence: ...


@dataclass(frozen=True, slots=True)
class CoreV1FinalizedCommit:
    schema_version: str
    decoder_identity: str
    source_hash: str
    ledger: FinalizedEconomicLedger
    release_capital: bool
    quarantine_capital: bool

    def __post_init__(self) -> None:
        if self.schema_version != CORE_V1_FINALIZED_SCHEMA:
            raise ValueError("finalized commit schema mismatch")
        if not self.decoder_identity.strip():
            raise ValueError("decoder identity required")
        _sha256(self.source_hash, "source_hash")
        if self.release_capital and self.quarantine_capital:
            raise ValueError("capital cannot be released and quarantined")


class CoreV1FinalizedCommitSink(Protocol):
    """Existing lifecycle/capital owner; this module never opens a database."""

    def commit_finalized_economics(self, command: CoreV1FinalizedCommit) -> object: ...


class CoreV1FinalizedSettlementProducer:
    """Derive one MPR-2610 ledger from raw evidence and no caller success booleans."""

    def __init__(self, decoder: CoreV1RawFinalizedDecoder) -> None:
        identity = getattr(decoder, "decoder_identity", None)
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("CORE_V1_FINALIZED_DECODER_IDENTITY_REQUIRED")
        self.decoder = decoder

    def classify(self, raw: Mapping[str, Any]) -> CoreV1FinalizedCommit:
        # Hash the complete immutable input before any semantic decoding.
        source_hash = _hash_json(raw)
        decoded = self.decoder.decode(raw)
        if decoded.raw_evidence_hash != source_hash:
            raise ValueError("CORE_V1_FINALIZED_RAW_EVIDENCE_HASH_MISMATCH")
        lineage = AttemptEconomicLineage(
            attempt_id=decoded.attempt_id,
            attempt_generation=decoded.attempt_generation,
            message_hash=decoded.message_hash,
            signed_transaction_digest=decoded.signed_transaction_digest,
            primary_signature=decoded.primary_signature,
            finalized_slot=decoded.finalized_slot,
            release_hash=decoded.release_hash,
            config_hash=decoded.config_hash,
            policy_hash=decoded.policy_hash,
            cluster_genesis_hash=decoded.cluster_genesis_hash,
            raw_evidence_hash=decoded.raw_evidence_hash,
        )
        ledger = classify_finalized_economics(
            FinalizedEconomicInput(
                lineage=lineage,
                confirmation_status=decoded.confirmation_status,
                meta_err=decoded.meta_err,
                marginfi_repayment_proven=decoded.marginfi_repayment_proven,
                economics_complete=decoded.economics_complete,
                postings=decoded.postings,
                payer_pre_lamports=decoded.payer_pre_lamports,
                payer_post_lamports=decoded.payer_post_lamports,
                meta_fee_lamports=decoded.meta_fee_lamports,
            )
        )
        release_states = {
            FinalizedEconomicOutcome.FINALIZED_FAILURE_COSTED,
            FinalizedEconomicOutcome.FINALIZED_REALIZED_LOSS,
            FinalizedEconomicOutcome.FINALIZED_REALIZED_BREAK_EVEN,
            FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT,
            FinalizedEconomicOutcome.FINALIZED_REALIZED_PARTIAL,
        }
        release_capital = ledger.outcome in release_states
        return CoreV1FinalizedCommit(
            schema_version=CORE_V1_FINALIZED_SCHEMA,
            decoder_identity=self.decoder.decoder_identity,
            source_hash=source_hash,
            ledger=ledger,
            release_capital=release_capital,
            quarantine_capital=not release_capital,
        )

    def classify_and_commit(
        self,
        raw: Mapping[str, Any],
        *,
        sink: CoreV1FinalizedCommitSink,
    ) -> object:
        command = self.classify(raw)
        return sink.commit_finalized_economics(command)


__all__ = [
    "CORE_V1_FINALIZED_SCHEMA",
    "CoreV1FinalizedCommit",
    "CoreV1FinalizedCommitSink",
    "CoreV1FinalizedSettlementProducer",
    "CoreV1RawFinalizedDecoder",
    "DecodedCoreV1FinalizedEvidence",
]
