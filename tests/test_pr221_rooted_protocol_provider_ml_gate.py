from __future__ import annotations

from copy import deepcopy

from src.pr221_rooted_protocol_provider_ml_gate import (
    REQUIRED_FINDINGS,
    REQUIRED_DRILLS,
    evaluate_pr221_gate,
)


GOOD_HASH = "a" * 64


def _complete_evidence():
    drill = {
        "target": "installed_sender_free_runtime",
        "result": "blocked_fail_closed",
        "evidence_sha256": GOOD_HASH,
    }
    return {
        "schema_version": "pr221.rooted-protocol-provider-ml-gate.v1",
        "roadmap": "PR-221",
        "capabilities": {
            "provider_network_allowed": False,
            "live_execution_allowed": False,
            "signer_allowed": False,
            "sender_allowed": False,
            "private_key_material_allowed": False,
        },
        "dependencies": {
            "PR-219": {
                "accepted": True,
                "materialized_evidence": True,
                "evidence_sha256": GOOD_HASH,
            },
            "PR-220": {
                "accepted": True,
                "materialized_evidence": True,
                "evidence_sha256": GOOD_HASH,
            },
        },
        "finding_coverage": sorted(REQUIRED_FINDINGS),
        "materialized_evidence": [
            {
                "materialized": True,
                "path": "evidence/pr221/protocol_bundle.json",
                "sha256": GOOD_HASH,
                "size_bytes": 123,
            }
        ],
        "protocol_attestation": {
            "protocols": [
                "solana_rpc",
                "jupiter_swap_v2",
                "marginfi",
                "helius",
                "spl_token",
                "token_2022",
            ],
            "materialized_contract_bytes": True,
            "self_attested_claims_allowed": False,
            "program_deployments_hashed": True,
            "token2022_extensions_bound": True,
            "wsol_lifecycle_bound": True,
            "release_contract_digest": GOOD_HASH,
        },
        "transport": {
            "single_owner": True,
            "https_only": True,
            "host_allowlist_enforced": True,
            "dns_ip_revalidation": True,
            "private_ip_blocked": True,
            "redirect_policy_enforced": True,
            "ca_bundle_digest_required": True,
            "strict_json_semantics": True,
            "duplicate_json_key_rejection": True,
            "response_byte_limit_streamed": True,
            "json_depth_key_budget": True,
            "headers_redacted": True,
            "bounded_cancellation": True,
            "shared_session_lifecycle": True,
            "max_response_bytes": 1_048_576,
            "max_json_depth": 48,
            "max_json_keys": 5000,
        },
        "endpoint_quota": {
            "typed_endpoint_registry": True,
            "credential_scoped_quota": True,
            "account_plan_environment_generation_bound": True,
            "reservation_state_machine": True,
            "reserved_issued_completed_released": True,
            "idempotent_transitions": True,
            "cache_bounded": True,
            "cache_returns_immutable_copy": True,
            "cooldown_for_429_without_retry_after": True,
        },
        "rooted_lineage": {
            "rpc_slot_before_after_provider_call": True,
            "min_context_slot_bound": True,
            "blockhash_window_bound": True,
            "genesis_cluster_identity_bound": True,
            "fork_skew_policy": True,
            "authoritative_backfill": True,
            "provider_response_hash_bound": True,
            "endpoint_credential_scope_bound": True,
            "max_slot_skew": 32,
        },
        "jupiter_v2": {
            "single_v2_adapter": True,
            "v1_legacy_removed_or_quarantined": True,
            "fabricated_context_slot_allowed": False,
            "official_build_schema_pinned": True,
            "route_plan_validated": True,
            "alt_addresses_bound": True,
            "tip_and_cu_policy_bound": True,
            "accepted_response_fields": [
                "routePlan",
                "computeBudgetInstructions",
                "tipInstruction",
                "addressLookupTableAddresses",
            ],
            "negative_percent_or_bps_rejected": True,
        },
        "helius": {
            "authenticated_ingress": True,
            "provider_delivery_id": True,
            "atomic_dedupe_audit": True,
            "bounded_retry": True,
            "correction_model": True,
            "rooted_gap_recovery": True,
            "webhook_is_hint_only": True,
            "bearer_only_empty_constraints_allowed": False,
        },
        "discovery": {
            "guaranteed_minimum_output_only": True,
            "route_continuity_required": True,
            "artifact_digest_bound": True,
            "freshness_amount_slot_coupled": True,
            "deterministic_value_risk_ordering": True,
            "request_cost_budget_per_cycle": True,
            "cancelled_child_tasks_joined": True,
            "failure_evidence_has_reason_status_retryability": True,
            "executable_from_discovery_only_response_allowed": False,
        },
        "opportunity_domain": {
            "finite_numeric_types": True,
            "u64_base_unit_money": True,
            "canonical_deep_freeze": True,
            "provider_evidence_aware_identity": True,
            "bounded_queues": True,
            "expired_after_ranker_rejected": True,
            "documented_priority_tiebreak": True,
            "input_mint_equals_output_allowed": False,
            "max_slippage_bps": 500,
        },
        "ml_dataset": {
            "no_temporal_leakage": True,
            "exact_label_event_provenance": True,
            "canonical_utc_timestamps": True,
            "atomic_dataset_manifest": True,
            "manifest_bound_to_exact_rows": True,
            "group_aware_splits": True,
            "embargo_validated": True,
            "minimum_sample_policy": True,
            "ood_gate": True,
            "deterministic_hash_between_hosts": True,
            "nested_object_float_validation": True,
            "minimum_training_rows": 1000,
            "undefined_metrics_as_strings_allowed": False,
        },
        "adversarial_drills": [
            {"name": name, **drill} for name in sorted(REQUIRED_DRILLS)
        ],
    }


def test_complete_evidence_passes_but_keeps_live_sender_disabled():
    report = evaluate_pr221_gate(_complete_evidence())
    assert report.accepted is True
    assert report.executable_opportunity_allowed is True
    assert report.decision_dataset_allowed is True
    assert report.provider_network_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.blockers == ()


def test_blocks_without_pr219_or_pr220_dependency_evidence():
    evidence = _complete_evidence()
    evidence["dependencies"]["PR-219"]["accepted"] = False
    evidence["dependencies"]["PR-220"]["materialized_evidence"] = False
    report = evaluate_pr221_gate(evidence)
    assert report.accepted is False
    assert "DEPENDENCY_NOT_ACCEPTED_PR-219" in report.blockers
    assert "DEPENDENCY_NOT_MATERIALIZED_PR-220" in report.blockers


def test_blocks_incomplete_finding_coverage():
    evidence = _complete_evidence()
    evidence["finding_coverage"] = ["F-012"]
    report = evaluate_pr221_gate(evidence)
    assert report.accepted is False
    assert any(item.startswith("FINDING_COVERAGE_INCOMPLETE") for item in report.blockers)


def test_blocks_self_attested_or_unmaterialized_protocol_claims():
    evidence = _complete_evidence()
    evidence["protocol_attestation"]["self_attested_claims_allowed"] = True
    evidence["protocol_attestation"]["materialized_contract_bytes"] = False
    report = evaluate_pr221_gate(evidence)
    assert "SELF_ATTESTED_PROTOCOL_CLAIMS_ALLOWED" in report.blockers
    assert "PROTOCOL_CONTRACT_BYTES_NOT_MATERIALIZED" in report.blockers


def test_blocks_insecure_transport_and_host_escape():
    evidence = _complete_evidence()
    evidence["transport"]["private_ip_blocked"] = False
    evidence["transport"]["host_allowlist_enforced"] = False
    evidence["transport"]["response_byte_limit_streamed"] = False
    report = evaluate_pr221_gate(evidence)
    assert "TRANSPORT_PRIVATE_IP_BLOCKED_MISSING" in report.blockers
    assert "TRANSPORT_HOST_ALLOWLIST_ENFORCED_MISSING" in report.blockers
    assert "TRANSPORT_RESPONSE_BYTE_LIMIT_STREAMED_MISSING" in report.blockers


def test_blocks_unscoped_quota_and_mutable_cache():
    evidence = _complete_evidence()
    evidence["endpoint_quota"]["credential_scoped_quota"] = False
    evidence["endpoint_quota"]["cache_returns_immutable_copy"] = False
    report = evaluate_pr221_gate(evidence)
    assert "QUOTA_CREDENTIAL_SCOPED_QUOTA_MISSING" in report.blockers
    assert "QUOTA_CACHE_RETURNS_IMMUTABLE_COPY_MISSING" in report.blockers


def test_blocks_fabricated_jupiter_context_and_v1_fallback():
    evidence = _complete_evidence()
    evidence["jupiter_v2"]["fabricated_context_slot_allowed"] = True
    evidence["jupiter_v2"]["v1_legacy_removed_or_quarantined"] = False
    evidence["jupiter_v2"]["accepted_response_fields"] = ["routePlan"]
    report = evaluate_pr221_gate(evidence)
    assert "JUPITER_FABRICATED_CONTEXT_SLOT_ALLOWED" in report.blockers
    assert "JUPITER_V1_NOT_RETIRED" in report.blockers
    assert "JUPITER_REQUIRED_FIELDS_MISSING" in report.blockers


def test_blocks_helius_as_source_of_truth_and_weak_ingress():
    evidence = _complete_evidence()
    evidence["helius"]["webhook_is_hint_only"] = False
    evidence["helius"]["bearer_only_empty_constraints_allowed"] = True
    report = evaluate_pr221_gate(evidence)
    assert "HELIUS_WEBHOOK_IS_HINT_ONLY_MISSING" in report.blockers
    assert "HELIUS_BEARER_ONLY_EMPTY_CONSTRAINTS_ALLOWED" in report.blockers


def test_blocks_discovery_only_executable_candidate():
    evidence = _complete_evidence()
    evidence["discovery"]["guaranteed_minimum_output_only"] = False
    evidence["discovery"]["executable_from_discovery_only_response_allowed"] = True
    report = evaluate_pr221_gate(evidence)
    assert "DISCOVERY_GUARANTEED_MINIMUM_OUTPUT_ONLY_MISSING" in report.blockers
    assert "DISCOVERY_ONLY_EXECUTABLE_ALLOWED" in report.blockers


def test_blocks_unsafe_opportunity_domain():
    evidence = _complete_evidence()
    evidence["opportunity_domain"]["finite_numeric_types"] = False
    evidence["opportunity_domain"]["input_mint_equals_output_allowed"] = True
    evidence["opportunity_domain"]["max_slippage_bps"] = 10_000
    report = evaluate_pr221_gate(evidence)
    assert "OPPORTUNITY_FINITE_NUMERIC_TYPES_MISSING" in report.blockers
    assert "OPPORTUNITY_SELF_SWAP_ALLOWED" in report.blockers
    assert "OPPORTUNITY_SLIPPAGE_POLICY_INVALID" in report.blockers


def test_blocks_temporal_leakage_and_tiny_training_set():
    evidence = _complete_evidence()
    evidence["ml_dataset"]["no_temporal_leakage"] = False
    evidence["ml_dataset"]["minimum_training_rows"] = 12
    evidence["ml_dataset"]["undefined_metrics_as_strings_allowed"] = True
    report = evaluate_pr221_gate(evidence)
    assert "ML_NO_TEMPORAL_LEAKAGE_MISSING" in report.blockers
    assert "ML_MINIMUM_SAMPLE_TOO_LOW" in report.blockers
    assert "ML_UNDEFINED_METRICS_AS_STRINGS_ALLOWED" in report.blockers


def test_blocks_missing_or_source_only_drills():
    evidence = _complete_evidence()
    evidence["adversarial_drills"] = [
        {
            "name": "dns_rebinding",
            "target": "source_tree",
            "result": "passed",
            "evidence_sha256": "not-a-hash",
        }
    ]
    report = evaluate_pr221_gate(evidence)
    assert any(item.startswith("ADVERSARIAL_DRILLS_MISSING") for item in report.blockers)
    assert "DRILL_dns_rebinding_NOT_INSTALLED_RUNTIME" in report.blockers
    assert "DRILL_dns_rebinding_DID_NOT_FAIL_CLOSED" in report.blockers
    assert "DRILL_dns_rebinding_DIGEST_INVALID" in report.blockers


def test_blocks_reachable_live_signer_sender_or_network():
    evidence = _complete_evidence()
    evidence["capabilities"]["provider_network_allowed"] = True
    evidence["capabilities"]["live_execution_allowed"] = True
    evidence["capabilities"]["signer_allowed"] = True
    evidence["capabilities"]["sender_allowed"] = True
    report = evaluate_pr221_gate(evidence)
    assert "FORBIDDEN_CAPABILITY_PROVIDER_NETWORK_ALLOWED" in report.blockers
    assert "FORBIDDEN_CAPABILITY_LIVE_EXECUTION_ALLOWED" in report.blockers
    assert "FORBIDDEN_CAPABILITY_SIGNER_ALLOWED" in report.blockers
    assert "FORBIDDEN_CAPABILITY_SENDER_ALLOWED" in report.blockers


def test_report_hash_is_deterministic_for_equivalent_mapping_order():
    evidence = _complete_evidence()
    reordered = deepcopy(evidence)
    reordered["capabilities"] = dict(reversed(list(reordered["capabilities"].items())))
    assert evaluate_pr221_gate(evidence).evidence_hash == evaluate_pr221_gate(reordered).evidence_hash
