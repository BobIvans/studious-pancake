from __future__ import annotations

from pathlib import Path

import pytest

from src.submission.pr202_isolated_signer_settlement import (
    AckStatus,
    IsolatedSignerBoundaryEvidence,
    PermitUseRequest,
    PR202EvidenceError,
    ReviewedPermit,
    SettlementEvidence,
    SQLitePermitAuthority,
    TransportAck,
    TransportKind,
    pr202_readiness_report,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
BLOCKHASH_A = "H" * 44
BLOCKHASH_B = "J" * 44
IMAGE = "registry.example/flashloan-bot@sha256:" + HASH_A


def _permit(**overrides: object) -> ReviewedPermit:
    values: dict[str, object] = {
        "permit_id": "permit-1",
        "release_hash": HASH_A,
        "config_hash": HASH_B,
        "policy_hash": HASH_C,
        "attempt_id": "attempt-1",
        "plan_hash": HASH_D,
        "message_hash": HASH_E,
        "blockhash": BLOCKHASH_A,
        "transport": TransportKind.RPC_SINGLE,
        "tip_lamports": 100,
        "risk_budget_hash": HASH_F,
        "boot_generation": 3,
        "issued_at_ms": 1_000,
        "expires_at_ms": 61_000,
        "signer_service_id": "signer-v1",
        "reviewer_hash": HASH_A,
    }
    values.update(overrides)
    return ReviewedPermit(**values)


def _request(permit: ReviewedPermit, **overrides: object) -> PermitUseRequest:
    values: dict[str, object] = {
        "permit": permit,
        "message_hash": permit.message_hash,
        "blockhash": permit.blockhash,
        "transport": permit.transport,
        "tip_lamports": permit.tip_lamports,
        "boot_generation": permit.boot_generation,
        "now_ms": 2_000,
    }
    values.update(overrides)
    return PermitUseRequest(**values)


def _signer(**overrides: object) -> IsolatedSignerBoundaryEvidence:
    values: dict[str, object] = {
        "signer_service_id": "signer-v1",
        "image_digest": IMAGE,
        "release_hash": HASH_A,
        "separate_process": True,
        "separate_container": True,
        "narrow_ipc": True,
        "key_never_enters_main_runtime": True,
        "key_not_in_logs": True,
        "key_not_in_files": True,
        "deny_by_default_egress": True,
        "no_general_network_access": True,
        "no_unreviewed_signing_method": True,
        "secret_rotation_drill_hash": HASH_B,
        "compromise_drill_hash": HASH_C,
        "break_glass_policy_hash": HASH_D,
    }
    values.update(overrides)
    return IsolatedSignerBoundaryEvidence(**values)


def _settlement(**overrides: object) -> SettlementEvidence:
    values: dict[str, object] = {
        "attempt_id": "attempt-1",
        "message_hash": HASH_E,
        "selected_transport": TransportKind.RPC_SINGLE,
        "ack_status": AckStatus.ACCEPTED,
        "signature_hash": HASH_A,
        "signature_finalized": True,
        "transaction_meta_hash": HASH_B,
        "native_balance_delta_hash": HASH_C,
        "token_balance_delta_hash": HASH_D,
        "repayment_verified": True,
        "minimum_rooted_slot": 1_000,
        "observed_rooted_slot": 1_010,
        "ambiguous_transport": False,
        "accounting_hash": HASH_F,
    }
    values.update(overrides)
    return SettlementEvidence(**values)


def _authority(tmp_path: Path) -> SQLitePermitAuthority:
    return SQLitePermitAuthority(tmp_path / "permits.sqlite3")


def _consume_and_intent(tmp_path: Path) -> tuple[SQLitePermitAuthority, object, object]:
    authority = _authority(tmp_path)
    permit = _permit()
    consumption = authority.consume_permit(_request(permit))
    intent = authority.record_submission_intent(
        attempt_id=permit.attempt_id,
        permit_id=permit.permit_id,
        message_hash=permit.message_hash,
        transport=permit.transport,
        tip_lamports=permit.tip_lamports,
        created_at_ms=2_100,
    )
    return authority, consumption, intent


def test_live_is_compile_config_runtime_disabled_for_signer_boundary() -> None:
    with pytest.raises(PR202EvidenceError, match="PR202_LIVE_MUST_REMAIN_DISABLED"):
        _signer(live_enabled=True)

    report = _signer().evaluate()
    assert report["signer_boundary_healthy"] is True
    assert report["live_enabled"] is False
    assert report["signer_reachable_from_main_runtime"] is False
    assert report["general_network_access"] is False
    assert report["unreviewed_signing_method"] is False


def test_permit_rejects_message_blockhash_expiry_and_boot_generation_drift() -> None:
    permit = _permit()
    _request(permit).validate_binding()

    with pytest.raises(PR202EvidenceError, match="PR202_MESSAGE_HASH_MISMATCH"):
        _request(permit, message_hash=HASH_D).validate_binding()

    with pytest.raises(PR202EvidenceError, match="PR202_BLOCKHASH_MISMATCH"):
        _request(permit, blockhash=BLOCKHASH_B).validate_binding()

    with pytest.raises(PR202EvidenceError, match="PR202_PERMIT_EXPIRED"):
        _request(permit, now_ms=permit.expires_at_ms + 1).validate_binding()

    with pytest.raises(PR202EvidenceError, match="PR202_BOOT_GENERATION_DRIFT"):
        _request(permit, boot_generation=permit.boot_generation + 1).validate_binding()


def test_short_lived_permit_ttl_is_enforced() -> None:
    with pytest.raises(PR202EvidenceError, match="PR202_PERMIT_TTL_TOO_LONG"):
        _permit(expires_at_ms=200_000)

    with pytest.raises(PR202EvidenceError, match="PR202_PERMIT_EXPIRY_NOT_AFTER_ISSUE"):
        _permit(expires_at_ms=1_000)


def test_sqlite_permit_authority_consumes_permit_once(tmp_path: Path) -> None:
    authority = _authority(tmp_path)
    permit = _permit()
    consumption = authority.consume_permit(_request(permit))
    assert consumption.permit_id == permit.permit_id
    assert consumption.attempt_id == permit.attempt_id

    with pytest.raises(PR202EvidenceError, match="PR202_PERMIT_ALREADY_CONSUMED"):
        authority.consume_permit(_request(permit, now_ms=3_000))
    authority.close()


def test_submission_intent_requires_consumed_permit_and_rejects_fallback(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    permit = _permit()

    with pytest.raises(PR202EvidenceError, match="PR202_INTENT_WITHOUT_CONSUMED_PERMIT"):
        authority.record_submission_intent(
            attempt_id=permit.attempt_id,
            permit_id=permit.permit_id,
            message_hash=permit.message_hash,
            transport=permit.transport,
            tip_lamports=permit.tip_lamports,
            created_at_ms=2_100,
        )

    authority.consume_permit(_request(permit))
    intent = authority.record_submission_intent(
        attempt_id=permit.attempt_id,
        permit_id=permit.permit_id,
        message_hash=permit.message_hash,
        transport=permit.transport,
        tip_lamports=permit.tip_lamports,
        created_at_ms=2_100,
    )
    assert intent.transport is TransportKind.RPC_SINGLE

    with pytest.raises(PR202EvidenceError, match="PR202_TRANSPORT_FALLBACK_OR_RESEND"):
        authority.record_submission_intent(
            attempt_id=permit.attempt_id,
            permit_id=permit.permit_id,
            message_hash=permit.message_hash,
            transport=TransportKind.JITO_BUNDLE,
            tip_lamports=permit.tip_lamports,
            created_at_ms=2_200,
        )
    authority.close()


def test_transport_ack_cannot_create_realized_pnl_and_must_match_intent(
    tmp_path: Path,
) -> None:
    authority, _consumption, intent = _consume_and_intent(tmp_path)

    with pytest.raises(PR202EvidenceError, match="PR202_ACK_CANNOT_SET_REALIZED_PNL"):
        TransportAck(
            attempt_id=intent.attempt_id,
            message_hash=intent.message_hash,
            transport=intent.transport,
            status=AckStatus.ACCEPTED,
            ack_hash=HASH_A,
            accepted_at_ms=2_200,
            realized_pnl_lamports=1,
        )

    with pytest.raises(PR202EvidenceError, match="PR202_ACK_INTENT_MISMATCH"):
        authority.record_transport_ack(
            TransportAck(
                attempt_id=intent.attempt_id,
                message_hash=intent.message_hash,
                transport=TransportKind.JITO_SINGLE,
                status=AckStatus.ACCEPTED,
                ack_hash=HASH_A,
                accepted_at_ms=2_200,
            )
        )

    ack = authority.record_transport_ack(
        TransportAck(
            attempt_id=intent.attempt_id,
            message_hash=intent.message_hash,
            transport=intent.transport,
            status=AckStatus.ACCEPTED,
            ack_hash=HASH_A,
            accepted_at_ms=2_200,
        )
    )
    assert ack.status is AckStatus.ACCEPTED
    authority.close()


def test_finalized_settlement_requires_rooted_meta_deltas_and_repayment() -> None:
    result = _settlement().evaluate()
    assert result["finalized"] is True
    assert result["realized_pnl_allowed"] is True
    assert result["ack_counts_as_realized_pnl"] is False

    blocked = _settlement(
        signature_finalized=False,
        observed_rooted_slot=999,
        repayment_verified=False,
    ).evaluate()
    assert blocked["finalized"] is False
    assert blocked["manual_review_required"] is True
    assert "PR202_SIGNATURE_NOT_FINALIZED" in blocked["blockers"]
    assert "PR202_ROOTED_SLOT_BELOW_MINIMUM" in blocked["blockers"]
    assert "PR202_REPAYMENT_NOT_VERIFIED" in blocked["blockers"]


def test_ambiguous_transport_locks_settlement_for_manual_review() -> None:
    result = _settlement(ambiguous_transport=True).evaluate()
    assert result["status"] == "locked_manual"
    assert result["finalized"] is False
    assert "PR202_AMBIGUOUS_TRANSPORT_MANUAL_LOCK" in result["blockers"]


def test_combined_report_remains_sender_free_and_default_off(tmp_path: Path) -> None:
    authority, consumption, intent = _consume_and_intent(tmp_path)
    report = pr202_readiness_report(
        signer_boundary=_signer(),
        permit_consumption=consumption,
        submission_intent=intent,
        settlement=_settlement(),
    )
    assert report["ready_for_live"] is False
    assert report["live_enabled"] is False
    assert report["signer_reachable"] is False
    assert report["sender_reachable"] is False
    assert report["submission_allowed"] is False
    assert report["permit_consumed_once"] is True
    assert report["finalized_settlement"] is True
    authority.close()
