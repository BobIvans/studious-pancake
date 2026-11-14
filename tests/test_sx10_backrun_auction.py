"""SX-10 permitted-backrun auction replay tests (deterministic, offline)."""

from __future__ import annotations

import pytest

from src.strategy_evolution.backrun_auction_replay import (
    CostLedger,
    FlowAuthorization,
    InclusionCalibration,
    PolicyViolation,
    SettlementOutcome,
    SettlementRecord,
    TxEvent,
    expected_value_atoms,
    realized_settlement_cost_atoms,
    replay_permitted_backrun_auction,
)
from src.strategy_evolution.core import EvolutionError

CANDIDATE_COST = CostLedger(
    priority_fee_tip_atoms=1_000,
    compute_budget_units=200_000,
    revert_cost_atoms=500,
)


def _writer_tx(tx_id: str = "tx-swap", slot: int = 10) -> TxEvent:
    return TxEvent(
        tx_id=tx_id,
        slot=slot,
        reads=("pool:base",),
        writes=("pool:quote",),
        flow_authorization=FlowAuthorization.PUBLIC_ORDERFLOW,
    )


def _candidate_tx(
    tx_id: str = "tx-backrun",
    slot: int = 10,
    flow_authorization: FlowAuthorization = FlowAuthorization.PUBLIC_ORDERFLOW,
    observed_versions: tuple[tuple[str, int], ...] = (("pool:quote", 1),),
) -> TxEvent:
    return TxEvent(
        tx_id=tx_id,
        slot=slot,
        reads=("pool:quote",),
        writes=(),
        flow_authorization=flow_authorization,
        protocol_permitted_backrun=True,
        observed_versions=observed_versions,
        cost=CANDIDATE_COST,
    )


def test_ordered_stream_replays_deterministically() -> None:
    events = (_writer_tx(), _candidate_tx())
    first = replay_permitted_backrun_auction(events)
    second = replay_permitted_backrun_auction(events)
    assert first == second
    assert first.evidence_hash == second.evidence_hash
    assert first.event_count == 2
    assert first.slot_count == 1
    assert len(first.candidates) == 1
    assert first.exclusions == ()
    assert first.blockers == ()
    # only written resources carry version counters; pool:base is read-only context
    assert first.final_resource_versions == (("pool:quote", 1),)


def test_dependency_detection_is_exact_and_same_slot_only() -> None:
    events = (
        _writer_tx(slot=10),
        _candidate_tx(slot=10),
        _writer_tx(tx_id="tx-cross-slot", slot=11),
    )
    report = replay_permitted_backrun_auction(events)
    assert len(report.candidates) == 1
    dependency = report.candidates[0].dependencies[0]
    assert dependency.resource == "pool:quote"
    assert dependency.writer_tx_id == "tx-swap"
    assert dependency.writer_index == 0
    assert dependency.version_before == 0
    assert dependency.version_after == 1

    late_candidate = _candidate_tx(
        tx_id="tx-backrun-late",
        slot=12,
        observed_versions=(("pool:quote", 1),),
    )
    cross_stream = (
        _writer_tx(tx_id="tx-early-writer", slot=9),
        late_candidate,
    )
    cross_report = replay_permitted_backrun_auction(cross_stream)
    assert cross_report.candidates == ()
    assert [exclusion.code for exclusion in cross_report.exclusions] == [
        "dependency_absent"
    ]


def test_stale_dependency_excluded_with_typed_reason() -> None:
    stale_candidate = _candidate_tx(observed_versions=(("pool:quote", 0),))
    report = replay_permitted_backrun_auction((_writer_tx(), stale_candidate))
    assert report.candidates == ()
    assert [exclusion.code for exclusion in report.exclusions] == [
        "state_dependency_stale"
    ]
    assert "expected_version=1" in report.exclusions[0].detail
    assert "observed_version=0" in report.exclusions[0].detail


def test_unauthorized_flow_yields_no_candidates_and_typed_blocker() -> None:
    events = (
        _writer_tx(),
        _candidate_tx(flow_authorization=FlowAuthorization.UNKNOWN),
    )
    report = replay_permitted_backrun_auction(events)
    assert report.candidates == ()
    assert [blocker.code for blocker in report.blockers] == [
        "flow_authorization_unproven"
    ]
    assert "tx=tx-backrun" in report.blockers[0].detail
    assert [exclusion.code for exclusion in report.exclusions] == [
        "flow_authorization_unproven"
    ]


def test_policy_violation_on_prohibited_or_unpermitted_input() -> None:
    sandwiched = (
        _writer_tx(),
        _candidate_tx(),
        TxEvent(
            tx_id="tx-sandwich",
            slot=10,
            reads=(),
            writes=(),
            flow_authorization=FlowAuthorization.UNKNOWN,
            prohibited_patterns=("SANDWICH",),
        ),
    )
    with pytest.raises(PolicyViolation, match="PROHIBITED_MEV_PATTERN"):
        replay_permitted_backrun_auction(sandwiched)

    unpermitted = (
        _writer_tx(),
        TxEvent(
            tx_id="tx-attempt",
            slot=10,
            reads=("pool:quote",),
            writes=(),
            flow_authorization=FlowAuthorization.PUBLIC_ORDERFLOW,
            backrun_attempt=True,
            protocol_permitted_backrun=False,
        ),
    )
    with pytest.raises(PolicyViolation, match="BACKRUN_NOT_PROTOCOL_PERMITTED"):
        replay_permitted_backrun_auction(unpermitted)


def test_uncalibrated_probability_blocks_expected_value() -> None:
    events = (_writer_tx(), _candidate_tx())

    uncalibrated = replay_permitted_backrun_auction(events)
    candidate = uncalibrated.candidates[0]
    assert candidate.inclusion_probability_ppm is None
    assert candidate.calibration_attempts_observed is None
    assert [blocker.code for blocker in candidate.blockers] == [
        "inclusion_probability_uncalibrated"
    ]
    with pytest.raises(EvolutionError, match="INCLUSION_PROBABILITY_UNCALIBRATED"):
        expected_value_atoms(
            candidate, gross_value_atoms=10_000, compute_cost_atoms=500
        )

    insufficient = replay_permitted_backrun_auction(
        events,
        calibration=InclusionCalibration(attempts_observed=5, inclusions_observed=1),
    )
    assert [blocker.code for blocker in insufficient.candidates[0].blockers] == [
        "inclusion_probability_uncalibrated"
    ]

    calibrated = replay_permitted_backrun_auction(
        events,
        calibration=InclusionCalibration(attempts_observed=120, inclusions_observed=36),
    )
    calibrated_candidate = calibrated.candidates[0]
    assert calibrated_candidate.blockers == ()
    assert calibrated_candidate.inclusion_probability_ppm == 300_000
    assert calibrated_candidate.calibration_attempts_observed == 120
    value = expected_value_atoms(
        calibrated_candidate,
        gross_value_atoms=10_000,
        compute_cost_atoms=500,
    )
    assert value == 2_200


def test_cost_ledger_exact_with_revert_cost_and_settlement() -> None:
    unknown = CostLedger()
    assert unknown.priority_fee_tip_atoms is None
    assert unknown.compute_budget_units is None
    assert unknown.revert_cost_atoms is None

    ledger = CANDIDATE_COST
    included = SettlementRecord(
        outcome=SettlementOutcome.INCLUDED, reason_code="INCLUDED_IN_BLOCK"
    )
    reverted = SettlementRecord(
        outcome=SettlementOutcome.INCLUDED_REVERTED, reason_code="PROGRAM_REVERT"
    )
    not_included = SettlementRecord(
        outcome=SettlementOutcome.NOT_INCLUDED, reason_code="BLOCK_FULL"
    )
    assert (
        realized_settlement_cost_atoms(ledger, included, compute_cost_atoms=500)
        == 1_500
    )
    assert (
        realized_settlement_cost_atoms(ledger, reverted, compute_cost_atoms=500)
        == 2_000
    )
    assert (
        realized_settlement_cost_atoms(ledger, not_included, compute_cost_atoms=500)
        == 0
    )

    with pytest.raises(EvolutionError, match="PRIORITY_FEE_UNKNOWN"):
        realized_settlement_cost_atoms(unknown, included, compute_cost_atoms=500)
    with pytest.raises(EvolutionError, match="REVERT_COST_UNKNOWN"):
        realized_settlement_cost_atoms(
            CostLedger(priority_fee_tip_atoms=1_000), reverted, compute_cost_atoms=500
        )
    with pytest.raises(EvolutionError, match="COMPUTE_COST_UNKNOWN"):
        realized_settlement_cost_atoms(ledger, included, compute_cost_atoms=None)

    # EV refuses unknown ledger fields even when probability is calibrated
    uncosted_stream = (
        _writer_tx(),
        TxEvent(
            tx_id="tx-backrun-uncosted",
            slot=10,
            reads=("pool:quote",),
            writes=(),
            flow_authorization=FlowAuthorization.PUBLIC_ORDERFLOW,
            protocol_permitted_backrun=True,
            observed_versions=(("pool:quote", 1),),
        ),
    )
    uncosted_report = replay_permitted_backrun_auction(
        uncosted_stream,
        calibration=InclusionCalibration(attempts_observed=120, inclusions_observed=36),
    )
    with pytest.raises(EvolutionError, match="PRIORITY_FEE_UNKNOWN"):
        expected_value_atoms(
            uncosted_report.candidates[0],
            gross_value_atoms=10_000,
            compute_cost_atoms=500,
        )

    report = replay_permitted_backrun_auction(
        (_writer_tx(), _candidate_tx()),
        calibration=InclusionCalibration(attempts_observed=120, inclusions_observed=36),
        settlements={"tx-backrun": reverted},
    )
    candidate = report.candidates[0]
    assert candidate.settlement == reverted
    assert candidate.settlement is not None
    assert candidate.settlement.outcome is SettlementOutcome.INCLUDED_REVERTED
    assert candidate.settlement.reason_code == "PROGRAM_REVERT"
    assert candidate.cost == ledger
