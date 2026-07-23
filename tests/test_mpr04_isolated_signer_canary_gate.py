from __future__ import annotations

from dataclasses import replace

from src.mpr04_isolated_signer_canary_gate import (
    MPR04Approval,
    MPR04Evidence,
    MPR04State,
    REQUIRED_DEBT_IDS,
    evaluate_mpr04_evidence,
)


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64


def _approval(principal_id: str, approval_hash: str) -> MPR04Approval:
    return MPR04Approval(
        principal_id=principal_id,
        approval_hash=approval_hash,
        issued_at_ns=100,
        expires_at_ns=1_000,
        fresh=True,
        independent=True,
    )


def _evidence() -> MPR04Evidence:
    return MPR04Evidence(
        release_manifest_hash=HEX_A,
        signer_policy_hash=HEX_B,
        authorization_policy_hash=HEX_C,
        jito_contract_hash=HEX_D,
        canary_policy_hash=HEX_E,
        debt_ids_covered=REQUIRED_DEBT_IDS,
        runtime_private_key_access=False,
        isolated_signer_process_required=True,
        exact_message_hash_bound=True,
        policy_hash_bound=True,
        config_generation_bound=True,
        reservation_id_bound=True,
        wallet_reference_bound=True,
        market_provider_bound=True,
        nonce_bound=True,
        expiry_enforced=True,
        durable_submission_intent_written_before_transport=True,
        replay_denied=True,
        stale_config_denied=True,
        stale_shadow_evidence_denied=True,
        stale_human_approval_denied=True,
        ack_not_settlement=True,
        bundle_id_not_settlement=True,
        finalized_settlement_required=True,
        tip_budget_enforced=True,
        rate_limit_enforced=True,
        unbundling_protection_present=True,
        transaction_local_safety_assertions_present=True,
        production_cutover_manifest_fresh=True,
        mpr01_evidence_present=True,
        mpr02_evidence_present=True,
        mpr03_evidence_present=True,
        no_unknown_outstanding_attempts=True,
        capital_budget_cap_enforced=True,
        max_attempt_day_cap_enforced=True,
        max_loss_cap_enforced=True,
        emergency_stop_clear_required=True,
        exact_message_proof_required=True,
        final_human_approval_bound_to_message_hash=True,
        dual_approvals=(
            _approval("alice", HEX_A),
            _approval("bob", HEX_B),
        ),
        unrestricted_live_available=False,
        live_canary_available_by_default=False,
    )


def test_mpr04_happy_path_is_ready_but_live_stays_denied() -> None:
    report = evaluate_mpr04_evidence(_evidence())

    assert report.schema_version == "mpr04.isolated-signer-jito-canary-boundary.v1"
    assert report.state is MPR04State.READY_FOR_MPR04_FOUNDATION
    assert report.blockers == ()
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.live_canary_allowed is False
    assert len(report.evidence_hash) == 64


def test_mpr04_missing_debt_ids_block_foundation() -> None:
    report = evaluate_mpr04_evidence(replace(_evidence(), debt_ids_covered=("runtime.live-entrypoint",)))

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_DEBT_IDS_INCOMPLETE" for item in report.blockers)


def test_mpr04_runtime_must_not_access_private_key() -> None:
    report = evaluate_mpr04_evidence(replace(_evidence(), runtime_private_key_access=True))

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_PRIVATE_KEY_EXPOSED" for item in report.blockers)


def test_mpr04_signer_authorization_binding_must_be_complete() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            exact_message_hash_bound=False,
            policy_hash_bound=False,
            nonce_bound=False,
        )
    )

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_SIGNER_AUTHORIZATION_INCOMPLETE" for item in report.blockers)


def test_mpr04_replay_and_submission_intent_must_be_durable() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            durable_submission_intent_written_before_transport=False,
            replay_denied=False,
            stale_human_approval_denied=False,
        )
    )

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_REPLAY_PROTECTION_INCOMPLETE" for item in report.blockers)


def test_mpr04_jito_ack_and_bundle_id_cannot_settle_attempt() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            ack_not_settlement=False,
            bundle_id_not_settlement=False,
            finalized_settlement_required=False,
        )
    )

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_JITO_SEMANTICS_INCOMPLETE" for item in report.blockers)


def test_mpr04_canary_requires_all_latches_and_real_prerequisites() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            production_cutover_manifest_fresh=False,
            mpr03_evidence_present=False,
            capital_budget_cap_enforced=False,
            final_human_approval_bound_to_message_hash=False,
        )
    )

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_CANARY_LATCHES_INCOMPLETE" for item in report.blockers)


def test_mpr04_dual_approval_requires_two_distinct_fresh_principals() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            dual_approvals=(
                _approval("alice", HEX_A),
                _approval("alice", HEX_B),
            ),
        )
    )

    assert report.state is MPR04State.BLOCKED
    assert any(item.code == "MPR04_DUAL_APPROVAL_NOT_DISTINCT" for item in report.blockers)


def test_mpr04_unrestricted_live_or_default_canary_are_forbidden() -> None:
    report = evaluate_mpr04_evidence(
        replace(
            _evidence(),
            unrestricted_live_available=True,
            live_canary_available_by_default=True,
        )
    )

    codes = {item.code for item in report.blockers}
    assert report.state is MPR04State.BLOCKED
    assert "MPR04_UNRESTRICTED_LIVE_FORBIDDEN" in codes
    assert "MPR04_CANARY_DEFAULT_FORBIDDEN" in codes
