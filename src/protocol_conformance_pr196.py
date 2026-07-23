"""Roadmap PR-196 external protocol conformance and rooted data-plane evidence.

This module is intentionally sender-free. It validates already-materialized,
read-only evidence for external protocols and provider contracts. It does not
open sockets, load wallets, sign messages, build transactions for submission, or
submit anything to RPC/Jito/Helius.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

PR196_SCHEMA_VERSION = "pr196.external-protocol-conformance.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ProtocolConformanceError(ValueError):
    """Fail-closed PR-196 validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class ProviderRole(StrEnum):
    EXECUTION_COMPOSABLE = "execution_composable"
    DISCOVERY_ONLY = "discovery_only"
    FORBIDDEN = "forbidden"


class EvidenceStatus(StrEnum):
    REVIEW_ONLY = "review_only"
    CREDENTIALED = "credentialed"
    ACCEPTED = "accepted"
    DISABLED = "disabled"


class DriftAction(StrEnum):
    AVAILABLE = "available"
    QUARANTINE = "quarantine"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class VersionedEvidence:
    """Versioned, expiring, reviewer-owned evidence envelope."""

    evidence_id: str
    schema_version: str
    status: EvidenceStatus
    collected_at: str
    expires_at: str
    source_hash: str
    reviewer: str

    def validate(self, *, now: datetime) -> None:
        _require_safe_id(self.evidence_id, "evidence_id")
        _require_safe_id(self.schema_version, "schema_version")
        _require_sha256(self.source_hash, "source_hash")
        _require_safe_id(self.reviewer, "reviewer")
        collected = _parse_utc(self.collected_at, "collected_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= collected:
            raise ProtocolConformanceError("PR196_EVIDENCE_EXPIRES_BEFORE_COLLECTION")
        if now >= expires:
            raise ProtocolConformanceError("PR196_EVIDENCE_EXPIRED")
        if self.status not in {EvidenceStatus.CREDENTIALED, EvidenceStatus.ACCEPTED}:
            raise ProtocolConformanceError("PR196_EVIDENCE_NOT_ACCEPTED")


@dataclass(frozen=True, slots=True)
class ProgramAttestation:
    """Read-only deployed Solana program/programdata attestation."""

    program_id: str
    loader_program_id: str
    programdata_address: str
    executable: bool
    deployed_program_hash: str
    programdata_hash: str
    idl_hash: str
    upgrade_authority: str | None = None

    def validate(self, *, allow_upgrade_authority: bool = False) -> None:
        for field_name in ("program_id", "loader_program_id", "programdata_address"):
            _require_safe_id(getattr(self, field_name), field_name)
        for field_name in ("deployed_program_hash", "programdata_hash", "idl_hash"):
            _require_sha256(getattr(self, field_name), field_name)
        if not self.executable:
            raise ProtocolConformanceError("PR196_PROGRAM_NOT_EXECUTABLE")
        if self.upgrade_authority and not allow_upgrade_authority:
            raise ProtocolConformanceError("PR196_PROGRAM_UPGRADE_AUTHORITY_PRESENT")


@dataclass(frozen=True, slots=True)
class MarginFiP0Evidence:
    """MarginFi/Project 0 protocol evidence required before execution admission."""

    evidence: VersionedEvidence
    sdk_package: str
    sdk_version: str
    sdk_deprecated: bool
    program: ProgramAttestation
    golden_vector_hashes: tuple[str, ...]
    flashloan_begin_instruction_hash: str
    flashloan_end_instruction_hash: str

    def validate(self, *, now: datetime) -> None:
        self.evidence.validate(now=now)
        if self.sdk_deprecated:
            raise ProtocolConformanceError("PR196_MARGINFI_SDK_DEPRECATED")
        if self.sdk_package != "@0dotxyz/p0-ts-sdk":
            raise ProtocolConformanceError("PR196_MARGINFI_P0_SDK_REQUIRED")
        _require_safe_id(self.sdk_version, "sdk_version")
        self.program.validate(allow_upgrade_authority=False)
        if len(self.golden_vector_hashes) < 2:
            raise ProtocolConformanceError("PR196_MARGINFI_GOLDEN_VECTORS_REQUIRED")
        for item in self.golden_vector_hashes:
            _require_sha256(item, "golden_vector_hash")
        _require_sha256(
            self.flashloan_begin_instruction_hash,
            "flashloan_begin_instruction_hash",
        )
        _require_sha256(
            self.flashloan_end_instruction_hash,
            "flashloan_end_instruction_hash",
        )
        if self.flashloan_begin_instruction_hash == self.flashloan_end_instruction_hash:
            raise ProtocolConformanceError("PR196_MARGINFI_BRACKET_HASH_COLLISION")


@dataclass(frozen=True, slots=True)
class JupiterBuildEvidence:
    """Jupiter Swap V2 build evidence, normalized before compiler use."""

    evidence: VersionedEvidence
    endpoint: str
    response_hash: str
    route_plan: tuple[Mapping[str, Any], ...]
    setup_instruction_hashes: tuple[str, ...] = ()
    swap_instruction_hash: str = ""
    cleanup_instruction_hashes: tuple[str, ...] = ()
    address_lookup_table_hashes: tuple[str, ...] = ()
    blockhash_metadata_hash: str = ""

    def validate(self, *, now: datetime) -> tuple[int, ...]:
        self.evidence.validate(now=now)
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or parsed.netloc != "api.jup.ag":
            raise ProtocolConformanceError("PR196_JUPITER_ENDPOINT_NOT_ALLOWED")
        if parsed.path != "/swap/v2/build":
            raise ProtocolConformanceError("PR196_JUPITER_BUILD_V2_REQUIRED")
        _require_sha256(self.response_hash, "response_hash")
        if not self.route_plan:
            raise ProtocolConformanceError("PR196_JUPITER_ROUTE_PLAN_REQUIRED")
        bps_values: list[int] = []
        for leg in self.route_plan:
            if "percent" in leg:
                raise ProtocolConformanceError("PR196_JUPITER_LEGACY_PERCENT_REJECTED")
            if "bps" not in leg:
                raise ProtocolConformanceError("PR196_JUPITER_BPS_REQUIRED")
            bps = _coerce_int(leg["bps"], "bps")
            if bps <= 0 or bps > 10_000:
                raise ProtocolConformanceError("PR196_JUPITER_BPS_OUT_OF_RANGE")
            if "programId" in leg:
                _require_safe_id(str(leg["programId"]), "programId")
            bps_values.append(bps)
        if sum(bps_values) != 10_000:
            raise ProtocolConformanceError("PR196_JUPITER_BPS_SUM_NOT_10000")
        _require_sha256(self.swap_instruction_hash, "swap_instruction_hash")
        for field_name in (
            "setup_instruction_hashes",
            "cleanup_instruction_hashes",
            "address_lookup_table_hashes",
        ):
            for item in getattr(self, field_name):
                _require_sha256(item, field_name)
        _require_sha256(self.blockhash_metadata_hash, "blockhash_metadata_hash")
        return tuple(bps_values)


@dataclass(frozen=True, slots=True)
class RootedRpcObservation:
    source_id: str
    source_group: str
    genesis_hash: str
    slot: int
    rooted_slot: int
    min_context_slot: int
    state_hash: str

    def validate(self) -> None:
        _require_safe_id(self.source_id, "source_id")
        _require_safe_id(self.source_group, "source_group")
        _require_sha256(self.genesis_hash, "genesis_hash")
        _require_sha256(self.state_hash, "state_hash")
        if self.slot < self.rooted_slot:
            raise ProtocolConformanceError("PR196_RPC_SLOT_BELOW_ROOT")
        if self.rooted_slot < self.min_context_slot:
            raise ProtocolConformanceError("PR196_RPC_ROOT_BELOW_MIN_CONTEXT")


@dataclass(frozen=True, slots=True)
class RootedRpcQuorum:
    observations: tuple[RootedRpcObservation, ...]
    required_independent_groups: int = 2

    def validate(self) -> str:
        if len(self.observations) < self.required_independent_groups:
            raise ProtocolConformanceError("PR196_RPC_QUORUM_TOO_SMALL")
        for observation in self.observations:
            observation.validate()
        genesis_hashes = {item.genesis_hash for item in self.observations}
        if len(genesis_hashes) != 1:
            raise ProtocolConformanceError("PR196_RPC_GENESIS_DISAGREEMENT")
        groups = {item.source_group for item in self.observations}
        if len(groups) < self.required_independent_groups:
            raise ProtocolConformanceError("PR196_RPC_INDEPENDENT_GROUPS_REQUIRED")
        state_hash_counts = Counter(item.state_hash for item in self.observations)
        state_hash, count = state_hash_counts.most_common(1)[0]
        if count < self.required_independent_groups:
            raise ProtocolConformanceError("PR196_RPC_STATE_HASH_NO_QUORUM")
        return state_hash


@dataclass(frozen=True, slots=True)
class ProviderRegistryEntry:
    provider_id: str
    role: ProviderRole
    evidence: VersionedEvidence | None
    allowed_endpoint_hosts: frozenset[str] = field(default_factory=frozenset)

    def validate(self, *, now: datetime) -> None:
        _require_safe_id(self.provider_id, "provider_id")
        for host in self.allowed_endpoint_hosts:
            _require_safe_host(host)
        if self.role is ProviderRole.EXECUTION_COMPOSABLE:
            if self.evidence is None:
                raise ProtocolConformanceError("PR196_EXECUTION_PROVIDER_EVIDENCE_REQUIRED")
            self.evidence.validate(now=now)
        if self.role is ProviderRole.FORBIDDEN and self.evidence is not None:
            raise ProtocolConformanceError("PR196_FORBIDDEN_PROVIDER_HAS_EVIDENCE")


@dataclass(frozen=True, slots=True)
class HeliusWebhookEvent:
    signature: str
    slot: int
    event_type: str
    source_delivery_id: str
    payload_hash: str

    def idempotency_key(self) -> str:
        _require_safe_id(self.signature, "signature")
        _require_safe_id(self.event_type, "event_type")
        _require_safe_id(self.source_delivery_id, "source_delivery_id")
        _require_sha256(self.payload_hash, "payload_hash")
        if self.slot < 0:
            raise ProtocolConformanceError("PR196_HELIUS_NEGATIVE_SLOT")
        return _stable_hash(
            {
                "signature": self.signature,
                "slot": self.slot,
                "event_type": self.event_type,
            }
        )


@dataclass(frozen=True, slots=True)
class HeliusNormalizationResult:
    normalized_events: tuple[HeliusWebhookEvent, ...]
    duplicate_deliveries: int
    min_slot: int | None
    max_slot: int | None
    requires_gap_backfill: bool


def normalize_helius_events(
    events: Iterable[HeliusWebhookEvent],
) -> HeliusNormalizationResult:
    by_key: dict[str, HeliusWebhookEvent] = {}
    duplicates = 0
    for event in events:
        key = event.idempotency_key()
        if key in by_key:
            duplicates += 1
            continue
        by_key[key] = event
    ordered = tuple(
        sorted(
            by_key.values(),
            key=lambda item: (item.slot, item.signature, item.event_type),
        )
    )
    slots = [item.slot for item in ordered]
    requires_gap_backfill = False
    if len(slots) >= 2:
        requires_gap_backfill = any(
            later > earlier + 1 for earlier, later in zip(slots, slots[1:])
        )
    return HeliusNormalizationResult(
        normalized_events=ordered,
        duplicate_deliveries=duplicates,
        min_slot=min(slots) if slots else None,
        max_slot=max(slots) if slots else None,
        requires_gap_backfill=requires_gap_backfill,
    )


@dataclass(frozen=True, slots=True)
class ProtocolConformanceReport:
    schema_version: str
    external_contract_hash: str
    provider_roles: Mapping[str, str]
    rooted_state_hash: str
    jupiter_route_bps: tuple[int, ...]
    normalized_helius_events: int
    helius_duplicate_deliveries: int
    helius_gap_backfill_required: bool
    drift_action: DriftAction
    live_execution_allowed: bool = False
    signer_or_sender_allowed: bool = False


def build_protocol_conformance_report(
    *,
    marginfi: MarginFiP0Evidence,
    jupiter: JupiterBuildEvidence,
    rpc_quorum: RootedRpcQuorum,
    provider_registry: Sequence[ProviderRegistryEntry],
    helius_events: Sequence[HeliusWebhookEvent],
    now: datetime,
) -> ProtocolConformanceReport:
    marginfi.validate(now=now)
    jupiter_bps = jupiter.validate(now=now)
    rooted_state_hash = rpc_quorum.validate()
    provider_roles: dict[str, str] = {}
    for entry in provider_registry:
        entry.validate(now=now)
        provider_roles[entry.provider_id] = entry.role.value
    if "jupiter" not in provider_roles:
        raise ProtocolConformanceError("PR196_JUPITER_PROVIDER_REQUIRED")
    if provider_roles["jupiter"] != ProviderRole.EXECUTION_COMPOSABLE.value:
        raise ProtocolConformanceError("PR196_JUPITER_MUST_BE_EXECUTION_PROVIDER")
    helius = normalize_helius_events(helius_events)
    external_contract_hash = _stable_hash(
        {
            "schema": PR196_SCHEMA_VERSION,
            "marginfi": marginfi.evidence.source_hash,
            "jupiter": jupiter.response_hash,
            "rpc_state": rooted_state_hash,
            "providers": provider_roles,
            "helius": [event.idempotency_key() for event in helius.normalized_events],
        }
    )
    drift_action = (
        DriftAction.QUARANTINE
        if helius.requires_gap_backfill
        else DriftAction.AVAILABLE
    )
    return ProtocolConformanceReport(
        schema_version=PR196_SCHEMA_VERSION,
        external_contract_hash=external_contract_hash,
        provider_roles=provider_roles,
        rooted_state_hash=rooted_state_hash,
        jupiter_route_bps=jupiter_bps,
        normalized_helius_events=len(helius.normalized_events),
        helius_duplicate_deliveries=helius.duplicate_deliveries,
        helius_gap_backfill_required=helius.requires_gap_backfill,
        drift_action=drift_action,
    )


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolConformanceError(f"PR196_INVALID_{field_name.upper()}") from exc
    if parsed.tzinfo is None:
        raise ProtocolConformanceError(f"PR196_NAIVE_{field_name.upper()}")
    return parsed.astimezone(timezone.utc)


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProtocolConformanceError(f"PR196_INVALID_{field_name.upper()}_SHA256")


def _require_safe_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ProtocolConformanceError(f"PR196_INVALID_{field_name.upper()}")


def _require_safe_host(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ProtocolConformanceError("PR196_INVALID_PROVIDER_HOST")
    if "/" in value or ":" in value or "@" in value:
        raise ProtocolConformanceError("PR196_PROVIDER_HOST_MUST_BE_HOST_ONLY")


def _coerce_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ProtocolConformanceError(f"PR196_INVALID_{field_name.upper()}_BOOLEAN")
    if not isinstance(value, int):
        raise ProtocolConformanceError(f"PR196_INVALID_{field_name.upper()}_INTEGER")
    return value
