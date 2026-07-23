from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.super_mpr_c_canary_gate import (  # noqa: E402
    CanaryGateState,
    CanaryPermit,
    CanaryRequestEvidence,
    DuplicateSubmissionSnapshot,
    FinalizedSettlementProof,
    HumanApprovalArtifact,
    JitoBundleStatus,
    JitoTransportEvidence,
    KillCondition,
    KillSwitchState,
    PermitLedgerSnapshot,
    SameMessageSigningRequest,
    SignerIsolationEvidence,
    SuperMprCError,
    SuperMprDependencyEvidence,
    TransportKind,
    consume_permit_before_signing,
    evaluate_canary_gate,
    evaluate_finalized_settlement,
)

NOW = "2026-07-23T18:00:00Z"
EXPIRY = "2026-07-23T19:00:00Z"
PROGRAM = "Jupiter1111111111111111111111111111111111"


def dg(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def deps(ok: bool = True) -> SuperMprDependencyEvidence:
    return SuperMprDependencyEvidence(
        ok,
        ok,
        dg("a") if ok else None,
        dg("b") if ok else None,
    )


def signer(**kwargs: object) -> SignerIsolationEvidence:
    data = dict(
        signer_service_id="signer-v1",
        separate_process_boundary=True,
        separate_entrypoint="flashloan-signer",
        separate_config_digest=dg("signer-config"),
        separate_capability_manifest_digest=dg("signer-cap"),
        separate_artifact_digest=dg("signer-image"),
        runtime_to_signer_channel_authenticated=True,
        namespace_isolation_evidence_digest=dg("ns"),
        key_backend_policy_digest=dg("key-policy"),
    )
    data.update(kwargs)
    return SignerIsolationEvidence(**data)


def approval(**kwargs: object) -> HumanApprovalArtifact:
    data = dict(
        approval_id="approval-1",
        operator="reviewer@example.invalid",
        timestamp="2026-07-23T17:55:00Z",
        expires_at=EXPIRY,
        runtime_artifact_digest=dg("runtime"),
        config_digest=dg("config"),
        capability_manifest_digest=dg("cap"),
        max_spend_lamports=100_000,
        max_tip_lamports=1_000,
        max_loss_lamports=10_000,
        allowed_route_digest=dg("route"),
        allowed_program_ids=(PROGRAM,),
    )
    data.update(kwargs)
    return HumanApprovalArtifact(**data)


def permit(appr: HumanApprovalArtifact, **kwargs: object) -> CanaryPermit:
    data = dict(
        permit_id="permit-1",
        nonce="nonce-1",
        expires_at=EXPIRY,
        final_message_digest=dg("message"),
        simulation_digest=dg("simulation"),
        route_digest=appr.allowed_route_digest,
        economic_digest=dg("economic"),
        account_metas_digest=dg("metas"),
        allowed_program_ids=appr.allowed_program_ids,
        max_fee_lamports=5_000,
        max_tip_lamports=500,
        max_loss_lamports=5_000,
        max_spend_lamports=50_000,
        approval_artifact_digest=appr.approval_digest,
        runtime_artifact_digest=appr.runtime_artifact_digest,
        config_digest=appr.config_digest,
        capability_manifest_digest=appr.capability_manifest_digest,
    )
    data.update(kwargs)
    return CanaryPermit(**data)


def sign_req(pmt: CanaryPermit, **kwargs: object) -> SameMessageSigningRequest:
    data = dict(
        request_id="sign-1",
        permit=pmt,
        final_message_digest=pmt.final_message_digest,
        simulation_digest=pmt.simulation_digest,
        route_digest=pmt.route_digest,
        economic_digest=pmt.economic_digest,
        account_metas_digest=pmt.account_metas_digest,
        requested_program_ids=pmt.allowed_program_ids,
        signing_request_digest=dg("signing-request"),
        requested_fee_lamports=3_000,
        requested_tip_lamports=400,
        requested_loss_lamports=2_000,
        requested_spend_lamports=40_000,
        blockhash=dg("blockhash"),
        blockhash_expires_at=EXPIRY,
    )
    data.update(kwargs)
    return SameMessageSigningRequest(**data)


def evidence(**kwargs: object) -> CanaryRequestEvidence:
    appr = approval()
    pmt = permit(appr)
    data = dict(
        dependencies=deps(),
        signer=signer(),
        approval=appr,
        permit=pmt,
        permit_ledger=PermitLedgerSnapshot(),
        signing_request=sign_req(pmt),
        kill_switch=KillSwitchState(),
        duplicate_guard=DuplicateSubmissionSnapshot(),
        jito=JitoTransportEvidence(False, TransportKind.RPC),
        signed_transaction_digest=dg("signed-tx"),
        opportunity_id="opp-1",
    )
    data.update(kwargs)
    return CanaryRequestEvidence(**data)


def settlement(**kwargs: object) -> FinalizedSettlementProof:
    data = dict(
        finalized_transaction_found=True,
        finalized_commitment="finalized",
        signature="sig1",
        final_message_digest=dg("message"),
        signed_transaction_digest=dg("signed-tx"),
        token_balance_deltas_digest=dg("token-deltas"),
        native_balance_deltas_digest=dg("native-deltas"),
        actual_fee_lamports=3000,
        rent_delta_lamports=0,
        ata_changes_digest=dg("ata"),
        wsol_lifecycle_digest=dg("wsol"),
        flashloan_repayment_digest=dg("repay"),
        realized_net_pnl_lamports=1234,
    )
    data.update(kwargs)
    return FinalizedSettlementProof(**data)


def assess(item: CanaryRequestEvidence):
    return evaluate_canary_gate(item, now=NOW)


def test_super_mpr_c_is_dependency_gated_until_super_a_and_b_complete() -> None:
    result = assess(evidence(dependencies=deps(False)))
    assert result.state is CanaryGateState.BLOCKED_DEPENDENCY_GATED
    assert result.live_ready is False
    assert result.canary_available is False
    assert {"super_mpr_a_incomplete", "super_mpr_b_incomplete"} <= set(result.blockers)


def test_clean_canary_evidence_is_available_but_never_unrestricted_live() -> None:
    result = assess(evidence())
    assert result.state is CanaryGateState.READY
    assert result.canary_available is True
    assert result.live_ready is False
    assert result.unrestricted_live_possible is False


def test_signer_rejects_arbitrary_message_and_runtime_key_exposure() -> None:
    result = assess(
        evidence(
            signer=signer(
                arbitrary_message_signing=True,
                signer_private_key_exposed_to_runtime=True,
            )
        )
    )
    assert "signer_allows_arbitrary_message_signing" in result.blockers
    assert "runtime_can_see_signer_private_key" in result.blockers


def test_signer_requires_human_approval_artifact() -> None:
    result = assess(evidence(approval=None))
    assert result.state is CanaryGateState.BLOCKED
    assert "missing_human_approval_artifact" in result.blockers
    assert result.signer_refuses is True


def test_permit_single_use_and_not_reused_after_restart() -> None:
    base = evidence()
    consumed = consume_permit_before_signing(
        base.permit_ledger,
        assess(base),
        base.permit,
    )
    assert consumed.contains(base.permit)
    replay = assess(evidence(permit_ledger=consumed))
    assert "permit_already_consumed" in replay.blockers
    with pytest.raises(SuperMprCError):
        consumed.consume(base.permit)


def test_permit_and_approval_expiry_block_signing() -> None:
    appr = approval(expires_at="2026-07-23T17:00:00Z")
    pmt = permit(appr, expires_at="2026-07-23T17:30:00Z")
    result = assess(evidence(approval=appr, permit=pmt, signing_request=sign_req(pmt)))
    assert "approval_expired" in result.blockers
    assert "permit_expired" in result.blockers


def test_same_message_digest_binding_rejects_mutation_after_simulation() -> None:
    appr = approval()
    pmt = permit(appr)
    result = assess(
        evidence(
            approval=appr,
            permit=pmt,
            signing_request=sign_req(pmt, final_message_digest=dg("mutated")),
        )
    )
    assert "signing_message_digest_mismatch" in result.blockers


def test_duplicate_submission_guard_blocks_repeat_tx_permit_and_opportunity() -> None:
    guard = DuplicateSubmissionSnapshot(
        (dg("signed-tx"),),
        ("permit-1",),
        ("opp-1",),
        (dg("blockhash"),),
    )
    result = assess(evidence(duplicate_guard=guard))
    assert "duplicate_signed_transaction" in result.blockers
    assert "duplicate_permit_submission" in result.blockers
    assert "duplicate_opportunity_submission" in result.blockers
    assert "duplicate_blockhash_submission" in result.blockers


def test_jito_landed_is_transport_not_settlement() -> None:
    jito = JitoTransportEvidence(
        True,
        TransportKind.JITO,
        JitoBundleStatus.LANDED,
        True,
    )
    result = evaluate_finalized_settlement(
        settlement(),
        expected_final_message_digest=dg("message"),
        expected_signed_transaction_digest=dg("signed-tx"),
        jito=jito,
    )
    assert jito.settlement_authority is False
    assert result.state is CanaryGateState.READY


def test_jito_disabled_or_uncled_status_fails_closed() -> None:
    jito = JitoTransportEvidence(False, TransportKind.JITO, JitoBundleStatus.UNCLED)
    result = assess(evidence(jito=jito))
    assert "jito_not_enabled_by_canary_policy" in result.blockers
    assert "jito_tip_not_inside_same_message_policy" in result.blockers
    assert "jito_uncled_fail_closed" in result.blockers


def test_finalized_deltas_required_and_ack_cannot_settle() -> None:
    result = evaluate_finalized_settlement(
        settlement(
            finalized_transaction_found=False,
            provider_ack_used_as_settlement=True,
            jito_bundle_id_used_as_settlement=True,
            signature_only_used_as_settlement=True,
        ),
        expected_final_message_digest=dg("message"),
        expected_signed_transaction_digest=dg("signed-tx"),
        jito=JitoTransportEvidence(False, TransportKind.RPC),
    )
    assert result.state is CanaryGateState.BLOCKED
    assert "settlement_finalized_transaction_missing" in result.blockers
    assert "provider_ack_cannot_settle" in result.blockers
    assert "jito_bundle_id_cannot_settle" in result.blockers
    assert "signature_only_cannot_settle" in result.blockers


def test_canary_budget_latch_and_kill_switch_block_signing() -> None:
    appr = approval()
    pmt = permit(appr)
    result = assess(evidence(
        approval=appr,
        permit=pmt,
        signing_request=sign_req(pmt, requested_fee_lamports=5_001),
        kill_switch=KillSwitchState((KillCondition.PROVIDER_DRIFT,), True),
    ))
    assert "signing_fee_exceeds_permit" in result.blockers
    assert "kill_switch:provider_drift" in result.blockers
    assert "kill_switch:manual_kill" in result.blockers


def test_blocked_assessment_cannot_consume_permit() -> None:
    item = evidence(approval=None)
    with pytest.raises(SuperMprCError):
        consume_permit_before_signing(item.permit_ledger, assess(item), item.permit)
