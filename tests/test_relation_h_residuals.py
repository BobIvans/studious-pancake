"""Stream H residual series families, lead/lag provenance gating and
negative promotion tests for the correlation ledger.

Positive: injected sign/lag/basis relationships are recovered from aligned
residual series. Negative: unproven anchors, misaligned timestamps, mismatched
sizes/legs/slots are excluded with typed reasons (never zero), and correlation
output can never change execution classification, evidence state or heat.
"""

from dataclasses import asdict, replace
import dataclasses

import pytest

from src.assets.resolution.evidence import digest
from src.discovery.dynamic_universe.universe import Lifecycle
from src.research.correlation_ledger.ledger import (
    CHAIN_ALIGNED,
    CorrelationLedger,
    NormalizedObservation,
    normalized_residual,
)
from src.research.correlation_ledger.residuals import (
    COST_UNPROVEN,
    DIRECT_SYNTHETIC,
    INSTANT_EXIT_UNPROVEN,
    LST_RATE_UNPROVEN,
    LEG_MISMATCH,
    LST_PREMIUM,
    NAV_UNPROVEN,
    ORACLE_MARKET,
    REFERENCE_UNPROVEN,
    REDEMPTION_UNPROVEN,
    SIZE_MISALIGNED,
    SLOT_MISALIGNED,
    STABLE_REDEMPTION,
    VWAP_EXECUTION,
    WRAPPER_BASIS,
    direct_synthetic_route_residual,
    lst_premium_residual,
    nav_basis_residual,
    oracle_market_residual,
    residual_observation,
    stable_redemption_residual,
    vwap_execution_residual,
    wrapper_basis_residual,
)
from src.strategy.relation_generators.generators import generate
from src.strategy.relation_generators.heat import HeatInputs, heat
from tests.test_dynamic_asset_resolution import (
    MINT,
    OTHER,
    evidence as base_evidence,
)
from tests.test_dynamic_relations import asset as relation_asset
from tests.test_dynamic_universe import market


def ev(provider="rpc", position=100, timestamp=100.0, generation="campaign"):
    return base_evidence(provider, position, generation, timestamp)


def observation(market_id, t, value, *, aligned=True, feature=STABLE_REDEMPTION):
    e = replace(
        ev(market_id, position=round(t * 100), timestamp=t),
        correlation_group=market_id,
    )
    return NormalizedObservation(
        "solana",
        market_id,
        "relation-" + market_id,
        e,
        ((feature, value),),
        (market_id,),
        "quiet",
        timestamp_alignment=CHAIN_ALIGNED if aligned else "UNALIGNED",
    )


# ---------------------------------------------------------------------------
# Residual family arithmetic: injected basis levels are recovered exactly.
# ---------------------------------------------------------------------------


def test_stable_redemption_residual_recovers_injected_level():
    sample = stable_redemption_residual(
        market_price=1.02,
        redemption_anchor=1.0,
        exit_cost=0.002,
        scale=1.0,
        redemption_proven=True,
        exit_cost_known=True,
        evidences=(ev("amm", 100), ev("protocol", 101)),
    )
    assert sample.feature == STABLE_REDEMPTION
    assert sample.value == pytest.approx(0.018)
    assert sample.timestamp_alignment == CHAIN_ALIGNED
    assert sample.exclusions == ()


def test_lst_premium_uses_protocol_exchange_and_instant_exit_cost():
    sample = lst_premium_residual(
        lst_price=1.05,
        underlying_price=1.0,
        exchange_rate=1.02,
        scale=1.0,
        rate_proven=True,
        instant_exit_available=True,
        instant_exit_cost=0.01,
        evidences=(ev("amm"), ev("amm"), ev("protocol")),
    )
    assert sample.value == pytest.approx(1.05 - 1.02 - 0.01)


def test_wrapper_nav_vwap_route_oracle_residuals_recover_levels():
    wrapper = wrapper_basis_residual(
        wrapper_price=1.01,
        reference_price=1.0,
        wrap_cost=0.004,
        scale=1.0,
        reference_proven=True,
        wrap_cost_known=True,
        evidences=(ev("clob"), ev("reference")),
    )
    assert wrapper.value == pytest.approx(0.006)
    nav = nav_basis_residual(
        market_price=1.03,
        nav_per_share=1.0,
        redemption_spread=0.01,
        scale=1.0,
        nav_proven=True,
        evidences=(ev("amm"), ev("protocol")),
    )
    assert nav.value == pytest.approx(0.02)
    vwap = vwap_execution_residual(
        amm_vwap=100.2,
        clob_vwap=100.0,
        amm_size=1000,
        clob_size=1000,
        fee_cost=0.1,
        scale=1.0,
        evidences=(ev("amm"), ev("clob")),
    )
    assert vwap.value == pytest.approx(0.1)
    route = direct_synthetic_route_residual(
        direct_output=16.0,
        synthetic_output=15.5,
        input_amount=10,
        legs_proven_equal=True,
        scale=1.0,
        evidences=(ev("amm"), ev("amm")),
    )
    assert route.value == pytest.approx(0.5)
    oracle = oracle_market_residual(
        market_price=1.5,
        oracle_price=1.49,
        confidence_scale=0.01,
        evidences=(ev("amm", 100), ev("oracle", 102)),
    )
    assert oracle.value == pytest.approx(1.0)
    assert oracle.timestamp_alignment == CHAIN_ALIGNED


# ---------------------------------------------------------------------------
# Negative: missing proof is excluded with a typed reason, never zero.
# ---------------------------------------------------------------------------


def test_unproven_family_inputs_are_excluded_with_typed_reasons():
    cases = (
        (
            stable_redemption_residual(
                market_price=1.02,
                redemption_anchor=1.0,
                exit_cost=0.0,
                scale=1.0,
                redemption_proven=False,
                exit_cost_known=True,
                evidences=(ev(), ev()),
            ),
            REDEMPTION_UNPROVEN,
        ),
        (
            stable_redemption_residual(
                market_price=1.02,
                redemption_anchor=1.0,
                exit_cost=0.0,
                scale=1.0,
                redemption_proven=True,
                exit_cost_known=False,
                evidences=(ev(), ev()),
            ),
            COST_UNPROVEN,
        ),
        (
            lst_premium_residual(
                lst_price=1.05,
                underlying_price=1.0,
                exchange_rate=1.02,
                scale=1.0,
                rate_proven=False,
                instant_exit_available=True,
                instant_exit_cost=0.0,
                evidences=(ev(), ev(), ev()),
            ),
            LST_RATE_UNPROVEN,
        ),
        (
            lst_premium_residual(
                lst_price=1.05,
                underlying_price=1.0,
                exchange_rate=1.02,
                scale=1.0,
                rate_proven=True,
                instant_exit_available=False,
                instant_exit_cost=0.0,
                evidences=(ev(), ev(), ev()),
            ),
            INSTANT_EXIT_UNPROVEN,
        ),
        (
            wrapper_basis_residual(
                wrapper_price=1.01,
                reference_price=1.0,
                wrap_cost=0.0,
                scale=1.0,
                reference_proven=False,
                wrap_cost_known=True,
                evidences=(ev(), ev()),
            ),
            REFERENCE_UNPROVEN,
        ),
        (
            nav_basis_residual(
                market_price=1.03,
                nav_per_share=1.0,
                redemption_spread=0.0,
                scale=1.0,
                nav_proven=False,
                evidences=(ev(), ev()),
            ),
            NAV_UNPROVEN,
        ),
        (
            vwap_execution_residual(
                amm_vwap=100.2,
                clob_vwap=100.0,
                amm_size=1000,
                clob_size=900,
                fee_cost=0.0,
                scale=1.0,
                evidences=(ev(), ev()),
            ),
            SIZE_MISALIGNED,
        ),
        (
            direct_synthetic_route_residual(
                direct_output=16.0,
                synthetic_output=15.5,
                input_amount=10,
                legs_proven_equal=False,
                scale=1.0,
                evidences=(ev(), ev()),
            ),
            LEG_MISMATCH,
        ),
    )
    for sample, reason in cases:
        assert sample.value is None  # unknown is not zero
        assert reason in sample.exclusions
        assert (
            residual_observation(
                sample,
                chain="solana",
                market_id="m",
                relation_id="r",
                evidence=ev(),
                liquidity_resources=("m",),
                regime="quiet",
            )
            is None
        )


def test_oracle_slot_misalignment_is_typed_and_never_correlated():
    aligned = oracle_market_residual(
        market_price=1.5,
        oracle_price=1.49,
        confidence_scale=0.01,
        evidences=(ev("amm", 100), ev("oracle", 102)),
    )
    assert aligned.value is not None
    misaligned = oracle_market_residual(
        market_price=1.5,
        oracle_price=1.49,
        confidence_scale=0.01,
        evidences=(ev("amm", 100), ev("oracle", 500)),
    )
    assert misaligned.value is None
    assert SLOT_MISALIGNED in misaligned.exclusions
    assert misaligned.timestamp_alignment == "UNALIGNED"


def test_raw_price_features_still_rejected_and_residual_math_exact():
    with pytest.raises(ValueError):
        observation("a", 100.0, 1.0, feature="price")
    assert normalized_residual(1.02, 1.0, conversion_cost=0.002) == pytest.approx(0.018)


# ---------------------------------------------------------------------------
# Lead/lag: injected sign/lag recovered on aligned series only.
# ---------------------------------------------------------------------------


X_PATTERN = (0.03, -0.02, 0.05, -0.04, 0.02, 0.01, -0.03, 0.04, -0.01, 0.02)


def append_series(ledger, *, aligned=True):
    # x leads y by 500ms with a negative sign: y(t + 0.5) = -x(t).
    samples = []
    for i, v in enumerate(X_PATTERN):
        t = 100 + i
        samples.append(observation("x", t, v, aligned=aligned))
        if i + 1 < len(X_PATTERN):
            samples.append(observation("y", t + 0.5, -v, aligned=aligned))
    ledger.append_many(tuple(samples))


def test_injected_sign_and_lag_are_recovered_from_aligned_residuals(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    append_series(ledger)
    report = ledger.lead_lag_report(
        "x", "y", (5,), feature=STABLE_REDEMPTION, now=109, lags=(0, 0.5)
    )
    by_lag = {f.lag_seconds: f for f in report.findings}
    assert by_lag[0.5].correlation == pytest.approx(-1)
    # Window (5s, now=109) covers x at t=104..109; y(t+0.5) exists for
    # t=104..108, so five lagged pairs participate.
    assert by_lag[0.5].sample_count == 5
    assert by_lag[0.5].confidence > 0
    # At lag 0 the series never share a timestamp (y sits on 500ms offsets),
    # so no pairs and no correlation: an unproven offset is not evidence.
    assert by_lag[0].correlation is None and by_lag[0].sample_count == 0
    assert report.exclusions == ()
    assert all(f.verification_state == "DISCOVERY_ONLY" for f in report.findings)
    # Deterministic replay across a restarted ledger.
    restarted = CorrelationLedger(tmp_path, "campaign")
    assert (
        restarted.lead_lag_report(
            "x", "y", (5,), feature=STABLE_REDEMPTION, now=109, lags=(0, 0.5)
        )
        == report
    )


def test_unaligned_series_excluded_with_typed_reason_and_no_correlation(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    append_series(ledger, aligned=False)
    report = ledger.lead_lag_report(
        "x", "y", (5,), feature=STABLE_REDEMPTION, now=109, lags=(0, 0.5)
    )
    assert len(report.exclusions) == 1
    exclusion = report.exclusions[0]
    assert exclusion.reason == "timestamp_alignment_unproven"
    # Query window (since=109-5-0.5): 6 x-samples + 6 y-samples, all unaligned.
    assert exclusion.sample_count == 12
    assert all(f.correlation is None and f.sample_count == 0 for f in report.findings)


def test_partially_aligned_series_uses_only_aligned_samples(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    append_series(ledger, aligned=True)
    unaligned = observation("y", 104.5, 0.02, aligned=False)
    ledger.append(unaligned)
    report = ledger.lead_lag_report(
        "x", "y", (5,), feature=STABLE_REDEMPTION, now=109, lags=(0.5,)
    )
    assert report.exclusions[0].sample_count == 1
    assert report.findings[0].correlation == pytest.approx(-1)


# ---------------------------------------------------------------------------
# Negative promotion: correlation never changes execution state or heat.
# ---------------------------------------------------------------------------


def test_correlation_output_cannot_change_execution_class_evidence_state_or_heat(
    tmp_path,
):
    ledger = CorrelationLedger(tmp_path, "campaign")
    append_series(ledger)
    report = ledger.lead_lag_report(
        "x", "y", (5,), feature=STABLE_REDEMPTION, now=109, lags=(0, 0.5)
    )
    findings = report.findings
    # DISCOVERY_ONLY is the terminal state; there is no path to any gate and
    # the finding is immutable.
    assert {f.verification_state for f in findings} == {"DISCOVERY_ONLY"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        findings[0].verification_state = "EXECUTION"

    # Relation generation is a pure function: identical inputs produce the
    # identical batch before and after any correlation output exists.
    assets = tuple(relation_asset(mint) for mint in (MINT, OTHER))
    markets = (market(),)
    before = generate(
        assets, markets, (), hubs=frozenset(), now=101, generation="campaign"
    )
    after = generate(
        assets, markets, (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert before == after
    correlation_findings = asdict(findings[0])
    assert not any(
        isinstance(value, Lifecycle) or value in set(Lifecycle)
        for value in correlation_findings.values()
    )

    # Heat treats source correlation as a strictly negative input: correlated
    # sources can never promote an asset toward HOT.
    strong = HeatInputs(
        executable_depth=3,
        independent_venues=2,
        structural_anchor=2,
        recurrence=2,
        verification_success=1,
    )
    assert heat(strong)[1] == Lifecycle.HOT
    correlated = replace(strong, source_correlation=10.0)
    score, state = heat(correlated)
    assert state != Lifecycle.HOT and score < sum(
        (
            strong.executable_depth,
            strong.structural_anchor,
            strong.divergence,
            strong.topology_change,
            strong.volume_acceleration,
            strong.recurrence,
            strong.verification_success,
            strong.flash_capacity,
        )
    ) + min(strong.independent_venues, 8)


# ---------------------------------------------------------------------------
# Windows layout: partition paths stay under MAX_PATH and legacy rows read.
# ---------------------------------------------------------------------------


def test_partition_layout_is_bounded_and_legacy_rows_still_read(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append(observation("deep-market", 100.0, 0.01))
    partition_dirs = sorted(
        p for p in (ledger.root / "normalized").glob("*/*/*/*") if p.is_dir()
    )
    assert len(partition_dirs) == 1
    components = partition_dirs[0].parts[-4:]
    assert all(len(c) <= 16 for c in (components[0], components[2], components[3]))
    files = list(partition_dirs[0].glob("*.parquet"))
    assert len(files) == 1
    full_path = files[0]
    assert len(str(full_path)) < 260  # Windows MAX_PATH regression guard
    stored = list(ledger.observations())
    assert len(stored) == 1 and stored[0].timestamp_alignment == CHAIN_ALIGNED

    # A legacy row (payload without the alignment field) stays readable and
    # conservatively UNALIGNED; its stored identity is still verified. The
    # physical 64-hex legacy directory layout is only reachable on POSIX roots
    # (it exceeds Windows MAX_PATH at any root depth), so this test exercises
    # the payload-level back-compat in a bounded directory.
    legacy_payload = asdict(observation("legacy", 100.0, 0.02))
    legacy_payload.pop("timestamp_alignment")
    import json

    row = {
        "identity": digest(legacy_payload),
        "observed_at": legacy_payload["evidence"]["observed_at"],
        "payload": json.dumps(legacy_payload, sort_keys=True, allow_nan=False),
    }
    import pyarrow as pa
    import pyarrow.parquet as pq

    legacy_dir = (
        ledger.root
        / "normalized"
        / digest("solana")[:16]
        / "1970-01-01"
        / digest("legacy")[:16]
        / digest("legacy-market")[:16]
    )
    legacy_dir.mkdir(parents=True)
    with (legacy_dir / (digest([row])[:16] + "legacy.parquet")).open("xb") as stream:
        pq.write_table(pa.Table.from_pylist([row]), stream)
    observations = ledger.observations()
    legacy = [o for o in observations if o.market_id == "legacy"]
    assert len(legacy) == 1
    assert legacy[0].timestamp_alignment == "UNALIGNED"
    # ... and an unaligned legacy sample never enters lead/lag windows.
    report = ledger.lead_lag_report(
        "legacy", "x", (5,), feature=STABLE_REDEMPTION, now=101
    )
    assert report.exclusions
    assert report.exclusions[0].reason == "timestamp_alignment_unproven"
    assert report.exclusions[0].sample_count == 1
    assert all(f.correlation is None for f in report.findings)


def test_ambiguous_same_timestamp_samples_still_fail_closed(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append_many(
        (
            observation("a", 100.0, 0.1),
            NormalizedObservation(
                "solana",
                "a",
                "relation-a",
                replace(
                    ev("a", position=10000, timestamp=100.0),
                    correlation_group="a2",
                ),
                ((STABLE_REDEMPTION, 0.2),),
                ("a",),
                "quiet",
                timestamp_alignment=CHAIN_ALIGNED,
            ),
        )
    )
    with pytest.raises(ValueError, match="ambiguous"):
        ledger.lead_lag_report("a", "b", feature=STABLE_REDEMPTION, now=101)
