from __future__ import annotations

import json

from src.mpr29_continuous_installed_paper_shadow_gate import (
    InstalledArtifactEvidence,
    LifecycleEvidence,
    MPR29Evidence,
    MPR29State,
    ReadinessEvidence,
    RuntimeModeEvidence,
    ShutdownChaosEvidence,
    SoakEvidence,
    blockers_by_code,
    evaluate_mpr29_evidence,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64


def runtime_modes(**overrides: object) -> RuntimeModeEvidence:
    values = {
        "mode_contract_sha256": H1,
        "runtime_graph_sha256": H2,
        "safe_idle_mode_present": True,
        "paper_mode_present": True,
        "shadow_mode_present": True,
        "live_gate_mode_present": True,
        "same_runtime_graph_for_all_modes": True,
        "safe_idle_never_satisfies_paper_ready": True,
        "safe_idle_never_satisfies_shadow_ready": True,
        "live_gate_default_off": True,
    }
    values.update(overrides)
    return RuntimeModeEvidence(**values)


def lifecycle(**overrides: object) -> LifecycleEvidence:
    values = {
        "lifecycle_trace_sha256": H1,
        "candidate_event_hash_sha256": H2,
        "exactly_one_terminal_state_per_candidate": True,
        "expiry_releases_lifecycle_and_reservation": True,
        "rejection_releases_lifecycle_and_reservation": True,
        "cancellation_releases_lifecycle_and_reservation": True,
        "deterministic_capture_replay": True,
        "no_process_local_terminal_truth": True,
        "no_unbounded_rejection_aggregation": True,
        "no_heap_mutation_outside_async_lock": True,
    }
    values.update(overrides)
    return LifecycleEvidence(**values)


def readiness(**overrides: object) -> ReadinessEvidence:
    values = {
        "readiness_contract_sha256": H1,
        "worker_generation_sha256": H2,
        "latest_terminal_cycle_sha256": H3,
        "provider_freshness_sha256": H4,
        "replay_state_sha256": H5,
        "ready_requires_real_workload": True,
        "unready_when_safe_idle": True,
        "unready_when_dead_worker": True,
        "unready_when_stale_provider_root": True,
        "unready_when_blocked_outbox": True,
        "unready_when_exact_simulator_missing": True,
        "management_liveness_alone_never_green": True,
    }
    values.update(overrides)
    return ReadinessEvidence(**values)


def chaos(**overrides: object) -> ShutdownChaosEvidence:
    values = {
        "chaos_matrix_sha256": H1,
        "bounded_shutdown_seconds": 30,
        "sigkill_boundaries_tested": True,
        "full_disk_tested": True,
        "locked_db_tested": True,
        "provider_timeout_tested": True,
        "malformed_payload_tested": True,
        "shutdown_during_handler_tested": True,
        "no_orphan_tasks_sockets_or_writes": True,
        "structured_concurrency_enforced": True,
    }
    values.update(overrides)
    return ShutdownChaosEvidence(**values)


def soak(**overrides: object) -> SoakEvidence:
    values = {
        "soak_report_sha256": H1,
        "replay_hash_sha256": H2,
        "pre_soak_hours": 24,
        "soak_hours": 72,
        "provider_faults_tested": True,
        "db_contention_tested": True,
        "backlog_pressure_tested": True,
        "clock_and_slot_drift_tested": True,
        "replay_hash_stable_across_restart": True,
        "identical_replay_hash_across_clean_hosts": True,
    }
    values.update(overrides)
    return SoakEvidence(**values)


def artifact(**overrides: object) -> InstalledArtifactEvidence:
    values = {
        "wheel_sha256": H1,
        "image_sha256": H2,
        "install_trace_sha256": H3,
        "digest_pinned_runtime_image": True,
        "runs_only_from_installed_artifact": True,
        "source_checkout_imports_blocked": True,
        "hidden_dependency_injection_blocked": True,
        "sender_namespace_absent": True,
        "signer_namespace_absent": True,
        "live_submission_namespace_absent": True,
    }
    values.update(overrides)
    return InstalledArtifactEvidence(**values)


def evidence(**overrides: object) -> MPR29Evidence:
    values = {
        "upstream_gates": {"mpr25": True, "mpr26": True, "mpr27": True, "mpr28": True},
        "runtime_modes": runtime_modes(),
        "lifecycle": lifecycle(),
        "readiness": readiness(),
        "shutdown_chaos": chaos(),
        "soak": soak(),
        "artifact": artifact(),
    }
    values.update(overrides)
    return MPR29Evidence(**values)


def codes(report) -> set[str]:
    return set(blockers_by_code(report))


def test_complete_evidence_unblocks_mpr30_but_never_live() -> None:
    report = evaluate_mpr29_evidence(evidence())
    assert report.state is MPR29State.READY_FOR_MPR30
    assert report.blockers == ()
    assert report.mpr30_unblocked is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False


def test_missing_or_false_upstream_gate_blocks() -> None:
    report = evaluate_mpr29_evidence(evidence(upstream_gates={"mpr25": True, "mpr26": False, "mpr27": True}))
    assert "MPR29_MISSING_UPSTREAM_GATE" in codes(report)
    assert "MPR29_UPSTREAM_NOT_READY" in codes(report)


def test_safe_idle_or_live_gate_profile_drift_blocks() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            runtime_modes=runtime_modes(
                same_runtime_graph_for_all_modes=False,
                safe_idle_never_satisfies_paper_ready=False,
                live_gate_default_off=False,
            )
        )
    )
    assert "MPR29_RUNTIME_MODE_INCOMPLETE" in codes(report)


def test_lifecycle_truth_requires_release_on_expiry_reject_cancel() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            lifecycle=lifecycle(
                exactly_one_terminal_state_per_candidate=False,
                expiry_releases_lifecycle_and_reservation=False,
                no_heap_mutation_outside_async_lock=False,
            )
        )
    )
    assert "MPR29_LIFECYCLE_INCOMPLETE" in codes(report)


def test_readiness_must_fail_when_workload_dependencies_missing() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            readiness=readiness(
                ready_requires_real_workload=False,
                unready_when_dead_worker=False,
                unready_when_stale_provider_root=False,
                management_liveness_alone_never_green=False,
            )
        )
    )
    assert "MPR29_READINESS_INCOMPLETE" in codes(report)


def test_shutdown_bound_and_chaos_matrix_are_required() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            shutdown_chaos=chaos(
                bounded_shutdown_seconds=0,
                provider_timeout_tested=False,
                no_orphan_tasks_sockets_or_writes=False,
            )
        )
    )
    assert "MPR29_BAD_SHUTDOWN_BOUND" in codes(report)
    assert "MPR29_CHAOS_INCOMPLETE" in codes(report)


def test_pre_soak_and_soak_duration_thresholds_are_enforced() -> None:
    report = evaluate_mpr29_evidence(
        evidence(soak=soak(pre_soak_hours=12, soak_hours=48))
    )
    assert "MPR29_PRE_SOAK_TOO_SHORT" in codes(report)
    assert "MPR29_SOAK_TOO_SHORT" in codes(report)


def test_soak_requires_restart_and_cross_host_replay_stability() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            soak=soak(
                replay_hash_stable_across_restart=False,
                identical_replay_hash_across_clean_hosts=False,
            )
        )
    )
    assert "MPR29_SOAK_INCOMPLETE" in codes(report)


def test_installed_artifact_boundary_blocks_source_imports_and_live_namespaces() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            artifact=artifact(
                runs_only_from_installed_artifact=False,
                source_checkout_imports_blocked=False,
                sender_namespace_absent=False,
                signer_namespace_absent=False,
                live_submission_namespace_absent=False,
            )
        )
    )
    assert "MPR29_ARTIFACT_BOUNDARY_INCOMPLETE" in codes(report)


def test_invalid_hashes_block_every_section() -> None:
    report = evaluate_mpr29_evidence(
        evidence(
            runtime_modes=runtime_modes(mode_contract_sha256="bad"),
            lifecycle=lifecycle(lifecycle_trace_sha256="bad"),
            readiness=readiness(readiness_contract_sha256="bad"),
            shutdown_chaos=chaos(chaos_matrix_sha256="bad"),
            soak=soak(soak_report_sha256="bad"),
            artifact=artifact(wheel_sha256="bad"),
        )
    )
    assert "MPR29_BAD_RUNTIME_HASH" in codes(report)
    assert "MPR29_BAD_LIFECYCLE_HASH" in codes(report)
    assert "MPR29_BAD_READINESS_HASH" in codes(report)
    assert "MPR29_BAD_CHAOS_HASH" in codes(report)
    assert "MPR29_BAD_SOAK_HASH" in codes(report)
    assert "MPR29_BAD_ARTIFACT_HASH" in codes(report)


def test_unknown_upstream_gate_is_rejected() -> None:
    report = evaluate_mpr29_evidence(
        evidence(upstream_gates={"mpr25": True, "mpr26": True, "mpr27": True, "mpr28": True, "mpr99": True})
    )
    assert "MPR29_UNKNOWN_UPSTREAM_GATE" in codes(report)


def test_report_json_is_stable_and_sorted() -> None:
    first = evaluate_mpr29_evidence(evidence()).to_json()
    second = evaluate_mpr29_evidence(evidence()).to_json()
    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == "mpr29.continuous-installed-paper-shadow-workload-gate.v1"
