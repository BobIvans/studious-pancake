from dataclasses import replace

from src.mpr14_durable_canary_operator_control import (
    DECISION_FLAGS,
    DURABLE_FLAGS,
    LATCH_FLAGS,
    RECONCILIATION_FLAGS,
    REQUIRED_FINDINGS,
    RISK_FLAGS,
    MPR14ControlEvidence,
    MPR14GateState,
    MPR14OperatorCommand,
    evaluate_mpr14_control_evidence,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
HASH_4 = "4" * 64


def all_true(names):
    return {name: True for name in names}


def valid_operator(principal, role, command_hash, signature_hash):
    return MPR14OperatorCommand(
        principal_id=principal,
        role=role,
        command_hash=command_hash,
        signature_scheme="ed25519",
        signature_hash=signature_hash,
        registry_entry_hash=HASH_2,
        session_fresh_until_ns=2_000,
        command_observed_at_ns=1_000,
        command_generation=7,
        mfa_bound=True,
        canonical_command_bound=True,
        replay_nonce_consumed=True,
    )


def valid_evidence():
    return MPR14ControlEvidence(
        release_artifact_hash=HASH_A,
        policy_generation_hash=HASH_B,
        operator_registry_hash=HASH_C,
        control_store_schema_hash=HASH_D,
        store_fence_token_hash=HASH_E,
        projection_head_hash=HASH_F,
        findings_covered=REQUIRED_FINDINGS,
        durable_flags=all_true(DURABLE_FLAGS),
        process_local_authority_disabled=True,
        restart_recovered_generation=7,
        failover_recovered_generation=8,
        operator_commands=(
            valid_operator("reviewer-1", "reviewer", HASH_1, HASH_2),
            valid_operator("armer-1", "armer", HASH_3, HASH_4),
        ),
        causal_timestamps_ns={
            "review": 1_000,
            "acknowledged": 1_100,
            "armed": 1_200,
            "decision": 1_300,
            "reserve": 1_350,
        },
        max_decision_ttl_ns=500,
        actual_decision_ttl_ns=50,
        current_generation=7,
        revocation_generation=8,
        rollback_or_kill_generation_bumped=True,
        prior_decisions_revoked_on_generation_bump=True,
        decision_flags=all_true(DECISION_FLAGS),
        latch_flags=all_true(LATCH_FLAGS),
        reconciliation_flags=all_true(RECONCILIATION_FLAGS),
        risk_flags=all_true(RISK_FLAGS),
        maximum_in_memory_events=1_000,
    )


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_valid_mpr14_evidence_is_ready_and_keeps_live_paths_disabled():
    report = evaluate_mpr14_control_evidence(valid_evidence())

    assert report.state is MPR14GateState.READY_FOR_DURABLE_CANARY_CONTROL
    assert report.blockers == ()
    assert report.covered_findings == tuple(sorted(REQUIRED_FINDINGS))
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False


def test_process_local_canary_state_blocks_restart_safe_live_control():
    evidence = valid_evidence()
    flags = dict(evidence.durable_flags)
    flags["mode_durable"] = False
    flags["latches_durable"] = False
    evidence = replace(
        evidence,
        durable_flags=flags,
        process_local_authority_disabled=False,
    )

    report = evaluate_mpr14_control_evidence(evidence)

    assert "MPR14_PROCESS_LOCAL_STATE" in codes(report)
    assert "MPR14_PROCESS_LOCAL_AUTHORITY" in codes(report)


def test_rollback_and_duplicate_decision_reserve_fail_closed():
    evidence = valid_evidence()
    decision_flags = dict(evidence.decision_flags)
    decision_flags["reserve_rechecks_current_mode_generation"] = False
    decision_flags["same_decision_second_reserve_rejected"] = False
    decision_flags["rollback_invalidated_prior_decisions"] = False
    evidence = replace(
        evidence,
        rollback_or_kill_generation_bumped=False,
        prior_decisions_revoked_on_generation_bump=False,
        decision_flags=decision_flags,
    )

    report = evaluate_mpr14_control_evidence(evidence)

    assert "MPR14_ROLLBACK_NO_GENERATION_BUMP" in codes(report)
    assert "MPR14_PRIOR_DECISIONS_NOT_REVOKED" in codes(report)
    assert "MPR14_DECISION_NOT_ONESHOT" in codes(report)


def test_self_declared_human_and_self_declared_pnl_are_rejected():
    evidence = valid_evidence()
    reconciliation_flags = dict(evidence.reconciliation_flags)
    reconciliation_flags["reconciliation_input_from_rooted_authority"] = False
    reconciliation_flags["pnl_decoder_owned"] = False
    reconciliation_flags["caller_declared_pnl_rejected"] = False
    evidence = replace(
        evidence,
        operator_commands=(
            replace(
                evidence.operator_commands[0],
                role="human",
                mfa_bound=False,
                canonical_command_bound=False,
                replay_nonce_consumed=False,
            ),
        ),
        reconciliation_flags=reconciliation_flags,
    )

    report = evaluate_mpr14_control_evidence(evidence)
    found = codes(report)

    assert "MPR14_OPERATOR_ROLE_INVALID" in found
    assert "MPR14_OPERATOR_MFA_MISSING" in found
    assert "MPR14_OPERATOR_COMMAND_NOT_CANONICAL" in found
    assert "MPR14_OPERATOR_REPLAY_NOT_FENCED" in found
    assert "MPR14_OPERATOR_DUAL_CONTROL_MISSING" in found
    assert "MPR14_RECONCILIATION_SELF_DECLARED" in found


def test_daily_loss_latches_and_unbounded_events_survive_restart_gate():
    evidence = valid_evidence()
    latch_flags = dict(evidence.latch_flags)
    latch_flags["loss_latch_survives_restart"] = False
    latch_flags["reconciliation_ambiguity_latch_survives_restart"] = False
    risk_flags = dict(evidence.risk_flags)
    risk_flags["utc_day_ledger_durable"] = False
    risk_flags["daily_loss_survives_restart"] = False
    risk_flags["bounded_event_log_enabled"] = False
    evidence = replace(
        evidence,
        latch_flags=latch_flags,
        risk_flags=risk_flags,
        maximum_in_memory_events=100_001,
    )

    report = evaluate_mpr14_control_evidence(evidence)

    assert "MPR14_LATCH_POLICY_INCOMPLETE" in codes(report)
    assert "MPR14_RISK_PROJECTION_UNSAFE" in codes(report)
    assert "MPR14_EVENT_BOUND_TOO_LARGE" in codes(report)


def test_bad_hash_causal_order_and_unbounded_ttl_block_evidence():
    evidence = replace(
        valid_evidence(),
        release_artifact_hash="not-a-hash",
        causal_timestamps_ns={
            "review": 1_000,
            "acknowledged": 999,
            "armed": 1_200,
            "decision": 1_300,
            "reserve": 1_350,
        },
        actual_decision_ttl_ns=501,
        live_execution_requested=True,
    )

    report = evaluate_mpr14_control_evidence(evidence)

    assert "MPR14_BAD_HASH" in codes(report)
    assert "MPR14_CAUSAL_ORDER_BROKEN" in codes(report)
    assert "MPR14_TTL_UNBOUNDED" in codes(report)
    assert "MPR14_LIVE_REQUESTED" in codes(report)
