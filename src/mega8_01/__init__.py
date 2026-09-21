"""MEGA8-01 offline qualification and reproducible-data contracts."""

from .common import Disposition, EvidenceArtifact
from .manifest import CHILDREN, NF_SYMBOLS, SAFETY_INVARIANTS
from .pr151 import (
    capture_head_delta,
    invalidate_stale_evidence,
    publish_delta_qualification,
    replay_impacted_qualifications,
)
from .pr152 import (
    attest_program_binary,
    detect_deployment_drift,
    revoke_capabilities_on_program_change,
    track_upgrade_authority,
)
from .pr153 import (
    diff_idl_account_layout,
    migrate_decoder_contract,
    register_schema_version,
    replay_schema_conformance,
)
from .pr154 import (
    classify_breaking_change,
    gate_dependency_upgrade,
    refresh_golden_vectors,
    scan_upstream_semantic_drift,
)
from .pr155 import (
    collect_provider_consensus_sample,
    quarantine_byzantine_source,
    reconstruct_consensus_state,
    score_source_disagreement,
)
from .pr156 import (
    calibrate_monotonic_clock,
    estimate_source_latency,
    propagate_timestamp_uncertainty,
    reject_temporally_ambiguous_frame,
)
from .pr157 import (
    execute_idempotent_backfill,
    plan_schema_migration,
    record_dataset_revision,
    validate_cross_revision_replay,
)
from .pr158 import (
    compact_evidence_segments,
    content_address_partition,
    deduplicate_raw_events,
    verify_compaction_equivalence,
)
from .pr159 import (
    fingerprint_query_plan,
    materialize_research_view,
    register_query_contract,
    reproduce_evidence_query,
)
from .pr160 import (
    adapt_sampling_cadence,
    allocate_source_quota_portfolio,
    audit_quota_allocation_gain,
    estimate_query_information_value,
)
from .pr161 import (
    detect_data_poisoning_pattern,
    quarantine_malformed_source,
    replay_adversarial_ingest_suite,
    validate_stream_payload_limits,
)
from .pr162 import (
    build_workload_manifest,
    freeze_benchmark_dataset,
    publish_benchmark_card,
    run_cross_adapter_benchmark,
)

__all__ = [
    "CHILDREN",
    "NF_SYMBOLS",
    "SAFETY_INVARIANTS",
    "Disposition",
    "EvidenceArtifact",
    *NF_SYMBOLS.values(),
]
