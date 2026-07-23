from __future__ import annotations

from copy import deepcopy

from src.atomic_sender_free_execution import (
    BORROW,
    LEG_A,
    LEG_B,
    REPAY,
    REQUIRED_FINDINGS,
    PR222Decision,
    evaluate_atomic_sender_free_evidence,
)

H = "a" * 64


def ix(index: int, role: str, **extra):
    row = {
        "index": index,
        "role": role,
        "program_id": "Program1111111111111111111111111111111111",
        "instruction_hash": H,
        "account_roles_hash": H,
        "decoded_semantics_hash": H,
        "input_lamports": 0,
        "output_lamports": 0,
        "principal_lamports": 0,
        "flash_fee_lamports": 0,
        "repayment_lamports": 0,
    }
    row.update(extra)
    return row


def valid():
    return {
        "plan": {
            "release_id": "rel-222",
            "plan_id": "plan-1",
            "wallet_pubkey": "Wallet1111111111111111111111111111111111",
            "durable_reservation_id": "reserve-1",
            "cluster_genesis_hash": H,
            "protocol_registry_hash": H,
            "provider_generation_hash": H,
            "build_artifact_hash": H,
            "principal_lamports": 1000,
            "flash_fee_lamports": 3,
            "minimum_profit_lamports": 1,
            "max_slippage_bps": 50,
        },
        "compiled_message": {
            "plan_id": "plan-1",
            "message_hash": H,
            "message_bytes_hash": H,
            "account_meta_hash": H,
            "alt_snapshot_hash": H,
            "recent_blockhash": "blockhash-ok",
            "current_block_height": 10,
            "last_valid_block_height": 100,
            "safety_margin_blocks": 5,
            "min_context_slot": 8,
            "observed_context_slot": 9,
            "unsigned_transaction_bytes": 300,
            "required_signature_count": 1,
            "max_wire_bytes": 1232,
        },
        "instructions": (
            ix(0, BORROW, principal_lamports=1000, flash_fee_lamports=3),
            ix(1, LEG_A, input_lamports=1000, output_lamports=1200),
            ix(2, LEG_B, input_lamports=1200, output_lamports=1050),
            ix(3, REPAY, repayment_lamports=1003),
        ),
        "simulation": {
            "message_hash": H,
            "request_hash": H,
            "response_hash": H,
            "pre_accounts_hash": H,
            "post_accounts_hash": H,
            "logs_hash": H,
            "success": True,
            "error_code": None,
            "local_signature_verification_passed": True,
            "units_consumed": 20_000,
            "total_transaction_fee_lamports": 5,
        },
        "economics": {
            "repayment_lamports": 1003,
            "guaranteed_leg_b_output_lamports": 1050,
            "total_transaction_fee_lamports": 5,
            "failed_landing_fee_lamports": 5,
            "rent_create_lamports": 1,
            "rent_refund_lamports": 0,
            "priority_fee_lamports": 1,
            "jito_tip_lamports": 1,
            "token_transfer_fee_lamports": 1,
            "contingency_lamports": 1,
            "minimum_profit_lamports": 1,
        },
        "qualification": {
            "installed_artifact_hash": H,
            "composition_root_hash": H,
            "durable_shadow_trace_hash": H,
            "replay_bundle_hash": H,
            "started_ns": 1,
            "ended_ns": 2,
            "non_synthetic_cycle_count": 1,
            "restart_drill_count": 1,
            "provider_degradation_drill_count": 1,
            "deterministic_replay_passed": True,
            "durable_trace_materialized": True,
            "compiled_from_installed_artifact": True,
            "exact_simulation_replayed": True,
            "economics_reconciled": True,
            "sender_namespace_reachable": False,
            "signer_namespace_reachable": False,
            "private_key_reachable": False,
            "network_submission_reachable": False,
        },
        "findings_covered": tuple(sorted(REQUIRED_FINDINGS)),
    }


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_ready_report_is_sender_free_and_pr223_ready():
    report = evaluate_atomic_sender_free_evidence(valid())
    assert report.decision is PR222Decision.READY_FOR_PR223_SIGNER_REVIEW
    assert report.ready_for_pr223_signer_review is True
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False


def test_forbidden_sender_signer_live_surfaces_block():
    evidence = valid()
    evidence["sender_requested"] = True
    evidence["qualification"]["private_key_reachable"] = True
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_FORBIDDEN_REQUEST" in result
    assert "PR222_FORBIDDEN_SURFACE" in result


def test_instruction_firewall_rejects_bad_bracket_and_unknown_role():
    evidence = valid()
    evidence["instructions"] = evidence["instructions"][1:] + evidence["instructions"][:1]
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_BAD_FLASH_BRACKET" in result

    evidence = valid()
    evidence["instructions"] = evidence["instructions"] + (ix(4, "system.transfer"),)
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_UNKNOWN_INSTRUCTION" in result


def test_blockhash_message_and_simulation_identity_are_bound():
    evidence = valid()
    evidence["compiled_message"]["current_block_height"] = 98
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_BLOCKHASH_STALE" in result

    evidence = valid()
    evidence["simulation"]["message_hash"] = "b" * 64
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_SIMULATION_BINDING" in result


def test_economics_are_conservative_and_simulation_fee_bound():
    evidence = valid()
    evidence["economics"]["failed_landing_fee_lamports"] = 0
    evidence["economics"]["total_transaction_fee_lamports"] = 4
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_FAILED_LANDING_FEE" in result
    assert "PR222_FEE_NOT_SIMULATION_BOUND" in result

    evidence = valid()
    evidence["economics"]["guaranteed_leg_b_output_lamports"] = 999
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_GUARANTEED_OUTPUT" in result
    assert "PR222_CONSERVATIVE_PROFIT" in result


def test_qualification_and_finding_coverage_are_required():
    evidence = valid()
    evidence["qualification"]["non_synthetic_cycle_count"] = 0
    evidence["qualification"]["deterministic_replay_passed"] = False
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_QUALIFICATION_COUNT" in result
    assert "PR222_QUALIFICATION_FLAG" in result

    evidence = valid()
    evidence["findings_covered"] = ("F-008", "F-008")
    result = codes(evaluate_atomic_sender_free_evidence(evidence))
    assert "PR222_DUPLICATE_FINDING" in result
    assert "PR222_FINDINGS_INCOMPLETE" in result


def test_report_hash_is_deterministic():
    left = evaluate_atomic_sender_free_evidence(valid()).evidence_hash
    right = evaluate_atomic_sender_free_evidence(deepcopy(valid())).evidence_hash
    assert left == right
