from src.mpr16_trusted_time_archive_gate import (
    ArchiveDurabilityEvidence,
    ArchiveLeaseEvidence,
    ManagementSnapshotEvidence,
    MPR16GateState,
    MPR16OperationalEvidence,
    ProcessGenerationEvidence,
    RemoteArchiveReceipt,
    TimeQualificationEvidence,
    evaluate_mpr16_operational_evidence,
)


def h(seed: str) -> str:
    return (seed * 64)[:64]


def complete_evidence(**overrides) -> MPR16OperationalEvidence:
    values = {
        "covered_findings": tuple(f"F-{number}" for number in range(350, 361)),
        "release_artifact_hash": h("a"),
        "time": TimeQualificationEvidence(
            source_id="chrony-host-timesync",
            source_status="SYNCHRONIZED",
            status_authenticated=True,
            host_timesync_attestation_hash=h("b"),
            policy_hash=h("c"),
            uncertainty_ns=5_000_000,
            max_uncertainty_ns=20_000_000,
            sample_count=5,
            min_required_samples=3,
            consecutive_consistent_samples=4,
            first_sample_sensitive_operations_blocked=True,
        ),
        "process_generation": ProcessGenerationEvidence(
            boot_id_hash=h("d"),
            process_incarnation_hash=h("e"),
            previous_generation=41,
            current_generation=42,
            durable_allocator_enabled=True,
            exclusive_startup_lease_acquired=True,
            cas_generation_allocated=True,
        ),
        "management_snapshot": ManagementSnapshotEvidence(
            release_id="release-2026-07-23-mpr16",
            policy_hash=h("8"),
            evidence_head_hash=h("1"),
            process_boot_id_hash=h("2"),
            runtime_generation=42,
            heartbeat_sequence=101,
            previous_accepted_sequence=100,
            snapshot_hash=h("3"),
            previous_accepted_snapshot_hash=h("4"),
            mac_verified=True,
            readiness_cross_bound_to_outer_identity=True,
            evaluated_at_ns=1_000_000,
            expires_at_ns=2_000_000,
            trusted_now_ns=1_500_000,
            durable_high_water_updated=True,
        ),
        "archive_lease": ArchiveLeaseEvidence(
            claim_id="claim-1",
            exporter_id="exporter-a",
            lease_generation=7,
            monotonic_deadline_ns=3_000_000,
            trusted_utc_expires_at_ns=4_000_000,
            renewable=True,
            cas_heartbeat_enabled=True,
            fence_validated_before_read=True,
            fence_validated_before_write=True,
            fence_validated_before_commit=True,
            stale_exporter_rejected_before_artifact_write=True,
        ),
        "archive_durability": ArchiveDurabilityEvidence(
            archive_policy_hash=h("5"),
            mandatory_archive_names=("worm-a", "worm-b"),
            remote_receipts=(
                RemoteArchiveReceipt("worm-a", "eu-west", "v1", h("6"), True, 9_000_000),
                RemoteArchiveReceipt("worm-b", "us-east", "v7", h("7"), True, 9_000_000),
            ),
            append_only_ack_events=True,
            mutable_ack_upsert_disabled=True,
            conflicting_second_ack_quarantined=True,
            terminal_ack_immutable=True,
            deterministic_remote_fsm=True,
            local_committed_state_separate_from_authoritative=True,
            promotion_requires_remote_quorum=True,
            manifest_authoritative_only_after_remote_quorum=True,
            latest_projection_replay_derived=True,
        ),
    }
    values.update(overrides)
    return MPR16OperationalEvidence(**values)


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_accepts_complete_sender_free_mpr16_evidence():
    report = evaluate_mpr16_operational_evidence(complete_evidence())

    assert report.state == MPR16GateState.READY_FOR_OPERATIONAL_CUTOVER_INTEGRATION
    assert report.blockers == ()
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False


def test_rejects_missing_v7_findings():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(covered_findings=("F-350", "F-351"))
    )

    assert report.state == MPR16GateState.BLOCKED
    assert "MPR16_FINDINGS_MISSING" in codes(report)


def test_rejects_unqualified_first_startup_time_sample():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            time=TimeQualificationEvidence(
                source_id="chrony-host-timesync",
                source_status="SYNCHRONIZED",
                status_authenticated=True,
                host_timesync_attestation_hash=h("b"),
                policy_hash=h("c"),
                uncertainty_ns=50_000_000,
                max_uncertainty_ns=20_000_000,
                sample_count=1,
                min_required_samples=3,
                consecutive_consistent_samples=1,
                first_sample_sensitive_operations_blocked=False,
            )
        )
    )

    assert "MPR16_TIME_UNCERTAINTY_TOO_HIGH" in codes(report)
    assert "MPR16_TIME_SAMPLE_COUNT_TOO_LOW" in codes(report)
    assert "MPR16_FIRST_SAMPLE_BYPASS" in codes(report)


def test_rejects_self_declared_time_status():
    base = complete_evidence().time
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            time=TimeQualificationEvidence(
                source_id=base.source_id,
                source_status=base.source_status,
                status_authenticated=False,
                host_timesync_attestation_hash=base.host_timesync_attestation_hash,
                policy_hash=base.policy_hash,
                uncertainty_ns=base.uncertainty_ns,
                max_uncertainty_ns=base.max_uncertainty_ns,
                sample_count=base.sample_count,
                min_required_samples=base.min_required_samples,
                consecutive_consistent_samples=base.consecutive_consistent_samples,
                first_sample_sensitive_operations_blocked=base.first_sample_sensitive_operations_blocked,
            )
        )
    )

    assert "MPR16_TIME_STATUS_UNAUTHENTICATED" in codes(report)


def test_rejects_non_incrementing_process_generation():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            process_generation=ProcessGenerationEvidence(
                boot_id_hash=h("d"),
                process_incarnation_hash=h("e"),
                previous_generation=42,
                current_generation=42,
                durable_allocator_enabled=False,
                exclusive_startup_lease_acquired=False,
                cas_generation_allocated=False,
            )
        )
    )

    assert "MPR16_PROCESS_GENERATION_NOT_INCREASING" in codes(report)
    assert "MPR16_NO_DURABLE_GENERATION_ALLOCATOR" in codes(report)
    assert "MPR16_NO_STARTUP_LEASE" in codes(report)
    assert "MPR16_NO_CAS_GENERATION" in codes(report)


def test_rejects_replayed_ready_management_snapshot():
    base = complete_evidence().management_snapshot
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            management_snapshot=ManagementSnapshotEvidence(
                release_id=base.release_id,
                policy_hash=base.policy_hash,
                evidence_head_hash=base.evidence_head_hash,
                process_boot_id_hash=base.process_boot_id_hash,
                runtime_generation=base.runtime_generation,
                heartbeat_sequence=100,
                previous_accepted_sequence=100,
                snapshot_hash=base.snapshot_hash,
                previous_accepted_snapshot_hash=base.previous_accepted_snapshot_hash,
                mac_verified=base.mac_verified,
                readiness_cross_bound_to_outer_identity=False,
                evaluated_at_ns=base.evaluated_at_ns,
                expires_at_ns=base.expires_at_ns,
                trusted_now_ns=base.trusted_now_ns,
                durable_high_water_updated=False,
            )
        )
    )

    assert "MPR16_SNAPSHOT_REPLAY" in codes(report)
    assert "MPR16_READINESS_NOT_CROSS_BOUND" in codes(report)
    assert "MPR16_HIGH_WATER_NOT_DURABLE" in codes(report)


def test_rejects_stale_or_future_dated_management_snapshot():
    base = complete_evidence().management_snapshot
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            management_snapshot=ManagementSnapshotEvidence(
                release_id=base.release_id,
                policy_hash=base.policy_hash,
                evidence_head_hash=base.evidence_head_hash,
                process_boot_id_hash=base.process_boot_id_hash,
                runtime_generation=base.runtime_generation,
                heartbeat_sequence=base.heartbeat_sequence,
                previous_accepted_sequence=base.previous_accepted_sequence,
                snapshot_hash=base.snapshot_hash,
                previous_accepted_snapshot_hash=base.previous_accepted_snapshot_hash,
                mac_verified=True,
                readiness_cross_bound_to_outer_identity=True,
                evaluated_at_ns=3_000_000,
                expires_at_ns=2_000_000,
                trusted_now_ns=2_000_000,
                durable_high_water_updated=True,
            )
        )
    )

    assert "MPR16_SNAPSHOT_STALE" in codes(report)
    assert "MPR16_SNAPSHOT_FROM_FUTURE" in codes(report)


def test_rejects_archive_lease_without_renewable_fencing():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            archive_lease=ArchiveLeaseEvidence(
                claim_id="claim-1",
                exporter_id="exporter-a",
                lease_generation=7,
                monotonic_deadline_ns=3_000_000,
                trusted_utc_expires_at_ns=4_000_000,
                renewable=False,
                cas_heartbeat_enabled=False,
                fence_validated_before_read=False,
                fence_validated_before_write=False,
                fence_validated_before_commit=False,
                stale_exporter_rejected_before_artifact_write=False,
            )
        )
    )

    assert "MPR16_ARCHIVE_LEASE_NOT_RENEWABLE" in codes(report)
    assert "MPR16_ARCHIVE_READ_WITHOUT_FENCE" in codes(report)
    assert "MPR16_ARCHIVE_WRITE_WITHOUT_FENCE" in codes(report)
    assert "MPR16_STALE_EXPORTER_CAN_WRITE" in codes(report)


def test_rejects_mutable_or_incomplete_archive_remote_ack():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            archive_durability=ArchiveDurabilityEvidence(
                archive_policy_hash=h("5"),
                mandatory_archive_names=("worm-a", "worm-b"),
                remote_receipts=(
                    RemoteArchiveReceipt("worm-a", "eu-west", "v1", h("6"), False, 9_000_000),
                ),
                append_only_ack_events=False,
                mutable_ack_upsert_disabled=False,
                conflicting_second_ack_quarantined=False,
                terminal_ack_immutable=False,
                deterministic_remote_fsm=False,
                local_committed_state_separate_from_authoritative=False,
                promotion_requires_remote_quorum=False,
                manifest_authoritative_only_after_remote_quorum=False,
                latest_projection_replay_derived=False,
            )
        )
    )

    assert "MPR16_REMOTE_QUORUM_INCOMPLETE" in codes(report)
    assert "MPR16_RECEIPT_NOT_WORM_LOCKED" in codes(report)
    assert "MPR16_REMOTE_ACK_NOT_APPEND_ONLY" in codes(report)
    assert "MPR16_MUTABLE_REMOTE_ACK" in codes(report)
    assert "MPR16_MANIFEST_AUTHORITATIVE_TOO_EARLY" in codes(report)


def test_rejects_runtime_enablement_requests():
    report = evaluate_mpr16_operational_evidence(
        complete_evidence(
            transaction_signer_requested=True,
            sender_requested=True,
            live_execution_requested=True,
        )
    )

    assert "MPR16_SIGNER_REQUESTED" in codes(report)
    assert "MPR16_SENDER_REQUESTED" in codes(report)
    assert "MPR16_LIVE_REQUESTED" in codes(report)
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
