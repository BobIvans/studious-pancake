"""OCA-W2 tests: deterministic episodes, UNKNOWN joins preserved, replay."""

from __future__ import annotations

from src.intelligence.operation_context import build_operation_episodes
from src.observability import make_event
from src.observability.events import EventType, Outcome
from src.observability.reasons import ReasonCode
from src.observability.store import ObservabilityStore

FIXTURE_EVENTS = [
    {
        "logical_opportunity_id": "opp-1",
        "event_type": EventType.opportunity_detected,
        "stage": "candidate",
        "outcome": Outcome.accepted,
        "sequence_no": 1,
    },
    {
        "logical_opportunity_id": "opp-1",
        "event_type": EventType.quote_received,
        "stage": "quote",
        "outcome": Outcome.observed,
        "sequence_no": 2,
    },
    {
        "logical_opportunity_id": "opp-1",
        "event_type": EventType.simulation_rejected,
        "stage": "simulation",
        "outcome": Outcome.rejected,
        "reason_code": ReasonCode.SIMULATION_SLIPPAGE_MIN_OUT,
        "sequence_no": 3,
    },
    {
        "logical_opportunity_id": "opp-2",
        "event_type": EventType.feasibility_rejected,
        "stage": "candidate",
        "outcome": Outcome.rejected,
        "reason_code": ReasonCode.ROUTE_NOT_FOUND,
        "sequence_no": 1,
    },
]


def _fixture_store(tmp_path) -> ObservabilityStore:
    store = ObservabilityStore(str(tmp_path / "events.sqlite"))
    for payload in FIXTURE_EVENTS:
        store.append(make_event(plan_hash="fixture-plan", **payload))
    return store


def test_episodes_deterministic_and_grouped(tmp_path) -> None:
    store = _fixture_store(tmp_path)
    projection_a = build_operation_episodes(store)
    projection_b = build_operation_episodes(store)
    assert projection_a == projection_b
    assert projection_a["coverage"]["opportunities_observed"] == 2
    by_opportunity = {
        episode["logical_opportunity_id"]: episode
        for episode in projection_a["episodes"]
    }
    assert by_opportunity["opp-1"]["event_count"] == 3
    assert "SLIPPAGE" in str(
        by_opportunity["opp-1"]["stage_timeline"][2]["reason_code"]
    )


def test_unknown_joins_and_terminal_outcome_honesty(tmp_path) -> None:
    store = _fixture_store(tmp_path)
    projection = build_operation_episodes(store)
    by_opportunity = {
        episode["logical_opportunity_id"]: episode for episode in projection["episodes"]
    }
    episode = by_opportunity["opp-1"]
    # No reconciliation evidence -> terminal outcome stays UNKNOWN.
    assert episode["terminal_outcome"]["outcome"] == "UNKNOWN"
    assert "NO_AUTHORITATIVE_RECONCILIATION_EVIDENCE" in (
        episode["terminal_outcome"]["reason"]
    )
    # Joins stay explicit; unknown is never zero.
    assert "UNKNOWN" in episode["joins"]["market_episode"]
    assert "MISSING" in episode["joins"]["runtime_lineage"]
    assert projection["coverage"]["joins_present"] == 0


def test_replay_after_reopen_is_identical(tmp_path) -> None:
    path = str(tmp_path / "events.sqlite")
    store = ObservabilityStore(path)
    for payload in FIXTURE_EVENTS:
        store.append(make_event(plan_hash="fixture-plan", **payload))
    first = build_operation_episodes(store)
    reopened = build_operation_episodes(ObservabilityStore(path))
    assert first["projection_digest"] == reopened["projection_digest"]
