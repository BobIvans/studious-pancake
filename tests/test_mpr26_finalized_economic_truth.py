from __future__ import annotations

from dataclasses import replace

import pytest

from src.mpr26_finalized_economic_truth import (
    EconomicLayer,
    Lineage,
    MPR26State,
    SettlementStatus,
    evaluate_mpr26_evidence,
    sample_ready_evidence,
)


def _codes(report: object) -> set[str]:
    return {blocker.code for blocker in report.blockers}  # type: ignore[attr-defined]


def test_ready_foundation_keeps_live_and_realized_pnl_disabled() -> None:
    report = evaluate_mpr26_evidence(sample_ready_evidence())

    assert report.schema_version == "mpr26.finalized-economic-truth.v1"
    assert report.state is MPR26State.READY_FOR_FOUNDATION
    assert report.blockers == ()
    assert report.layers_present == (
        "finalized_realized",
        "paper_estimated",
        "quoted",
        "simulated",
    )
    assert report.paper_pnl_estimated_only is True
    assert report.realized_pnl_allowed is False
    assert report.live_execution_allowed is False


def test_paper_cannot_claim_realized_pnl() -> None:
    evidence = sample_ready_evidence()
    paper = next(
        item for item in evidence.observations if item.layer is EconomicLayer.PAPER_ESTIMATED
    )

    with pytest.raises(ValueError, match="MPR26_NON_FINALIZED_REALIZED_CLAIM"):
        replace(paper, realized_claimed=True)


def test_fixture_lineage_cannot_promote_paper_or_finalized_economics() -> None:
    evidence = sample_ready_evidence()
    observations = tuple(
        replace(item, lineage=Lineage.RECORDED_PROVIDER_FIXTURE)
        if item.layer is EconomicLayer.PAPER_ESTIMATED
        else item
        for item in evidence.observations
    )
    report = evaluate_mpr26_evidence(replace(evidence, observations=observations))

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_FIXTURE_PROMOTION_FORBIDDEN" in _codes(report)


def test_realized_economics_require_finalized_settlement_and_message_match() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr26_evidence(
        replace(
            evidence,
            settlement=replace(
                evidence.settlement,
                settlement_status=SettlementStatus.LANDED,
                exact_message_hash="e" * 64,
                landed_used_as_success=True,
            ),
        )
    )

    codes = _codes(report)
    assert report.state is MPR26State.BLOCKED
    assert "MPR26_REALIZED_WITHOUT_FINALITY" in codes
    assert "MPR26_FINALIZED_MESSAGE_HASH_MISMATCH" in codes
    assert "MPR26_LANDED_USED_AS_FINAL_ECONOMICS" in codes


def test_ack_or_bundle_id_cannot_be_settlement() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr26_evidence(
        replace(
            evidence,
            settlement=replace(evidence.settlement, ack_or_bundle_id_used_as_success=True),
        )
    )

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_ACK_USED_AS_SETTLEMENT" in _codes(report)


def test_instruction_firewall_is_required() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr26_evidence(
        replace(
            evidence,
            firewall=replace(
                evidence.firewall,
                no_unknown_writable_accounts=False,
                no_hidden_tip_transfer=False,
            ),
        )
    )

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_INSTRUCTION_FIREWALL_INCOMPLETE" in _codes(report)


def test_jito_semantics_fail_closed() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr26_evidence(
        replace(
            evidence,
            jito=replace(
                evidence.jito,
                bundle_ack_transport_only=False,
                bundle_landed_not_final_economics=False,
                uncle_rebroadcast_classified=False,
            ),
        )
    )

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_JITO_SEMANTICS_INCOMPLETE" in _codes(report)


def test_lineage_quarantine_policy_is_required() -> None:
    evidence = sample_ready_evidence()
    report = evaluate_mpr26_evidence(
        replace(
            evidence,
            lineage_policy=replace(
                evidence.lineage_policy,
                metrics_lineage_label_required=False,
                paper_and_realized_pnl_separated=False,
            ),
        )
    )

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_LINEAGE_QUARANTINE_INCOMPLETE" in _codes(report)


def test_unrestricted_live_is_forbidden() -> None:
    report = evaluate_mpr26_evidence(
        replace(sample_ready_evidence(), unrestricted_live_available=True)
    )

    assert report.state is MPR26State.BLOCKED
    assert "MPR26_UNRESTRICTED_LIVE_FORBIDDEN" in _codes(report)
    assert report.live_execution_allowed is False
