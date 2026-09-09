from __future__ import annotations

import sqlite3

import pytest

from src.live_canary.mpr2609 import (
    CanaryAdmissionBundle,
    CanaryBudget,
    DurableCanaryAuthority,
    DurableCanaryMode,
    HumanPermit,
    MPR2609Error,
    PrerequisiteIdentity,
)


H = "a" * 64
H2 = "b" * 64
H3 = "c" * 64


def prerequisites() -> PrerequisiteIdentity:
    return PrerequisiteIdentity(
        runtime_2601=H,
        human_control_2603=H,
        frozen_release_2604=H,
        protocol_2605=H,
        vertical_2606=H,
        shadow_2607=H,
        signer_transport_2608=H,
        release_hash=H,
        config_hash=H,
        policy_hash=H,
        capability_hash=H,
        wallet_ref="wallet-ref",
        cluster="mainnet-beta",
        genesis_hash=H,
    )


def budget() -> CanaryBudget:
    return CanaryBudget(
        max_principal_base_units=1,
        max_wallet_spend_lamports=1,
        protected_wallet_reserve_lamports=1,
        max_base_fee_lamports=1,
        max_priority_fee_lamports=1,
        max_jito_tip_lamports=1,
        max_total_cost_lamports=1,
        max_attempt_loss_lamports=1,
        max_cumulative_loss_lamports=10,
        max_attempts=1,
        max_consecutive_failures=2,
        max_data_age_ms=1,
        max_rpc_slot_divergence=1,
        min_blockheight_margin=2,
    )


def permit(p: PrerequisiteIdentity, b: CanaryBudget) -> HumanPermit:
    return HumanPermit(
        permit_id="permit-1",
        principal_a="human-a",
        principal_b="human-b",
        prerequisite_digest=p.digest,
        budget_digest=b.digest,
        candidate_scope_hash=H3,
        issued_at_ms=100,
        expires_at_ms=1000,
    )


def bundle(generation: int, p: PrerequisiteIdentity, b: CanaryBudget) -> CanaryAdmissionBundle:
    return CanaryAdmissionBundle(
        attempt_id="attempt-1",
        attempt_generation=generation,
        prerequisite_digest=p.digest,
        budget_digest=b.digest,
        candidate_digest=H,
        route_digest=H2,
        message_digest=H3,
        simulation_digest=H,
        account_metas_digest=H2,
        blockhash="blockhash-1",
        last_valid_block_height=120,
        wallet_ref=p.wallet_ref,
        market="SOL/USDC",
        reservation_id="reservation-1",
        transport="mpr2608:jito",
        permit_id="permit-1",
        deadline_ms=900,
    )


def authority() -> tuple[sqlite3.Connection, DurableCanaryAuthority]:
    db = sqlite3.connect(":memory:")
    a = DurableCanaryAuthority(db)
    a.install_schema()
    return db, a


def test_default_is_shadow_and_not_armed() -> None:
    _, a = authority()
    assert a.status()["mode"] == DurableCanaryMode.SHADOW.value
    p, b = prerequisites(), budget()
    with pytest.raises(MPR2609Error, match="not armed"):
        a.admit_one_shot(
            bundle=bundle(1, p, b),
            now_ms=200,
            current_block_height=100,
            min_blockheight_margin=2,
        )


def test_dual_human_identity_is_mandatory() -> None:
    p, b = prerequisites(), budget()
    with pytest.raises(MPR2609Error, match="two distinct"):
        HumanPermit(
            permit_id="permit-x",
            principal_a="same-human",
            principal_b="same-human",
            prerequisite_digest=p.digest,
            budget_digest=b.digest,
            candidate_scope_hash=H,
            issued_at_ms=1,
            expires_at_ms=2,
        )


def test_one_arm_allows_exactly_one_admission() -> None:
    _, a = authority()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    digest = a.admit_one_shot(
        bundle=bundle(generation, p, b),
        now_ms=300,
        current_block_height=100,
        min_blockheight_margin=2,
    )
    assert len(digest) == 64
    assert a.status()["mode"] == DurableCanaryMode.SUBMISSION_OUTSTANDING.value
    with pytest.raises(MPR2609Error):
        a.admit_one_shot(
            bundle=bundle(generation, p, b),
            now_ms=301,
            current_block_height=100,
            min_blockheight_margin=2,
        )


def test_restart_preserves_consumed_and_outstanding_state(tmp_path) -> None:
    path = tmp_path / "canary.sqlite"
    db = sqlite3.connect(path)
    a = DurableCanaryAuthority(db)
    a.install_schema()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    a.admit_one_shot(
        bundle=bundle(generation, p, b),
        now_ms=300,
        current_block_height=100,
        min_blockheight_margin=2,
    )
    db.commit()
    db.close()

    reopened = sqlite3.connect(path)
    recovered = DurableCanaryAuthority(reopened)
    state = recovered.status()
    assert state["outstanding_attempt_id"] == "attempt-1"
    assert state["consumed_admission_digest"] is not None
    assert state["mode"] == DurableCanaryMode.SUBMISSION_OUTSTANDING.value


def test_unknown_outcome_is_sticky_and_blocks_rearm() -> None:
    _, a = authority()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    a.admit_one_shot(
        bundle=bundle(generation, p, b),
        now_ms=300,
        current_block_height=100,
        min_blockheight_margin=2,
    )
    a.mark_unknown(attempt_id="attempt-1")
    assert a.status()["mode"] == DurableCanaryMode.LATCHED.value
    with pytest.raises(MPR2609Error, match="blocks arming"):
        a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=400)


def test_terminal_success_returns_to_shadow_without_auto_rearm() -> None:
    _, a = authority()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    a.admit_one_shot(
        bundle=bundle(generation, p, b),
        now_ms=300,
        current_block_height=100,
        min_blockheight_margin=2,
    )
    a.finalize(
        attempt_id="attempt-1",
        realized_pnl_lamports=1,
        success=True,
        reconciliation_digest=H,
        max_cumulative_loss_lamports=10,
        max_consecutive_failures=2,
    )
    state = a.status()
    assert state["mode"] == DurableCanaryMode.SHADOW.value
    assert state["outstanding_attempt_id"] is None
    with pytest.raises(MPR2609Error, match="not armed"):
        a.admit_one_shot(
            bundle=bundle(generation, p, b),
            now_ms=400,
            current_block_height=100,
            min_blockheight_margin=2,
        )


def test_blockheight_margin_fails_closed_before_consumption() -> None:
    _, a = authority()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    with pytest.raises(MPR2609Error, match="blockheight safety"):
        a.admit_one_shot(
            bundle=bundle(generation, p, b),
            now_ms=300,
            current_block_height=119,
            min_blockheight_margin=2,
        )
    assert a.status()["consumed_admission_digest"] is None


def test_rollback_revokes_generation_but_preserves_outstanding() -> None:
    _, a = authority()
    p, b = prerequisites(), budget()
    generation = a.arm(prerequisites=p, budget=b, permit=permit(p, b), now_ms=200)
    a.admit_one_shot(
        bundle=bundle(generation, p, b),
        now_ms=300,
        current_block_height=100,
        min_blockheight_margin=2,
    )
    next_generation = a.rollback_to_shadow()
    state = a.status()
    assert next_generation == generation + 1
    assert state["outstanding_attempt_id"] == "attempt-1"
    assert state["mode"] == DurableCanaryMode.SHADOW.value
