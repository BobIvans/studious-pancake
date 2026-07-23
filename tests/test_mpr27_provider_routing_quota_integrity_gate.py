from __future__ import annotations

import json

import pytest

from src.mpr27_provider_routing_quota_integrity_gate import (
    REQUIRED_FINDINGS,
    SCHEMA_ID,
    DependencyEvidence,
    EvidenceRef,
    HeliusQueueEvidence,
    LegacyBypassEvidence,
    MPR27ProviderRoutingQuotaEvidence,
    PeerBindingEvidence,
    ProviderRegistryEvidence,
    QuotaCircuitEvidence,
    QuoteFreshnessEvidence,
    QuoteIdentityEvidence,
    RootedProviderIntakeEvidence,
    TransportPolicyEvidence,
    evaluate_mpr27_provider_routing_quota,
)


def ref(name: str, digit: str = "2") -> EvidenceRef:
    return EvidenceRef(
        path=f"evidence/mpr27/{name}.json",
        sha256=(digit * 64),
        size_bytes=1024,
        materialized=True,
        immutable=True,
        signed=True,
    )


def valid_evidence(**overrides) -> MPR27ProviderRoutingQuotaEvidence:
    evidence = MPR27ProviderRoutingQuotaEvidence(
        schema_id=SCHEMA_ID,
        covered_findings=REQUIRED_FINDINGS,
        dependencies=DependencyEvidence(
            mpr25_product_graph_frozen=True,
            mpr25_release_qualification_authoritative=True,
            mpr26_durable_authority_accepted=True,
            mpr26_outbox_and_attempt_authority_available=True,
            mpr25_artifact_manifest=ref("mpr25", "2"),
            mpr26_authority_manifest=ref("mpr26", "3"),
        ),
        provider_intake=RootedProviderIntakeEvidence(
            provider_artifacts=(ref("provider-bytes", "4"),),
            recorded_json_production_input_disabled=True,
            provider_owned_content_addressing=True,
            rpc_helius_jupiter_bytes_materialized=True,
            request_policy_hash_bound=True,
            decoded_schema_quarantine=True,
            caller_declared_digest_rejected=True,
            stale_or_unrooted_bytes_block_candidate=True,
            candidate_requires_stored_evidence_id=True,
        ),
        transport=TransportPolicyEvidence(
            single_transport_owner=True,
            total_deadline_ms=5_000,
            response_byte_limit=2_000_000,
            decompressed_byte_limit=4_000_000,
            json_depth_limit=32,
            duplicate_keys_rejected=True,
            non_finite_numbers_rejected=True,
            schema_quarantine=True,
            bounded_cancellation=True,
            retry_storm_budgeted=True,
            diagnostic_redaction=True,
        ),
        peer_binding=PeerBindingEvidence(
            dns_preflight_bound_to_connect_peer=True,
            tls_sni_verified=True,
            tls_peer_certificate_bound=True,
            private_ip_denied=True,
            link_local_denied=True,
            loopback_denied=True,
            redirect_revalidated=True,
            unapproved_origin_redirect_denied=True,
            injected_client_policy_bypass_removed=True,
        ),
        registry=ProviderRegistryEvidence(
            registry_artifact=ref("provider-registry", "5"),
            signed_provider_registry=True,
            unique_provider_ids=True,
            unique_operator_groups=True,
            unique_network_path_groups=True,
            quorum_independence_enforced=True,
            caller_created_group_labels_rejected=True,
            provider_cluster_generation_bound=True,
        ),
        quota=QuotaCircuitEvidence(
            quota_authority_artifact=ref("quota", "6"),
            cross_process_serialized=True,
            request_bound_reservation=True,
            ttl_revalidated_on_retry=True,
            static_snapshot_cannot_authorize_multiple_retries=True,
            mark_used_exactly_once=True,
            release_is_idempotent=True,
            cooldown_persisted_across_restart=True,
            provider_account_plan_generation_bound=True,
            two_process_race_probe=True,
        ),
        quote_identity=QuoteIdentityEvidence(
            length_prefixed_or_canonical_tuple_encoding=True,
            includes_provider=True,
            includes_cluster=True,
            includes_mint_pair=True,
            includes_amount=True,
            includes_mode=True,
            includes_slippage=True,
            includes_route_params=True,
            includes_policy_generation=True,
            includes_request_hash=True,
            delimiter_collision_regression=True,
            mutable_cached_quote_copy_denied=True,
        ),
        freshness=QuoteFreshnessEvidence(
            trusted_current_slot_or_time=True,
            missing_expiry_non_executable=True,
            future_timestamp_rejected=True,
            nan_or_infinite_age_rejected=True,
            stale_slot_rejected=True,
            self_relative_freshness_rejected=True,
            route_mutation_after_admission_invalidates_candidate=True,
            slippage_widening_rejected=True,
            mint_amount_or_swap_mode_mutation_rejected=True,
        ),
        helius=HeliusQueueEvidence(
            durable_queue_artifact=ref("helius-queue", "7"),
            ack_after_atomic_audit_event_commit=True,
            claim_lease_retry_dlq_backfill=True,
            idempotent_downstream_attempt_identity=True,
            filtered_webhook_semantics_backfill_bounded=True,
            crash_after_accept_enqueue_claim_processing_probe=True,
            no_double_apply_after_restart=True,
            webhook_not_source_of_truth=True,
        ),
        legacy_bypass=LegacyBypassEvidence(
            raw_provider_digest_strings_rejected=True,
            injected_http_client_escape_hatches_removed=True,
            legacy_recorded_json_production_adapter_disabled=True,
            slot_gap_rpc_storm_logic_removed_or_filter_bound=True,
            old_path_cannot_create_candidate=True,
            old_path_cannot_mark_paper_success=True,
        ),
    )
    for key, value in overrides.items():
        object.__setattr__(evidence, key, value)
    return evidence


def blockers(evidence: MPR27ProviderRoutingQuotaEvidence) -> tuple[str, ...]:
    return evaluate_mpr27_provider_routing_quota(evidence).blockers


def test_happy_path_allows_review_only() -> None:
    report = evaluate_mpr27_provider_routing_quota(valid_evidence())

    assert report.accepted is True
    assert report.provider_plane_review_allowed is True
    assert report.executable_candidate_allowed is False
    assert report.provider_network_allowed is False
    assert report.paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.private_key_material_allowed is False
    assert json.loads(report.to_json())["schema_id"] == SCHEMA_ID


def test_missing_or_duplicate_finding_coverage_fails_closed() -> None:
    missing = valid_evidence(covered_findings=REQUIRED_FINDINGS[:-1])
    duplicate = valid_evidence(covered_findings=REQUIRED_FINDINGS + (REQUIRED_FINDINGS[0],))

    assert "MPR27_FINDING_COVERAGE_INCOMPLETE" in blockers(missing)
    assert "MPR27_FINDING_COVERAGE_INCOMPLETE" in blockers(duplicate)


def test_mpr25_and_mpr26_dependencies_are_mandatory() -> None:
    deps = DependencyEvidence(
        mpr25_product_graph_frozen=False,
        mpr25_release_qualification_authoritative=True,
        mpr26_durable_authority_accepted=False,
        mpr26_outbox_and_attempt_authority_available=True,
        mpr25_artifact_manifest=ref("mpr25"),
        mpr26_authority_manifest=ref("mpr26"),
    )
    result = blockers(valid_evidence(dependencies=deps))

    assert "MPR27_MPR25_PRODUCT_GRAPH_NOT_FROZEN" in result
    assert "MPR27_MPR26_DURABLE_AUTHORITY_NOT_ACCEPTED" in result


def test_placeholder_or_source_only_evidence_fails_closed() -> None:
    bad = EvidenceRef(
        path="<missing>",
        sha256="0" * 64,
        size_bytes=0,
        materialized=False,
        immutable=False,
        signed=False,
    )
    deps = DependencyEvidence(
        mpr25_product_graph_frozen=True,
        mpr25_release_qualification_authoritative=True,
        mpr26_durable_authority_accepted=True,
        mpr26_outbox_and_attempt_authority_available=True,
        mpr25_artifact_manifest=bad,
        mpr26_authority_manifest=ref("mpr26"),
    )

    assert "MPR27_EVIDENCE_NOT_MATERIALIZED" in blockers(valid_evidence(dependencies=deps))


def test_rooted_provider_intake_rejects_recorded_json_as_production_input() -> None:
    intake = RootedProviderIntakeEvidence(
        provider_artifacts=(),
        recorded_json_production_input_disabled=False,
        provider_owned_content_addressing=True,
        rpc_helius_jupiter_bytes_materialized=True,
        request_policy_hash_bound=True,
        decoded_schema_quarantine=True,
        caller_declared_digest_rejected=True,
        stale_or_unrooted_bytes_block_candidate=True,
        candidate_requires_stored_evidence_id=True,
    )

    result = blockers(valid_evidence(provider_intake=intake))

    assert "MPR27_ROOTED_PROVIDER_INTAKE_REQUIRED" in result
    assert "MPR27_RECORDED_JSON_STILL_PRODUCTION_INPUT" in result


def test_transport_requires_budgeted_strict_json_and_retry_storm_bounds() -> None:
    transport = TransportPolicyEvidence(
        single_transport_owner=True,
        total_deadline_ms=0,
        response_byte_limit=2_000_000,
        decompressed_byte_limit=4_000_000,
        json_depth_limit=32,
        duplicate_keys_rejected=False,
        non_finite_numbers_rejected=True,
        schema_quarantine=True,
        bounded_cancellation=True,
        retry_storm_budgeted=False,
        diagnostic_redaction=True,
    )

    assert "MPR27_BOUNDED_TRANSPORT_REQUIRED" in blockers(valid_evidence(transport=transport))


def test_dns_tls_peer_binding_blocks_private_redirect_and_injected_clients() -> None:
    peer = PeerBindingEvidence(
        dns_preflight_bound_to_connect_peer=False,
        tls_sni_verified=True,
        tls_peer_certificate_bound=True,
        private_ip_denied=True,
        link_local_denied=True,
        loopback_denied=True,
        redirect_revalidated=False,
        unapproved_origin_redirect_denied=True,
        injected_client_policy_bypass_removed=False,
    )

    assert "MPR27_DNS_TLS_PEER_BINDING_REQUIRED" in blockers(valid_evidence(peer_binding=peer))


def test_provider_registry_must_prevent_self_labeled_quorum() -> None:
    registry = ProviderRegistryEvidence(
        registry_artifact=ref("registry"),
        signed_provider_registry=True,
        unique_provider_ids=True,
        unique_operator_groups=False,
        unique_network_path_groups=True,
        quorum_independence_enforced=False,
        caller_created_group_labels_rejected=False,
        provider_cluster_generation_bound=True,
    )

    assert "MPR27_PROVIDER_REGISTRY_REQUIRED" in blockers(valid_evidence(registry=registry))


def test_quota_requires_cross_process_request_bound_authority() -> None:
    quota = QuotaCircuitEvidence(
        quota_authority_artifact=ref("quota"),
        cross_process_serialized=False,
        request_bound_reservation=False,
        ttl_revalidated_on_retry=True,
        static_snapshot_cannot_authorize_multiple_retries=False,
        mark_used_exactly_once=True,
        release_is_idempotent=True,
        cooldown_persisted_across_restart=True,
        provider_account_plan_generation_bound=False,
        two_process_race_probe=False,
    )

    assert "MPR27_CROSS_PROCESS_QUOTA_REQUIRED" in blockers(valid_evidence(quota=quota))


def test_quote_identity_must_be_collision_proof_and_policy_bound() -> None:
    identity = QuoteIdentityEvidence(
        length_prefixed_or_canonical_tuple_encoding=False,
        includes_provider=True,
        includes_cluster=True,
        includes_mint_pair=True,
        includes_amount=True,
        includes_mode=True,
        includes_slippage=True,
        includes_route_params=True,
        includes_policy_generation=False,
        includes_request_hash=True,
        delimiter_collision_regression=False,
        mutable_cached_quote_copy_denied=True,
    )

    assert "MPR27_QUOTE_IDENTITY_NOT_COLLISION_PROOF" in blockers(
        valid_evidence(quote_identity=identity)
    )


def test_quote_freshness_blocks_missing_expiry_future_nan_and_mutation() -> None:
    freshness = QuoteFreshnessEvidence(
        trusted_current_slot_or_time=True,
        missing_expiry_non_executable=False,
        future_timestamp_rejected=False,
        nan_or_infinite_age_rejected=False,
        stale_slot_rejected=True,
        self_relative_freshness_rejected=False,
        route_mutation_after_admission_invalidates_candidate=False,
        slippage_widening_rejected=False,
        mint_amount_or_swap_mode_mutation_rejected=True,
    )

    assert "MPR27_QUOTE_FRESHNESS_NOT_TRUSTED" in blockers(
        valid_evidence(freshness=freshness)
    )


def test_helius_must_ack_after_durable_commit_and_not_be_truth_source() -> None:
    helius = HeliusQueueEvidence(
        durable_queue_artifact=ref("helius"),
        ack_after_atomic_audit_event_commit=False,
        claim_lease_retry_dlq_backfill=True,
        idempotent_downstream_attempt_identity=True,
        filtered_webhook_semantics_backfill_bounded=False,
        crash_after_accept_enqueue_claim_processing_probe=True,
        no_double_apply_after_restart=False,
        webhook_not_source_of_truth=False,
    )

    assert "MPR27_HELIUS_QUEUE_NOT_DURABLE" in blockers(valid_evidence(helius=helius))


def test_legacy_bypasses_must_be_deleted_or_hard_disabled() -> None:
    legacy = LegacyBypassEvidence(
        raw_provider_digest_strings_rejected=False,
        injected_http_client_escape_hatches_removed=False,
        legacy_recorded_json_production_adapter_disabled=True,
        slot_gap_rpc_storm_logic_removed_or_filter_bound=False,
        old_path_cannot_create_candidate=True,
        old_path_cannot_mark_paper_success=False,
    )

    assert "MPR27_LEGACY_PROVIDER_BYPASS_REACHABLE" in blockers(
        valid_evidence(legacy_bypass=legacy)
    )


@pytest.mark.parametrize(
    "flag",
    [
        "provider_network_requested",
        "executable_candidate_requested",
        "live_execution_requested",
        "signer_requested",
        "sender_requested",
        "private_key_material_requested",
    ],
)
def test_forbidden_runtime_capability_requests_fail_closed(flag: str) -> None:
    evidence = valid_evidence(**{flag: True})

    report = evaluate_mpr27_provider_routing_quota(evidence)

    assert "MPR27_FORBIDDEN_RUNTIME_CAPABILITY_REQUESTED" in report.blockers
    assert report.provider_network_allowed is False
    assert report.executable_candidate_allowed is False
    assert report.live_execution_allowed is False
