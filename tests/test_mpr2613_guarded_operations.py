from __future__ import annotations

import hashlib
import sqlite3

import pytest

from src.operations.mpr2613_guarded_operations import (
    AcceptedReleaseIdentity,
    AdmissionDenied,
    CurrentAdmissionFacts,
    IntegrationBlocked,
    MonetaryCaps,
    OperatingEnvelope,
    OperatingState,
    ResourceCaps,
    SLOBudget,
    ScaleTier,
    StateTransitionDenied,
    evaluate_current_admission,
    initialize_scope,
    install_guarded_operations_schema,
    persist_envelope,
    recommended_downshift,
    record_slo_budget,
    transition_state,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    install_guarded_operations_schema(db)
    return db


def _release(*, accepted: bool = True) -> AcceptedReleaseIdentity:
    return AcceptedReleaseIdentity(
        release_decision_hash=_h("release-decision"),
        tree_hash=_h("tree"),
        wheel_hash=_h("wheel"),
        image_hash=_h("image"),
        config_hash=_h("config"),
        policy_hash=_h("policy"),
        schema_hash=_h("schema"),
        profile_hash=_h("profile"),
        accepted_at_utc="2026-09-09T15:00:00Z",
        expires_at_utc="2026-09-10T15:00:00Z",
        accepted=accepted,
    )


def _envelope(*, accepted: bool = True, tier: ScaleTier = ScaleTier.CANARY) -> OperatingEnvelope:
    return OperatingEnvelope(
        release=_release(accepted=accepted),
        cluster_genesis_hash=_h("genesis"),
        wallet_identity_hash=_h("wallet"),
        payer_identity_hash=_h("payer"),
        strategy="circular_arbitrage",
        lender="MarginFi",
        router="Jupiter",
        program_set_hash=_h("programs"),
        provider_set_hash=_h("providers"),
        credential_generation_hash=_h("credentials"),
        signer_generation_hash=_h("signer"),
        submission_generation_hash=_h("submission"),
        monetary_caps=MonetaryCaps(
            principal_atoms=1_000,
            fee_atoms=100,
            tip_atoms=50,
            rent_atoms=50,
            realized_loss_atoms=200,
            unresolved_exposure_atoms=500,
            protected_reserve_atoms=2_000,
        ),
        resource_caps=ResourceCaps(
            max_attempts=10,
            max_concurrency=2,
            max_pending_reconciliations=4,
            max_db_backlog=100,
        ),
        tier=tier,
        issued_at_utc="2026-09-09T15:01:00Z",
        expires_at_utc="2026-09-10T14:00:00Z",
        generation=1,
    )


def _facts(env: OperatingEnvelope) -> CurrentAdmissionFacts:
    return CurrentAdmissionFacts(
        release_decision_hash=env.release.release_decision_hash,
        config_hash=env.release.config_hash,
        policy_hash=env.release.policy_hash,
        profile_hash=env.release.profile_hash,
        cluster_genesis_hash=env.cluster_genesis_hash,
        wallet_identity_hash=env.wallet_identity_hash,
        provider_set_hash=env.provider_set_hash,
        signer_generation_hash=env.signer_generation_hash,
        submission_generation_hash=env.submission_generation_hash,
        rooted_data_fresh=True,
        protocol_evidence_valid=True,
        exact_candidate_valid=True,
        firewall_allowed=True,
        final_simulation_valid=True,
        conservative_economics_valid=True,
        unresolved_attempts=0,
        current_finalized_balance_atoms=10_000,
        committed_capital_atoms=1_000,
        realized_loss_atoms=0,
        fee_spend_atoms=0,
        tip_spend_atoms=0,
        rent_spend_atoms=0,
        unresolved_exposure_atoms=0,
        open_hard_latches=0,
    )


def _initialized_active() -> tuple[sqlite3.Connection, OperatingEnvelope]:
    db = _db()
    env = _envelope()
    persist_envelope(db, env)
    initialize_scope(
        db,
        scope_key="wallet:v1",
        envelope_hash=env.envelope_hash,
        writer_generation=7,
        current_utc="2026-09-09T15:02:00Z",
    )
    transition_state(
        db,
        scope_key="wallet:v1",
        target_state=OperatingState.ACTIVE,
        reason="accepted-human-release-control",
        writer_generation=7,
        current_utc="2026-09-09T15:03:00Z",
        automated=False,
        upward_authorization_hash=_h("human-control-permit"),
    )
    return db, env


def test_unaccepted_2612_release_cannot_materialize_envelope() -> None:
    db = _db()
    with pytest.raises(IntegrationBlocked, match="ACCEPTED_MPR2612_REQUIRED"):
        persist_envelope(db, _envelope(accepted=False))
    assert db.execute("SELECT COUNT(*) FROM mpr2613_operating_envelopes").fetchone() == (0,)


def test_new_scope_is_dormant_and_automation_cannot_promote() -> None:
    db = _db()
    env = _envelope()
    persist_envelope(db, env)
    initialize_scope(
        db,
        scope_key="wallet:v1",
        envelope_hash=env.envelope_hash,
        writer_generation=1,
        current_utc="2026-09-09T15:02:00Z",
    )
    with pytest.raises(StateTransitionDenied, match="AUTOMATIC_AUTHORITY_INCREASE_FORBIDDEN"):
        transition_state(
            db,
            scope_key="wallet:v1",
            target_state=OperatingState.ACTIVE,
            reason="self-promote",
            writer_generation=1,
            current_utc="2026-09-09T15:03:00Z",
            automated=True,
        )
    assert db.execute(
        "SELECT state FROM mpr2613_operating_state WHERE scope_key='wallet:v1'"
    ).fetchone() == (int(OperatingState.DORMANT),)


def test_human_authorized_upward_then_automatic_downshift_only() -> None:
    db, _env = _initialized_active()
    state = transition_state(
        db,
        scope_key="wallet:v1",
        target_state=OperatingState.DEGRADED,
        reason="provider-slo-breach",
        writer_generation=7,
        current_utc="2026-09-09T15:04:00Z",
        automated=True,
    )
    assert state is OperatingState.DEGRADED
    with pytest.raises(StateTransitionDenied, match="AUTOMATIC_AUTHORITY_INCREASE_FORBIDDEN"):
        transition_state(
            db,
            scope_key="wallet:v1",
            target_state=OperatingState.ACTIVE,
            reason="slo-recovered",
            writer_generation=7,
            current_utc="2026-09-09T15:05:00Z",
            automated=True,
        )


def test_stale_writer_generation_cannot_transition_or_admit() -> None:
    db, env = _initialized_active()
    with pytest.raises(StateTransitionDenied, match="STALE_WRITER_GENERATION"):
        transition_state(
            db,
            scope_key="wallet:v1",
            target_state=OperatingState.DEGRADED,
            reason="old-worker",
            writer_generation=6,
            current_utc="2026-09-09T15:04:00Z",
            automated=True,
        )
    with pytest.raises(AdmissionDenied, match="STALE_WRITER_GENERATION"):
        evaluate_current_admission(
            db,
            scope_key="wallet:v1",
            envelope=env,
            facts=_facts(env),
            current_utc="2026-09-09T15:04:00Z",
            writer_generation=6,
        )


def test_current_admission_rechecks_identity_and_release_drift() -> None:
    db, env = _initialized_active()
    ok = evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=_facts(env),
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    )
    assert ok.allowed is True
    assert ok.max_additional_principal_atoms == 1_000

    facts = _facts(env)
    drift = CurrentAdmissionFacts(**{**facts.__dict__, "config_hash": _h("config-rotated")})
    denied = evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=drift,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    )
    assert denied.allowed is False
    assert denied.reason == "identity-drift:config_hash"


def test_realized_loss_and_reserve_use_current_finalized_facts() -> None:
    db, env = _initialized_active()
    facts = _facts(env)
    loss = CurrentAdmissionFacts(**{**facts.__dict__, "realized_loss_atoms": 201})
    assert evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=loss,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    ).reason == "realized-loss-cap"

    reserve = CurrentAdmissionFacts(**{**facts.__dict__, "current_finalized_balance_atoms": 1_999})
    assert evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=reserve,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    ).reason == "protected-reserve-breached"


def test_automatic_sizing_can_only_shrink_inside_envelope() -> None:
    db, env = _initialized_active()
    facts = _facts(env)
    constrained = CurrentAdmissionFacts(
        **{
            **facts.__dict__,
            "current_finalized_balance_atoms": 2_500,
            "committed_capital_atoms": 100,
        }
    )
    decision = evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=constrained,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    )
    assert decision.allowed is True
    assert decision.max_additional_principal_atoms == 400
    assert decision.max_additional_principal_atoms <= env.monetary_caps.principal_atoms


def test_hard_latch_and_final_simulation_block_immediately() -> None:
    db, env = _initialized_active()
    facts = _facts(env)
    latched = CurrentAdmissionFacts(**{**facts.__dict__, "open_hard_latches": 1})
    assert evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=latched,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    ).reason == "hard-latch-open"
    simulation = CurrentAdmissionFacts(**{**facts.__dict__, "final_simulation_valid": False})
    assert evaluate_current_admission(
        db,
        scope_key="wallet:v1",
        envelope=env,
        facts=simulation,
        current_utc="2026-09-09T15:04:00Z",
        writer_generation=7,
    ).reason == "final-simulation-invalid"


def test_slo_budget_is_monotone_and_only_recommends_downshift() -> None:
    db = _db()
    env = _envelope()
    persist_envelope(db, env)
    budget = SLOBudget(
        metric="provider_latency",
        window="2026-09-09T15",
        denominator="attempts",
        min_samples=10,
        threshold=3,
        consumed=4,
    )
    record_slo_budget(db, envelope_hash=env.envelope_hash, budget=budget)
    assert recommended_downshift(budget) is OperatingState.DEGRADED
    record_slo_budget(
        db,
        envelope_hash=env.envelope_hash,
        budget=SLOBudget(
            metric="provider_latency",
            window="2026-09-09T15",
            denominator="attempts",
            min_samples=10,
            threshold=3,
            consumed=1,
        ),
    )
    assert db.execute(
        "SELECT consumed FROM mpr2613_slo_budgets WHERE metric='provider_latency'"
    ).fetchone() == (4,)
    hard = SLOBudget(
        metric="ledger_discrepancy",
        window="2026-09-09T15",
        denominator="checks",
        min_samples=1,
        threshold=0,
        consumed=1,
        hard_failure=True,
    )
    assert recommended_downshift(hard) is OperatingState.LATCHED
