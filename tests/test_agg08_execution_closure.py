from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.execution.core_v1_finalized_settlement import CoreV1FinalizedCommit
from src.execution.finalized_economic_ledger import (
    AttemptEconomicLineage,
    FinalizedEconomicLedger,
    FinalizedEconomicOutcome,
)
from src.live_boundary.agg08_execution_closure import (
    AGG08_COMPILE_TIME_LIVE_ENABLED,
    Agg08Error,
    Agg08ExecutionGate,
    AuthorizationRecord,
    CanaryReservationEvidence,
    CoverageStatus,
    ExecutionProfile,
    FreshExecutionEvidence,
    agg08_static_coverage,
    build_submission_permit_request,
    finalized_landing_label,
)
from src.live_boundary.pr202_isolated_signer_settlement import (
    IsolatedSignerBoundaryEvidence,
    ReviewedPermit,
    TransportKind as ReviewedTransportKind,
)
from src.live_canary.models import CanaryMode, CanaryReport
from src.submission.permit_bound import TransportKind

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64
G = "1" * 64
H = "2" * 64
SIG = "5" * 88
NOW = 1_800_000_000_000


def _profile(**overrides: object) -> ExecutionProfile:
    values: dict[str, object] = {
        "profile_id": "agg08-canary-v1",
        "generation": 8,
        "qualification_hash": A,
        "release_hash": B,
        "config_hash": C,
        "policy_hash": D,
        "risk_budget_hash": H,
        "cluster_genesis_hash": E,
        "wallet_pubkey": "wallet111111111111111111111111111111111",
        "asset_ids": ("native:SOL:lamports", "spl:USDC:6"),
        "program_ids": ("program-jupiter", "program-slumlord"),
        "financing_ids": ("jupiter_lend", "slumlord"),
        "route_ids": ("rpc-main",),
        "transport": TransportKind.RPC,
        "max_principal_base_units": 1_000_000,
        "max_native_debit_lamports": 100_000,
        "max_tip_lamports": 0,
        "failure_budget_lamports": 100_000,
        "expires_at_ms": NOW + 60_000,
    }
    values.update(overrides)
    return ExecutionProfile(**values)  # type: ignore[arg-type]


def _auth(profile: ExecutionProfile, **overrides: object) -> AuthorizationRecord:
    values: dict[str, object] = {
        "authorization_id": "auth-agg08",
        "actor_id": "human-operator",
        "source_reference": "release-authority:review-1",
        "profile_hash": profile.profile_hash,
        "qualification_hash": profile.qualification_hash,
        "release_hash": profile.release_hash,
        "risk_budget_hash": profile.risk_budget_hash,
        "reviewer_hash": A,
        "wallet_pubkey": profile.wallet_pubkey,
        "cluster_genesis_hash": profile.cluster_genesis_hash,
        "maximum_native_debit_lamports": 100_000,
        "issued_at_ms": NOW - 1_000,
        "expires_at_ms": NOW + 30_000,
        "allow_sign": True,
        "allow_submit": True,
    }
    values.update(overrides)
    return AuthorizationRecord(**values)  # type: ignore[arg-type]


def _permit(profile: ExecutionProfile, **overrides: object) -> ReviewedPermit:
    values: dict[str, object] = {
        "permit_id": "permit-agg08",
        "release_hash": profile.release_hash,
        "config_hash": profile.config_hash,
        "policy_hash": profile.policy_hash,
        "attempt_id": "attempt-agg08",
        "plan_hash": F,
        "message_hash": G,
        "blockhash": "1" * 32,
        "transport": ReviewedTransportKind.RPC_SINGLE,
        "tip_lamports": 0,
        "risk_budget_hash": profile.risk_budget_hash,
        "boot_generation": 4,
        "issued_at_ms": NOW - 500,
        "expires_at_ms": NOW + 20_000,
        "signer_service_id": "signer-primary",
        "reviewer_hash": A,
    }
    values.update(overrides)
    return ReviewedPermit(**values)  # type: ignore[arg-type]


def _signer(
    profile: ExecutionProfile,
    **overrides: object,
) -> IsolatedSignerBoundaryEvidence:
    values: dict[str, object] = {
        "signer_service_id": "signer-primary",
        "image_digest": f"signer@sha256:{A}",
        "release_hash": profile.release_hash,
        "separate_process": True,
        "separate_container": True,
        "narrow_ipc": True,
        "key_never_enters_main_runtime": True,
        "key_not_in_logs": True,
        "key_not_in_files": True,
        "deny_by_default_egress": True,
        "no_general_network_access": True,
        "no_unreviewed_signing_method": True,
        "secret_rotation_drill_hash": B,
        "compromise_drill_hash": C,
        "break_glass_policy_hash": D,
    }
    values.update(overrides)
    return IsolatedSignerBoundaryEvidence(**values)  # type: ignore[arg-type]


def _report(profile: ExecutionProfile, **overrides: object) -> CanaryReport:
    values: dict[str, object] = {
        "schema_version": "pr046.canary-report.v1",
        "policy_hash": profile.policy_hash,
        "evidence_hash": profile.qualification_hash,
        "mode": CanaryMode.LIMITED_LIVE,
        "armed": True,
        "armed_until_ms": NOW + 20_000,
        "outstanding_attempt_id": "attempt-agg08",
        "active_latches": (),
        "daily_realized_pnl_lamports": 0,
        "consecutive_failures": 0,
        "event_count": 3,
        "event_digest": E,
        "ai_authority": False,
    }
    values.update(overrides)
    return CanaryReport(**values)  # type: ignore[arg-type]


def _reservation(**overrides: object) -> CanaryReservationEvidence:
    values: dict[str, object] = {
        "attempt_id": "attempt-agg08",
        "message_hash": G,
        "candidate_hash": C,
        "reserved_at_ms": NOW - 200,
    }
    values.update(overrides)
    return CanaryReservationEvidence(**values)  # type: ignore[arg-type]


def _fresh(profile: ExecutionProfile, **overrides: object) -> FreshExecutionEvidence:
    values: dict[str, object] = {
        "attempt_id": "attempt-agg08",
        "profile_generation": profile.generation,
        "qualification_hash": profile.qualification_hash,
        "release_hash": profile.release_hash,
        "config_hash": profile.config_hash,
        "policy_hash": profile.policy_hash,
        "risk_budget_hash": profile.risk_budget_hash,
        "cluster_genesis_hash": profile.cluster_genesis_hash,
        "wallet_pubkey": profile.wallet_pubkey,
        "asset_ids": ("native:SOL:lamports", "spl:USDC:6"),
        "program_ids": ("program-jupiter", "program-slumlord"),
        "financing_ids": ("jupiter_lend", "slumlord"),
        "route_id": "rpc-main",
        "candidate_hash": C,
        "plan_hash": F,
        "state_frame_hash": A,
        "message_hash": G,
        "exact_simulation_hash": G,
        "blockhash": "1" * 32,
        "repayment_evidence_hash": B,
        "principal_base_units": 500_000,
        "failure_cost_lamports": 10_000,
        "available_native_lamports": 1_000_000,
        "other_active_reserved_lamports": 200_000,
        "reserved_for_attempt_lamports": 50_000,
        "requested_native_debit_lamports": 50_000,
        "tip_lamports": 0,
        "observed_at_ms": NOW - 100,
        "expires_at_ms": NOW + 5_000,
    }
    values.update(overrides)
    return FreshExecutionEvidence(**values)  # type: ignore[arg-type]


def _admit(
    *,
    gate_enabled: bool,
    profile: ExecutionProfile | None = None,
    **fresh: object,
):
    profile = profile or _profile()
    return Agg08ExecutionGate(effect_gate_enabled=gate_enabled).admit_pre_sign(
        profile=profile,
        authorization=_auth(profile),
        permit=_permit(profile),
        signer_boundary=_signer(profile),
        canary_report=_report(profile),
        canary_reservation=_reservation(),
        evidence=_fresh(profile, **fresh),
        now_ms=NOW,
    )


def test_agg08_is_compile_time_default_off() -> None:
    assert AGG08_COMPILE_TIME_LIVE_ENABLED is False
    decision = _admit(gate_enabled=False)
    assert decision.accepted is False
    assert "AGG08_EFFECT_GATE_CLOSED" in decision.blockers


def test_exact_bound_fixture_passes_only_with_explicit_test_gate() -> None:
    decision = _admit(gate_enabled=True)
    assert decision.accepted is True
    assert decision.blockers == ()


@pytest.mark.parametrize(
    ("fresh", "blocker"),
    [
        ({"exact_simulation_hash": H}, "AGG08_MESSAGE_NOT_EXACT_SIMULATION"),
        ({"profile_generation": 9}, "AGG08_PROFILE_GENERATION_STALE"),
        ({"kill_switch_active": True}, "AGG08_KILL_SWITCH_ACTIVE"),
        (
            {"unresolved_attempt_ids": ("older-unknown",)},
            "AGG08_UNRESOLVED_OUTCOME_PRESENT",
        ),
        (
            {
                "requested_native_debit_lamports": 100_001,
                "reserved_for_attempt_lamports": 100_001,
            },
            "AGG08_PROFILE_NATIVE_DEBIT_CAP",
        ),
        ({"blockhash": "2" * 32}, "AGG08_PERMIT_BLOCKHASH_MISMATCH"),
        ({"principal_base_units": 1_000_001}, "AGG08_PRINCIPAL_CAP"),
        ({"failure_cost_lamports": 100_001}, "AGG08_FAILURE_BUDGET_CAP"),
    ],
)
def test_effect_adjacent_recheck_fails_closed(
    fresh: dict[str, object],
    blocker: str,
) -> None:
    decision = _admit(gate_enabled=True, **fresh)
    assert decision.accepted is False
    assert blocker in decision.blockers


def test_slumlord_is_a_required_financing_dependency() -> None:
    profile = _profile(financing_ids=("jupiter_lend",))
    decision = _admit(gate_enabled=True, profile=profile)
    assert decision.accepted is False
    blocker = "AGG08_REQUIRED_FINANCING_NOT_QUALIFIED:slumlord"
    assert blocker in decision.blockers


def test_global_slumlord_requirement_cannot_be_removed() -> None:
    with pytest.raises(
        Agg08Error,
        match="AGG08_GLOBAL_FINANCING_REQUIREMENT_REMOVED",
    ):
        _profile(
            financing_ids=("jupiter_lend",),
            required_financing_ids=("jupiter_lend",),
        )


def test_canary_reservation_is_bound_to_message_and_candidate() -> None:
    profile = _profile()
    gate = Agg08ExecutionGate(effect_gate_enabled=True)

    message_mismatch = gate.admit_pre_sign(
        profile=profile,
        authorization=_auth(profile),
        permit=_permit(profile),
        signer_boundary=_signer(profile),
        canary_report=_report(profile),
        canary_reservation=_reservation(message_hash=H),
        evidence=_fresh(profile),
        now_ms=NOW,
    )
    assert "AGG08_RESERVATION_MESSAGE_MISMATCH" in message_mismatch.blockers

    candidate_mismatch = gate.admit_pre_sign(
        profile=profile,
        authorization=_auth(profile),
        permit=_permit(profile),
        signer_boundary=_signer(profile),
        canary_report=_report(profile),
        canary_reservation=_reservation(candidate_hash=H),
        evidence=_fresh(profile),
        now_ms=NOW,
    )
    assert "AGG08_RESERVATION_CANDIDATE_MISMATCH" in candidate_mismatch.blockers


def test_expired_canary_arm_is_rejected() -> None:
    profile = _profile()
    decision = Agg08ExecutionGate(effect_gate_enabled=True).admit_pre_sign(
        profile=profile,
        authorization=_auth(profile),
        permit=_permit(profile),
        signer_boundary=_signer(profile),
        canary_report=_report(profile, armed_until_ms=NOW),
        canary_reservation=_reservation(),
        evidence=_fresh(profile),
        now_ms=NOW,
    )
    assert "AGG08_CANARY_ARM_EXPIRED" in decision.blockers


@dataclass(frozen=True)
class _FakeTip:
    lamports: int
    evidence_hash: str


@dataclass(frozen=True)
class _FakeSignedPayload:
    primary_message_hash: str
    payload_digest: str
    message_hashes: tuple[str, ...]
    transaction_digests: tuple[str, ...]
    signatures: tuple[str, ...]
    tip_evidence: _FakeTip | None = None


def test_post_sign_bridge_reuses_submission_permit_contract() -> None:
    profile = _profile()
    reviewed = _permit(profile)
    decision = _admit(gate_enabled=True, profile=profile)
    payload = _FakeSignedPayload(
        primary_message_hash=G,
        payload_digest=A,
        message_hashes=(G,),
        transaction_digests=(B,),
        signatures=(SIG,),
    )
    request = build_submission_permit_request(
        admission=decision,
        reviewed_permit=reviewed,
        signed_payload=payload,  # type: ignore[arg-type]
        exact_simulation_hash=G,
        now_ms=NOW,
        expires_at_ns=(NOW + 4_000) * 1_000_000,
        last_valid_block_height=123,
        min_context_slot=100,
    )
    assert request.transport is TransportKind.RPC
    assert request.message_hash == G
    assert request.expected_signatures == (SIG,)


def test_post_sign_bridge_rejects_expired_admission() -> None:
    profile = _profile()
    reviewed = _permit(profile)
    decision = _admit(gate_enabled=True, profile=profile)
    payload = _FakeSignedPayload(
        primary_message_hash=G,
        payload_digest=A,
        message_hashes=(G,),
        transaction_digests=(B,),
        signatures=(SIG,),
    )
    with pytest.raises(Agg08Error, match="AGG08_ADMISSION_EXPIRED"):
        build_submission_permit_request(
            admission=decision,
            reviewed_permit=reviewed,
            signed_payload=payload,  # type: ignore[arg-type]
            exact_simulation_hash=G,
            now_ms=decision.expires_at_ms,
            expires_at_ns=decision.expires_at_ms * 1_000_000,
            last_valid_block_height=123,
            min_context_slot=100,
        )


def test_multi_transaction_jito_bundle_requires_separate_review() -> None:
    profile = _profile(
        transport=TransportKind.JITO_BUNDLE,
        route_ids=("jito-main",),
        max_tip_lamports=1_000,
    )
    reviewed = _permit(
        profile,
        transport=ReviewedTransportKind.JITO_BUNDLE,
        tip_lamports=100,
    )
    evidence = _fresh(
        profile,
        route_id="jito-main",
        tip_lamports=100,
    )
    decision = Agg08ExecutionGate(effect_gate_enabled=True).admit_pre_sign(
        profile=profile,
        authorization=_auth(profile),
        permit=reviewed,
        signer_boundary=_signer(profile),
        canary_report=_report(profile),
        canary_reservation=_reservation(),
        evidence=evidence,
        now_ms=NOW,
    )
    assert decision.accepted is True

    payload = _FakeSignedPayload(
        primary_message_hash=G,
        payload_digest=A,
        message_hashes=(G, H),
        transaction_digests=(B, C),
        signatures=(SIG, "6" * 88),
        tip_evidence=_FakeTip(lamports=100, evidence_hash=D),
    )
    with pytest.raises(
        Agg08Error,
        match="AGG08_MULTI_TX_BUNDLE_REQUIRES_SEPARATE_REVIEW",
    ):
        build_submission_permit_request(
            admission=decision,
            reviewed_permit=reviewed,
            signed_payload=payload,  # type: ignore[arg-type]
            exact_simulation_hash=G,
            now_ms=NOW,
            expires_at_ns=(NOW + 10_000) * 1_000_000,
            last_valid_block_height=123,
            min_context_slot=100,
        )


def _commit(outcome: FinalizedEconomicOutcome) -> CoreV1FinalizedCommit:
    lineage = AttemptEconomicLineage(
        attempt_id="attempt-agg08",
        attempt_generation=1,
        message_hash=G,
        signed_transaction_digest=B,
        primary_signature=SIG,
        finalized_slot=555,
        release_hash=C,
        config_hash=D,
        policy_hash=E,
        cluster_genesis_hash=F,
        raw_evidence_hash=A,
    )
    ledger = FinalizedEconomicLedger(
        schema_version="mpr2610.finalized-economic-ledger.v1",
        lineage=lineage,
        outcome=outcome,
        economically_successful=(
            outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT
        ),
        per_asset_delta=(("spl:USDC:6", 1),),
        blockers=(),
        ledger_hash=H,
    )
    quarantined = outcome in {
        FinalizedEconomicOutcome.UNKNOWN_QUARANTINED,
        FinalizedEconomicOutcome.FINALIZED_PENDING_ECONOMICS,
    }
    return CoreV1FinalizedCommit(
        schema_version="core-v1.finalized-settlement-producer.v1",
        decoder_identity="decoder-v1",
        source_hash=A,
        ledger=ledger,
        release_capital=not quarantined,
        quarantine_capital=quarantined,
    )


def test_landing_label_is_finalized_actual_not_simulation() -> None:
    label = finalized_landing_label(
        _commit(FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT)
    )
    assert label.landed_finalized is True
    assert label.attempt_id == "attempt-agg08"
    assert label.economically_successful is True


@pytest.mark.parametrize(
    "outcome",
    [
        FinalizedEconomicOutcome.UNKNOWN_QUARANTINED,
        FinalizedEconomicOutcome.FINALIZED_PENDING_ECONOMICS,
    ],
)
def test_unknown_or_incomplete_finality_never_becomes_landing_label(
    outcome: FinalizedEconomicOutcome,
) -> None:
    expected = "AGG08_FINALIZED_TERMINAL_ECONOMICS_REQUIRED"
    with pytest.raises(Agg08Error, match=expected):
        finalized_landing_label(_commit(outcome))


def test_static_coverage_contains_all_21_agg08_nf_cards() -> None:
    rows = agg08_static_coverage()
    assert len(rows) == 21
    assert {row.nf for row in rows} == {
        "NF-194",
        "NF-195",
        "NF-196",
        "NF-198",
        "NF-199",
        "NF-200",
        "NF-201",
        "NF-202",
        "NF-203",
        "NF-204",
        "NF-205",
        "NF-206",
        "NF-207",
        "NF-208",
        "NF-209",
        "NF-210",
        "NF-211",
        "NF-212",
        "NF-213",
        "NF-214",
        "NF-215",
    }
    assert any(
        row.status is CoverageStatus.BLOCKED_PREREQUISITE for row in rows
    )
