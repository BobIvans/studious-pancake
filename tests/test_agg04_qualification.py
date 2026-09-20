from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production_qualification import (
    AGG04CampaignPolicy,
    AGG04DelayStressSample,
    AGG04DemotionTransition,
    AGG04PairedEpisodeResult,
    AGG04SelectionBiasReport,
    AGG04EpisodeEvidence,
    AGG04ProbeEvidence,
    AGG04TemporalSplit,
    AGG04VariantEvidence,
    AGG04_INSUFFICIENT_EVIDENCE,
    AGG04_NEGATIVE,
    AGG04_QUALIFIED_SCOPE,
    build_agg04_dashboard,
    build_agg04_evidence_package,
    build_agg04_survival_observation,
    compare_agg04_baselines,
    compute_agg04_class_statistics,
    build_agg04_funnel,
    qualify_agg04_campaign,
    summarize_agg04_delay_stress,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def policy(*, positive: int = 1) -> AGG04CampaignPolicy:
    return AGG04CampaignPolicy(
        campaign_id="agg04-test",
        profile_id="solana-circular-paper-v1",
        source_commit="0c4f216",
        policy_version="v1",
        allowed_assets=("SOL", "USDC"),
        allowed_venues=("jupiter", "raydium-cpmm", "meteora-dlmm"),
        allowed_lenders=("marginfi",),
        survival_horizon_ms=500,
        min_simulated_episodes=1,
        min_horizon_episodes=1,
        min_positive_net_episodes=positive,
    )


def split(*episode_ids: str) -> AGG04TemporalSplit:
    return AGG04TemporalSplit(
        train_episode_ids=episode_ids,
        validation_episode_ids=(),
        holdout_episode_ids=(),
        train_end_ns=100,
        validation_start_ns=200,
        validation_end_ns=300,
        holdout_start_ns=400,
        embargo_ns=10,
    )


def episode(name: str, *observations: str) -> AGG04EpisodeEvidence:
    return AGG04EpisodeEvidence(name, tuple(observations))


def variant(
    *,
    episode_id: str,
    variant_id: str,
    message: str = SHA_D,
    simulated: bool = True,
    net: int | None = 7,
    lender_id: str = "marginfi",
    asset_ids: tuple[str, ...] = ("SOL", "USDC"),
    venue_ids: tuple[str, ...] = ("jupiter",),
    rejection_code: str | None = None,
) -> AGG04VariantEvidence:
    return AGG04VariantEvidence(
        episode_id=episode_id,
        variant_id=variant_id,
        amount_atomic=100,
        lender_id=lender_id,
        asset_ids=asset_ids,
        venue_ids=venue_ids,
        route_sha256=SHA_A,
        frame_sha256=SHA_B,
        cost_sha256=SHA_C,
        message_sha256=message,
        evidence_kind="simulated",
        simulated=simulated,
        conservative_net_atomic=net,
        rejection_code=rejection_code,
    )


def probe(
    variant_id: str,
    *,
    elapsed_ms: int,
    positive: bool | None,
    message: str = SHA_D,
) -> AGG04ProbeEvidence:
    return AGG04ProbeEvidence(
        variant_id=variant_id,
        message_sha256=message,
        elapsed_ms=elapsed_ms,
        positive=positive,
        evidence_kind="simulated",
    )


def test_variants_do_not_inflate_independent_episode_funnel() -> None:
    episodes = (
        episode("e1", "o1", "o2"),
        episode("e2", "o3"),
    )
    variants = (
        variant(episode_id="e1", variant_id="v1", net=8),
        variant(episode_id="e1", variant_id="v2", net=9),
        variant(episode_id="e2", variant_id="v3", simulated=False, net=None),
    )
    report = build_agg04_funnel(
        episodes=episodes,
        variants=variants,
        probes=(probe("v1", elapsed_ms=501, positive=True),),
        survival_horizon_ms=500,
    )

    assert report.counts == {"A": 3, "E": 2, "C": 2, "S": 1, "H": 1, "N": 1}
    assert report.positive_net_episode_ids == ("e1",)


def test_horizon_requires_actual_elapsed_strictly_above_threshold() -> None:
    episodes = (episode("e1", "o1"),)
    variants = (variant(episode_id="e1", variant_id="v1"),)
    at_boundary = build_agg04_funnel(
        episodes=episodes,
        variants=variants,
        probes=(probe("v1", elapsed_ms=500, positive=True),),
        survival_horizon_ms=500,
    )
    after_boundary = build_agg04_funnel(
        episodes=episodes,
        variants=variants,
        probes=(probe("v1", elapsed_ms=501, positive=True),),
        survival_horizon_ms=500,
    )

    assert at_boundary.counts["H"] == 0
    assert after_boundary.counts["H"] == 1


def test_unknown_probe_is_not_counted_as_positive_or_negative() -> None:
    report = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=900, positive=None),),
        survival_horizon_ms=500,
    )
    assert report.counts["S"] == 1
    assert report.counts["H"] == 0
    assert report.counts["N"] == 0


def test_probe_cannot_borrow_message_evidence_from_another_generation() -> None:
    with pytest.raises(ValueError, match="generation mismatch"):
        build_agg04_funnel(
            episodes=(episode("e1", "o1"),),
            variants=(
                variant(
                    episode_id="e1",
                    variant_id="v1",
                    message=SHA_A,
                ),
            ),
            probes=(
                probe(
                    "v1",
                    elapsed_ms=600,
                    positive=True,
                    message=SHA_B,
                ),
            ),
            survival_horizon_ms=500,
        )


def test_temporal_split_rejects_episode_leakage() -> None:
    with pytest.raises(ValueError, match="leakage"):
        AGG04TemporalSplit(
            train_episode_ids=("e1",),
            validation_episode_ids=("e1",),
            holdout_episode_ids=(),
            train_end_ns=100,
            validation_start_ns=200,
            validation_end_ns=300,
            holdout_start_ns=400,
            embargo_ns=10,
        )


def test_external_venue_blocker_forces_insufficient_evidence() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=split("e1"),
        as_of_ns=500,
        external_blockers=("RAYDIUM_CPMM_DEPLOYED_VECTORS_MISSING",),
    )

    assert verdict.status == AGG04_INSUFFICIENT_EVIDENCE
    assert not verdict.qualified
    assert not verdict.live_enabled
    assert not verdict.release_claim_allowed
    assert not verdict.production_ready
    assert verdict.reason_codes == (
        "EXTERNAL_BLOCKER:RAYDIUM_CPMM_DEPLOYED_VECTORS_MISSING",
    )


def test_sufficient_horizon_with_nonpositive_net_is_negative() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1", net=0),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=split("e1"),
        as_of_ns=500,
    )

    assert verdict.status == AGG04_NEGATIVE
    assert verdict.reason_codes == ("POSITIVE_NET_THRESHOLD_NOT_MET",)


def test_scoped_qualification_never_becomes_live_authorization() -> None:
    p = policy()
    temporal = split("e1")
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1", net=7),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=temporal,
        as_of_ns=500,
    )
    package = build_agg04_evidence_package(
        policy=p,
        temporal_split=temporal,
        funnel=f,
        verdict=verdict,
        reproducible_command="python -m pytest -q tests/test_agg04_qualification.py",
        limitations=("sender-free paper evidence only",),
    )

    assert verdict.status == AGG04_QUALIFIED_SCOPE
    assert verdict.qualified
    assert not verdict.live_enabled
    assert not verdict.release_claim_allowed
    assert not verdict.production_ready
    assert len(package.manifest_sha256) == 64


def test_coverage_manifest_lists_exactly_41_primary_nf() -> None:
    path = Path("config/agg04_qualification_coverage.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["primary_nf"]
    ids = [row["id"] for row in rows]

    assert payload["agg_id"] == "AGG-04"
    assert len(rows) == 41
    assert len(set(ids)) == 41
    assert all(item.startswith("NF-") for item in ids)
    assert payload["live_enabled"] is False

def test_survival_is_interval_or_right_censored_not_continuous_assumption() -> None:
    v = variant(episode_id="e1", variant_id="v1")
    interval = build_agg04_survival_observation(
        variant=v,
        probes=(
            probe("v1", elapsed_ms=100, positive=True),
            probe("v1", elapsed_ms=700, positive=True),
            probe("v1", elapsed_ms=900, positive=False),
        ),
        horizon_ms=500,
    )
    right = build_agg04_survival_observation(
        variant=v,
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        horizon_ms=500,
    )

    assert interval.last_positive_ms == 700
    assert interval.first_negative_ms == 900
    assert interval.interval_censored
    assert not interval.right_censored
    assert interval.positive_at_horizon
    assert right.right_censored
    assert right.first_negative_ms is None


def test_selection_bias_never_claims_unbiasedness_with_unknown_propensity() -> None:
    incomplete = AGG04SelectionBiasReport(
        tested_hypotheses=12,
        sampled_episode_ids=("e1", "e2"),
        known_propensity_episode_ids=("e1",),
        correction_method="holm",
    )
    complete = AGG04SelectionBiasReport(
        tested_hypotheses=12,
        sampled_episode_ids=("e1", "e2"),
        known_propensity_episode_ids=("e1", "e2"),
        correction_method="holm",
    )

    assert incomplete.unknown_propensity_episode_ids == ("e2",)
    assert not incomplete.unbiased_claim_allowed
    assert complete.unbiased_claim_allowed


def test_class_statistics_forbid_two_selected_variants_from_same_episode() -> None:
    variants = (
        variant(episode_id="e1", variant_id="v1", net=4),
        variant(episode_id="e1", variant_id="v2", net=9),
    )
    with pytest.raises(ValueError, match="cherry-pick"):
        compute_agg04_class_statistics(
            variants=variants,
            selected_variant_ids=("v1", "v2"),
            selection_policy_sha256=SHA_A,
        )


def test_class_statistics_keep_unknown_net_separate_from_zero() -> None:
    stats = compute_agg04_class_statistics(
        variants=(
            variant(episode_id="e1", variant_id="v1", net=9),
            variant(episode_id="e2", variant_id="v2", net=-3),
            variant(episode_id="e3", variant_id="v3", net=0),
            variant(episode_id="e4", variant_id="v4", net=None),
        ),
        selected_variant_ids=("v1", "v2", "v3", "v4"),
        selection_policy_sha256=SHA_A,
    )

    assert stats.episode_count == 4
    assert stats.known_net_episode_count == 3
    assert stats.positive_net_episode_count == 1
    assert stats.negative_net_episode_count == 1
    assert stats.zero_net_episode_count == 1
    assert stats.unknown_net_episode_count == 1
    assert stats.total_net_atomic == 6
    assert stats.mean_net_ratio == (6, 3)


def test_paired_baseline_comparison_accounts_for_resource_costs_and_unknowns() -> None:
    report = compare_agg04_baselines(
        (
            AGG04PairedEpisodeResult("e1", 10, 14, 1, 2),
            AGG04PairedEpisodeResult("e2", 5, 4, 0, 0),
            AGG04PairedEpisodeResult("e3", None, 8, 0, 0),
        )
    )

    assert report.paired_episode_count == 2
    assert report.unknown_episode_count == 1
    assert report.challenger_incremental_net_atomic == 2
    assert report.improved_episode_count == 1
    assert report.degraded_episode_count == 1


def test_delay_stress_is_counterfactual_and_unknown_is_preserved() -> None:
    report = summarize_agg04_delay_stress(
        (
            AGG04DelayStressSample("e1", 50, True, SHA_A),
            AGG04DelayStressSample("e2", 400, False, SHA_B),
            AGG04DelayStressSample("e3", 900, None, SHA_C),
        )
    )
    assert report.sample_count == 3
    assert report.positive_count == 1
    assert report.negative_count == 1
    assert report.unknown_count == 1
    assert report.maximum_latency_ms == 900

    with pytest.raises(ValueError, match="counterfactual"):
        AGG04DelayStressSample("e4", 10, True, SHA_D, counterfactual=False)


def test_dashboard_and_demotion_remain_fail_closed() -> None:
    p = policy()
    temporal = split("e1")
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1", net=7),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=temporal,
        as_of_ns=500,
    )
    dashboard = build_agg04_dashboard(
        funnel=f,
        verdict=verdict,
        unresolved_reason_codes=("DEPLOYED_VECTOR_EXPIRY",),
    )
    transition = AGG04DemotionTransition(
        prior_verdict_sha256=verdict.verdict_sha256,
        trigger="deployment-drift",
        affected_scope=("raydium-cpmm",),
    )

    assert dashboard["status"] == AGG04_QUALIFIED_SCOPE
    assert dashboard["live_enabled"] is False
    assert dashboard["unresolved_reason_codes"] == ["DEPLOYED_VECTOR_EXPIRY"]
    assert transition.requalification_required
    assert not transition.live_enabled
    assert not transition.automatic_rearm_allowed

def test_frozen_horizon_mismatch_blocks_qualification() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=2, positive=True),),
        survival_horizon_ms=1,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=split("e1"),
        as_of_ns=500,
    )
    assert verdict.status == AGG04_INSUFFICIENT_EVIDENCE
    assert "SURVIVAL_HORIZON_POLICY_MISMATCH" in verdict.reason_codes


def test_out_of_scope_variant_cannot_qualify_frozen_campaign() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(
            variant(
                episode_id="e1",
                variant_id="v1",
                lender_id="unknown-lender",
                venue_ids=("unknown-venue",),
            ),
        ),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=split("e1"),
        as_of_ns=500,
    )
    assert verdict.status == AGG04_INSUFFICIENT_EVIDENCE
    assert "LENDER_OUTSIDE_FROZEN_SCOPE" in verdict.reason_codes
    assert "VENUE_OUTSIDE_FROZEN_SCOPE" in verdict.reason_codes


def test_rejected_variant_never_enters_simulated_horizon_or_positive_cohorts() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(
            variant(
                episode_id="e1",
                variant_id="v1",
                simulated=True,
                net=100,
                rejection_code="GUARD",
            ),
        ),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    assert f.counts == {"A": 1, "E": 1, "C": 1, "S": 0, "H": 0, "N": 0}


def test_verdict_counts_are_immutable_after_evidence_hashing() -> None:
    p = policy()
    f = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=f,
        temporal_split=split("e1"),
        as_of_ns=500,
    )
    before = verdict.verdict_sha256
    with pytest.raises(TypeError):
        verdict.counts["N"] = 999
    assert verdict.verdict_sha256 == before


def test_dashboard_rejects_mixed_funnel_and_verdict_evidence() -> None:
    p = policy()
    good = build_agg04_funnel(
        episodes=(episode("e1", "o1"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    verdict = qualify_agg04_campaign(
        policy=p,
        funnel=good,
        temporal_split=split("e1"),
        as_of_ns=500,
    )
    other = build_agg04_funnel(
        episodes=(episode("e1", "different-observation"),),
        variants=(variant(episode_id="e1", variant_id="v1"),),
        probes=(probe("v1", elapsed_ms=700, positive=True),),
        survival_horizon_ms=p.survival_horizon_ms,
    )
    with pytest.raises(ValueError, match="funnel/verdict mismatch"):
        build_agg04_dashboard(funnel=other, verdict=verdict)

