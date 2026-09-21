"""Canonical MEGA8-01 roadmap ownership manifest."""

from __future__ import annotations

CHILDREN = {
    "PR-151": {
        "NF-353": "capture_head_delta",
        "NF-354": "invalidate_stale_evidence",
        "NF-355": "replay_impacted_qualifications",
        "NF-356": "publish_delta_qualification",
    },
    "PR-152": {
        "NF-357": "attest_program_binary",
        "NF-358": "track_upgrade_authority",
        "NF-359": "detect_deployment_drift",
        "NF-360": "revoke_capabilities_on_program_change",
    },
    "PR-153": {
        "NF-361": "register_schema_version",
        "NF-362": "diff_idl_account_layout",
        "NF-363": "migrate_decoder_contract",
        "NF-364": "replay_schema_conformance",
    },
    "PR-154": {
        "NF-365": "scan_upstream_semantic_drift",
        "NF-366": "refresh_golden_vectors",
        "NF-367": "classify_breaking_change",
        "NF-368": "gate_dependency_upgrade",
    },
    "PR-155": {
        "NF-369": "collect_provider_consensus_sample",
        "NF-370": "score_source_disagreement",
        "NF-371": "quarantine_byzantine_source",
        "NF-372": "reconstruct_consensus_state",
    },
    "PR-156": {
        "NF-373": "calibrate_monotonic_clock",
        "NF-374": "estimate_source_latency",
        "NF-375": "propagate_timestamp_uncertainty",
        "NF-376": "reject_temporally_ambiguous_frame",
    },
    "PR-157": {
        "NF-377": "plan_schema_migration",
        "NF-378": "execute_idempotent_backfill",
        "NF-379": "record_dataset_revision",
        "NF-380": "validate_cross_revision_replay",
    },
    "PR-158": {
        "NF-381": "content_address_partition",
        "NF-382": "deduplicate_raw_events",
        "NF-383": "compact_evidence_segments",
        "NF-384": "verify_compaction_equivalence",
    },
    "PR-159": {
        "NF-385": "register_query_contract",
        "NF-386": "materialize_research_view",
        "NF-387": "fingerprint_query_plan",
        "NF-388": "reproduce_evidence_query",
    },
    "PR-160": {
        "NF-389": "estimate_query_information_value",
        "NF-390": "allocate_source_quota_portfolio",
        "NF-391": "adapt_sampling_cadence",
        "NF-392": "audit_quota_allocation_gain",
    },
    "PR-161": {
        "NF-393": "validate_stream_payload_limits",
        "NF-394": "detect_data_poisoning_pattern",
        "NF-395": "quarantine_malformed_source",
        "NF-396": "replay_adversarial_ingest_suite",
    },
    "PR-162": {
        "NF-397": "build_workload_manifest",
        "NF-398": "freeze_benchmark_dataset",
        "NF-399": "run_cross_adapter_benchmark",
        "NF-400": "publish_benchmark_card",
    },
}

NF_SYMBOLS = {
    nf: symbol for functions in CHILDREN.values() for nf, symbol in functions.items()
}

SAFETY_INVARIANTS = {
    "signing": False,
    "submission": False,
    "live_trading": False,
    "remote_mutation": False,
    "automatic_capital_increase": False,
    "external_code_execution": False,
}
