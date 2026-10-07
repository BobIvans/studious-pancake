from dataclasses import asdict
import pytest

from src.agg02.storage import DurableRawJournal
from src.market_data_evolution.contracts import MarketEpisode
from src.research.evidence import ResearchExperimentManifest
from src.production_qualification import AGG04EpisodeEvidence, AGG04PairedEpisodeResult
from src.intelligence.experiment_manifest import (
    seal_experiment,
    verify_experiment_identity,
)
from src.intelligence.episode_builder import build_market_episode
from src.intelligence.provider_utility import provider_funnel
from src.intelligence.strategy_report import (
    build_strategy_funnel,
    compare_strategy_baselines,
)
from src.intelligence.laya_triage import score_observation, build_compact_state
from src.intelligence.triage_loop import (
    apply_laya_retention_extension,
    queue_strong_ai_review,
)
from .test_storage import event


def identity():
    manifest = ResearchExperimentManifest(
        experiment_id="experiment-1",
        hypothesis_id="h-1",
        baseline_id="baseline-1",
        problem_sha256="a" * 64,
        dataset_sha256="b" * 64,
        code_sha256="c" * 64,
        source_ids=("provider",),
        compute_budget_units=10,
    )
    return seal_experiment(
        manifest, repo_sha="d" * 40, config_sha="e" * 64, policy_sha="f" * 64
    )


def test_episode_owner_stage_negatives_no_lookahead_and_pins(tmp_path):
    experiment = identity()
    assert verify_experiment_identity(experiment).experiment_id == "experiment-1"
    with DurableRawJournal(tmp_path / "raw.db") as journal:
        journal.append(event(1, b"source"), b"source")
        observations = [
            {
                "observation_id": "o-1",
                "available_at_ms": 1001,
                "raw_event_ids": ["event-1"],
            }
        ]
        decisions = [
            {
                "decision_id": "decision-1",
                "stage": "PRE_QUOTE",
                "available_at_ms": 2000,
                "source_refs": ["o-1"],
                "features": {"candidate_age_ms": 999},
                "action": "REJECT",
                "reason_code": "STALE_QUOTE",
                "thresholds": {"maximum_age_ms": 900},
                "strategy_id": "strategy-1",
                "strategy_version": "v1",
            }
        ]
        episode = MarketEpisode("episode-1", 2000, None, None, "CENSORED")
        receipt = build_market_episode(
            episode,
            experiment=experiment,
            observations=observations,
            decisions=decisions,
            journal=journal,
            raw_event_ids=["event-1"],
        )
        assert receipt["episode"] == asdict(episode)
        assert receipt["negative_examples"][0]["reason_code"] == "STALE_QUOTE"
        assert "event-1" in journal.retention_pins()
        decisions[0]["features"] = {"final_profit": 123}
        with pytest.raises(ValueError, match="forbidden"):
            build_market_episode(
                episode,
                experiment=experiment,
                observations=observations,
                decisions=decisions,
                journal=journal,
                raw_event_ids=["event-1"],
            )
        decisions[0]["features"] = {}
        observations[0]["available_at_ms"] = 3000
        with pytest.raises(ValueError, match="lookahead"):
            build_market_episode(
                episode,
                experiment=experiment,
                observations=observations,
                decisions=decisions,
                journal=journal,
                raw_event_ids=["event-1"],
            )


def test_owner_funnel_provider_cohorts_and_unknowns():
    funnel = build_strategy_funnel(
        episodes=(AGG04EpisodeEvidence("ep", ("o",)),),
        variants=(),
        probes=(),
        survival_horizon_ms=100,
    )
    assert funnel["episode_ids"] == ("ep",)
    providers = provider_funnel(
        [
            {"event_id": "a", "source_id": "p1", "candidate_ids": ["unique", "shared"]},
            {"event_id": "b", "source_id": "p2", "candidate_ids": ["shared"]},
        ]
    )
    assert providers["p1"]["contribution"]["unique_candidate_ids"] == ["unique"]
    assert providers["p1"]["latency_mean_ms"] is None
    assert providers["p1"]["utility"]["quota_units"] is None
    result = compare_strategy_baselines(
        (
            AGG04PairedEpisodeResult(
                episode_id="ep",
                baseline_net_atomic=None,
                challenger_net_atomic=None,
                baseline_resource_cost_atomic=0,
                challenger_resource_cost_atomic=0,
            ),
        )
    )
    assert result["unknown_episode_count"] == 1


def test_laya_typed_cache_optional_and_no_delete_authority(tmp_path):
    state = {
        "event_id": "event-1",
        "source_id": "p",
        "delta_atoms": 1,
        "available_at_ms": 0,
    }
    kwargs = {
        "cache_root": tmp_path,
        "model_version": "local-test-v1",
        "policy_sha": "p" * 64,
    }
    assert score_observation(state, **kwargs)["status"] == "NOT_OBSERVED"
    calls = []

    def backend(compact, questions):
        calls.append(compact)
        assert "payload" not in compact["state"]
        return {
            "novelty": 4,
            "research_value": 4,
            "anomaly": 0.9,
            "new_failure_class": 0.8,
            "strong_ai_needed": 0.9,
            "retention_extension": "extend_24h",
            "confidence": 0.95,
        }

    response = score_observation(
        {**state, "payload": "must never be sent"}, backend=backend, **kwargs
    )
    assert response["status"] == "SCORED"
    assert score_observation(state, backend=backend, **kwargs)["status"] == "CACHED"
    assert len(calls) == 1
    receipt = response["receipt"]
    extended = apply_laya_retention_extension(state, receipt, now_ms=1000)
    assert extended["retain_until_ms"] == 86_401_000
    assert receipt["delete_authorized"] is False and receipt["live_authorized"] is False
    assert queue_strong_ai_review([receipt])[0]["status"] == "QUEUED"
    with pytest.raises(ValueError, match="source mismatch"):
        apply_laya_retention_extension(
            {**state, "event_id": "other"}, receipt, now_ms=1000
        )
    with pytest.raises(ValueError, match="budget"):
        build_compact_state({"goal": "x" * 20_000}, kind="repo_group")
    with pytest.raises(ValueError, match="fields"):
        score_observation(
            {**state, "delta_atoms": 2}, backend=lambda s, q: {"delete": True}, **kwargs
        )
