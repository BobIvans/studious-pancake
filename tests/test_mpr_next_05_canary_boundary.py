from __future__ import annotations

import hashlib

from src.live_boundary.mpr_next_05_canary_boundary import (
    CanaryApprovalArtifact,
    CanaryPermit,
    CanarySigningRequest,
    CanarySigningState,
    FilePermitLedger,
    FinalizedSettlementEvidence,
    JitoLifecycleState,
    JitoTransportReceipt,
    evaluate_canary_signing_request,
    evaluate_finalized_settlement,
)

PROGRAM_A = "11111111111111111111111111111111"
PROGRAM_B = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def approval(**overrides):
    values = {
        "approval_id": "approval-1",
        "operator": "operator-a",
        "second_reviewer": "reviewer-b",
        "approved_at_unix_ms": 1_000,
        "expires_at_unix_ms": 10_000,
        "runtime_artifact_digest": h("runtime"),
        "config_digest": h("config"),
        "capability_manifest_digest": h("capabilities"),
        "max_spend_lamports": 10_000,
        "max_tip_lamports": 1_000,
        "max_loss_lamports": 2_000,
        "allowed_program_ids": (PROGRAM_A, PROGRAM_B),
        "one_transaction_limit": True,
        "approved": True,
    }
    values.update(overrides)
    return CanaryApprovalArtifact(**values)


def permit(package: CanaryApprovalArtifact, **overrides):
    values = {
        "permit_id": "permit-1",
        "approval_digest": package.digest,
        "attempt_id": "attempt-1",
        "final_message_digest": h("message"),
        "route_digest": h("route"),
        "simulation_digest": h("simulation"),
        "account_metas_digest": h("account-metas"),
        "allowed_program_ids": (PROGRAM_A,),
        "max_fee_lamports": 5_000,
        "max_tip_lamports": 500,
        "max_loss_lamports": 1_000,
        "expires_at_unix_ms": 5_000,
        "nonce_digest": h("nonce"),
    }
    values.update(overrides)
    return CanaryPermit(**values)


def request(ticket: CanaryPermit, **overrides):
    values = {
        "permit_id": ticket.permit_id,
        "final_message_digest": ticket.final_message_digest,
        "route_digest": ticket.route_digest,
        "simulation_digest": ticket.simulation_digest,
        "account_metas_digest": ticket.account_metas_digest,
        "program_ids": (PROGRAM_A,),
        "fee_lamports": 1_000,
        "tip_lamports": 100,
        "requested_at_unix_ms": 2_000,
        "kill_switch_active": False,
        "jito_requested": False,
        "jito_policy_allowed": False,
    }
    values.update(overrides)
    return CanarySigningRequest(**values)


def ledger(tmp_path):
    return FilePermitLedger(tmp_path / "permit-ledger.json")


def test_signer_rejects_arbitrary_message(tmp_path):
    package = approval()
    ticket = permit(package)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, final_message_digest=h("mutated-message")),
        ledger=ledger(tmp_path),
    )
    assert verdict.state is CanarySigningState.BLOCKED
    assert verdict.signer_refuses is True
    assert "FINAL_MESSAGE_DIGEST_MISMATCH" in verdict.blockers
    assert verdict.permit_consumed is False


def test_signer_requires_human_approval_artifact(tmp_path):
    package = approval(approved=False)
    ticket = permit(package)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket),
        ledger=ledger(tmp_path),
    )
    assert verdict.live_ready is False
    assert verdict.canary_available is False
    assert "HUMAN_APPROVAL_NOT_APPROVED" in verdict.blockers


def test_permit_single_use_and_restart_persistence(tmp_path):
    package = approval()
    ticket = permit(package)
    path = tmp_path / "permit-ledger.json"
    first = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket),
        ledger=FilePermitLedger(path),
    )
    assert first.state is CanarySigningState.READY_FOR_ISOLATED_SIGNER
    assert first.signing_intent_digest is not None
    assert first.permit_consumed is True
    assert first.live_ready is False

    after_restart = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket),
        ledger=FilePermitLedger(path),
    )
    assert after_restart.state is CanarySigningState.BLOCKED
    assert after_restart.blockers == ("PERMIT_ALREADY_CONSUMED",)


def test_permit_expiry_blocks_before_consumption(tmp_path):
    package = approval()
    ticket = permit(package, expires_at_unix_ms=1_500)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, requested_at_unix_ms=2_000),
        ledger=ledger(tmp_path),
    )
    assert "PERMIT_EXPIRED" in verdict.blockers
    assert verdict.permit_consumed is False


def test_permit_digest_binding_blocks_route_and_simulation_mutation(tmp_path):
    package = approval()
    ticket = permit(package)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, route_digest=h("other-route"), simulation_digest=h("other-sim")),
        ledger=ledger(tmp_path),
    )
    assert "ROUTE_DIGEST_MISMATCH" in verdict.blockers
    assert "SIMULATION_DIGEST_MISMATCH" in verdict.blockers


def test_canary_budget_latch_blocks_fee_tip_and_program_escape(tmp_path):
    package = approval(max_tip_lamports=100)
    ticket = permit(package, max_fee_lamports=100, max_tip_lamports=50)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, fee_lamports=101, tip_lamports=51, program_ids=(PROGRAM_B,)),
        ledger=ledger(tmp_path),
    )
    assert "FEE_EXCEEDS_PERMIT" in verdict.blockers
    assert "TIP_EXCEEDS_PERMIT" in verdict.blockers
    assert f"PROGRAM_NOT_IN_PERMIT:{PROGRAM_B}" in verdict.blockers


def test_kill_switch_blocks_signing(tmp_path):
    package = approval()
    ticket = permit(package)
    verdict = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, kill_switch_active=True),
        ledger=ledger(tmp_path),
    )
    assert verdict.signer_refuses is True
    assert "KILL_SWITCH_ACTIVE" in verdict.blockers


def test_jito_requested_requires_explicit_canary_policy(tmp_path):
    package = approval()
    ticket = permit(package)
    blocked = evaluate_canary_signing_request(
        approval=package,
        permit=ticket,
        request=request(ticket, jito_requested=True, jito_policy_allowed=False),
        ledger=ledger(tmp_path),
    )
    assert "JITO_DISABLED_FOR_CANARY" in blocked.blockers


def test_jito_ack_or_landed_is_not_settlement_without_finalized_deltas():
    receipt = JitoTransportReceipt(
        state=JitoLifecycleState.LANDED,
        bundle_id="bundle-1",
        transaction_signature="sig-1",
        transport_acknowledged=True,
        landed=True,
        confirmed=False,
        finalized=False,
    )
    verdict = evaluate_finalized_settlement(
        receipt=receipt,
        evidence=None,
        expected_final_message_digest=h("message"),
    )
    assert verdict.settled is False
    assert verdict.realized_profit_allowed is False
    assert "JITO_ACK_IS_NOT_SETTLEMENT" in verdict.blockers
    assert "JITO_LANDED_IS_NOT_FINAL_ECONOMIC_PROOF" in verdict.blockers
    assert "FINALIZED_CHAIN_EVIDENCE_REQUIRED" in verdict.blockers


def test_finalized_deltas_required_for_settlement():
    receipt = JitoTransportReceipt(
        state=JitoLifecycleState.FINALIZED,
        bundle_id="bundle-1",
        transaction_signature="sig-1",
        transport_acknowledged=True,
        landed=True,
        confirmed=True,
        finalized=True,
    )
    accepted = evaluate_finalized_settlement(
        receipt=receipt,
        evidence=FinalizedSettlementEvidence(
            transaction_signature="sig-1",
            final_message_digest=h("message"),
            finalized_slot=123,
            token_balance_deltas_digest=h("token-deltas"),
            native_balance_deltas_digest=h("native-deltas"),
            actual_fee_lamports=5_000,
            rent_delta_lamports=0,
            ata_delta_lamports=0,
            wsol_delta_lamports=0,
            flashloan_repaid=True,
            realized_net_pnl_lamports=100,
        ),
        expected_final_message_digest=h("message"),
    )
    assert accepted.settled is True
    assert accepted.realized_profit_allowed is True

    rejected = evaluate_finalized_settlement(
        receipt=receipt,
        evidence=FinalizedSettlementEvidence(
            transaction_signature="sig-1",
            final_message_digest=h("mutated-message"),
            finalized_slot=123,
            token_balance_deltas_digest=h("token-deltas"),
            native_balance_deltas_digest=h("native-deltas"),
            actual_fee_lamports=5_000,
            rent_delta_lamports=0,
            ata_delta_lamports=0,
            wsol_delta_lamports=0,
            flashloan_repaid=False,
            realized_net_pnl_lamports=100,
        ),
        expected_final_message_digest=h("message"),
    )
    assert rejected.settled is False
    assert "SETTLEMENT_MESSAGE_DIGEST_MISMATCH" in rejected.blockers
    assert "FLASHLOAN_REPAYMENT_NOT_PROVEN" in rejected.blockers
