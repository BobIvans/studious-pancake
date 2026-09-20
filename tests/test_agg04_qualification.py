from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production_qualification import (
    AGG04CampaignPolicy,
    AGG04EpisodeEvidence,
    AGG04ProbeEvidence,
    AGG04TemporalSplit,
    AGG04VariantEvidence,
    AGG04_INSUFFICIENT_EVIDENCE,
    AGG04_NEGATIVE,
    AGG04_QUALIFIED_SCOPE,
    build_agg04_evidence_package,
    build_agg04_funnel,
    qualify_agg04_campaign,
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
) -> AGG04VariantEvidence:
    return AGG04VariantEvidence(
        episode_id=episode_id,
        variant_id=variant_id,
        amount_atomic=100,
        lender_id="marginfi",
        route_sha256=SHA_A,
        frame_sha256=SHA_B,
        cost_sha256=SHA_C,
        message_sha256=message,
        evidence_kind="simulated",
        simulated=simulated,
        conservative_net_atomic=net,
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
