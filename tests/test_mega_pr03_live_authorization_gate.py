from __future__ import annotations

import pytest

from src.submission.mega_pr03_live_authorization_gate import (
    AuthorizationStatus,
    MegaPR03AuthorizationGate,
    MegaPR03Error,
    PermitEvidence,
    SettlementEvidence,
    SignedWireEvidence,
    SubmissionIntentEvidence,
)

pytestmark = pytest.mark.unit

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64


def _permit(**overrides: object) -> PermitEvidence:
    payload: dict[str, object] = {
        "attempt_id": "attempt-001",
        "attempt_generation": 1,
        "message_hash": A,
        "blockhash": "blockhash-001",
        "selected_transport": "jito_bundle",
        "jito_tip_lamports": 5000,
        "tip_account": "tip-account-001",
        "last_valid_block_height": 10_000,
        "issued_at_ns": 100,
        "expires_at_ns": 200,
        "issuer_key_id": "issuer-key-v1",
        "reviewer_signature_hash": B,
        "predecessor_absence_hash": E,
        "resend_authorization_hash": None,
    }
    payload.update(overrides)
    return PermitEvidence(**payload)  # type: ignore[arg-type]


def _wire(**overrides: object) -> SignedWireEvidence:
    payload: dict[str, object] = {
        "message_hash": A,
        "signed_transaction_hash": C,
        "blockhash": "blockhash-001",
        "selected_transport": "jito_bundle",
        "wire_tip_lamports": 5000,
        "wire_tip_account": "tip-account-001",
        "wire_tip_static_account": True,
    }
    payload.update(overrides)
    return SignedWireEvidence(**payload)  # type: ignore[arg-type]


def _intent(permit: PermitEvidence, **overrides: object) -> SubmissionIntentEvidence:
    payload: dict[str, object] = {
        "permit_hash": permit.permit_hash,
        "attempt_id": permit.attempt_id,
        "attempt_generation": permit.attempt_generation,
        "message_hash": permit.message_hash,
        "signed_transaction_hash": C,
        "selected_transport": permit.selected_transport,
        "jito_tip_lamports": permit.jito_tip_lamports,
        "tip_account": permit.tip_account,
        "blockhash": permit.blockhash,
        "resend_authorization_hash": permit.resend_authorization_hash,
    }
    payload.update(overrides)
    return SubmissionIntentEvidence(**payload)  # type: ignore[arg-type]


def _settlement(permit: PermitEvidence, **overrides: object) -> SettlementEvidence:
    payload: dict[str, object] = {
        "permit_hash": permit.permit_hash,
        "message_hash": permit.message_hash,
        "selected_transport": permit.selected_transport,
        "jito_tip_lamports": permit.jito_tip_lamports,
        "tip_account": permit.tip_account,
        "rooted_finalized": True,
    }
    payload.update(overrides)
    return SettlementEvidence(**payload)  # type: ignore[arg-type]


def _decision(
    permit: PermitEvidence,
    *,
    wire: SignedWireEvidence | None = None,
    intent: SubmissionIntentEvidence | None = None,
    settlement: SettlementEvidence | None = None,
    now_ns: int = 150,
    current_block_height: int = 9000,
    remaining_height_margin: int = 50,
    live_runtime_enabled: bool = False,
    legacy_live_path_reachable: bool = False,
):
    return MegaPR03AuthorizationGate().evaluate(
        permit=permit,
        wire=wire or _wire(),
        intent=intent or _intent(permit),
        settlement=settlement or _settlement(permit),
        now_ns=now_ns,
        current_block_height=current_block_height,
        remaining_height_margin=remaining_height_margin,
        live_runtime_enabled=live_runtime_enabled,
        legacy_live_path_reachable=legacy_live_path_reachable,
    )


def test_positive_chain_is_ready_but_live_default_off() -> None:
    permit = _permit()

    decision = _decision(permit)

    assert decision.status is AuthorizationStatus.READY_DEFAULT_OFF
    assert decision.ready is True
    assert decision.permit_hash == permit.permit_hash
    assert decision.authorization_hash is not None
    assert decision.reason_codes == ("MEGA_PR03_READY_BUT_LIVE_DEFAULT_OFF",)


@pytest.mark.parametrize(
    ("now_ns", "reason"),
    [
        (99, "MEGA_PR03_PERMIT_NOT_YET_VALID"),
        (200, "MEGA_PR03_PERMIT_EXPIRED"),
    ],
)
def test_permit_time_bounds_are_strict(now_ns: int, reason: str) -> None:
    permit = _permit()

    decision = _decision(permit, now_ns=now_ns)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert reason in decision.reason_codes


def test_current_block_height_margin_is_required_at_consumption() -> None:
    permit = _permit(last_valid_block_height=100)

    decision = _decision(permit, current_block_height=96, remaining_height_margin=5)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_BLOCKHASH_HEIGHT_MARGIN_EXPIRED" in decision.reason_codes


def test_authenticated_review_digest_and_integer_fields_fail_closed() -> None:
    with pytest.raises(MegaPR03Error, match="reviewer_signature_hash"):
        _permit(reviewer_signature_hash="unsigned-reviewer-dto")
    with pytest.raises(MegaPR03Error, match="attempt_generation"):
        _permit(attempt_generation=True)
    with pytest.raises(MegaPR03Error, match="jito_tip_lamports"):
        _permit(jito_tip_lamports=1.5)


def test_wire_derived_tip_and_transport_cannot_drift_after_permit() -> None:
    permit = _permit()
    wire = _wire(selected_transport="rpc", wire_tip_lamports=0, wire_tip_account=None)
    intent = _intent(permit, selected_transport="rpc", jito_tip_lamports=0, tip_account=None)

    decision = _decision(permit, wire=wire, intent=intent)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_WIRE_TRANSPORT_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_WIRE_TIP_AMOUNT_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_INTENT_TRANSPORT_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_INTENT_TIP_AMOUNT_MISMATCH" in decision.reason_codes


def test_submission_intent_must_match_permit_and_signed_wire_identity() -> None:
    permit = _permit()
    intent = _intent(
        permit,
        permit_hash=D,
        signed_transaction_hash=F,
        blockhash="other-blockhash",
    )

    decision = _decision(permit, intent=intent)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_INTENT_PERMIT_HASH_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_INTENT_SIGNED_TX_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_INTENT_BLOCKHASH_MISMATCH" in decision.reason_codes


def test_resend_generation_requires_archive_complete_authorization() -> None:
    permit = _permit(
        attempt_generation=2,
        predecessor_absence_hash=None,
        resend_authorization_hash=None,
    )

    decision = _decision(permit)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_RESEND_AUTHORIZATION_REQUIRED" in decision.reason_codes


def test_resend_authorization_identity_must_survive_into_intent() -> None:
    permit = _permit(
        attempt_generation=2,
        predecessor_absence_hash=None,
        resend_authorization_hash=F,
    )
    intent = _intent(permit, resend_authorization_hash=None)

    decision = _decision(permit, intent=intent)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_INTENT_RESEND_AUTH_MISMATCH" in decision.reason_codes


def test_first_generation_requires_explicit_predecessor_absence() -> None:
    permit = _permit(predecessor_absence_hash=None)

    decision = _decision(permit)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_FIRST_GENERATION_ABSENCE_PROOF_REQUIRED" in decision.reason_codes


def test_readiness_rejects_settlement_transport_tip_and_root_mismatch() -> None:
    permit = _permit()
    settlement = _settlement(
        permit,
        selected_transport="rpc",
        jito_tip_lamports=0,
        tip_account=None,
        rooted_finalized=False,
    )

    decision = _decision(permit, settlement=settlement)

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_SETTLEMENT_NOT_ROOTED_FINALIZED" in decision.reason_codes
    assert "MEGA_PR03_SETTLEMENT_TRANSPORT_MISMATCH" in decision.reason_codes
    assert "MEGA_PR03_SETTLEMENT_TIP_AMOUNT_MISMATCH" in decision.reason_codes


def test_live_runtime_and_legacy_paths_are_hard_blockers() -> None:
    permit = _permit()

    decision = _decision(
        permit,
        live_runtime_enabled=True,
        legacy_live_path_reachable=True,
    )

    assert decision.status is AuthorizationStatus.BLOCKED
    assert "MEGA_PR03_LIVE_RUNTIME_MUST_REMAIN_DEFAULT_OFF" in decision.reason_codes
    assert "MEGA_PR03_LEGACY_LIVE_PATH_REACHABLE" in decision.reason_codes
