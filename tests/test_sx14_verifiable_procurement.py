"""SX-14 — verifiable task procurement + mechanism lab tests (offline)."""

from __future__ import annotations

import pytest

from src.research.verifiable_procurement import (
    AwardMechanism,
    Bid,
    ProcurementAward,
    ProcurementError,
    ProcurementRejectionReason,
    TaskKind,
    VerifiableTaskBoard,
    VerifiableTaskSpec,
    canonical_payload_hash,
    MechanismLabRunner,
)


def _spec(
    payload: str = '{"decode":"block-1","mint":"0xABC"}',
    kind: TaskKind = TaskKind.DECODE,
    latency: int | None = 120,
) -> VerifiableTaskSpec:
    return VerifiableTaskSpec(
        task_type=kind,
        canonical_payload=payload,
        data_rights="pinned fixture, CC0, retrieved 2026-11-14",
        latency_bounds_ms=latency,
    )


def test_post_task_idempotent_by_hash() -> None:
    board = VerifiableTaskBoard()
    first = board.post_task(_spec())
    second = board.post_task(_spec())
    assert first == second
    # Different payload -> different hash -> different task.
    other = board.post_task(_spec(payload='{"decode":"block-2"}'))
    assert other != first


def test_hash_canonicalization_stable() -> None:
    payload = '{"decode":"block-1"}'
    assert canonical_payload_hash(payload) == canonical_payload_hash(payload)
    assert canonical_payload_hash(payload) != canonical_payload_hash(payload + " ")


def test_missing_data_rights_rejected_typed() -> None:
    with pytest.raises(ProcurementError) as err:
        VerifiableTaskSpec(
            task_type=TaskKind.EXACT_QUOTE,
            canonical_payload="p",
            data_rights="   ",
        )
    assert err.value.args[0] == ProcurementRejectionReason.DATA_RIGHTS_UNDECLARED.value


def test_recomputation_match_and_mismatch() -> None:
    board = VerifiableTaskBoard()
    task_id = board.post_task(_spec())
    assert board.verify_result(task_id, "decoded-ok", lambda _payload: "decoded-ok")
    with pytest.raises(ProcurementError) as err:
        board.verify_result(task_id, "wrong", lambda _payload: "decoded-ok")
    assert err.value.args[0] == ProcurementRejectionReason.RECOMPUTATION_MISMATCH.value


def test_award_deterministic_lowest_price_with_stable_tiebreak() -> None:
    board = VerifiableTaskBoard()
    task_id = board.post_task(_spec())
    board.submit_bid(Bid(task_id, "op-b", 50))
    board.submit_bid(Bid(task_id, "op-a", 50))
    board.submit_bid(Bid(task_id, "op-c", 70))
    first = board.award(task_id, AwardMechanism.POSTED_PRICE)
    second = board.award(task_id, AwardMechanism.POSTED_PRICE)
    assert first is second  # idempotent award
    assert first.winner_id == "op-a"
    assert first.payment_units == 50
    assert first.surplus_units is None  # posted price records no surplus


def test_no_bid_is_typed_never_fabricated() -> None:
    board = VerifiableTaskBoard()
    task_id = board.post_task(_spec())
    award = board.award(task_id, AwardMechanism.POSTED_PRICE)
    assert award.winner_id is None
    assert award.payment_units is None
    assert award.reason == ProcurementRejectionReason.NO_BIDS.value


def test_reservation_auction_rejects_below_reserve_and_records_surplus() -> None:
    board = VerifiableTaskBoard()
    task_id = board.post_task(_spec())
    board.submit_bid(Bid(task_id, "op-low", 5))
    board.submit_bid(Bid(task_id, "op-high", 30))
    rejected = board.award(
        task_id, AwardMechanism.RESERVATION_AUCTION, reserve_units=10
    )
    assert rejected.winner_id == "op-high"
    assert rejected.payment_units == 10
    assert rejected.surplus_units == 20

    board2 = VerifiableTaskBoard()
    task2 = board2.post_task(_spec(payload="p2"))
    board2.submit_bid(Bid(task2, "op-low", 5))
    below = board2.award(task2, AwardMechanism.RESERVATION_AUCTION, reserve_units=10)
    assert below.winner_id is None
    assert below.reason == ProcurementRejectionReason.RESERVE_NOT_MET.value


def test_unknown_task_rejected() -> None:
    board = VerifiableTaskBoard()
    with pytest.raises(ProcurementError) as err:
        board.submit_bid(Bid("missing", "op", 1))
    assert err.value.args[0] == ProcurementRejectionReason.TASK_UNKNOWN.value


def _task_id(payload: str) -> str:
    return "vtask-" + canonical_payload_hash(payload)[:20]


def test_fixed_workload_comparison_reproducible() -> None:
    tasks = [
        _spec('{"t":"1"}', latency=100),
        _spec('{"t":"2"}', latency=300),
        _spec('{"t":"3"}', TaskKind.REPLAY, latency=None),
    ]
    bids = {
        _task_id('{"t":"1"}'): [Bid(_task_id('{"t":"1"}'), "op-1", 20)],
        _task_id('{"t":"2"}'): [Bid(_task_id('{"t":"2"}'), "op-2", 40)],
        _task_id('{"t":"3"}'): [Bid(_task_id('{"t":"3"}'), "op-3", 60)],
    }
    runner = MechanismLabRunner(tasks, bids)
    first = runner.run()
    second = MechanismLabRunner(tasks, bids).run()
    assert {k: v.canonical_json() for k, v in first.items()} == {
        k: v.canonical_json() for k, v in second.items()
    }
    posted = first[AwardMechanism.POSTED_PRICE]
    assert posted.awarded_task_count == 3
    assert posted.total_cost_units == 120
    assert posted.worst_case_latency_ms == 300


def test_mechanism_reports_differ_when_cost_profiles_differ() -> None:
    tasks = [_spec('{"t":"1"}', latency=100)]
    cheap = MechanismLabRunner(
        tasks,
        {_task_id('{"t":"1"}'): [Bid(_task_id('{"t":"1"}'), "op-cheap", 5)]},
    ).run()
    expensive = MechanismLabRunner(
        tasks,
        {_task_id('{"t":"1"}'): [Bid(_task_id('{"t":"1"}'), "op-exp", 500)]},
    ).run()
    assert (
        cheap[AwardMechanism.POSTED_PRICE].total_cost_units
        != expensive[AwardMechanism.POSTED_PRICE].total_cost_units
    )


def test_unknown_latency_stays_none_never_zero() -> None:
    tasks = [_spec('{"t":"1"}', latency=None)]
    bids = {_task_id('{"t":"1"}'): [Bid(_task_id('{"t":"1"}'), "op-1", 10)]}
    report = MechanismLabRunner(tasks, bids).run()[AwardMechanism.POSTED_PRICE]
    assert report.worst_case_latency_ms is None


def test_no_deployment_or_execution_surface() -> None:
    import src.research.verifiable_procurement as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "def deploy" not in source
    assert "def submit_transaction" not in source
    award = ProcurementAward(
        task_id="t",
        mechanism=AwardMechanism.POSTED_PRICE,
        winner_id="op",
        payment_units=1,
        reserve_units=None,
        surplus_units=None,
        reason="r",
        award_hash="h",
        execution_right=False,
    )
    assert award.execution_right is False
    with pytest.raises(ProcurementError):
        ProcurementAward(
            task_id="t",
            mechanism=AwardMechanism.POSTED_PRICE,
            winner_id="op",
            payment_units=1,
            reserve_units=None,
            surplus_units=None,
            reason="r",
            award_hash="h",
            execution_right=True,
        )
