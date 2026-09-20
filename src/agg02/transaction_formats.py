"""Version-aware transaction-read contracts for SUPER-01 / PR-077.

The module does not invent a Solana v1 codec. A format is readable only when a
current capability report and an explicitly supplied decoder agree on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
from typing import Callable, Mapping

from .contracts import Agg02Error, canonical_hash


class TransactionFormat(StrEnum):
    LEGACY = "legacy"
    V0 = "v0"
    V1 = "v1"


Decoder = Callable[[bytes], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class TransactionReadCapabilityReport:
    provider_id: str
    chain_identity: str
    sdk_identity: str
    supported_formats: tuple[TransactionFormat, ...]
    evidence_sha256: str
    observed_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        if (
            not self.provider_id
            or not self.chain_identity
            or not self.sdk_identity
        ):
            raise Agg02Error("SUPER01_TRANSACTION_CAPABILITY_IDENTITY_REQUIRED")
        if len(self.supported_formats) != len(set(self.supported_formats)):
            raise Agg02Error("SUPER01_TRANSACTION_FORMAT_DUPLICATED")
        if (
            len(self.evidence_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.evidence_sha256)
        ):
            raise Agg02Error("SUPER01_TRANSACTION_CAPABILITY_EVIDENCE_INVALID")
        if (
            type(self.observed_at_ms) is not int
            or type(self.expires_at_ms) is not int
            or self.observed_at_ms < 0
            or self.expires_at_ms <= self.observed_at_ms
        ):
            raise Agg02Error("SUPER01_TRANSACTION_CAPABILITY_TIME_INVALID")

    @property
    def report_hash(self) -> str:
        return canonical_hash(
            {
                "provider_id": self.provider_id,
                "chain_identity": self.chain_identity,
                "sdk_identity": self.sdk_identity,
                "supported_formats": tuple(
                    item.value for item in self.supported_formats
                ),
                "evidence_sha256": self.evidence_sha256,
                "observed_at_ms": self.observed_at_ms,
                "expires_at_ms": self.expires_at_ms,
            }
        )

    def supports(self, format_id: TransactionFormat, *, now_ms: int) -> bool:
        return (
            type(now_ms) is int
            and self.observed_at_ms <= now_ms < self.expires_at_ms
            and format_id in self.supported_formats
        )


def qualify_transaction_read_capabilities(
    *,
    provider_id: str,
    chain_identity: str,
    sdk_identity: str,
    supported_formats: tuple[TransactionFormat, ...],
    evidence_sha256: str,
    observed_at_ms: int,
    expires_at_ms: int,
) -> TransactionReadCapabilityReport:
    return TransactionReadCapabilityReport(
        provider_id=provider_id,
        chain_identity=chain_identity,
        sdk_identity=sdk_identity,
        supported_formats=supported_formats,
        evidence_sha256=evidence_sha256,
        observed_at_ms=observed_at_ms,
        expires_at_ms=expires_at_ms,
    )


@dataclass(frozen=True, slots=True)
class DecodedTransactionEnvelope:
    format_id: TransactionFormat
    raw_sha256: str
    capability_hash: str
    signatures: tuple[str, ...]
    account_keys: tuple[str, ...]
    instruction_count: int
    fee_lamports: int | None
    resource_config: str | None
    decoder_identity: str


def decode_versioned_transaction_envelope(
    raw: bytes,
    *,
    declared_format: TransactionFormat,
    capability: TransactionReadCapabilityReport,
    now_ms: int,
    decoder_registry: Mapping[TransactionFormat, tuple[str, Decoder]],
) -> DecodedTransactionEnvelope:
    if not raw:
        raise Agg02Error("SUPER01_MALFORMED_ENVELOPE")
    if not capability.supports(declared_format, now_ms=now_ms):
        raise Agg02Error("SUPER01_PROVIDER_VERSION_UNSUPPORTED")
    decoder_entry = decoder_registry.get(declared_format)
    if decoder_entry is None:
        raise Agg02Error("SUPER01_SDK_CODEC_UNAVAILABLE")
    decoder_identity, decoder = decoder_entry
    if not decoder_identity:
        raise Agg02Error("SUPER01_SDK_CODEC_UNAVAILABLE")
    try:
        decoded = decoder(raw)
    except Exception as exc:
        raise Agg02Error("SUPER01_MALFORMED_ENVELOPE") from exc
    if not isinstance(decoded, Mapping):
        raise Agg02Error("SUPER01_RESPONSE_SCHEMA_MISMATCH")

    signatures_raw = decoded.get("signatures")
    accounts_raw = decoded.get("account_keys")
    instruction_count = decoded.get("instruction_count")
    fee_lamports = decoded.get("fee_lamports")
    resource_config = decoded.get("resource_config")
    if (
        not isinstance(signatures_raw, (tuple, list))
        or not all(isinstance(item, str) and item for item in signatures_raw)
        or not isinstance(accounts_raw, (tuple, list))
        or not all(isinstance(item, str) and item for item in accounts_raw)
        or not isinstance(instruction_count, int)
        or isinstance(instruction_count, bool)
        or instruction_count < 0
    ):
        raise Agg02Error("SUPER01_RESPONSE_SCHEMA_MISMATCH")
    if fee_lamports is not None and (
        not isinstance(fee_lamports, int)
        or isinstance(fee_lamports, bool)
        or fee_lamports < 0
    ):
        raise Agg02Error("SUPER01_AMBIGUOUS_FEE_EVIDENCE")
    if resource_config is not None and not isinstance(resource_config, str):
        raise Agg02Error("SUPER01_UNRECOGNIZED_CONFIG")

    return DecodedTransactionEnvelope(
        format_id=declared_format,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        capability_hash=capability.report_hash,
        signatures=tuple(signatures_raw),
        account_keys=tuple(accounts_raw),
        instruction_count=instruction_count,
        fee_lamports=fee_lamports,
        resource_config=resource_config,
        decoder_identity=decoder_identity,
    )


@dataclass(frozen=True, slots=True)
class TransactionResourceEvidence:
    format_id: TransactionFormat
    raw_sha256: str
    instruction_count: int
    fee_lamports: int | None
    fee_unit: str
    resource_config: str | None
    resource_hash: str


def normalize_format_specific_resources(
    envelope: DecodedTransactionEnvelope,
) -> TransactionResourceEvidence:
    payload = {
        "format_id": envelope.format_id.value,
        "raw_sha256": envelope.raw_sha256,
        "instruction_count": envelope.instruction_count,
        "fee_lamports": envelope.fee_lamports,
        "fee_unit": "lamports",
        "resource_config": envelope.resource_config,
        "decoder_identity": envelope.decoder_identity,
    }
    return TransactionResourceEvidence(
        format_id=envelope.format_id,
        raw_sha256=envelope.raw_sha256,
        instruction_count=envelope.instruction_count,
        fee_lamports=envelope.fee_lamports,
        fee_unit="lamports",
        resource_config=envelope.resource_config,
        resource_hash=canonical_hash(payload),
    )


@dataclass(frozen=True, slots=True)
class FormatCoverageGap:
    provider_id: str
    chain_identity: str
    requested_start: int
    requested_end: int
    format_id: TransactionFormat
    failure_code: str
    evidence_sha256: str
    checkpoint_advance_allowed: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requested_start, int)
            or isinstance(self.requested_start, bool)
            or not isinstance(self.requested_end, int)
            or isinstance(self.requested_end, bool)
            or self.requested_start < 0
            or self.requested_end < self.requested_start
        ):
            raise Agg02Error("SUPER01_INVALID_FORMAT_GAP_RANGE")
        if (
            not self.provider_id
            or not self.chain_identity
            or not self.failure_code
        ):
            raise Agg02Error("SUPER01_INVALID_FORMAT_GAP")
        if (
            len(self.evidence_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.evidence_sha256)
        ):
            raise Agg02Error("SUPER01_FORMAT_GAP_EVIDENCE_INVALID")
        if self.checkpoint_advance_allowed:
            raise Agg02Error("SUPER01_NO_SILENT_ADVANCE")


def record_format_coverage_gap(
    *,
    capability: TransactionReadCapabilityReport,
    requested_start: int,
    requested_end: int,
    format_id: TransactionFormat,
    failure_code: str,
    evidence_sha256: str,
) -> FormatCoverageGap:
    return FormatCoverageGap(
        provider_id=capability.provider_id,
        chain_identity=capability.chain_identity,
        requested_start=requested_start,
        requested_end=requested_end,
        format_id=format_id,
        failure_code=failure_code,
        evidence_sha256=evidence_sha256,
    )


__all__ = [
    "DecodedTransactionEnvelope",
    "FormatCoverageGap",
    "TransactionFormat",
    "TransactionReadCapabilityReport",
    "TransactionResourceEvidence",
    "decode_versioned_transaction_envelope",
    "normalize_format_specific_resources",
    "qualify_transaction_read_capabilities",
    "record_format_coverage_gap",
]
