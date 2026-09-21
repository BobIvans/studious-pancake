from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from src.market_data_evolution import (
    ForecastRecord,
    InstrumentIdentity,
    MarketDataEvolutionError,
    MarketEpisode,
    ModelCandidate,
    NormalizedObservation,
    PredictiveRelation,
    QualificationEvidence,
    RawObservation,
    SourceManifest,
    all_cross_market_packs,
    evaluate_retention,
    materialize_state,
    research_effect_boundary,
    select_as_of,
)

ROOT = Path(__file__).resolve().parents[2]
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _config() -> dict[str, object]:
    return json.loads(
        (ROOT / "config/market_data_evolution.json").read_text(encoding="utf-8")
    )


def _row(
    *,
    revision: int,
    available_at: int,
    value_atoms: int,
    digest: str,
) -> NormalizedObservation:
    return NormalizedObservation(
        observation_id="obs-1",
        source_id="fixture-source",
        instrument_id="BTC-PERP",
        value_atoms=value_atoms,
        event_at=10,
        first_seen_at=min(available_at, 20),
        available_at=available_at,
        revision_id=revision,
        effective_from=10,
        effective_until=None,
        instrument_version="v1",
        raw_payload_hash=digest,
    )


def test_document_registry_has_exact_counts_and_ids() -> None:
    payload = _config()
    assert payload["counts"] == {
        "layers": 9,
        "experiments": 8,
        "milestones": 8,
        "sources": 23,
        "cross_market_packs": 3,
    }
    assert [row["id"] for row in payload["layers"]] == [
        f"L{i}" for i in range(9)
    ]
    assert [row["id"] for row in payload["experiments"]] == [
        f"E{i:02d}" for i in range(1, 9)
    ]
    assert [row["id"] for row in payload["milestones"]] == [
        f"D{i:02d}" for i in range(1, 9)
    ]
    assert [row["id"] for row in payload["sources"]] == [
        f"S{i:02d}" for i in range(1, 24)
    ]


def test_every_layer_owner_and_reused_owner_is_importable() -> None:
    for row in _config()["layers"]:
        refs = [row["child_owner"], *row["canonical_reuse"]]
        if row.get("secondary_child"):
            refs.append(row["secondary_child"])
        for ref in refs:
            module_name, symbol = ref.split(":", 1)
            module = importlib.import_module(module_name)
            assert callable(getattr(module, symbol))


def test_source_manifest_is_reference_only_and_cannot_grant_execution() -> None:
    source = SourceManifest(
        source_id="S01",
        title="FRED fixture",
        source_family="macro",
        licence_status="REVERIFY",
        entitlement_status="REVERIFY",
        endpoint_quota_units=0,
        data_delay_ms=0,
        retention_class="reference-only",
        source_version="document-2026-09-20",
    )
    assert source.research_read_admitted is False
    assert source.execution_right is False
    with pytest.raises(MarketDataEvolutionError, match="EXTERNAL_FETCH_FORBIDDEN"):
        SourceManifest(
            source_id="S01",
            title="FRED fixture",
            source_family="macro",
            licence_status="VERIFIED",
            entitlement_status="VERIFIED_READ_ONLY",
            endpoint_quota_units=1,
            data_delay_ms=0,
            retention_class="bounded",
            source_version="v1",
            reference_only=False,
            external_fetch_performed=True,
        )


def test_instrument_identity_is_not_ticker_only() -> None:
    left = InstrumentIdentity(
        instrument_id="gold-a",
        ticker="GOLD",
        underlying_id="xau",
        issuer_id="issuer-a",
        venue="venue-a",
        chain="ethereum",
        settlement_asset="usd",
        maturity="none",
        multiplier_num=1,
        multiplier_den=1,
        session_id="session-a",
        licence_id="lic-a",
        claim_rights_hash=DIGEST_A,
    )
    right = InstrumentIdentity(
        instrument_id="gold-b",
        ticker="GOLD",
        underlying_id="xau",
        issuer_id="issuer-b",
        venue="venue-b",
        chain="ethereum",
        settlement_asset="usd",
        maturity="none",
        multiplier_num=1,
        multiplier_den=1,
        session_id="session-b",
        licence_id="lic-b",
        claim_rights_hash=DIGEST_B,
    )
    assert left.identity_hash != right.identity_hash


def test_raw_observation_enforces_availability_clock() -> None:
    RawObservation(
        observation_id="raw-1",
        source_id="S03",
        instrument_id="BTC-PERP",
        event_at=10,
        first_seen_at=11,
        available_at=12,
        payload_hash=DIGEST_A,
        schema_version="v1",
        units="atoms",
        quality_flags=("OK",),
    )
    with pytest.raises(MarketDataEvolutionError, match="OBSERVATION_CLOCK_ORDER"):
        RawObservation(
            observation_id="raw-2",
            source_id="S03",
            instrument_id="BTC-PERP",
            event_at=10,
            first_seen_at=15,
            available_at=12,
            payload_hash=DIGEST_A,
            schema_version="v1",
            units="atoms",
            quality_flags=("OK",),
        )


def test_as_of_never_uses_future_revision_and_selects_latest_known() -> None:
    rows = (
        _row(revision=1, available_at=20, value_atoms=100, digest=DIGEST_A),
        _row(revision=2, available_at=30, value_atoms=110, digest=DIGEST_B),
        _row(revision=3, available_at=50, value_atoms=999, digest=DIGEST_C),
    )
    selected, proof = select_as_of(rows, cutoff=35)
    assert len(selected) == 1
    assert selected[0].revision_id == 2
    assert selected[0].value_atoms == 110
    assert proof.max_available_at == 30
    assert proof.future_revision_used is False


def test_state_replay_is_deterministic_and_content_addressed() -> None:
    rows = (
        _row(revision=1, available_at=20, value_atoms=100, digest=DIGEST_A),
        _row(revision=2, available_at=30, value_atoms=110, digest=DIGEST_B),
    )
    left_state, left_manifest = materialize_state(rows, cutoff=35)
    right_state, right_manifest = materialize_state(tuple(reversed(rows)), cutoff=35)
    assert left_state.state_hash == right_state.state_hash
    assert left_manifest.state_hash == right_manifest.state_hash
    assert left_manifest.latest_state_read is False


def test_no_fill_missing_censored_are_not_matured_labels() -> None:
    no_fill = MarketEpisode(
        episode_id="episode-no-fill",
        feature_available_at=10,
        label_available_at=None,
        label_atoms=None,
        outcome_state="NO_FILL",
    )
    missing = MarketEpisode(
        episode_id="episode-missing",
        feature_available_at=10,
        label_available_at=None,
        label_atoms=None,
        outcome_state="MISSING",
    )
    assert no_fill.outcome_state != missing.outcome_state
    with pytest.raises(MarketDataEvolutionError, match="MATURED_LABEL_REQUIRED"):
        MarketEpisode(
            episode_id="bad",
            feature_available_at=10,
            label_available_at=None,
            label_atoms=None,
            outcome_state="MATURED",
        )


def test_predictive_relation_can_never_be_executable_or_causal_by_declaration() -> None:
    relation = PredictiveRelation(
        relation_id="rel-1",
        source_features=("funding",),
        target="basis",
        lag=1,
        horizon="1h",
        regime="normal",
        estimator_version="v1",
        fit_cutoff=100,
        oos_period="holdout-a",
        effect_estimate_ppm=10_000,
        uncertainty_ppm=1_000,
        multiple_test_family="family-a",
        expiry=200,
    )
    assert relation.executable is False
    with pytest.raises(MarketDataEvolutionError, match="NOT_EXECUTABLE"):
        PredictiveRelation(
            relation_id="rel-2",
            source_features=("funding",),
            target="basis",
            lag=1,
            horizon="1h",
            regime="normal",
            estimator_version="v1",
            fit_cutoff=100,
            oos_period="holdout-a",
            effect_estimate_ppm=10_000,
            uncertainty_ppm=1_000,
            multiple_test_family="family-a",
            expiry=200,
            executable=True,
        )


def test_forecast_binds_train_and_information_cutoffs() -> None:
    forecast = ForecastRecord(
        forecast_id="forecast-1",
        model_version="model-v1",
        information_cutoff=100,
        train_cutoff=90,
        target="basis",
        horizon="1h",
        feature_snapshot_hash=DIGEST_A,
        distribution_or_quantiles=(10, 20, 30),
        calibration_version="cal-v1",
        valid_until=200,
        market_regime="normal",
        abstention_reason=None,
    )
    assert forecast.execution_right is False
    with pytest.raises(MarketDataEvolutionError, match="CUTOFF_ORDER"):
        ForecastRecord(
            forecast_id="bad",
            model_version="model-v1",
            information_cutoff=100,
            train_cutoff=101,
            target="basis",
            horizon="1h",
            feature_snapshot_hash=DIGEST_A,
            distribution_or_quantiles=(10,),
            calibration_version="cal-v1",
            valid_until=200,
            market_regime="normal",
            abstention_reason=None,
        )


def test_qualification_requires_oos_structure_and_rejects_synthetic_pnl_claim() -> None:
    evidence = QualificationEvidence(
        experiment_id="E01",
        split_policy="blocked-walk-forward",
        matured_labels_only=True,
        nonoverlapping_groups=True,
        held_out_market=True,
        unseen_forward_period=True,
        null_control_passed=True,
        fdr_control_passed=True,
        calibration_measured=True,
        net_utility_after_costs_atoms=0,
    )
    assert evidence.live_authorized is False
    with pytest.raises(MarketDataEvolutionError, match="PNL_OVERCLAIM"):
        QualificationEvidence(
            experiment_id="E01",
            split_policy="blocked-walk-forward",
            matured_labels_only=True,
            nonoverlapping_groups=True,
            held_out_market=True,
            unseen_forward_period=True,
            null_control_passed=True,
            fdr_control_passed=True,
            calibration_measured=True,
            net_utility_after_costs_atoms=1,
            synthetic_pnl_as_real=True,
        )


def test_continual_candidate_rolls_back_on_old_regime_degradation() -> None:
    candidate = ModelCandidate(
        candidate_id="candidate-1",
        model_hash=DIGEST_A,
        feature_schema_hash=DIGEST_B,
        train_cutoff=100,
        new_window_metric_ppm=120,
        old_regime_metric_ppm=70,
        rollback_hash=DIGEST_C,
    )
    report = evaluate_retention(
        candidate=candidate,
        incumbent_new_window_metric_ppm=100,
        incumbent_old_regime_metric_ppm=100,
        minimum_new_window_gain_ppm=10,
        maximum_old_regime_degradation_ppm=20,
    )
    assert report.accepted_for_research is False
    assert report.rollback_required is True
    assert report.live_authorized is False


def test_three_cross_market_packs_are_disabled_and_external_blocked() -> None:
    packs = all_cross_market_packs()
    assert [pack.pack_id for pack in packs] == ["MDE-P01", "MDE-P02", "MDE-P03"]
    for pack in packs:
        assert pack.state == "DISABLED"
        assert pack.evidence_status == "BLOCKED_EXTERNAL"
        assert pack.blockers
        assert not any(
            (
                pack.live_enabled,
                pack.signing_allowed,
                pack.submission_allowed,
                pack.funds_movement_allowed,
            )
        )


def test_source_ledger_is_reference_only_and_no_external_fetch_is_claimed() -> None:
    for row in _config()["sources"]:
        assert row["reuse_mode"] == "REFERENCE_ONLY"
        assert row["license_status"] == "REVERIFY"
        assert row["entitlement_status"] == "REVERIFY"
        assert row["external_fetch_performed"] is False


def test_experiments_are_preregistered_but_not_empirically_qualified() -> None:
    for row in _config()["experiments"]:
        assert row["execution_right"] is False
        assert "QUALIFIED" not in row["status"]
        assert row["targets"]
        assert row["horizons"]


def test_document_boundaries_and_conditional_observation_contract_are_preserved() -> None:
    payload = _config()
    assert len(payload["document_boundaries"]) == 8
    assert payload["observation_contract_conditionally_required"] == [
        "published_at",
        "revision_id",
        "block_or_checkpoint",
        "source_sequence",
        "commitment",
        "request_hash",
        "licence_id",
    ]
    assert "available_at" in payload["availability_rule"]
    assert "эмпирический эксперимент не выполнен" in payload["forecast_note"]
    assert "Graph Continual Learning" in payload["document_hint"]["topic"]


def test_effect_boundary_is_all_false() -> None:
    assert not any(_config()["effect_boundary"].values())
    assert not any(research_effect_boundary().values())
