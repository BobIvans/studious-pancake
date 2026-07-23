"""MPR-27 provider/routing/quota integrity evidence gate.

This module is intentionally offline and side-effect free.  It does not perform
HTTP, RPC, Helius, Jupiter, signer, sender, or live-runtime operations.  It
describes the fail-closed evidence contract required by the V11 MPR-27 provider
plane before later cutover work can make provider data executable.

The important property is negative: missing, stale, caller-declared, unrooted,
or internally inconsistent provider evidence must block candidate admission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from typing import Sequence

SCHEMA_ID = "mpr27.provider-routing-quota-integrity.v1"

REQUIRED_FINDINGS: tuple[str, ...] = (
    "V10-F-441",
    "V10-F-442",
    "V10-F-443",
    "PROVIDER_ROOTED_INTAKE",
    "BOUNDED_TRANSPORT",
    "DNS_TLS_PEER_BINDING",
    "SIGNED_PROVIDER_REGISTRY",
    "CROSS_PROCESS_QUOTA",
    "QUOTE_IDENTITY",
    "QUOTE_FRESHNESS",
    "HELIUS_DURABLE_QUEUE",
    "DISCOVERY_PRODUCTION_INPUT_CUTOVER",
)

_PLACEHOLDER_DIGESTS = {
    "",
    "0" * 64,
    "1" * 64,
    "f" * 64,
    "a" * 64,
    "placeholder",
    "todo",
    "sha256",
}


class MPR27Blocker(str, Enum):
    SCHEMA = "MPR27_SCHEMA_MISMATCH"
    FINDING_COVERAGE = "MPR27_FINDING_COVERAGE_INCOMPLETE"
    MPR25_DEPENDENCY = "MPR27_MPR25_PRODUCT_GRAPH_NOT_FROZEN"
    MPR26_DEPENDENCY = "MPR27_MPR26_DURABLE_AUTHORITY_NOT_ACCEPTED"
    EVIDENCE = "MPR27_EVIDENCE_NOT_MATERIALIZED"
    ROOTED_INTAKE = "MPR27_ROOTED_PROVIDER_INTAKE_REQUIRED"
    TRANSPORT = "MPR27_BOUNDED_TRANSPORT_REQUIRED"
    PEER_BINDING = "MPR27_DNS_TLS_PEER_BINDING_REQUIRED"
    REGISTRY = "MPR27_PROVIDER_REGISTRY_REQUIRED"
    QUOTA = "MPR27_CROSS_PROCESS_QUOTA_REQUIRED"
    QUOTE_IDENTITY = "MPR27_QUOTE_IDENTITY_NOT_COLLISION_PROOF"
    FRESHNESS = "MPR27_QUOTE_FRESHNESS_NOT_TRUSTED"
    HELIUS = "MPR27_HELIUS_QUEUE_NOT_DURABLE"
    BYPASS = "MPR27_LEGACY_PROVIDER_BYPASS_REACHABLE"
    PRODUCTION_INPUT = "MPR27_RECORDED_JSON_STILL_PRODUCTION_INPUT"
    FORBIDDEN = "MPR27_FORBIDDEN_RUNTIME_CAPABILITY_REQUESTED"


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _canonical_json(value: object) -> str:
    return json.dumps(
        asdict(value) if hasattr(value, "__dataclass_fields__") else value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRef:
    """Materialized evidence artifact reference.

    A path/string/digest alone is not proof.  The caller must state that the
    bytes were materialized and re-hashed by the review pipeline.
    """

    path: str
    sha256: str
    size_bytes: int
    materialized: bool = True
    immutable: bool = True
    signed: bool = True

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        normalized = self.sha256.lower()
        if (
            not self.materialized
            or not self.immutable
            or not self.signed
            or not self.path
            or self.path.startswith("<")
            or self.size_bytes <= 0
            or not _is_sha256(normalized)
            or normalized in _PLACEHOLDER_DIGESTS
        ):
            blockers.append(MPR27Blocker.EVIDENCE.value)
        return tuple(blockers)


@dataclass(frozen=True)
class DependencyEvidence:
    """Upstream V11 gates that MPR-27 is allowed to depend on."""

    mpr25_product_graph_frozen: bool
    mpr25_release_qualification_authoritative: bool
    mpr26_durable_authority_accepted: bool
    mpr26_outbox_and_attempt_authority_available: bool
    mpr25_artifact_manifest: EvidenceRef
    mpr26_authority_manifest: EvidenceRef

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not (
            self.mpr25_product_graph_frozen
            and self.mpr25_release_qualification_authoritative
        ):
            blockers.append(MPR27Blocker.MPR25_DEPENDENCY.value)
        if not (
            self.mpr26_durable_authority_accepted
            and self.mpr26_outbox_and_attempt_authority_available
        ):
            blockers.append(MPR27Blocker.MPR26_DEPENDENCY.value)
        for ref in (self.mpr25_artifact_manifest, self.mpr26_authority_manifest):
            blockers.extend(ref.blockers())
        return tuple(blockers)


@dataclass(frozen=True)
class RootedProviderIntakeEvidence:
    """Provider bytes are the source of candidates, not caller strings."""

    provider_artifacts: tuple[EvidenceRef, ...]
    recorded_json_production_input_disabled: bool
    provider_owned_content_addressing: bool
    rpc_helius_jupiter_bytes_materialized: bool
    request_policy_hash_bound: bool
    decoded_schema_quarantine: bool
    caller_declared_digest_rejected: bool
    stale_or_unrooted_bytes_block_candidate: bool
    candidate_requires_stored_evidence_id: bool

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.provider_artifacts:
            blockers.append(MPR27Blocker.ROOTED_INTAKE.value)
        for ref in self.provider_artifacts:
            blockers.extend(ref.blockers())
        if not (
            self.recorded_json_production_input_disabled
            and self.provider_owned_content_addressing
            and self.rpc_helius_jupiter_bytes_materialized
            and self.request_policy_hash_bound
            and self.decoded_schema_quarantine
            and self.caller_declared_digest_rejected
            and self.stale_or_unrooted_bytes_block_candidate
            and self.candidate_requires_stored_evidence_id
        ):
            blockers.append(MPR27Blocker.ROOTED_INTAKE.value)
        if not self.recorded_json_production_input_disabled:
            blockers.append(MPR27Blocker.PRODUCTION_INPUT.value)
        return tuple(blockers)


@dataclass(frozen=True)
class TransportPolicyEvidence:
    """One bounded HTTP/JSON-RPC transport policy for provider intake."""

    single_transport_owner: bool
    total_deadline_ms: int
    response_byte_limit: int
    decompressed_byte_limit: int
    json_depth_limit: int
    duplicate_keys_rejected: bool
    non_finite_numbers_rejected: bool
    schema_quarantine: bool
    bounded_cancellation: bool
    retry_storm_budgeted: bool
    diagnostic_redaction: bool

    def blockers(self) -> tuple[str, ...]:
        if not (
            self.single_transport_owner
            and 1 <= self.total_deadline_ms <= 60_000
            and 1 <= self.response_byte_limit <= 16_777_216
            and 1 <= self.decompressed_byte_limit <= 33_554_432
            and 1 <= self.json_depth_limit <= 128
            and self.duplicate_keys_rejected
            and self.non_finite_numbers_rejected
            and self.schema_quarantine
            and self.bounded_cancellation
            and self.retry_storm_budgeted
            and self.diagnostic_redaction
        ):
            return (MPR27Blocker.TRANSPORT.value,)
        return ()


@dataclass(frozen=True)
class PeerBindingEvidence:
    """DNS preflight is bound to the actual peer and TLS origin."""

    dns_preflight_bound_to_connect_peer: bool
    tls_sni_verified: bool
    tls_peer_certificate_bound: bool
    private_ip_denied: bool
    link_local_denied: bool
    loopback_denied: bool
    redirect_revalidated: bool
    unapproved_origin_redirect_denied: bool
    injected_client_policy_bypass_removed: bool

    def blockers(self) -> tuple[str, ...]:
        if not all(
            (
                self.dns_preflight_bound_to_connect_peer,
                self.tls_sni_verified,
                self.tls_peer_certificate_bound,
                self.private_ip_denied,
                self.link_local_denied,
                self.loopback_denied,
                self.redirect_revalidated,
                self.unapproved_origin_redirect_denied,
                self.injected_client_policy_bypass_removed,
            )
        ):
            return (MPR27Blocker.PEER_BINDING.value,)
        return ()


@dataclass(frozen=True)
class ProviderRegistryEvidence:
    """Provider/operator/network-path groups are signed and unique."""

    registry_artifact: EvidenceRef
    signed_provider_registry: bool
    unique_provider_ids: bool
    unique_operator_groups: bool
    unique_network_path_groups: bool
    quorum_independence_enforced: bool
    caller_created_group_labels_rejected: bool
    provider_cluster_generation_bound: bool

    def blockers(self) -> tuple[str, ...]:
        blockers = list(self.registry_artifact.blockers())
        if not all(
            (
                self.signed_provider_registry,
                self.unique_provider_ids,
                self.unique_operator_groups,
                self.unique_network_path_groups,
                self.quorum_independence_enforced,
                self.caller_created_group_labels_rejected,
                self.provider_cluster_generation_bound,
            )
        ):
            blockers.append(MPR27Blocker.REGISTRY.value)
        return tuple(blockers)


@dataclass(frozen=True)
class QuotaCircuitEvidence:
    """Cross-process quota/circuit authority for Jupiter and RPC providers."""

    quota_authority_artifact: EvidenceRef
    cross_process_serialized: bool
    request_bound_reservation: bool
    ttl_revalidated_on_retry: bool
    static_snapshot_cannot_authorize_multiple_retries: bool
    mark_used_exactly_once: bool
    release_is_idempotent: bool
    cooldown_persisted_across_restart: bool
    provider_account_plan_generation_bound: bool
    two_process_race_probe: bool

    def blockers(self) -> tuple[str, ...]:
        blockers = list(self.quota_authority_artifact.blockers())
        if not all(
            (
                self.cross_process_serialized,
                self.request_bound_reservation,
                self.ttl_revalidated_on_retry,
                self.static_snapshot_cannot_authorize_multiple_retries,
                self.mark_used_exactly_once,
                self.release_is_idempotent,
                self.cooldown_persisted_across_restart,
                self.provider_account_plan_generation_bound,
                self.two_process_race_probe,
            )
        ):
            blockers.append(MPR27Blocker.QUOTA.value)
        return tuple(blockers)


@dataclass(frozen=True)
class QuoteIdentityEvidence:
    """Quote identity is collision-proof and policy-bound."""

    length_prefixed_or_canonical_tuple_encoding: bool
    includes_provider: bool
    includes_cluster: bool
    includes_mint_pair: bool
    includes_amount: bool
    includes_mode: bool
    includes_slippage: bool
    includes_route_params: bool
    includes_policy_generation: bool
    includes_request_hash: bool
    delimiter_collision_regression: bool
    mutable_cached_quote_copy_denied: bool

    def blockers(self) -> tuple[str, ...]:
        if not all(
            (
                self.length_prefixed_or_canonical_tuple_encoding,
                self.includes_provider,
                self.includes_cluster,
                self.includes_mint_pair,
                self.includes_amount,
                self.includes_mode,
                self.includes_slippage,
                self.includes_route_params,
                self.includes_policy_generation,
                self.includes_request_hash,
                self.delimiter_collision_regression,
                self.mutable_cached_quote_copy_denied,
            )
        ):
            return (MPR27Blocker.QUOTE_IDENTITY.value,)
        return ()


@dataclass(frozen=True)
class QuoteFreshnessEvidence:
    """Executable quote freshness is trusted-slot/time-bound."""

    trusted_current_slot_or_time: bool
    missing_expiry_non_executable: bool
    future_timestamp_rejected: bool
    nan_or_infinite_age_rejected: bool
    stale_slot_rejected: bool
    self_relative_freshness_rejected: bool
    route_mutation_after_admission_invalidates_candidate: bool
    slippage_widening_rejected: bool
    mint_amount_or_swap_mode_mutation_rejected: bool

    def blockers(self) -> tuple[str, ...]:
        if not all(
            (
                self.trusted_current_slot_or_time,
                self.missing_expiry_non_executable,
                self.future_timestamp_rejected,
                self.nan_or_infinite_age_rejected,
                self.stale_slot_rejected,
                self.self_relative_freshness_rejected,
                self.route_mutation_after_admission_invalidates_candidate,
                self.slippage_widening_rejected,
                self.mint_amount_or_swap_mode_mutation_rejected,
            )
        ):
            return (MPR27Blocker.FRESHNESS.value,)
        return ()


@dataclass(frozen=True)
class HeliusQueueEvidence:
    """Helius ingress is a durable hint queue, not a source of truth."""

    durable_queue_artifact: EvidenceRef
    ack_after_atomic_audit_event_commit: bool
    claim_lease_retry_dlq_backfill: bool
    idempotent_downstream_attempt_identity: bool
    filtered_webhook_semantics_backfill_bounded: bool
    crash_after_accept_enqueue_claim_processing_probe: bool
    no_double_apply_after_restart: bool
    webhook_not_source_of_truth: bool

    def blockers(self) -> tuple[str, ...]:
        blockers = list(self.durable_queue_artifact.blockers())
        if not all(
            (
                self.ack_after_atomic_audit_event_commit,
                self.claim_lease_retry_dlq_backfill,
                self.idempotent_downstream_attempt_identity,
                self.filtered_webhook_semantics_backfill_bounded,
                self.crash_after_accept_enqueue_claim_processing_probe,
                self.no_double_apply_after_restart,
                self.webhook_not_source_of_truth,
            )
        ):
            blockers.append(MPR27Blocker.HELIUS.value)
        return tuple(blockers)


@dataclass(frozen=True)
class LegacyBypassEvidence:
    """Old provider paths that bypass MPR-27 must be deleted or hard-disabled."""

    raw_provider_digest_strings_rejected: bool
    injected_http_client_escape_hatches_removed: bool
    legacy_recorded_json_production_adapter_disabled: bool
    slot_gap_rpc_storm_logic_removed_or_filter_bound: bool
    old_path_cannot_create_candidate: bool
    old_path_cannot_mark_paper_success: bool

    def blockers(self) -> tuple[str, ...]:
        if not all(
            (
                self.raw_provider_digest_strings_rejected,
                self.injected_http_client_escape_hatches_removed,
                self.legacy_recorded_json_production_adapter_disabled,
                self.slot_gap_rpc_storm_logic_removed_or_filter_bound,
                self.old_path_cannot_create_candidate,
                self.old_path_cannot_mark_paper_success,
            )
        ):
            return (MPR27Blocker.BYPASS.value,)
        return ()


@dataclass(frozen=True)
class MPR27ProviderRoutingQuotaEvidence:
    """Complete offline evidence for the V11 MPR-27 review boundary."""

    schema_id: str
    covered_findings: tuple[str, ...]
    dependencies: DependencyEvidence
    provider_intake: RootedProviderIntakeEvidence
    transport: TransportPolicyEvidence
    peer_binding: PeerBindingEvidence
    registry: ProviderRegistryEvidence
    quota: QuotaCircuitEvidence
    quote_identity: QuoteIdentityEvidence
    freshness: QuoteFreshnessEvidence
    helius: HeliusQueueEvidence
    legacy_bypass: LegacyBypassEvidence
    provider_network_requested: bool = False
    executable_candidate_requested: bool = False
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_material_requested: bool = False


@dataclass(frozen=True)
class MPR27ProviderRoutingQuotaReport:
    schema_id: str
    accepted: bool
    blockers: tuple[str, ...]
    covered_findings: tuple[str, ...]
    evidence_digest: str
    provider_plane_review_allowed: bool
    executable_candidate_allowed: bool
    provider_network_allowed: bool
    paper_ready_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    private_key_material_allowed: bool

    def to_json(self) -> str:
        return _canonical_json(
            {
                "schema_id": self.schema_id,
                "accepted": self.accepted,
                "blockers": list(self.blockers),
                "covered_findings": list(self.covered_findings),
                "evidence_digest": self.evidence_digest,
                "provider_plane_review_allowed": self.provider_plane_review_allowed,
                "executable_candidate_allowed": self.executable_candidate_allowed,
                "provider_network_allowed": self.provider_network_allowed,
                "paper_ready_allowed": self.paper_ready_allowed,
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
                "private_key_material_allowed": self.private_key_material_allowed,
            }
        )


def _finding_blockers(covered_findings: Sequence[str]) -> tuple[str, ...]:
    if sorted(set(covered_findings)) != sorted(REQUIRED_FINDINGS):
        return (MPR27Blocker.FINDING_COVERAGE.value,)
    if len(tuple(covered_findings)) != len(set(covered_findings)):
        return (MPR27Blocker.FINDING_COVERAGE.value,)
    return ()


def _forbidden_surface_blockers(
    evidence: MPR27ProviderRoutingQuotaEvidence,
) -> tuple[str, ...]:
    if any(
        (
            evidence.provider_network_requested,
            evidence.executable_candidate_requested,
            evidence.live_execution_requested,
            evidence.signer_requested,
            evidence.sender_requested,
            evidence.private_key_material_requested,
        )
    ):
        return (MPR27Blocker.FORBIDDEN.value,)
    return ()


def evaluate_mpr27_provider_routing_quota(
    evidence: MPR27ProviderRoutingQuotaEvidence,
) -> MPR27ProviderRoutingQuotaReport:
    """Evaluate MPR-27 evidence without side effects.

    A clean report only means the evidence contract is internally consistent and
    can be reviewed.  It never enables provider networking, executable live
    candidates, signing, sending, paper readiness, or live execution.
    """

    blockers: list[str] = []

    if evidence.schema_id != SCHEMA_ID:
        blockers.append(MPR27Blocker.SCHEMA.value)

    blockers.extend(_finding_blockers(evidence.covered_findings))
    blockers.extend(evidence.dependencies.blockers())
    blockers.extend(evidence.provider_intake.blockers())
    blockers.extend(evidence.transport.blockers())
    blockers.extend(evidence.peer_binding.blockers())
    blockers.extend(evidence.registry.blockers())
    blockers.extend(evidence.quota.blockers())
    blockers.extend(evidence.quote_identity.blockers())
    blockers.extend(evidence.freshness.blockers())
    blockers.extend(evidence.helius.blockers())
    blockers.extend(evidence.legacy_bypass.blockers())
    blockers.extend(_forbidden_surface_blockers(evidence))

    unique_blockers = tuple(sorted(set(blockers)))
    accepted = not unique_blockers

    return MPR27ProviderRoutingQuotaReport(
        schema_id=SCHEMA_ID,
        accepted=accepted,
        blockers=unique_blockers,
        covered_findings=tuple(sorted(set(evidence.covered_findings))),
        evidence_digest=_digest(evidence),
        provider_plane_review_allowed=accepted,
        executable_candidate_allowed=False,
        provider_network_allowed=False,
        paper_ready_allowed=False,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        private_key_material_allowed=False,
    )


__all__ = [
    "SCHEMA_ID",
    "REQUIRED_FINDINGS",
    "DependencyEvidence",
    "EvidenceRef",
    "HeliusQueueEvidence",
    "LegacyBypassEvidence",
    "MPR27ProviderRoutingQuotaEvidence",
    "MPR27ProviderRoutingQuotaReport",
    "PeerBindingEvidence",
    "ProviderRegistryEvidence",
    "QuotaCircuitEvidence",
    "QuoteFreshnessEvidence",
    "QuoteIdentityEvidence",
    "RootedProviderIntakeEvidence",
    "TransportPolicyEvidence",
    "evaluate_mpr27_provider_routing_quota",
]
