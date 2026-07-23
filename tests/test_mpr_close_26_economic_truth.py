from __future__ import annotations

import pytest

from src.economic_truth_pr26 import (
    EconomicGateState,
    EconomicLineage,
    EconomicTruthBundle,
    FinalizedChainEconomics,
    InstructionAccount,
    InstructionFirewallPolicy,
    JitoEvidenceKind,
    JitoSettlementEvidence,
    LifecycleCostBreakdown,
    PaperEconomics,
    QuoteEconomics,
    ReportMetric,
    ReportMetricName,
    SettlementState,
    SimulationEconomics,
    TokenAccountDelta,
    evaluate_economic_truth_bundle,
    evaluate_instruction_firewall,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
ROUTE = "c" * 64
FINAL_SIM = DIGEST_A


def quote() -> QuoteEconomics:
    return QuoteEconomics(
        quote_id="quote-1",
        route_digest=ROUTE,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="TokenMint1111111111111111111111111111111111",
        input_amount_lamports=1_000_000,
        expected_output_lamports=1_010_000,
        quoted_profit_lamports=10_000,
        context_slot=100,
        expiry_slot=120,
        cost_budget=LifecycleCostBreakdown(
            network_fee_lamports=5_000,
            priority_fee_lamports=1_000,
            rent_lamports=2_039_280,
            ata_creation_lamports=2_039_280,
            wsol_wrap_lamports=1_000_000,
            flashloan_repayment_lamports=1_000_500,
            failed_attempt_lamports=5_000,
            retry_lamports=5_000,
        ),
    )


def simulation(message_digest: str = DIGEST_A) -> SimulationEconomics:
    return SimulationEconomics(
        simulation_id="sim-1",
        quote_id="quote-1",
        route_digest=ROUTE,
        message_digest=message_digest,
        final_simulation_digest=FINAL_SIM,
        blockhash="blockhash-1",
        context_slot=101,
        simulated_profit_lamports=3_000,
        cost_budget=LifecycleCostBreakdown(network_fee_lamports=5_000),
    )


def paper() -> PaperEconomics:
    return PaperEconomics(
        paper_outcome_id="paper-1",
        quote_id="quote-1",
        simulation_id="sim-1",
        message_digest=DIGEST_A,
        paper_estimated_net_lamports=2_500,
        lifecycle_costs=LifecycleCostBreakdown(
            network_fee_lamports=5_000,
            priority_fee_lamports=1_000,
            rent_lamports=2_039_280,
            ata_creation_lamports=2_039_280,
            wsol_wrap_lamports=1_000_000,
            flashloan_repayment_lamports=1_000_500,
            failed_attempt_lamports=5_000,
            retry_lamports=5_000,
        ),
    )


def finalized(message_digest: str = DIGEST_A) -> FinalizedChainEconomics:
    return FinalizedChainEconomics(
        signature="finalized-signature-1",
        message_digest=message_digest,
        finalized_slot=130,
        payer_pre_lamports=10_000_000,
        payer_post_lamports=10_002_500,
        network_fee_lamports=5_000,
        priority_fee_lamports=1_000,
        token_deltas=(
            TokenAccountDelta(
                mint="TokenMint1111111111111111111111111111111111",
                owner="payer111111111111111111111111111111111111",
                pre_amount_base_units=0,
                post_amount_base_units=42,
            ),
        ),
    )


def test_canonical_models_keep_quote_sim_paper_and_finalized_separate() -> None:
    q = quote()
    s = simulation()
    p = paper()
    f = finalized()

    assert q.to_dict()["schema"] == "quote_economics.v1"
    assert s.to_dict()["schema"] == "simulation_economics.v1"
    assert p.to_dict()["schema"] == "paper_economics.v1"
    assert f.to_dict()["schema"] == "finalized_chain_economics.v1"
    assert q.to_dict()["realized"] is False
    assert s.to_dict()["realized"] is False
    assert p.to_dict()["realized"] is False
    assert f.to_dict()["realized"] is True


def test_paper_outcome_cannot_be_realized_settlement() -> None:
    with pytest.raises(ValueError, match="paper economics must remain paper_estimated"):
        PaperEconomics(
            paper_outcome_id="paper-1",
            quote_id="quote-1",
            simulation_id="sim-1",
            message_digest=DIGEST_A,
            paper_estimated_net_lamports=1,
            terminal_state=SettlementState.FINALIZED,
        )


def test_finalized_realized_metric_requires_finalized_chain_proof() -> None:
    # Bypass the ReportMetric constructor with object.__new__ to verify the bundle
    # gate is still fail-closed if a legacy/deserialized row claims realized PnL.
    metric = object.__new__(ReportMetric)
    object.__setattr__(metric, "name", ReportMetricName.FINALIZED_REALIZED_PNL)
    object.__setattr__(metric, "value_lamports", 10)
    object.__setattr__(metric, "lineage", EconomicLineage.FINALIZED_ON_CHAIN)
    object.__setattr__(metric, "source_id", "legacy-row")
    object.__setattr__(metric, "bucket", None)

    assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(),
            paper=paper(),
            finalized=None,
            report_metrics=(metric,),
        )
    )

    assert assessment.state is EconomicGateState.BLOCKED
    assert "finalized_realized_pnl_without_finalized_settlement" in assessment.blockers
    assert assessment.finalized_realized_pnl_allowed is False


def test_lineage_quarantine_rejects_mixed_report_bucket() -> None:
    metrics = (
        ReportMetric(
            name=ReportMetricName.PAPER_PNL_ESTIMATED,
            value_lamports=2_500,
            lineage=EconomicLineage.PAPER_ESTIMATED,
            source_id="paper-1",
            bucket="combined_pnl",
        ),
        ReportMetric(
            name=ReportMetricName.SIMULATED_NET_EDGE,
            value_lamports=3_000,
            lineage=EconomicLineage.SIMULATED,
            source_id="sim-1",
            bucket="combined_pnl",
        ),
    )

    assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(),
            paper=paper(),
            report_metrics=metrics,
        )
    )

    assert assessment.state is EconomicGateState.BLOCKED
    assert "lineage_quarantine_mixed_report_bucket:combined_pnl" in assessment.blockers


def test_instruction_firewall_blocks_unknown_writable_signer_tip_and_mutation() -> None:
    policy = InstructionFirewallPolicy(
        expected_message_digest=DIGEST_A,
        final_simulation_message_digest=DIGEST_A,
        allowed_writable_accounts=frozenset({"payer"}),
        allowed_signer_accounts=frozenset({"payer"}),
        same_message_tip_accounts=frozenset({"jito-tip"}),
    )

    result = evaluate_instruction_firewall(
        (
            InstructionAccount("payer", is_writable=True, is_signer=True),
            InstructionAccount("unknown-vault", is_writable=True),
            InstructionAccount("unknown-signer", is_signer=True),
        ),
        policy,
        message_digest=DIGEST_A,
        compute_budget_mutated_after_final_simulation=True,
        hidden_tip_transfer_account="external-tip",
    )

    assert result.allowed is False
    assert "firewall_compute_budget_mutated_after_final_simulation" in result.blockers
    assert "firewall_hidden_tip_transfer_outside_same_message_policy" in result.blockers
    assert "firewall_unknown_writable_account:unknown-vault" in result.blockers
    assert "firewall_unknown_signer_account:unknown-signer" in result.blockers


def test_jito_ack_and_landed_are_transport_not_settlement() -> None:
    ack_assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(),
            jito=JitoSettlementEvidence(
                kind=JitoEvidenceKind.BUNDLE_LANDED,
                message_digest=DIGEST_A,
                bundle_id="bundle-1",
                claims_settlement=True,
            ),
        )
    )

    assert ack_assessment.state is EconomicGateState.BLOCKED
    assert "jito_transport_evidence_claims_settlement" in ack_assessment.blockers

    uncle_assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(),
            jito=JitoSettlementEvidence(
                kind=JitoEvidenceKind.UNCLE_REBROADCAST,
                message_digest=DIGEST_A,
                bundle_id="bundle-2",
            ),
        )
    )

    assert uncle_assessment.state is EconomicGateState.BLOCKED
    assert (
        "jito_uncle_rebroadcast_requires_fail_closed_classification"
        in uncle_assessment.blockers
    )


def test_ready_bundle_allows_finalized_realized_pnl_only_with_exact_binding() -> None:
    metrics = (
        ReportMetric(
            name=ReportMetricName.PAPER_PNL_ESTIMATED,
            value_lamports=2_500,
            lineage=EconomicLineage.PAPER_ESTIMATED,
            source_id="paper-1",
        ),
        ReportMetric(
            name=ReportMetricName.SIMULATED_NET_EDGE,
            value_lamports=3_000,
            lineage=EconomicLineage.SIMULATED,
            source_id="sim-1",
        ),
        ReportMetric(
            name=ReportMetricName.FINALIZED_REALIZED_PNL,
            value_lamports=-3_500,
            lineage=EconomicLineage.FINALIZED_ON_CHAIN,
            source_id="finalized-signature-1",
        ),
    )
    firewall = evaluate_instruction_firewall(
        (InstructionAccount("payer", is_writable=True, is_signer=True),),
        InstructionFirewallPolicy(
            expected_message_digest=DIGEST_A,
            final_simulation_message_digest=DIGEST_A,
            allowed_writable_accounts=frozenset({"payer"}),
            allowed_signer_accounts=frozenset({"payer"}),
        ),
        message_digest=DIGEST_A,
    )

    assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(),
            paper=paper(),
            finalized=finalized(),
            firewall=firewall,
            jito=JitoSettlementEvidence(
                kind=JitoEvidenceKind.FINALIZED_TRANSACTION,
                message_digest=DIGEST_A,
                finalized_signature="finalized-signature-1",
            ),
            report_metrics=metrics,
        )
    )

    assert assessment.state is EconomicGateState.READY
    assert assessment.blockers == ()
    assert assessment.finalized_realized_pnl_allowed is True
    assert sorted(assessment.reports) == [
        "finalized_realized_pnl",
        "paper_pnl_estimated",
        "simulated_net_edge",
    ]


def test_message_mutation_after_final_simulation_blocks_settlement_claim() -> None:
    assessment = evaluate_economic_truth_bundle(
        EconomicTruthBundle(
            quote=quote(),
            simulation=simulation(message_digest=DIGEST_B),
            finalized=finalized(message_digest=DIGEST_B),
        )
    )

    assert assessment.state is EconomicGateState.BLOCKED
    assert "simulation_message_mutated_after_final_simulation" in assessment.blockers
