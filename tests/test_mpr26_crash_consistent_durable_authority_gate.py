from __future__ import annotations

from dataclasses import replace

from src.mpr26_crash_consistent_durable_authority_gate import (
    AuthorityTopologyEvidence,
    CrashRaceEvidence,
    EventLogEvidence,
    IdentityDomainEvidence,
    MPR26Evidence,
    OutboxRecoveryEvidence,
    REQUIRED_FAULT_BOUNDARIES,
    REQUIRED_FINDINGS,
    REQUIRED_RACE_PROBES,
    REQUIRED_RESTORE_PROBES,
    StorageRecoveryEvidence,
    TransactionProtocolEvidence,
    blockers_by_code,
    evaluate_mpr26_evidence,
)


H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
H8 = "8" * 64
H9 = "9" * 64


def valid_evidence() -> MPR26Evidence:
    return MPR26Evidence(
        release_id="release/mpr26.2026-07-23",
        finding_coverage=REQUIRED_FINDINGS,
        topology=AuthorityTopologyEvidence(
            authority_generation="authority/mpr26.v1",
            schema_manifest_sha256=H1,
            transaction_api_sha256=H2,
            one_durable_authority_api=True,
            attempt_capital_lease_event_outbox_recovery_in_one_authority=True,
            independent_terminal_stores_disabled=True,
            projection_truth_derived_from_events_only=True,
            readiness_reads_replayed_authority_state=True,
        ),
        transaction_protocol=TransactionProtocolEvidence(
            explicit_begin_immediate_or_serial_writer=True,
            no_autocommit_multi_statement_paths=True,
            no_connection_context_manager_transaction_assumption=True,
            every_conditional_update_checks_rowcount=True,
            rereads_committed_row_before_external_effect=True,
            fault_injection_after_each_sql_statement=True,
        ),
        identity_domain=IdentityDomainEvidence(
            canonical_identity_codec_sha256=H3,
            length_prefixed_attempt_cycle_outbox_keys=True,
            rejects_nul_delimiter_collisions=True,
            rejects_bool_as_int=True,
            rejects_nan_and_float_money=True,
            rejects_malformed_pubkeys=True,
            collision_corpus_sha256=H4,
        ),
        event_log=EventLogEvidence(
            event_schema_sha256=H5,
            append_only_event_log_authoritative=True,
            payload_digest_recomputed_from_stored_payload=True,
            hash_chain_or_signed_checkpoints=True,
            materialized_rows_replay_equal_events=True,
            child_table_tamper_detected_before_readiness=True,
            projection_tamper_detected_before_readiness=True,
            startup_blocks_on_integrity_failure=True,
        ),
        outbox_recovery=OutboxRecoveryEvidence(
            outbox_fsm_sha256=H6,
            has_queued_claimed_delivered_dead_letter_states=True,
            renewable_claim_leases=True,
            fencing_token_required_on_every_claim_write=True,
            stale_owner_after_expiry_rejected=True,
            retry_history_backoff_and_poison_quarantine=True,
            unknown_has_durable_reconciliation_owner=True,
            no_orphaned_outbox_claim_after_restart=True,
        ),
        storage_recovery=StorageRecoveryEvidence(
            storage_policy_sha256=H7,
            parent_directories_0700=True,
            database_files_0600=True,
            no_symlink_traversal=True,
            ownership_and_inode_checked=True,
            wal_and_shm_included_in_backup_protocol=True,
            generation_backup_and_atomic_restore_pointer=True,
            previous_generation_preserved_on_restore_failure=True,
            restore_rehearses_required_failures=REQUIRED_RESTORE_PROBES,
        ),
        crash_race=CrashRaceEvidence(
            statement_crash_matrix_sha256=H8,
            two_process_race_report_sha256=H9,
            fault_boundaries_tested=REQUIRED_FAULT_BOUNDARIES,
            race_probes_tested=REQUIRED_RACE_PROBES,
            kill_at_every_write_boundary_proves_exactly_one_terminal=True,
            duplicate_opportunities_do_not_overreserve_capital=True,
            no_split_attempt_projection_or_outbox_truth=True,
            restart_releases_or_reconciles_leases_and_reservations=True,
        ),
    )


def codes(evidence: MPR26Evidence) -> set[str]:
    return set(blockers_by_code(evaluate_mpr26_evidence(evidence)))


def test_valid_evidence_is_ready_and_sender_free() -> None:
    report = evaluate_mpr26_evidence(valid_evidence())

    assert report.ready is True
    assert report.state.value == "ready-for-durable-cutover-review"
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.provider_network_allowed is False
    assert report.to_dict()["violation_count"] == 0


def test_missing_or_extra_finding_blocks_gate() -> None:
    evidence = replace(
        valid_evidence(),
        finding_coverage=REQUIRED_FINDINGS[:-1] + ("F-999",),
    )

    assert {"MPR26_MISSING_FINDING", "MPR26_UNKNOWN_FINDING"} <= codes(evidence)


def test_topology_must_be_one_authority_with_replayed_readiness() -> None:
    topology = replace(
        valid_evidence().topology,
        one_durable_authority_api=False,
        independent_terminal_stores_disabled=False,
        readiness_reads_replayed_authority_state=False,
    )
    evidence = replace(valid_evidence(), topology=topology)

    assert "MPR26_TOPOLOGY_INCOMPLETE" in codes(evidence)


def test_autocommit_and_missing_rowcount_are_blocked() -> None:
    protocol = replace(
        valid_evidence().transaction_protocol,
        no_autocommit_multi_statement_paths=False,
        every_conditional_update_checks_rowcount=False,
        fault_injection_after_each_sql_statement=False,
    )
    evidence = replace(valid_evidence(), transaction_protocol=protocol)

    assert "MPR26_TRANSACTION_PROTOCOL_INCOMPLETE" in codes(evidence)


def test_identity_must_reject_collision_bool_float_and_bad_pubkey_inputs() -> None:
    identity = replace(
        valid_evidence().identity_domain,
        rejects_nul_delimiter_collisions=False,
        rejects_bool_as_int=False,
        rejects_nan_and_float_money=False,
        rejects_malformed_pubkeys=False,
    )
    evidence = replace(valid_evidence(), identity_domain=identity)

    assert "MPR26_IDENTITY_DOMAIN_INCOMPLETE" in codes(evidence)


def test_event_log_must_replay_and_detect_child_projection_tampering() -> None:
    event_log = replace(
        valid_evidence().event_log,
        materialized_rows_replay_equal_events=False,
        child_table_tamper_detected_before_readiness=False,
        projection_tamper_detected_before_readiness=False,
    )
    evidence = replace(valid_evidence(), event_log=event_log)

    assert "MPR26_EVENT_LOG_INCOMPLETE" in codes(evidence)


def test_outbox_requires_fencing_stale_owner_rejection_and_poison_policy() -> None:
    outbox = replace(
        valid_evidence().outbox_recovery,
        fencing_token_required_on_every_claim_write=False,
        stale_owner_after_expiry_rejected=False,
        retry_history_backoff_and_poison_quarantine=False,
    )
    evidence = replace(valid_evidence(), outbox_recovery=outbox)

    assert "MPR26_OUTBOX_RECOVERY_INCOMPLETE" in codes(evidence)


def test_storage_requires_permissions_and_complete_restore_matrix() -> None:
    storage = replace(
        valid_evidence().storage_recovery,
        database_files_0600=False,
        restore_rehearses_required_failures=REQUIRED_RESTORE_PROBES[:-1],
    )
    evidence = replace(valid_evidence(), storage_recovery=storage)

    observed = codes(evidence)
    assert "MPR26_STORAGE_RECOVERY_INCOMPLETE" in observed
    assert "MPR26_RESTORE_MATRIX_INCOMPLETE" in observed


def test_crash_race_matrix_must_cover_boundaries_and_prevent_split_truth() -> None:
    crash_race = replace(
        valid_evidence().crash_race,
        fault_boundaries_tested=REQUIRED_FAULT_BOUNDARIES[:-1],
        race_probes_tested=REQUIRED_RACE_PROBES[:-1],
        kill_at_every_write_boundary_proves_exactly_one_terminal=False,
        no_split_attempt_projection_or_outbox_truth=False,
    )
    evidence = replace(valid_evidence(), crash_race=crash_race)

    observed = codes(evidence)
    assert "MPR26_FAULT_MATRIX_INCOMPLETE" in observed
    assert "MPR26_RACE_MATRIX_INCOMPLETE" in observed
    assert "MPR26_CRASH_RACE_INCOMPLETE" in observed


def test_placeholder_hash_and_forbidden_runtime_capabilities_fail_closed() -> None:
    topology = replace(valid_evidence().topology, schema_manifest_sha256="0" * 64)
    evidence = replace(
        valid_evidence(),
        topology=topology,
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
        provider_network_requested=True,
    )

    observed = codes(evidence)
    assert "MPR26_BAD_TOPOLOGY_HASH" in observed
    assert "MPR26_FORBIDDEN_RUNTIME_CAPABILITY" in observed
