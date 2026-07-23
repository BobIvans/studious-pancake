from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.pr216_unified_persistence_backup_recovery_gate import (
    PR216Blocker,
    PR216EvidenceError,
    BackupPublicationEvidence,
    FaultInjectionEvidence,
    PersistenceCatalogEvidence,
    PR216UnifiedPersistenceEvidence,
    PragmaPolicyEvidence,
    REQUIRED_FAULT_SCENARIOS,
    RestoreCutoverEvidence,
    SCHEMA_VERSION,
    TerminalTruthEvidence,
    evaluate_pr216_unified_persistence,
)


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def complete_evidence() -> PR216UnifiedPersistenceEvidence:
    catalog = PersistenceCatalogEvidence(
        platform_factory_sha256=h("factory"),
        catalog_sha256=h("catalog"),
        discovered_connect_sites=61,
        approved_platform_connect_sites=61,
        direct_connects_outside_platform=0,
        catalogued_databases=8,
        catalogued_tables=42,
        every_database_has_owner=True,
        every_table_has_rebuild_or_authority=True,
    )
    pragma_policy = PragmaPolicyEvidence(
        policy_sha256=h("pragma-policy"),
        durable_critical_profile_sha256=h("durable-critical"),
        read_model_profile_sha256=h("read-model"),
        test_profile_sha256=h("test-profile"),
        all_connections_apply_factory_policy=True,
        wal_enabled_for_durable_critical=True,
        synchronous_full_for_durable_critical=True,
        busy_timeout_configured=True,
        trusted_schema_disabled=True,
        foreign_keys_enabled=True,
        profile_validation_after_connect=True,
    )
    terminal_truth = TerminalTruthEvidence(
        system_of_record_sha256=h("system-of-record"),
        projection_catalog_sha256=h("projection-catalog"),
        terminal_authority_count=1,
        projections_have_sequence_fence=True,
        projections_are_rebuildable_from_record=True,
        outbox_consumers_are_idempotent=True,
        recovery_order_sha256=h("recovery-order"),
        recovery_order_covers_all_stores=True,
    )
    backup = BackupPublicationEvidence(
        backup_bundle_sha256=h("backup-bundle"),
        schema_manifest_sha256=h("schema-manifest"),
        product_manifest_sha256=h("product-manifest"),
        generation_directory_used=True,
        database_backup_fsynced=True,
        manifest_written_to_temp_then_renamed=True,
        manifest_file_fsynced=True,
        parent_directory_fsynced=True,
        atomic_pointer_publish=True,
        independent_verifier_recomputes_db_hash=True,
    )
    restore = RestoreCutoverEvidence(
        restore_plan_sha256=h("restore-plan"),
        replacement_materialized_before_cutover=True,
        replacement_opened_and_checked_before_closing_live=True,
        live_store_kept_available_until_validated=True,
        old_generation_preserved_until_healthcheck=True,
        rollback_marker_written=True,
        rollback_proven_after_replace_failure=True,
        directory_fsync_after_replace=True,
        healthcheck_before_retiring_old_generation=True,
    )
    fault = FaultInjectionEvidence(
        matrix_sha256=h("fault-matrix"),
        executed_scenarios=tuple(sorted(REQUIRED_FAULT_SCENARIOS)),
        all_failures_preserved_old_generation=True,
        old_generation_available_after_each_failure=True,
        failure_reports_have_stable_reason_codes=True,
        subprocess_or_fork_crash_tests=True,
    )
    return PR216UnifiedPersistenceEvidence(
        catalog=catalog,
        pragma_policy=pragma_policy,
        terminal_truth=terminal_truth,
        backup_publication=backup,
        restore_cutover=restore,
        fault_injection=fault,
    )


def blocker_set(report) -> set[str]:
    return set(report.blockers)


def test_complete_evidence_is_ready_but_does_not_mutate_runtime() -> None:
    report = evaluate_pr216_unified_persistence(complete_evidence())

    assert report.schema_version == SCHEMA_VERSION
    assert report.ready
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.restore_mutation_allowed is False
    assert report.database_connection_allowed is False
    assert len(report.evidence_hash) == 64


def test_direct_sqlite_connects_outside_platform_are_blocked() -> None:
    evidence = complete_evidence()
    catalog = replace(
        evidence.catalog,
        approved_platform_connect_sites=60,
        direct_connects_outside_platform=1,
    )

    report = evaluate_pr216_unified_persistence(replace(evidence, catalog=catalog))

    assert not report.ready
    assert PR216Blocker.DIRECT_SQLITE_CONNECT_OUTSIDE_PLATFORM.value in blocker_set(
        report
    )


def test_database_catalog_must_cover_owners_and_rebuild_rules() -> None:
    evidence = complete_evidence()
    catalog = replace(
        evidence.catalog,
        every_database_has_owner=False,
        every_table_has_rebuild_or_authority=False,
    )

    report = evaluate_pr216_unified_persistence(replace(evidence, catalog=catalog))

    assert not report.ready
    assert PR216Blocker.DATABASE_CATALOG_INCOMPLETE.value in blocker_set(report)


def test_pragma_policy_must_be_centralized_and_complete() -> None:
    evidence = complete_evidence()
    policy = replace(
        evidence.pragma_policy,
        all_connections_apply_factory_policy=False,
        synchronous_full_for_durable_critical=False,
        trusted_schema_disabled=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, pragma_policy=policy)
    )

    assert not report.ready
    assert PR216Blocker.PRAGMA_POLICY_NOT_CENTRALIZED.value in blocker_set(report)
    assert PR216Blocker.PRAGMA_PROFILE_INCOMPLETE.value in blocker_set(report)


def test_multiple_terminal_truths_are_blocked() -> None:
    evidence = complete_evidence()
    terminal = replace(evidence.terminal_truth, terminal_authority_count=3)

    report = evaluate_pr216_unified_persistence(
        replace(evidence, terminal_truth=terminal)
    )

    assert not report.ready
    assert PR216Blocker.MULTIPLE_TERMINAL_TRUTHS.value in blocker_set(report)


def test_projection_rebuild_and_recovery_order_are_required() -> None:
    evidence = complete_evidence()
    terminal = replace(
        evidence.terminal_truth,
        projections_have_sequence_fence=False,
        recovery_order_sha256=None,
        recovery_order_covers_all_stores=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, terminal_truth=terminal)
    )

    assert not report.ready
    assert PR216Blocker.PROJECTIONS_NOT_REBUILDABLE.value in blocker_set(report)
    assert PR216Blocker.RECOVERY_ORDER_NOT_DECLARED.value in blocker_set(report)


def test_backup_publication_must_be_atomic_and_durable() -> None:
    evidence = complete_evidence()
    backup = replace(
        evidence.backup_publication,
        generation_directory_used=False,
        manifest_written_to_temp_then_renamed=False,
        database_backup_fsynced=False,
        parent_directory_fsynced=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, backup_publication=backup)
    )

    assert not report.ready
    assert PR216Blocker.BACKUP_PUBLICATION_NOT_ATOMIC.value in blocker_set(report)
    assert PR216Blocker.BACKUP_PUBLICATION_NOT_DURABLE.value in blocker_set(report)


def test_restore_must_validate_before_cutover_and_keep_old_generation() -> None:
    evidence = complete_evidence()
    restore = replace(
        evidence.restore_cutover,
        replacement_opened_and_checked_before_closing_live=False,
        live_store_kept_available_until_validated=False,
        old_generation_preserved_until_healthcheck=False,
        rollback_proven_after_replace_failure=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, restore_cutover=restore)
    )

    assert not report.ready
    assert PR216Blocker.RESTORE_CLOSES_LIVE_STORE_TOO_EARLY.value in blocker_set(
        report
    )
    assert PR216Blocker.RESTORE_ROLLBACK_NOT_PROVEN.value in blocker_set(report)


def test_restore_requires_directory_fsync_after_replace() -> None:
    evidence = complete_evidence()
    restore = replace(evidence.restore_cutover, directory_fsync_after_replace=False)

    report = evaluate_pr216_unified_persistence(
        replace(evidence, restore_cutover=restore)
    )

    assert not report.ready
    assert PR216Blocker.RESTORE_DIRECTORY_FSYNC_MISSING.value in blocker_set(report)


def test_fault_matrix_must_cover_every_required_failure() -> None:
    evidence = complete_evidence()
    scenarios = tuple(
        scenario
        for scenario in sorted(REQUIRED_FAULT_SCENARIOS)
        if scenario != "failed_reopen"
    )
    fault = replace(
        evidence.fault_injection,
        executed_scenarios=scenarios,
        subprocess_or_fork_crash_tests=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, fault_injection=fault)
    )

    assert not report.ready
    assert PR216Blocker.FAULT_MATRIX_INCOMPLETE.value in blocker_set(report)


def test_fault_matrix_must_preserve_old_generation_after_each_failure() -> None:
    evidence = complete_evidence()
    fault = replace(
        evidence.fault_injection,
        all_failures_preserved_old_generation=False,
        old_generation_available_after_each_failure=False,
    )

    report = evaluate_pr216_unified_persistence(
        replace(evidence, fault_injection=fault)
    )

    assert not report.ready
    assert PR216Blocker.OLD_GENERATION_NOT_PRESERVED.value in blocker_set(report)


def test_live_sender_or_restore_mutation_surface_blocks_gate() -> None:
    evidence = replace(
        complete_evidence(),
        live_execution_reachable=True,
        sender_reachable=True,
        direct_restore_mutation_reachable=True,
    )

    report = evaluate_pr216_unified_persistence(evidence)

    assert not report.ready
    assert PR216Blocker.LIVE_OR_SENDER_REACHABLE.value in blocker_set(report)


def test_placeholder_digests_are_rejected() -> None:
    with pytest.raises(PR216EvidenceError, match="placeholder"):
        BackupPublicationEvidence(
            backup_bundle_sha256="0" * 64,
            schema_manifest_sha256=h("schema"),
            product_manifest_sha256=h("product"),
            generation_directory_used=True,
            database_backup_fsynced=True,
            manifest_written_to_temp_then_renamed=True,
            manifest_file_fsynced=True,
            parent_directory_fsynced=True,
            atomic_pointer_publish=True,
            independent_verifier_recomputes_db_hash=True,
        )


def test_report_json_is_stable() -> None:
    report = evaluate_pr216_unified_persistence(complete_evidence())
    payload = json.loads(report.to_json())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ready"] is True
    assert payload["blockers"] == []
