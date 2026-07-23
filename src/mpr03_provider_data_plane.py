"""MPR-03 rooted provider and authenticated data-plane evidence gate.

This module is deliberately offline and side-effect free.  It validates release
evidence for the provider/data-plane boundary without opening sockets, parsing
secrets, starting webhook listeners, or enabling live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Mapping, Sequence

MPR03_SCHEMA_VERSION = "mpr03.rooted-provider-data-plane.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_ARTIFACT_HASHES = (
    "provider_registry_hash",
    "transport_policy_hash",
    "quota_authority_hash",
    "rooted_quorum_hash",
    "ingress_policy_hash",
    "webhook_queue_hash",
    "async_writer_hash",
    "backfill_policy_hash",
)

_REQUIRED_TRANSPORT_FLAGS = (
    "pinned_resolution",
    "peer_ip_verified_after_connect",
    "tls_peer_verified",
    "private_ip_rejected",
    "dns_rebinding_negative_test",
    "response_body_limit_enforced",
    "gzip_bomb_rejected",
    "duplicate_json_keys_rejected",
    "json_nan_rejected",
    "malformed_schema_is_4xx",
    "retry_policy_has_full_jitter",
    "non_retryable_send_classified",
)

_REQUIRED_REGISTRY_FLAGS = (
    "signed_registry",
    "credential_generation_bound",
    "operator_independence_bound",
    "network_path_independence_bound",
    "no_caller_defined_groups",
)

_REQUIRED_QUORUM_FLAGS = (
    "unique_provider_identity",
    "registry_backed_independence",
    "request_response_hash_bound",
    "min_context_slot_bound",
    "duplicate_endpoint_probe_rejected",
    "caller_created_label_probe_rejected",
)

_REQUIRED_INGRESS_FLAGS = (
    "mandatory_ingress_policy",
    "compatibility_mode_disabled",
    "constant_time_auth_compare",
    "tls_proxy_generation_bound",
    "atomic_audit_delivery_event_commit",
    "ack_after_commit_only",
    "duplicate_delivery_conflict_quarantined",
    "malformed_json_rejected_4xx",
    "durable_backfill_on_provider_loss",
)

_REQUIRED_QUEUE_FLAGS = (
    "queued_claimed_processed_dlq_states",
    "claim_owner_lease_and_fence",
    "ack_nack_retry_schedule",
    "max_attempts_and_dead_letter",
    "idempotent_downstream_attempt_identity",
)

_REQUIRED_WRITER_FLAGS = (
    "durable_enqueue_is_proof_critical",
    "accepted_work_not_cancelled_on_shutdown",
    "operation_descriptor_hash_bound",
    "operation_id_payload_mismatch_rejected",
    "byte_size_computed_inside_authority",
    "assert_free_runtime_invariants",
    "writer_crash_fails_all_promises",
    "result_reconciled_from_durable_journal",
)

_REQUIRED_DRILLS = {
    "dns_rebinding_private_ip",
    "gzip_bomb",
    "duplicate_json_key",
    "json_nan",
    "malformed_schema",
    "retry_storm",
    "duplicate_quorum_endpoint",
    "webhook_enqueue_crash",
    "webhook_claim_crash",
    "webhook_processing_crash",
    "async_writer_crash",
    "provider_loss_backfill",
}


class MPR03ProviderPlaneError(ValueError):
    """Raised when MPR-03 evidence is malformed."""


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProviderPlaneDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class ProviderPlaneReport:
    schema_version: str
    ready: bool
    diagnostics: tuple[ProviderPlaneDiagnostic, ...]

    @property
    def blockers(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.severity is DiagnosticSeverity.ERROR
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "blockers": [diagnostic.to_dict() for diagnostic in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class TransportEvidence:
    flags: frozenset[str]
    redirect_policy: str
    total_deadline_ms: int
    response_body_limit_bytes: int
    json_rpc_batch_limit: int
    websocket_message_limit_bytes: int

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TransportEvidence":
        return cls(
            flags=_string_set(raw.get("flags"), "transport.flags"),
            redirect_policy=_non_empty(raw.get("redirect_policy"), "transport.redirect_policy"),
            total_deadline_ms=_int(raw.get("total_deadline_ms"), "transport.total_deadline_ms"),
            response_body_limit_bytes=_int(
                raw.get("response_body_limit_bytes"),
                "transport.response_body_limit_bytes",
            ),
            json_rpc_batch_limit=_int(raw.get("json_rpc_batch_limit"), "transport.json_rpc_batch_limit"),
            websocket_message_limit_bytes=_int(
                raw.get("websocket_message_limit_bytes"),
                "transport.websocket_message_limit_bytes",
            ),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        diagnostics.extend(_missing_flags("TRANSPORT_FLAG_MISSING", "transport.flags", _REQUIRED_TRANSPORT_FLAGS, self.flags))
        if self.redirect_policy != "deny-cross-origin":
            diagnostics.append(_err("REDIRECT_POLICY_NOT_DENY_CROSS_ORIGIN", "redirects must fail closed across origin/IP-class changes", "transport.redirect_policy"))
        if self.total_deadline_ms <= 0 or self.total_deadline_ms > 30_000:
            diagnostics.append(_err("TOTAL_DEADLINE_INVALID", "provider operations need a bounded total deadline <= 30000 ms", "transport.total_deadline_ms"))
        if self.response_body_limit_bytes <= 0 or self.response_body_limit_bytes > 2_000_000:
            diagnostics.append(_err("RESPONSE_LIMIT_INVALID", "response body limit must be positive and bounded", "transport.response_body_limit_bytes"))
        if self.json_rpc_batch_limit <= 0 or self.json_rpc_batch_limit > 100:
            diagnostics.append(_err("JSON_RPC_BATCH_LIMIT_INVALID", "JSON-RPC batch limit must be positive and bounded", "transport.json_rpc_batch_limit"))
        if self.websocket_message_limit_bytes <= 0 or self.websocket_message_limit_bytes > 2_000_000:
            diagnostics.append(_err("WEBSOCKET_LIMIT_INVALID", "WebSocket message limit must be positive and bounded", "transport.websocket_message_limit_bytes"))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ProviderRegistryEvidence:
    flags: frozenset[str]
    provider_ids: tuple[str, ...]
    min_independent_sources: int
    registry_signature_sha256: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProviderRegistryEvidence":
        provider_ids = tuple(
            _non_empty(value, f"provider_registry.provider_ids[{index}]")
            for index, value in enumerate(_list(raw.get("provider_ids"), "provider_registry.provider_ids"))
        )
        return cls(
            flags=_string_set(raw.get("flags"), "provider_registry.flags"),
            provider_ids=provider_ids,
            min_independent_sources=_int(
                raw.get("min_independent_sources"),
                "provider_registry.min_independent_sources",
            ),
            registry_signature_sha256=_sha256(
                raw.get("registry_signature_sha256"),
                "provider_registry.registry_signature_sha256",
            ),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        diagnostics.extend(_missing_flags("PROVIDER_REGISTRY_FLAG_MISSING", "provider_registry.flags", _REQUIRED_REGISTRY_FLAGS, self.flags))
        if len(set(self.provider_ids)) != len(self.provider_ids):
            diagnostics.append(_err("PROVIDER_ID_NOT_UNIQUE", "provider ids must be unique", "provider_registry.provider_ids"))
        if len(self.provider_ids) < 2:
            diagnostics.append(_err("PROVIDER_REGISTRY_TOO_SMALL", "at least two provider identities are required", "provider_registry.provider_ids"))
        if self.min_independent_sources < 2:
            diagnostics.append(_err("MIN_INDEPENDENT_SOURCES_TOO_LOW", "rooted quorum requires at least two independent sources", "provider_registry.min_independent_sources"))
        if self.min_independent_sources > len(set(self.provider_ids)):
            diagnostics.append(_err("MIN_INDEPENDENT_SOURCES_UNSATISFIABLE", "min independent sources exceeds unique provider identities", "provider_registry.min_independent_sources"))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class QuotaEvidence:
    cross_process: bool
    authority_owned_clock: bool
    transactional_reservation: bool
    retention_policy: bool
    retry_storm_probe_rejected: bool
    max_reserved_cost_units_per_cycle: int

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "QuotaEvidence":
        return cls(
            cross_process=_bool(raw.get("cross_process"), "quota.cross_process"),
            authority_owned_clock=_bool(raw.get("authority_owned_clock"), "quota.authority_owned_clock"),
            transactional_reservation=_bool(raw.get("transactional_reservation"), "quota.transactional_reservation"),
            retention_policy=_bool(raw.get("retention_policy"), "quota.retention_policy"),
            retry_storm_probe_rejected=_bool(raw.get("retry_storm_probe_rejected"), "quota.retry_storm_probe_rejected"),
            max_reserved_cost_units_per_cycle=_int(
                raw.get("max_reserved_cost_units_per_cycle"),
                "quota.max_reserved_cost_units_per_cycle",
            ),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        for field_name in (
            "cross_process",
            "authority_owned_clock",
            "transactional_reservation",
            "retention_policy",
            "retry_storm_probe_rejected",
        ):
            if not getattr(self, field_name):
                diagnostics.append(_err("QUOTA_AUTHORITY_INCOMPLETE", f"quota evidence requires {field_name}", f"quota.{field_name}"))
        if self.max_reserved_cost_units_per_cycle <= 0:
            diagnostics.append(_err("QUOTA_CYCLE_BUDGET_INVALID", "cycle quota budget must be positive", "quota.max_reserved_cost_units_per_cycle"))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class RootedQuorumEvidence:
    flags: frozenset[str]
    observations: tuple[Mapping[str, Any], ...]
    min_context_slot: int
    max_slot_skew: int
    max_age_ms: int

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RootedQuorumEvidence":
        observations = tuple(
            _mapping(value, f"rooted_quorum.observations[{index}]")
            for index, value in enumerate(_list(raw.get("observations"), "rooted_quorum.observations"))
        )
        return cls(
            flags=_string_set(raw.get("flags"), "rooted_quorum.flags"),
            observations=observations,
            min_context_slot=_int(raw.get("min_context_slot"), "rooted_quorum.min_context_slot"),
            max_slot_skew=_int(raw.get("max_slot_skew"), "rooted_quorum.max_slot_skew"),
            max_age_ms=_int(raw.get("max_age_ms"), "rooted_quorum.max_age_ms"),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        diagnostics.extend(_missing_flags("ROOTED_QUORUM_FLAG_MISSING", "rooted_quorum.flags", _REQUIRED_QUORUM_FLAGS, self.flags))
        if len(self.observations) < 2:
            diagnostics.append(_err("ROOTED_QUORUM_TOO_SMALL", "at least two observations are required", "rooted_quorum.observations"))
            return tuple(diagnostics)
        provider_ids: list[str] = []
        groups: list[str] = []
        slots: list[int] = []
        state_hashes: set[str] = set()
        request_hashes: set[str] = set()
        for index, observation in enumerate(self.observations):
            provider_ids.append(_non_empty(observation.get("provider_id"), f"rooted_quorum.observations[{index}].provider_id"))
            groups.append(_non_empty(observation.get("independence_group"), f"rooted_quorum.observations[{index}].independence_group"))
            slots.append(_int(observation.get("rooted_slot"), f"rooted_quorum.observations[{index}].rooted_slot"))
            state_hashes.add(_sha256(observation.get("state_hash"), f"rooted_quorum.observations[{index}].state_hash"))
            request_hashes.add(_sha256(observation.get("request_response_hash"), f"rooted_quorum.observations[{index}].request_response_hash"))
        if len(set(provider_ids)) != len(provider_ids):
            diagnostics.append(_err("ROOTED_QUORUM_DUPLICATE_PROVIDER", "quorum observations must use unique provider identities", "rooted_quorum.observations"))
        if len(set(groups)) < 2:
            diagnostics.append(_err("ROOTED_QUORUM_NOT_INDEPENDENT", "quorum observations must span independent groups", "rooted_quorum.observations"))
        if len(state_hashes) != 1:
            diagnostics.append(_err("ROOTED_QUORUM_STATE_HASH_MISMATCH", "all quorum observations must agree on state hash", "rooted_quorum.observations"))
        if len(request_hashes) != len(self.observations):
            diagnostics.append(_err("ROOTED_QUORUM_REQUEST_HASH_NOT_UNIQUE", "each provider response must be bound to its own request/response hash", "rooted_quorum.observations"))
        if min(slots) < self.min_context_slot:
            diagnostics.append(_err("ROOTED_QUORUM_BELOW_MIN_CONTEXT_SLOT", "all observations must be at or above minContextSlot", "rooted_quorum.observations"))
        if max(slots) - min(slots) > self.max_slot_skew:
            diagnostics.append(_err("ROOTED_QUORUM_SLOT_SKEW_EXCEEDED", "slot skew exceeds declared maximum", "rooted_quorum.max_slot_skew"))
        if self.max_slot_skew < 0 or self.max_slot_skew > 32:
            diagnostics.append(_err("ROOTED_QUORUM_SLOT_SKEW_INVALID", "max slot skew must be between 0 and 32", "rooted_quorum.max_slot_skew"))
        if self.max_age_ms <= 0 or self.max_age_ms > 60_000:
            diagnostics.append(_err("ROOTED_QUORUM_AGE_INVALID", "quorum evidence max age must be positive and <= 60000 ms", "rooted_quorum.max_age_ms"))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class HeliusIngressEvidence:
    flags: frozenset[str]
    queue_flags: frozenset[str]
    ack_statuses: tuple[int, ...]
    durable_transaction_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "HeliusIngressEvidence":
        ack_statuses = tuple(
            _int(value, f"helius_ingress.ack_statuses[{index}]")
            for index, value in enumerate(_list(raw.get("ack_statuses"), "helius_ingress.ack_statuses"))
        )
        return cls(
            flags=_string_set(raw.get("flags"), "helius_ingress.flags"),
            queue_flags=_string_set(raw.get("queue_flags"), "helius_ingress.queue_flags"),
            ack_statuses=ack_statuses,
            durable_transaction_hash=_sha256(
                raw.get("durable_transaction_hash"),
                "helius_ingress.durable_transaction_hash",
            ),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        diagnostics.extend(_missing_flags("INGRESS_FLAG_MISSING", "helius_ingress.flags", _REQUIRED_INGRESS_FLAGS, self.flags))
        diagnostics.extend(_missing_flags("INGRESS_QUEUE_FLAG_MISSING", "helius_ingress.queue_flags", _REQUIRED_QUEUE_FLAGS, self.queue_flags))
        if not self.ack_statuses:
            diagnostics.append(_err("INGRESS_ACK_EVIDENCE_MISSING", "ack status evidence is required", "helius_ingress.ack_statuses"))
        for status in self.ack_statuses:
            if status < 200 or status >= 300:
                diagnostics.append(_err("INGRESS_ACK_NOT_2XX", "successful delivery evidence must contain only 2xx ACK statuses after durable commit", "helius_ingress.ack_statuses"))
                break
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class AsyncWriterEvidence:
    flags: frozenset[str]
    max_queue_bytes: int
    max_close_drain_ms: int

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AsyncWriterEvidence":
        return cls(
            flags=_string_set(raw.get("flags"), "async_writer.flags"),
            max_queue_bytes=_int(raw.get("max_queue_bytes"), "async_writer.max_queue_bytes"),
            max_close_drain_ms=_int(raw.get("max_close_drain_ms"), "async_writer.max_close_drain_ms"),
        )

    def validate(self) -> tuple[ProviderPlaneDiagnostic, ...]:
        diagnostics: list[ProviderPlaneDiagnostic] = []
        diagnostics.extend(_missing_flags("ASYNC_WRITER_FLAG_MISSING", "async_writer.flags", _REQUIRED_WRITER_FLAGS, self.flags))
        if self.max_queue_bytes <= 0 or self.max_queue_bytes > 50_000_000:
            diagnostics.append(_err("ASYNC_WRITER_QUEUE_BOUND_INVALID", "writer queue byte bound must be positive and reasonable", "async_writer.max_queue_bytes"))
        if self.max_close_drain_ms <= 0 or self.max_close_drain_ms > 60_000:
            diagnostics.append(_err("ASYNC_WRITER_DRAIN_DEADLINE_INVALID", "writer close drain deadline must be positive and <= 60000 ms", "async_writer.max_close_drain_ms"))
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class FaultDrillEvidence:
    name: str
    passed: bool
    invariant: str
    evidence_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], index: int) -> "FaultDrillEvidence":
        return cls(
            name=_non_empty(raw.get("name"), f"fault_drills[{index}].name"),
            passed=_bool(raw.get("passed"), f"fault_drills[{index}].passed"),
            invariant=_non_empty(raw.get("invariant"), f"fault_drills[{index}].invariant"),
            evidence_hash=_sha256(raw.get("evidence_hash"), f"fault_drills[{index}].evidence_hash"),
        )


def validate_mpr03_provider_plane_evidence(evidence: Mapping[str, Any]) -> ProviderPlaneReport:
    """Validate MPR-03 provider/data-plane evidence and return fail-closed report."""

    raw = _mapping(evidence, "evidence")
    schema_version = _non_empty(raw.get("schema_version"), "schema_version")
    if schema_version != MPR03_SCHEMA_VERSION:
        raise MPR03ProviderPlaneError(
            f"schema_version must be {MPR03_SCHEMA_VERSION}, got {schema_version!r}"
        )

    diagnostics: list[ProviderPlaneDiagnostic] = []

    artifact_hashes = _mapping(raw.get("artifact_hashes"), "artifact_hashes")
    for key in _REQUIRED_ARTIFACT_HASHES:
        _sha256(artifact_hashes.get(key), f"artifact_hashes.{key}")

    transport = TransportEvidence.from_dict(_mapping(raw.get("transport"), "transport"))
    provider_registry = ProviderRegistryEvidence.from_dict(_mapping(raw.get("provider_registry"), "provider_registry"))
    quota = QuotaEvidence.from_dict(_mapping(raw.get("quota"), "quota"))
    rooted_quorum = RootedQuorumEvidence.from_dict(_mapping(raw.get("rooted_quorum"), "rooted_quorum"))
    helius_ingress = HeliusIngressEvidence.from_dict(_mapping(raw.get("helius_ingress"), "helius_ingress"))
    async_writer = AsyncWriterEvidence.from_dict(_mapping(raw.get("async_writer"), "async_writer"))

    diagnostics.extend(transport.validate())
    diagnostics.extend(provider_registry.validate())
    diagnostics.extend(quota.validate())
    diagnostics.extend(rooted_quorum.validate())
    diagnostics.extend(helius_ingress.validate())
    diagnostics.extend(async_writer.validate())

    drills = tuple(
        FaultDrillEvidence.from_dict(_mapping(value, f"fault_drills[{index}]"), index)
        for index, value in enumerate(_list(raw.get("fault_drills"), "fault_drills"))
    )
    diagnostics.extend(_validate_drills(drills))

    if _bool(raw.get("live_enabled"), "live_enabled"):
        diagnostics.append(_err("LIVE_ENABLED_IN_PROVIDER_PLANE", "MPR-03 must not enable live trading", "live_enabled"))
    if _bool(raw.get("signer_enabled"), "signer_enabled"):
        diagnostics.append(_err("SIGNER_ENABLED_IN_PROVIDER_PLANE", "MPR-03 must not enable signer capability", "signer_enabled"))
    if _bool(raw.get("sender_enabled"), "sender_enabled"):
        diagnostics.append(_err("SENDER_ENABLED_IN_PROVIDER_PLANE", "MPR-03 must not enable sender capability", "sender_enabled"))
    if _bool(raw.get("compatibility_ingress_allowed"), "compatibility_ingress_allowed"):
        diagnostics.append(_err("COMPATIBILITY_INGRESS_ALLOWED", "production ingress policy cannot be optional", "compatibility_ingress_allowed"))

    ready = not any(diagnostic.severity is DiagnosticSeverity.ERROR for diagnostic in diagnostics)
    if ready:
        diagnostics.append(
            ProviderPlaneDiagnostic(
                "MPR03_PROVIDER_PLANE_READY",
                DiagnosticSeverity.INFO,
                "provider/data-plane evidence satisfies offline MPR-03 gate",
                "",
            )
        )

    return ProviderPlaneReport(
        schema_version=MPR03_SCHEMA_VERSION,
        ready=ready,
        diagnostics=tuple(diagnostics),
    )


def live_capability_allowed() -> bool:
    """MPR-03 never enables live trading."""

    return False


def signer_capability_allowed() -> bool:
    """MPR-03 never enables signer/private-key access."""

    return False


def sender_capability_allowed() -> bool:
    """MPR-03 never enables RPC/Jito submission."""

    return False


def _validate_drills(drills: Sequence[FaultDrillEvidence]) -> tuple[ProviderPlaneDiagnostic, ...]:
    diagnostics: list[ProviderPlaneDiagnostic] = []
    by_name = {drill.name: drill for drill in drills}
    missing = sorted(_REQUIRED_DRILLS - set(by_name))
    if missing:
        diagnostics.append(
            _err(
                "FAULT_DRILL_MISSING",
                "required provider/data-plane fault drills are missing",
                "fault_drills",
            )
        )
    for drill in drills:
        if not drill.passed:
            diagnostics.append(
                _err(
                    "FAULT_DRILL_FAILED",
                    f"fault drill {drill.name!r} did not pass",
                    f"fault_drills.{drill.name}",
                )
            )
    return tuple(diagnostics)


def _missing_flags(
    code: str,
    path: str,
    required: Sequence[str],
    flags: frozenset[str],
) -> tuple[ProviderPlaneDiagnostic, ...]:
    missing = sorted(set(required) - flags)
    if not missing:
        return ()
    return (
        _err(
            code,
            f"missing required flags: {', '.join(missing)}",
            path,
        ),
    )


def _err(code: str, message: str, path: str) -> ProviderPlaneDiagnostic:
    return ProviderPlaneDiagnostic(code, DiagnosticSeverity.ERROR, message, path)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MPR03ProviderPlaneError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise MPR03ProviderPlaneError(f"{path} must be a list")
    return value


def _string_set(value: Any, path: str) -> frozenset[str]:
    return frozenset(
        _non_empty(item, f"{path}[{index}]")
        for index, item in enumerate(_list(value, path))
    )


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise MPR03ProviderPlaneError(f"{path} must be a boolean")
    return value


def _int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MPR03ProviderPlaneError(f"{path} must be an integer")
    return value


def _non_empty(value: Any, path: str | None = None, *, field: str | None = None) -> str:
    actual_path = path if path is not None else field
    if not isinstance(value, str) or not value.strip():
        raise MPR03ProviderPlaneError(f"{actual_path} must be a non-empty string")
    return value


def _sha256(value: Any, path: str) -> str:
    text = _non_empty(value, path)
    if not _SHA256_RE.fullmatch(text):
        raise MPR03ProviderPlaneError(f"{path} must be a lowercase SHA-256 hex digest")
    return text
