from dataclasses import replace

import pytest

from src.research.correlation_ledger.ledger import (
    CorrelationLedger,
    NormalizedObservation,
    normalized_residual,
)
from tests.test_dynamic_asset_resolution import evidence


def sample(market, t, value, *, group=None):
    e = replace(
        evidence(market, position=round(t * 100), timestamp=t),
        correlation_group=group or market,
    )
    return NormalizedObservation(
        "solana",
        market,
        "relation-" + market,
        e,
        (("stable_residual", value),),
        (market,),
        "quiet",
    )


def test_real_parquet_deterministic_replay_and_lead_lag(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    values = [0.1, -0.2, 0.5, 0.3, -0.1]
    samples = tuple(
        o
        for i, v in enumerate(values)
        for o in (sample("a", 100 + i, v), sample("b", 100.1 + i, v * 2))
    )
    refs = ledger.append_many(samples)
    ledger.append_many(samples)
    assert len(ledger.observations()) == 10
    restarted = CorrelationLedger(tmp_path, "campaign")
    assert restarted.replay(refs) == samples
    findings = ledger.lead_lag(
        "a", "b", (5,), feature="stable_residual", now=105, lags=(0, 0.1)
    )
    assert findings[0].sample_count == 0
    assert findings[1].correlation == pytest.approx(1)
    assert findings[1].sample_count == 5 and findings[1].confidence > 0
    assert findings == restarted.lead_lag(
        "a", "b", (5,), feature="stable_residual", now=105, lags=(0, 0.1)
    )
    ref = ledger.preserve_anomaly("candidate", at=105, findings=findings)
    assert len(ledger.proofs.replay(ref)["payload"]["samples"]) == 10


def test_correlated_providers_cannot_be_independent_confirmation(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append_many(
        tuple(
            o
            for i in range(4)
            for o in (
                sample("a", 100 + i, i, group="shared"),
                sample("b", 100 + i, i, group="shared"),
            )
        )
    )
    result = ledger.lead_lag(
        "a", "b", (5,), feature="stable_residual", now=104, lags=(0,)
    )[0]
    assert (
        result.correlation == 1
        and result.source_correlation_penalty == 1
        and result.confidence == 0
    )
    assert result.verification_state == "DISCOVERY_ONLY"


def test_raw_price_missing_position_and_wrong_generation_rejected(tmp_path):
    s = sample("a", 100, 1)
    with pytest.raises(ValueError):
        replace(s, features=(("price", 1),))
    with pytest.raises(ValueError):
        replace(s, evidence=replace(s.evidence, slot_or_checkpoint=None))
    with pytest.raises(ValueError):
        CorrelationLedger(tmp_path, "other").append(s)
    assert normalized_residual(1.02, 1, conversion_cost=0.01) == pytest.approx(0.01)


def test_missing_replay_and_ambiguous_timestamp_fail_closed(tmp_path):
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append_many((sample("a", 100, 1), sample("a", 100, 2)))
    with pytest.raises(ValueError, match="missing replay"):
        ledger.replay(("missing",))
    with pytest.raises(ValueError, match="ambiguous"):
        ledger.lead_lag("a", "b", feature="stable_residual", now=101)
