from __future__ import annotations

import json

from src.economic_authority_super_mpr_b import (
    DurableCapitalLedger,
    EconomicAuthoritySnapshot,
    EconomicEvent,
    EconomicIdentity,
    EvidenceKind,
    PaperAccounting,
    assert_net_paper_profit,
    build_shadow_soak_report,
    evaluate_super_mpr_b_evidence,
    validate_economic_authority_snapshot,
    validate_shadow_soak_report,
)


def _event(state: str, index: int) -> EconomicEvent:
    return EconomicEvent(
        state=state,
        event_digest=f"sha256:{index:064x}",
        observed_at_unix_ns=1_000 + index,
        reason=f"state_{state.lower()}",
    )


def test_economic_state_machine_all_transitions() -> None:
    identity = EconomicIdentity.derive(
        run_trace_id="trace-super-mpr-b",
        opportunity_payload={"pair": "SOL/USDC", "slot": 123},
    )
    snapshot = EconomicAuthoritySnapshot(
        schema_version="super-mpr-b.economic-authority.v1",
        identity=identity,
        current_state="RECONCILED",
        events=(
            _event("DISCOVERED", 1),
            _event("NORMALIZED", 2),
            _event("ADMITTED", 3),
            _event("RESERVED", 4),
            _event("SIMULATED", 5),
            _event("PAPER_FILLED", 6),
            _event("PAPER_SETTLED", 7),
            _event("RECONCILED", 8),
        ),
        evidence_kind=EvidenceKind.REAL.value,
    )

    assert validate_economic_authority_snapshot(snapshot.to_dict()) == ()


def test_capital_reservation_single_use_and_restart_recovery(tmp_path) -> None:
    ledger_path = tmp_path / "capital-ledger.json"
    ledger = DurableCapitalLedger(ledger_path)

    record = ledger.reserve(
        reservation_id="res-1",
        opportunity_id="opp-1",
        amount_lamports=1_000,
        expires_at_unix_ns=10_000,
        request_payload={"route": "a", "amount": 1_000},
        now_unix_ns=1,
    )
    assert record.state == "RESERVED"
    assert ledger.active_reserved_lamports() == 1_000

    restarted = DurableCapitalLedger(ledger_path)
    same = restarted.reserve(
        reservation_id="res-1",
        opportunity_id="opp-1",
        amount_lamports=1_000,
        expires_at_unix_ns=10_000,
        request_payload={"route": "a", "amount": 1_000},
        now_unix_ns=2,
    )
    assert same.request_digest == record.request_digest
    assert restarted.active_reserved_lamports() == 1_000

    assert restarted.reconcile_expired(now_unix_ns=10_001) == ("res-1",)
    assert DurableCapitalLedger(ledger_path).active_reserved_lamports() == 0


def test_capital_reservation_rejects_replay_conflict(tmp_path) -> None:
    ledger = DurableCapitalLedger(tmp_path / "capital-ledger.json")
    ledger.reserve(
        reservation_id="res-1",
        opportunity_id="opp-1",
        amount_lamports=1_000,
        expires_at_unix_ns=10_000,
        request_payload={"route": "a"},
    )

    try:
        ledger.reserve(
            reservation_id="res-1",
            opportunity_id="opp-1",
            amount_lamports=1_000,
            expires_at_unix_ns=10_000,
            request_payload={"route": "mutated"},
        )
    except ValueError as exc:
        assert "reservation replay conflict" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("replay conflict was accepted")


def test_paper_pnl_includes_fee_rent_wsol_repayment() -> None:
    accounting = PaperAccounting(
        estimated_swap_output_lamports=1_060,
        gross_input_lamports=1_000,
        slippage_lamports=10,
        network_fee_lamports=5,
        priority_fee_lamports=5,
        ata_rent_lamports=10,
        wsol_lifecycle_lamports=5,
        flashloan_repayment_lamports=20,
        borrow_repay_fee_lamports=10,
        provider_drift_lamports=5,
        quote_expiry_cost_lamports=0,
        failed_attempt_cost_lamports=0,
    )

    assert accounting.gross_pnl_lamports == 60
    assert accounting.total_cost_lamports == 70
    assert accounting.net_pnl_lamports == -10
    assert assert_net_paper_profit(accounting) is False


def test_shadow_soak_report_schema() -> None:
    report = build_shadow_soak_report(
        runtime_version="test",
        wheel_digest="sha256:wheel",
        config_digest="sha256:config",
        provider_set=("helius",),
        rpc_set=("rpc-a",),
        opportunities_seen=1,
        opportunities_rejected_by_reason={"risk": 1},
        opportunities_admitted=0,
        paper_simulations=0,
        paper_settlements=0,
        expired_quotes=0,
        provider_errors=0,
        rpc_errors=0,
        restart_count=1,
        recovery_count=1,
        capital_ledger_reconciled=True,
        max_drawdown_paper=0,
        gross_pnl_paper=0,
        net_pnl_paper=0,
        fee_rent_repayment_impact=0,
    )

    assert validate_shadow_soak_report(report) == ()


def test_synthetic_evidence_cannot_promote_paper_ready(tmp_path) -> None:
    release_dir = tmp_path / "release_artifacts"
    release_dir.mkdir()
    bundle = {
        "schema_version": "super-mpr-b.evidence-bundle.v1",
        "evidence_kind": "synthetic",
        "shadow_soak_report": {},
        "economic_authority": {},
        "fault_injection": {"covered": []},
        "backup_restore": {"restore_verified": False},
    }
    (release_dir / "super_mpr_b_evidence.json").write_text(
        json.dumps(bundle),
        encoding="utf-8",
    )

    report = evaluate_super_mpr_b_evidence(tmp_path)

    assert report["accepted"] is False
    assert "SYNTHETIC_EVIDENCE_CANNOT_PROMOTE" in report["blockers"]
    assert any(str(item).startswith("RELEASE_ARTIFACT_MISSING") for item in report["blockers"])


def test_missing_evidence_artifact_is_a_blocker(tmp_path) -> None:
    report = evaluate_super_mpr_b_evidence(tmp_path)

    assert report["accepted"] is False
    assert report["blockers"] == ("SUPER_MPR_B_EVIDENCE_MISSING",)
