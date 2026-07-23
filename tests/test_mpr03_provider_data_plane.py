import pytest

from src.mpr03_provider_data_plane import (
    MPR03ProviderPlaneError,
    MPR03_SCHEMA_VERSION,
    live_capability_allowed,
    sender_capability_allowed,
    signer_capability_allowed,
    validate_mpr03_provider_plane_evidence,
)

H = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


def complete_evidence():
    return {
        "schema_version": MPR03_SCHEMA_VERSION,
        "artifact_hashes": {
            "provider_registry_hash": H,
            "transport_policy_hash": H,
            "quota_authority_hash": H,
            "rooted_quorum_hash": H,
            "ingress_policy_hash": H,
            "webhook_queue_hash": H,
            "async_writer_hash": H,
            "backfill_policy_hash": H,
        },
        "transport": {
            "flags": [
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
            ],
            "redirect_policy": "deny-cross-origin",
            "total_deadline_ms": 10_000,
            "response_body_limit_bytes": 1_000_000,
            "json_rpc_batch_limit": 32,
            "websocket_message_limit_bytes": 1_000_000,
        },
        "provider_registry": {
            "flags": [
                "signed_registry",
                "credential_generation_bound",
                "operator_independence_bound",
                "network_path_independence_bound",
                "no_caller_defined_groups",
            ],
            "provider_ids": ["helius-main", "triton-main"],
            "min_independent_sources": 2,
            "registry_signature_sha256": H,
        },
        "quota": {
            "cross_process": True,
            "authority_owned_clock": True,
            "transactional_reservation": True,
            "retention_policy": True,
            "retry_storm_probe_rejected": True,
            "max_reserved_cost_units_per_cycle": 100,
        },
        "rooted_quorum": {
            "flags": [
                "unique_provider_identity",
                "registry_backed_independence",
                "request_response_hash_bound",
                "min_context_slot_bound",
                "duplicate_endpoint_probe_rejected",
                "caller_created_label_probe_rejected",
            ],
            "observations": [
                {
                    "provider_id": "helius-main",
                    "independence_group": "helius",
                    "rooted_slot": 500,
                    "state_hash": H,
                    "request_response_hash": H2,
                },
                {
                    "provider_id": "triton-main",
                    "independence_group": "triton",
                    "rooted_slot": 503,
                    "state_hash": H,
                    "request_response_hash": H3,
                },
            ],
            "min_context_slot": 490,
            "max_slot_skew": 16,
            "max_age_ms": 15_000,
        },
        "helius_ingress": {
            "flags": [
                "mandatory_ingress_policy",
                "compatibility_mode_disabled",
                "constant_time_auth_compare",
                "tls_proxy_generation_bound",
                "atomic_audit_delivery_event_commit",
                "ack_after_commit_only",
                "duplicate_delivery_conflict_quarantined",
                "malformed_json_rejected_4xx",
                "durable_backfill_on_provider_loss",
            ],
            "queue_flags": [
                "queued_claimed_processed_dlq_states",
                "claim_owner_lease_and_fence",
                "ack_nack_retry_schedule",
                "max_attempts_and_dead_letter",
                "idempotent_downstream_attempt_identity",
            ],
            "ack_statuses": [200, 202],
            "durable_transaction_hash": H,
        },
        "async_writer": {
            "flags": [
                "durable_enqueue_is_proof_critical",
                "accepted_work_not_cancelled_on_shutdown",
                "operation_descriptor_hash_bound",
                "operation_id_payload_mismatch_rejected",
                "byte_size_computed_inside_authority",
                "assert_free_runtime_invariants",
                "writer_crash_fails_all_promises",
                "result_reconciled_from_durable_journal",
            ],
            "max_queue_bytes": 5_000_000,
            "max_close_drain_ms": 30_000,
        },
        "fault_drills": [
            {"name": name, "passed": True, "invariant": "fails closed", "evidence_hash": H}
            for name in [
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
            ]
        ],
        "live_enabled": False,
        "signer_enabled": False,
        "sender_enabled": False,
        "compatibility_ingress_allowed": False,
    }


def codes(report):
    return {diagnostic.code for diagnostic in report.diagnostics}


def test_complete_evidence_is_ready_and_capabilities_are_disabled():
    report = validate_mpr03_provider_plane_evidence(complete_evidence())

    assert report.ready is True
    assert not report.blockers
    assert "MPR03_PROVIDER_PLANE_READY" in codes(report)
    assert live_capability_allowed() is False
    assert signer_capability_allowed() is False
    assert sender_capability_allowed() is False


def test_transport_missing_negative_probes_fails_closed():
    evidence = complete_evidence()
    evidence["transport"]["flags"].remove("dns_rebinding_negative_test")
    evidence["transport"]["flags"].remove("json_nan_rejected")
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "TRANSPORT_FLAG_MISSING" in codes(report)


def test_redirect_policy_must_deny_cross_origin():
    evidence = complete_evidence()
    evidence["transport"]["redirect_policy"] = "follow"
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "REDIRECT_POLICY_NOT_DENY_CROSS_ORIGIN" in codes(report)


def test_provider_registry_rejects_duplicates_and_caller_groups():
    evidence = complete_evidence()
    evidence["provider_registry"]["provider_ids"] = ["same", "same"]
    evidence["provider_registry"]["flags"].remove("no_caller_defined_groups")
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "PROVIDER_ID_NOT_UNIQUE" in codes(report)
    assert "PROVIDER_REGISTRY_FLAG_MISSING" in codes(report)


def test_quorum_rejects_duplicate_provider_labels():
    evidence = complete_evidence()
    evidence["rooted_quorum"]["observations"][1]["provider_id"] = "helius-main"
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "ROOTED_QUORUM_DUPLICATE_PROVIDER" in codes(report)


def test_quorum_rejects_state_mismatch_slot_skew_and_stale_policy():
    evidence = complete_evidence()
    evidence["rooted_quorum"]["observations"][1]["state_hash"] = H2
    evidence["rooted_quorum"]["observations"][1]["rooted_slot"] = 600
    evidence["rooted_quorum"]["max_age_ms"] = 120_000
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "ROOTED_QUORUM_STATE_HASH_MISMATCH" in codes(report)
    assert "ROOTED_QUORUM_SLOT_SKEW_EXCEEDED" in codes(report)
    assert "ROOTED_QUORUM_AGE_INVALID" in codes(report)


def test_ingress_requires_atomic_ack_after_commit_and_durable_queue():
    evidence = complete_evidence()
    evidence["helius_ingress"]["flags"].remove("atomic_audit_delivery_event_commit")
    evidence["helius_ingress"]["queue_flags"].remove("claim_owner_lease_and_fence")
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "INGRESS_FLAG_MISSING" in codes(report)
    assert "INGRESS_QUEUE_FLAG_MISSING" in codes(report)


def test_async_writer_rejects_optional_enqueue_and_mismatch_cache():
    evidence = complete_evidence()
    evidence["async_writer"]["flags"].remove("durable_enqueue_is_proof_critical")
    evidence["async_writer"]["flags"].remove("operation_id_payload_mismatch_rejected")
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "ASYNC_WRITER_FLAG_MISSING" in codes(report)


def test_fault_drill_failure_blocks_readiness():
    evidence = complete_evidence()
    evidence["fault_drills"][0]["passed"] = False
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "FAULT_DRILL_FAILED" in codes(report)


def test_missing_fault_drill_blocks_readiness():
    evidence = complete_evidence()
    evidence["fault_drills"] = evidence["fault_drills"][:-1]
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "FAULT_DRILL_MISSING" in codes(report)


def test_live_signer_sender_or_compat_ingress_blocks():
    evidence = complete_evidence()
    evidence["live_enabled"] = True
    evidence["signer_enabled"] = True
    evidence["sender_enabled"] = True
    evidence["compatibility_ingress_allowed"] = True
    report = validate_mpr03_provider_plane_evidence(evidence)

    assert report.ready is False
    assert "LIVE_ENABLED_IN_PROVIDER_PLANE" in codes(report)
    assert "SIGNER_ENABLED_IN_PROVIDER_PLANE" in codes(report)
    assert "SENDER_ENABLED_IN_PROVIDER_PLANE" in codes(report)
    assert "COMPATIBILITY_INGRESS_ALLOWED" in codes(report)


def test_malformed_schema_and_sha_raise():
    evidence = complete_evidence()
    evidence["schema_version"] = "wrong"
    with pytest.raises(MPR03ProviderPlaneError):
        validate_mpr03_provider_plane_evidence(evidence)

    evidence = complete_evidence()
    evidence["artifact_hashes"]["provider_registry_hash"] = "not-sha"
    with pytest.raises(MPR03ProviderPlaneError):
        validate_mpr03_provider_plane_evidence(evidence)
