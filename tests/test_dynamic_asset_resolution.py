from dataclasses import replace
from pathlib import Path

import pytest

from src.asset_mint_registry_pr117 import (
    LEGACY_SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
)
from src.assets.resolution.evidence import Evidence, EvidenceStore, digest
from src.assets.resolution.resolver import (
    AssetResolutionJob,
    BindingPolicy,
    CandidateAsset,
    ChainAssetProof,
    ResolutionState,
    bootstrap_jobs,
    canonical_identifier,
    resolve,
)

MINT = "So11111111111111111111111111111111111111112"
OTHER = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def evidence(provider="registry", position=None, generation="campaign", timestamp=100):
    return Evidence(
        "https://example.com/registry",
        provider,
        provider,
        generation,
        timestamp,
        digest(provider),
        digest("request"),
        position,
    )


def candidate(**changes):
    return replace(
        CandidateAsset(
            "solana",
            MINT,
            "COLLISION",
            9,
            LEGACY_SPL_TOKEN_PROGRAM_ID,
            evidence(),
            True,
        ),
        **changes,
    )


def proof(**changes):
    return replace(
        ChainAssetProof(
            "solana",
            MINT,
            9,
            LEGACY_SPL_TOKEN_PROGRAM_ID,
            True,
            evidence("rpc-a", 10),
            supply=100,
        ),
        **changes,
    )


def run(candidates=None, proofs=None, **kwargs):
    return resolve(
        AssetResolutionJob("solana", "COLLISION", "campaign"),
        (candidate(),) if candidates is None else candidates,
        (proof(),) if proofs is None else proofs,
        now=101,
        **kwargs,
    )


def test_new_live_identity_and_generation_history(tmp_path):
    store = EvidenceStore(tmp_path)
    first = run(store=store)
    assert first.state == ResolutionState.IDENTIFIER_VERIFIED
    second = run(proofs=(proof(evidence=evidence("rpc-a", 11)),), store=store)
    assert first.identity.asset_id == second.identity.asset_id
    assert first.identity.identity_generation != second.identity.identity_generation
    assert len(list(tmp_path.glob("*.gz"))) == 2
    for path in tmp_path.glob("*.gz"):
        store.replay(path.name.split(".")[0])


def test_ticker_collision_preserves_candidates_and_fails_closed():
    result = run((candidate(), candidate(identifier=OTHER)))
    assert result.state == ResolutionState.AMBIGUOUS
    assert result.identity is None and len(result.candidates) == 2


@pytest.mark.parametrize(
    "candidates,proofs,reason",
    [
        ((), (), "no_current_authoritative_candidate"),
        ((candidate(authoritative=False),), (), "no_current_authoritative_candidate"),
        (
            (candidate(evidence=evidence(timestamp=1)),),
            (),
            "no_current_authoritative_candidate",
        ),
        ((candidate(),), (), "missing_current_chain_evidence"),
        ((candidate(),), (proof(decimals=6),), "chain_registry_semantics_mismatch"),
        ((candidate(),), (proof(exists=False),), "chain_existence_or_position_missing"),
        (
            (candidate(),),
            (proof(evidence=evidence("rpc-a", 10, generation="old")),),
            "missing_current_chain_evidence",
        ),
        (
            (candidate(),),
            (proof(), proof(supply=99, evidence=evidence("rpc-b", 10))),
            "chain_provider_disagreement",
        ),
    ],
)
def test_negative_resolution(candidates, proofs, reason):
    result = run(candidates, proofs)
    assert result.identity is None and reason in result.reasons


def test_seed_verification_is_mandatory_and_migration_is_explicit():
    job = AssetResolutionJob(
        "solana", "COLLISION", "campaign", BindingPolicy.HARD_BIND, MINT
    )
    assert resolve(job, (candidate(),), (), now=101).identity is None
    changed = resolve(
        job, (candidate(identifier=OTHER),), (proof(identifier=OTHER),), now=101
    )
    assert "historical_seed_disagreement_preserved" in changed.reasons
    assert (
        changed.identity.canonical_identifier == OTHER
        and changed.identity.historical_seed == MINT
    )


def test_token2022_semantics_cannot_disappear():
    c = candidate(
        program_or_package=TOKEN_2022_PROGRAM_ID, extensions=("transfer_fee_config",)
    )
    p = proof(program_or_package=TOKEN_2022_PROGRAM_ID)
    assert run((c,), (p,)).identity is None
    # Identity verification describes extensions; it grants no execution support.
    assert run((c,), (replace(p, extensions=c.extensions),)).identity is not None


def test_move_full_type_and_version_are_required():
    coin = canonical_identifier("sui", "0x2::sui::SUI")
    assert coin.endswith("::sui::SUI")
    with pytest.raises(ValueError):
        canonical_identifier("sui", "0x2")
    c = CandidateAsset("sui", coin, "SUI", 9, coin.rsplit("::", 1)[0], evidence(), True)
    p = ChainAssetProof(
        "sui", coin, 9, c.program_or_package, True, evidence("grpc", 20)
    )
    job = AssetResolutionJob("sui", "SUI", "campaign")
    assert resolve(job, (c,), (p,), now=101).identity is None
    assert (
        resolve(job, (c,), (replace(p, package_version="1"),), now=101).identity
        is not None
    )


def test_bootstrap_reuses_registry_and_all_live_jobs():
    jobs = bootstrap_jobs(Path(__file__).resolve().parents[1], "campaign")
    live = [j for j in jobs if j.policy == BindingPolicy.RESOLVE_LIVE]
    assert len(live) == 27 and all(j.seed_identifier is None for j in live)


def test_replay_checks_integrity(tmp_path):
    store = EvidenceStore(tmp_path)
    payload = {"negative": "timeout"}
    ref = store.append(replace(evidence(), response_hash=digest(payload)), payload)
    assert store.replay(ref)["payload"] == payload
    with pytest.raises(ValueError):
        store.replay("../escape")
