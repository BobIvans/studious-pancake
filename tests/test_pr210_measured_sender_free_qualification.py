from __future__ import annotations

from src.pr210_measured_sender_free_qualification import (
    SCHEMA_VERSION,
    evaluate_pr210_sender_free_qualification,
    live_capability_allowed,
    sender_capability_allowed,
    signer_capability_allowed,
)

H = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


def valid_evidence() -> dict:
    start = 1_000_000_000_000
    checkpoint_step = 10 * 60 * 1000
    checkpoints = [
        {
            "checkpoint_id": f"cp-{index:03d}",
            "observed_at_unix_ms": start + index * checkpoint_step,
            "event_store_head_hash": H,
            "signed_by_observer": True,
        }
        for index in range(433)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "release_artifact_digest": H,
        "installed_entrypoint": "flashloan-bot.paper",
        "composition_root_id": "sender-free-root-v1",
        "artifacts": [
            {"artifact_id": "shadow_trace", "path": "artifacts/shadow-trace.jsonl", "sha256": H, "size_bytes": 100, "schema_id": "shadow.trace.v1", "producer": "installed-runtime", "materialized": True},
            {"artifact_id": "replay_bundle", "path": "artifacts/replay-bundle.tar", "sha256": H2, "size_bytes": 101, "schema_id": "replay.bundle.v1", "producer": "replay-tool", "materialized": True},
            {"artifact_id": "chaos_report", "path": "artifacts/chaos-report.json", "sha256": H3, "size_bytes": 102, "schema_id": "chaos.report.v1", "producer": "chaos-runner", "materialized": True},
            {"artifact_id": "event_store_export", "path": "artifacts/events.sqlite", "sha256": H, "size_bytes": 103, "schema_id": "event-store.v1", "producer": "durable-store", "materialized": True},
            {"artifact_id": "installed_artifact_manifest", "path": "artifacts/installed-manifest.json", "sha256": H2, "size_bytes": 104, "schema_id": "installed.manifest.v1", "producer": "release-qualification", "materialized": True},
        ],
        "trace_stages": [
            {"stage_id": stage, "event_id": f"trace-event-{index:02d}", "reached": True, "artifact_id": "shadow_trace", "occurred_at_unix_ms": start + 1_000 + index * 1000}
            for index, stage in enumerate([
                "installed_entrypoint_start", "provider_fixture_ingest", "durable_attempt_created", "capital_reservation", "protocol_bound_plan", "exact_compile_or_blocker", "exact_simulation_or_blocker", "economic_decision", "terminal_outcome", "restart_recovery", "deterministic_replay"
            ])
        ],
        "attempts": [
            {"attempt_id": "attempt-001", "terminal_state": "BLOCKED", "terminal_event_id": "terminal-event-001", "admitted": True, "cycle_id": "cycle-001"},
            {"attempt_id": "attempt-002", "terminal_state": "REJECTED", "terminal_event_id": "terminal-event-002", "admitted": True, "cycle_id": "cycle-002"},
        ],
        "derived_metrics": [
            {"metric_id": "cycles_completed", "value": 3, "source_event_ids": ["cycle-001", "cycle-002", "cycle-003"]},
            {"metric_id": "real_provider_cycles", "value": 2, "source_event_ids": ["cycle-001", "cycle-002"]},
            {"metric_id": "chaos_cycles", "value": 1, "source_event_ids": ["cycle-003"]},
            {"metric_id": "terminal_outcomes", "value": 2, "source_event_ids": ["terminal-event-001", "terminal-event-002"]},
            {"metric_id": "unknown_outcomes", "value": 0, "source_event_ids": []},
        ],
        "checkpoints": checkpoints,
        "runtime_health": {
            "management_listener_alive": True,
            "workload_ready": False,
            "dead_worker_detected": True,
            "stale_worker_detected": False,
            "backlog_pressure_seen": True,
            "readiness_failed_on_dead_or_stale": True,
        },
        "replay": {
            "restart_recovery_event_ids": ["restart-recovery-001"],
            "replay_input_hash": H,
            "replay_output_hash": H2,
            "deterministic_replay_hash": H3,
            "leaked_reservations": 0,
            "leaked_claims": 0,
            "unexplained_balance_deltas": 0,
        },
    }


def reason_codes(payload: dict, **kwargs) -> set[str]:
    return set(evaluate_pr210_sender_free_qualification(payload, **kwargs).reason_codes)


def test_valid_evidence_qualifies_and_keeps_capabilities_off() -> None:
    report = evaluate_pr210_sender_free_qualification(valid_evidence())
    assert report.qualified
    assert report.reason_codes == ()
    assert not report.live_capability_allowed
    assert not report.signer_capability_allowed
    assert not report.sender_capability_allowed
    assert not live_capability_allowed()
    assert not signer_capability_allowed()
    assert not sender_capability_allowed()


def test_rejects_contradictory_provider_cycles() -> None:
    payload = valid_evidence()
    payload["derived_metrics"][1]["value"] = 999
    payload["derived_metrics"][1]["source_event_ids"] = [f"provider-{i}" for i in range(999)]
    assert "PROVIDER_CYCLES_EXCEED_TOTAL" in reason_codes(payload)


def test_rejects_chaos_cycles_exceeding_total() -> None:
    payload = valid_evidence()
    payload["derived_metrics"][2]["value"] = 4
    payload["derived_metrics"][2]["source_event_ids"] = [f"chaos-{i}" for i in range(4)]
    assert "CHAOS_CYCLES_EXCEED_TOTAL" in reason_codes(payload)


def test_rejects_metric_count_that_is_not_derived_from_unique_events() -> None:
    payload = valid_evidence()
    payload["derived_metrics"][0]["source_event_ids"] = ["cycle-001", "cycle-001"]
    assert "DERIVED_METRIC_VALUE_MISMATCH" in reason_codes(payload)


def test_rejects_unknown_terminal_outcome() -> None:
    payload = valid_evidence()
    payload["attempts"][0]["terminal_state"] = "UNKNOWN"
    payload["derived_metrics"][4]["value"] = 1
    payload["derived_metrics"][4]["source_event_ids"] = ["unknown-001"]
    codes = reason_codes(payload)
    assert "NON_TERMINAL_OR_UNKNOWN_OUTCOME" in codes
    assert "UNKNOWN_OUTCOMES_PRESENT" in codes


def test_rejects_self_reported_short_soak() -> None:
    payload = valid_evidence()
    payload["checkpoints"] = payload["checkpoints"][:3]
    assert "SOAK_DURATION_TOO_SHORT" in reason_codes(payload)


def test_rejects_checkpoint_gap_and_unsigned_observer() -> None:
    payload = valid_evidence()
    payload["checkpoints"][10]["observed_at_unix_ms"] += 30 * 60 * 1000
    payload["checkpoints"][11]["observed_at_unix_ms"] += 30 * 60 * 1000
    payload["checkpoints"][12]["observed_at_unix_ms"] += 30 * 60 * 1000
    payload["checkpoints"][13]["signed_by_observer"] = False
    codes = reason_codes(payload)
    assert "CHECKPOINT_GAP_TOO_LARGE" in codes
    assert "UNSIGNED_CHECKPOINT" in codes


def test_rejects_non_materialized_or_placeholder_artifacts() -> None:
    payload = valid_evidence()
    payload["artifacts"][0]["materialized"] = False
    payload["artifacts"][1]["sha256"] = "0" * 64
    codes = reason_codes(payload)
    assert "ARTIFACT_NOT_MATERIALIZED" in codes
    assert "PLACEHOLDER_ARTIFACT_HASH" in codes


def test_rejects_missing_installed_trace_stage() -> None:
    payload = valid_evidence()
    payload["trace_stages"] = payload["trace_stages"][:-1]
    assert "INSTALLED_TRACE_STAGE_MISSING" in reason_codes(payload)


def test_rejects_workload_ready_when_worker_dead() -> None:
    payload = valid_evidence()
    payload["runtime_health"]["workload_ready"] = True
    assert "WORKLOAD_READY_WITH_DEAD_OR_STALE_WORKER" in reason_codes(payload)


def test_rejects_leaked_replay_state() -> None:
    payload = valid_evidence()
    payload["replay"]["leaked_reservations"] = 1
    payload["replay"]["leaked_claims"] = 1
    payload["replay"]["unexplained_balance_deltas"] = 1
    codes = reason_codes(payload)
    assert "LEAKED_RESERVATIONS" in codes
    assert "LEAKED_CLAIMS" in codes
    assert "UNEXPLAINED_BALANCE_DELTAS" in codes


def test_rejects_live_or_signer_capability_flags() -> None:
    codes = reason_codes(valid_evidence(), live_capability=True, signer_capability=True, sender_capability=True)
    assert "LIVE_OR_SIGNER_CAPABILITY_ENABLED" in codes
