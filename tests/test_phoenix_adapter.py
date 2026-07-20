import pytest

from src.execution.models import AccountSnapshot, Instruction, SimulationReport
from src.providers.orderbook import *
from tests.orderbook_fixture_helpers import (
    fixture_flash_loan_plan,
    fixture_registry,
    fixture_snapshot,
)


def registry():
    return fixture_registry()


def snap(kind):
    return fixture_snapshot(kind)


def flp():
    return fixture_flash_loan_plan()


def test_registry_digest_and_unknown_program_rejects():
    r = registry()
    assert r.digest()
    from src.ingest.amm_math_dispatcher import classify_pool_type

    with pytest.raises(ValueError, match="UNKNOWN_VENUE_OR_POOL"):
        classify_pool_type("UnknownProgram")


def test_phoenix_and_openbook_decode_and_reject_wrong_layouts():
    for kind in (VenueKind.PHOENIX_LEGACY_SPOT, VenueKind.OPENBOOK_V2):
        ad, s = snap(kind)
        assert s.depth.bids[0].price_lots == 99
        assert s.depth.asks[0].price_lots == 101
        with pytest.raises(OrderbookReject) as e:
            ad.decode_snapshot(
                market=s.market_pubkey,
                owner=s.program_id,
                market_data=b"BAD" + b"0" * 60,
                book_data=b"",
                context_slot=1,
                source_slot=1,
            )
        assert e.value.code is OrderbookRejectCode.MARKET_LAYOUT_INVALID


def test_quote_engine_multilevel_vwap_and_safety():
    _, s = snap(VenueKind.PHOENIX_LEGACY_SPOT)
    q = OrderbookQuoteEngine().quote(s, TradeDirection.SELL_BASE, 1500, min_output=0)
    assert q.executable_base_lots == 15
    assert len(q.consumed_levels) == 2
    assert q.max_in <= 1500
    assert q.min_out == 1480 - 4
    assert q.vwap.numerator == 74
    assert q.vwap.denominator == 75
    with pytest.raises(OrderbookReject) as e:
        OrderbookQuoteEngine().quote(s, TradeDirection.SELL_BASE, 999999999)
    assert e.value.code is OrderbookRejectCode.ORDERBOOK_DEPTH_INSUFFICIENT


def test_lifecycle_seat_and_open_orders():
    svc = VenueAccountLifecycleService()
    p = svc.validate(
        venue_kind=VenueKind.PHOENIX_LEGACY_SPOT,
        market="M",
        authority="A",
        account=None,
        data=None,
        expected_marker=b"SEAT",
    )
    assert p.state.status is VenueAccountStatus.PREPARATION_REQUIRED
    assert (
        svc.validate(
            venue_kind=VenueKind.OPENBOOK_V2,
            market="M",
            authority="A",
            account="oo",
            data=b"M|A|OPEN_ORDERS",
            expected_marker=b"OPEN_ORDERS",
        ).state.status
        is VenueAccountStatus.READY
    )
    with pytest.raises(OrderbookReject) as e:
        svc.validate(
            venue_kind=VenueKind.PHOENIX_LEGACY_SPOT,
            market="M",
            authority="A",
            account="seat",
            data=b"wrong",
            expected_marker=b"SEAT",
        )
    assert e.value.code is OrderbookRejectCode.SEAT_INVALID


def test_ioc_planner_fails_closed_until_canonical_solders_builder():
    ad, s = snap(VenueKind.OPENBOOK_V2)
    q = OrderbookQuoteEngine().quote(s, TradeDirection.BUY_BASE, 2000)
    ixp = ad.build_ioc_instruction(s, q, "auth", "baseata", "quoteata")
    assert ixp.ioc_only
    assert ixp.instructions[0].kind.endswith("_ioc")
    cand = OrderbookAmmCandidate(
        "opp",
        "payer",
        "auth",
        "CLOB_TO_AMM",
        s,
        ixp,
        (Instruction("amm", ("baseata", "quoteata"), b"swap", "swap", "amm_swap"),),
        flp(),
        ExecutionProfile(s.venue_spec.venue_kind, "fixture", 16, 8, 1232, 400000, 8, 2),
        q.min_out,
        ("payer",),
    )
    with pytest.raises(OrderbookReject) as e:
        OrderbookAmmPlanner().plan(cand)
    assert e.value.code is OrderbookRejectCode.SETTLEMENT_PATH_UNPROVEN
    assert e.value.diagnostics["legacy_plan_hash"]

    message_hash = "0" * 64
    rep = SimulationReport(
        True,
        None,
        (),
        None,
        1,
        1,
        None,
        (),
        (AccountSnapshot(s.market_pubkey, 1, s.program_id, b"ZERO"),),
        (),
        0,
        0,
        None,
        10,
        10,
        message_hash,
    )
    ad.prove_postconditions(rep, s.market_pubkey)
    bad = SimulationReport(
        True,
        None,
        (),
        None,
        1,
        1,
        None,
        (),
        (AccountSnapshot(s.market_pubkey, 1, s.program_id, b"RESTING"),),
        (),
        0,
        0,
        None,
        10,
        10,
        message_hash,
    )
    with pytest.raises(OrderbookReject) as e:
        ad.prove_postconditions(bad, s.market_pubkey)
    assert e.value.code is OrderbookRejectCode.ORDERBOOK_RESIDUAL_ORDER
