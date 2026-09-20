from __future__ import annotations

import sqlite3

import pytest

from src.operations.agg09_ops02 import (
    DataScaleEvidence,
    OperatorAction,
    OperatorAuthorization,
    OperatorRole,
    PerformanceEvidence,
    TelemetryWindow,
    build_production_telemetry,
    evaluate_data_scale,
    evaluate_performance_patch,
    execute_operator_command,
)
from src.operations.mpr2613_guarded_operations import (
    AcceptedReleaseIdentity,
    MonetaryCaps,
    OperatingEnvelope,
    OperatingState,
    ResourceCaps,
    ScaleTier,
    StateTransitionDenied,
    initialize_scope,
    install_guarded_operations_schema,
    persist_envelope,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64
H8 = "8" * 64
HA = "a" * 64


def _release() -> AcceptedReleaseIdentity:
    return AcceptedReleaseIdentity(
        release_decision_hash=H1,
        tree_hash=H2,
        wheel_hash=H3,
        image_hash=H4,
        config_hash=H5,
        policy_hash=H6,
        schema_hash=H7,
        profile_hash=H8,
        accepted_at_utc="2026-09-20T00:00:00Z",
        expires_at_utc="2026-09-22T00:00:00Z",
        accepted=True,
    )


def _envelope() -> OperatingEnvelope:
    return OperatingEnvelope(
        release=_release(),
        cluster_genesis_hash=H1,
        wallet_identity_hash=H2,
        payer_identity_hash=H3,
        strategy="circular_arbitrage",
        lender="MarginFi",
        router="Jupiter",
        program_set_hash=H4,
        provider_set_hash=H5,
        credential_generation_hash=H6,
        signer_generation_hash=H7,
        submission_generation_hash=H8,
        monetary_caps=MonetaryCaps(
            principal_atoms=1_000,
            fee_atoms=100,
            tip_atoms=100,
            rent_atoms=100,
            realized_loss_atoms=100,
            unresolved_exposure_atoms=100,
            protected_reserve_atoms=100,
        ),
        resource_caps=ResourceCaps(
            max_attempts=1,
            max_concurrency=1,
            max_pending_reconciliations=1,
            max_db_backlog=16,
        ),
        tier=ScaleTier.CANARY,
        issued_at_utc="2026-09-20T00:00:01Z",
        expires_at_utc="2026-09-21T00:00:00Z",
        generation=1,
    )


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    install_guarded_operations_schema(db)
    envelope = _envelope()
    persist_envelope(db, envelope)
    initialize_scope(
        db,
        scope_key="core-v1",
        envelope_hash=envelope.envelope_hash,
        writer_generation=1,
        current_utc="2026-09-20T00:00:02Z",
    )
    return db


def test_nf247_liveness_does_not_promote_market_readiness() -> None:
    telemetry = build_production_telemetry(
        TelemetryWindow(
            campaign_id="agg09",
            latency_ns=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
            data_gap_count=0,
            dropped_work_count=0,
            quota_used=10,
            quota_limit=100,
            provider_error_count=0,
            stalled_state_count=0,
            unresolved_reconciliation_count=0,
            useful_episode_count=2,
            process_liveness_healthy=True,
            market_readiness_qualified=False,
            evidence_age_seconds=3,
        )
    )
    assert telemetry.p50_latency_ns == 50
    assert telemetry.p95_latency_ns == 100
    assert telemetry.p99_latency_ns == 100
    assert "AGG09_MARKET_READINESS_NOT_QUALIFIED" in telemetry.reason_codes


def test_nf248_read_only_cannot_mutate_and_risk_operator_can_pause_resume_shadow() -> None:
    db = _db()
    readonly = OperatorAuthorization("viewer", OperatorRole.READ_ONLY, HA)
    inspect = execute_operator_command(
        db,
        scope_key="core-v1",
        action=OperatorAction.INSPECT,
        authorization=readonly,
        writer_generation=1,
        current_utc="2026-09-20T00:00:03Z",
    )
    assert inspect.mutated is False
    assert inspect.to_state is OperatingState.DORMANT

    with pytest.raises(StateTransitionDenied, match="AGG09_OPERATOR_ROLE_DENIED"):
        execute_operator_command(
            db,
            scope_key="core-v1",
            action=OperatorAction.RESUME_SHADOW,
            authorization=readonly,
            writer_generation=1,
            current_utc="2026-09-20T00:00:04Z",
        )

    risk = OperatorAuthorization("risk", OperatorRole.RISK_OPERATOR, HA)
    resumed = execute_operator_command(
        db,
        scope_key="core-v1",
        action=OperatorAction.RESUME_SHADOW,
        authorization=risk,
        writer_generation=1,
        current_utc="2026-09-20T00:00:05Z",
    )
    assert resumed.to_state is OperatingState.SHADOW_ONLY
    assert resumed.live_enabled is False
    paused = execute_operator_command(
        db,
        scope_key="core-v1",
        action=OperatorAction.STOP,
        authorization=risk,
        writer_generation=1,
        current_utc="2026-09-20T00:00:06Z",
    )
    assert paused.to_state is OperatingState.LATCHED
    assert db.execute("SELECT COUNT(*) FROM mpr2613_state_events").fetchone()[0] == 3


def test_nf249_performance_patch_requires_same_exact_semantics_and_tail_uplift() -> None:
    accepted = evaluate_performance_patch(
        PerformanceEvidence(
            workload_hash=H1,
            baseline_semantics_hash=H2,
            candidate_semantics_hash=H2,
            baseline_p95_ns=200,
            candidate_p95_ns=150,
            baseline_p99_ns=500,
            candidate_p99_ns=400,
            baseline_cost_units=20,
            candidate_cost_units=20,
        )
    )
    assert accepted.accepted is True

    changed = evaluate_performance_patch(
        PerformanceEvidence(
            workload_hash=H1,
            baseline_semantics_hash=H2,
            candidate_semantics_hash=H3,
            baseline_p95_ns=200,
            candidate_p95_ns=100,
            baseline_p99_ns=500,
            candidate_p99_ns=300,
            baseline_cost_units=20,
            candidate_cost_units=10,
        )
    )
    assert changed.accepted is False
    assert "AGG09_PERFORMANCE_SEMANTICS_CHANGED" in changed.reason_codes


def test_nf250_scale_must_preserve_replay_and_authoritative_owners() -> None:
    same = evaluate_data_scale(
        DataScaleEvidence(
            before_replay_hash=H1,
            after_replay_hash=H1,
            identity_registry_hash_before=H2,
            identity_registry_hash_after=H2,
            cursor_semantics_hash_before=H3,
            cursor_semantics_hash_after=H3,
            quota_authority_hash_before=H4,
            quota_authority_hash_after=H4,
            economic_authority_hash_before=H5,
            economic_authority_hash_after=H5,
            within_budget=True,
            duplicate_episode_count=0,
        )
    )
    assert same.accepted is True
    assert same.authoritative_economic_owner_preserved is True

    drift = evaluate_data_scale(
        DataScaleEvidence(
            before_replay_hash=H1,
            after_replay_hash=H2,
            identity_registry_hash_before=H2,
            identity_registry_hash_after=H2,
            cursor_semantics_hash_before=H3,
            cursor_semantics_hash_after=H3,
            quota_authority_hash_before=H4,
            quota_authority_hash_after=H4,
            economic_authority_hash_before=H5,
            economic_authority_hash_after=H6,
            within_budget=False,
            duplicate_episode_count=1,
        )
    )
    assert drift.accepted is False
    assert "AGG09_SCALE_REPLAY_DRIFT" in drift.reason_codes
    assert "AGG09_SCALE_ECONOMIC_AUTHORITY_DRIFT" in drift.reason_codes
    assert "AGG09_SCALE_DUPLICATE_EPISODES" in drift.reason_codes
