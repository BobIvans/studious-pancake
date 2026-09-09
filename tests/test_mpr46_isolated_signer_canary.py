from __future__ import annotations

import hashlib

from src.mpr46_isolated_signer_canary import (
    SCHEMA_VERSION,
    default_policy_path,
    evaluate_default_policy,
    evaluate_mpr46_policy,
)


def _message() -> bytes:
    return b"mpr-46-one-transaction-canary-message"


def _digest() -> str:
    return hashlib.sha256(_message()).hexdigest()


def _eligible_evidence() -> dict[str, object]:
    digest = _digest()
    return {
        "schema_version": SCHEMA_VERSION,
        "canary_state": "CANARY_ELIGIBLE",
        "paper_qualified_evidence_complete": True,
        "provider_protocol_binaries_attested": True,
        "exact_transaction_settlement_authority_operational": True,
        "deployment_supply_chain_controls_passed": True,
        "backup_restore_runbooks_approved": True,
        "human_release_authority_signed": True,
        "signer_separate_artifact": True,
        "signer_no_arbitrary_egress": True,
        "signer_no_provider_rpc_access": True,
        "authenticated_ipc": True,
        "external_key_backend": True,
        "durable_single_use_permit_store": True,
        "signer_independent_policy_checks": True,
        "signed_receipts": True,
        "signer_side_kill_switch": True,
        "monotonic_anti_rollback_state": True,
        "permit_binds_final_simulation": True,
        "permit_binds_reservation": True,
        "sender_submits_only_signed_bytes": True,
        "finalized_reconciliation_required": True,
        "abnormality_auto_pauses_canary": True,
        "unrestricted_live_available": False,
        "live_by_env_flag": False,
        "jito_authoritative_for_settlement": False,
        "signer_can_build_transactions": False,
        "signer_can_submit_transactions": False,
        "sender_can_mutate_message": False,
        "signature_material_returned": False,
        "max_transaction_count": 1,
        "max_submission_count": 1,
        "max_borrow_atomic": 1_000_000,
        "max_total_fee_atomic": 50_000,
        "max_jito_tip_atomic": 10_000,
        "release_generation": 7,
        "runtime_generation": 11,
        "config_generation": 13,
        "permit_store_generation": 7,
        "operator_approval_ref": "approval/mpr46/canary-001",
        "final_simulation_message_sha256": digest,
        "reservation_message_sha256": digest,
    }


def _valid_request() -> dict[str, object]:
    digest = _digest()
    return {
        "permit_id": "permit/mpr46/001",
        "permit_consumed": False,
        "serialized_message_hex": _message().hex(),
        "message_digest_sha256": digest,
        "final_simulation_message_sha256": digest,
        "reservation_message_sha256": digest,
        "release_generation": 7,
        "runtime_generation": 11,
        "config_generation": 13,
        "operator_approval_ref": "approval/mpr46/canary-001",
        "borrow_atomic": 999_999,
        "total_fee_atomic": 49_999,
        "jito_tip_atomic": 9_999,
        "transaction_count": 1,
        "submission_count": 1,
    }


def _codes(report: dict[str, object]) -> set[str]:
    return {row["code"] for row in report["blockers"]}  # type: ignore[index]


def test_default_policy_is_fail_closed_without_live() -> None:
    assert default_policy_path().as_posix().endswith("mpr46_permit_canary_policy.json")
    report = evaluate_default_policy().to_dict()

    assert report["accepted"] is False
    assert report["permit_eligible"] is False
    assert report["one_tx_canary_authorized"] is False
    assert report["live_enabled"] is False
    assert report["signature_material_returned"] is False
    assert "REQUIRED_PAPER_QUALIFIED_EVIDENCE_COMPLETE" in _codes(report)


def test_complete_evidence_can_be_canary_eligible_without_enabling_live() -> None:
    report = evaluate_mpr46_policy(_eligible_evidence()).to_dict()

    assert report["accepted"] is True
    assert report["state"] == "CANARY_ELIGIBLE"
    assert report["permit_eligible"] is False
    assert report["live_enabled"] is False
    assert report["signature_material_returned"] is False


def test_valid_request_becomes_single_tx_permit_eligible_only() -> None:
    report = evaluate_mpr46_policy(
        _eligible_evidence(), request=_valid_request()
    ).to_dict()

    assert report["accepted"] is True
    assert report["state"] == "ONE_TX_PERMIT_ELIGIBLE"
    assert report["permit_eligible"] is True
    assert report["one_tx_canary_authorized"] is True
    assert report["canary_latch_remaining"] == 1
    assert report["live_enabled"] is False
    assert report["signature_material_returned"] is False


def test_request_with_mutated_serialized_message_is_denied() -> None:
    request = _valid_request()
    request["serialized_message_hex"] = b"different-message".hex()

    report = evaluate_mpr46_policy(_eligible_evidence(), request=request).to_dict()

    assert report["accepted"] is False
    assert "SERIALIZED_MESSAGE_DIGEST_MISMATCH" in _codes(report)
    assert "REQUEST_NOT_FINAL_SIMULATED_MESSAGE" in _codes(report)
    assert report["one_tx_canary_authorized"] is False


def test_consumed_or_over_budget_permit_is_denied() -> None:
    request = _valid_request()
    request["permit_consumed"] = True
    request["borrow_atomic"] = 1_000_001

    report = evaluate_mpr46_policy(_eligible_evidence(), request=request).to_dict()

    assert report["accepted"] is False
    assert "PERMIT_ALREADY_CONSUMED" in _codes(report)
    assert "REQUEST_BORROW_ATOMIC_EXCEEDS_CEILING" in _codes(report)


def test_unrestricted_live_or_signer_capability_is_never_accepted() -> None:
    evidence = _eligible_evidence()
    evidence["unrestricted_live_available"] = True
    evidence["signer_can_submit_transactions"] = True
    evidence["signature_material_returned"] = True

    report = evaluate_mpr46_policy(evidence, request=_valid_request()).to_dict()

    assert report["accepted"] is False
    assert report["live_enabled"] is False
    assert report["signature_material_returned"] is False
    assert "DANGEROUS_UNRESTRICTED_LIVE_AVAILABLE" in _codes(report)
    assert "DANGEROUS_SIGNER_CAN_SUBMIT_TRANSACTIONS" in _codes(report)
    assert "DANGEROUS_SIGNATURE_MATERIAL_RETURNED" in _codes(report)


def test_canary_latch_must_remain_exactly_one_transaction() -> None:
    evidence = _eligible_evidence()
    evidence["max_transaction_count"] = 2

    report = evaluate_mpr46_policy(evidence, request=_valid_request()).to_dict()

    assert report["accepted"] is False
    assert "CANARY_LATCH_NOT_SINGLE_TX" in _codes(report)
