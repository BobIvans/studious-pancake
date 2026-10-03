from dataclasses import replace
import json
import pytest
from tests.test_exact_cpmm_capacity import _pool, A, B
from src.direct_venue.cpmm_math import (
    cpmm_fee_accounted_quote,
    CpmmMathError,
    RAYDIUM_FEE_SOURCE_REVISION,
)
from src.strategy.exact_cpmm_capacity import (
    QualifiedRaydiumCpmmAdapter,
    CpmmEvaluationError,
)
from src.strategy.cpmm_split_replay import (
    shared_cpmm_state,
    ExactCpmmSplitPath,
    pool_key,
)
from tests.test_cpmm_split_replay import paths


def test_protocol_and_fund_fee_counters_are_excluded_from_next_reserve():
    quote = cpmm_fee_accounted_quote(
        amount_in=10000,
        reserve_in=1000000,
        reserve_out=2000000,
        trade_fee_rate_ppm=2500,
        protocol_fee_rate_ppm=120000,
        fund_fee_rate_ppm=40000,
    )
    assert quote.trade_fee_amount == 25
    assert quote.protocol_fee_amount == 3
    assert quote.fund_fee_amount == 1
    assert quote.output_amount == 19752
    assert quote.next_input_reserve == 1009996
    assert quote.next_output_reserve == 1980248
    state = _pool(
        1,
        A,
        B,
        (1000000, 2000000),
        protocol_fee_rate_ppm=120000,
        fund_fee_rate_ppm=40000,
    )
    leg = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=A, requested_input=10000
    )
    assert leg.state_after.accrued_fees_a == (3, 1, 0)
    assert leg.state_after.reserve_a + sum(leg.state_after.accrued_fees_a) == 1010000
    assert leg.state_after.reserve_b == 1980248


def test_creator_fee_input_and_output_rounding_and_direction():
    # Source: total input fee ceil(10000*3500/1e6)=35;
    # creator split floor(35*1000/3500)=10, trade=25.
    on_input = cpmm_fee_accounted_quote(
        amount_in=10000,
        reserve_in=1000000,
        reserve_out=2000000,
        trade_fee_rate_ppm=2500,
        creator_fee_rate_ppm=1000,
        protocol_fee_rate_ppm=120000,
        fund_fee_rate_ppm=40000,
    )
    assert on_input.creator_fee_amount == 10
    assert on_input.trade_fee_amount == 25
    assert on_input.output_amount == 19733
    assert on_input.next_input_reserve == 1009986
    on_output = cpmm_fee_accounted_quote(
        amount_in=10000,
        reserve_in=1000000,
        reserve_out=2000000,
        trade_fee_rate_ppm=2500,
        creator_fee_rate_ppm=1000,
        creator_fee_on_input=False,
    )
    assert on_output.creator_fee_amount == 20
    assert on_output.output_amount == 19732
    assert on_output.next_output_reserve == 1980248
    state = _pool(
        1, A, B, (1000000, 2000000), creator_fee_rate_ppm=1000, creator_fee_on="token-b"
    )
    leg = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=A, requested_input=10000
    )
    assert leg.state_after.accrued_fees_b == (0, 0, 20)
    assert leg.state_after.reserve_b + 20 == 2000000 - leg.conservative_output
    with pytest.raises(CpmmEvaluationError):
        QualifiedRaydiumCpmmAdapter().evaluate(
            replace(state, fee_accounting_revision="unknown"),
            input_asset=A,
            requested_input=10000,
        )


def test_shared_fork_preserves_fee_counters_across_branches():
    a, b = paths()

    def with_fees(path):
        return replace(
            path,
            plan=replace(
                path.plan,
                pools=tuple(
                    replace(
                        pool,
                        fee_bps=1000,
                        protocol_fee_rate_ppm=200000,
                        creator_fee_rate_ppm=1000,
                    )
                    for pool in path.plan.pools
                ),
            ),
        )

    a, b = with_fees(a), with_fees(b)
    initial = shared_cpmm_state((a.plan, b.plan))
    first = a.evaluate(100, initial)
    assert first is not None
    second = b.evaluate(100, first.next_state)
    assert second is not None
    key = pool_key(a.plan.pools[0])
    first_row = json.loads(dict(first.next_state.market_states)[key])
    second_row = json.loads(dict(second.next_state.market_states)[key])
    assert first_row[3][0] > 0
    assert second_row[3][0] > first_row[3][0]
    assert second_row[3][2] >= first_row[3][2]


def test_non_bps_fee_rate_is_not_truncated_or_overridden():
    state = _pool(1, A, B, (1000000, 2000000), fee_bps=0, trade_fee_rate_ppm=2501)
    leg = QualifiedRaydiumCpmmAdapter().evaluate(
        state, input_asset=A, requested_input=10000
    )
    assert leg.embedded_fee_input == 26
    assert leg.conservative_output == 19751
    with pytest.raises(ValueError, match="legacy"):
        replace(state, fee_bps=25)


def test_vault_u64_capacity_is_not_an_unbounded_integer_execution_claim():
    state = _pool(1, A, B, (2**64 - 10, 1000000))
    with pytest.raises(CpmmEvaluationError, match="input-capacity"):
        QualifiedRaydiumCpmmAdapter().evaluate(state, input_asset=A, requested_input=10)
    with pytest.raises(ValueError, match="u64"):
        replace(state, accrued_fees_a=(10, 0, 0))
