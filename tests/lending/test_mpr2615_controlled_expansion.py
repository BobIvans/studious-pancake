from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.lending.controlled_expansion import (
    ControlledLenderExpansionRegistry,
    ExpansionCandidateIdentity,
    ExpansionError,
    FIRST_V1_PROFILE,
    LenderCapability,
    LenderCapabilityStatus,
    LenderCombinationIdentity,
    LenderFeeObligation,
    QualifiedLenderCandidate,
    require_fresh_fallback_identity,
    select_best_qualified_lender,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def capability(*, status="production_qualified", cid="marginfi", combo="m1"):
    return LenderCapability.from_mapping(
        {
            "capability_id": cid,
            "profile": "circular_arbitrage+marginfi+jupiter",
            "status": status,
            "blockers": [],
            "combination_ids": [combo],
        }
    )


def candidate(*, cap, combo, cid, gross, cost, effect=False, sim=H2):
    identity = ExpansionCandidateIdentity(cid, cap.capability_id, combo, H1, H2, sim)
    return QualifiedLenderCandidate(
        identity=identity,
        capability=cap,
        gross_edge_atomic=gross,
        obligation=LenderFeeObligation(1000, 1010, 10, cost),
        repayment_proven=True,
        simulation_message_sha256=sim,
        effect_issued=effect,
    )


def test_packaged_registry_keeps_first_v1_and_new_lenders_default_off():
    root = Path(__file__).resolve().parents[2]
    raw = json.loads(
        (root / "src/resources/kamino_supported_combinations.json").read_text()
    )
    registry = ControlledLenderExpansionRegistry.from_mapping(raw)
    assert registry.first_v1_profile == FIRST_V1_PROFILE
    assert registry.predecessor_2614 == "RESERVED_PREDECESSOR_UNOBSERVED"
    kamino = registry.require("kamino_klend")
    assert kamino.status == LenderCapabilityStatus.RESEARCH
    assert not kamino.executable
    assert kamino.combination_ids == ()
    assert registry.require("save_main_pool").status == LenderCapabilityStatus.UNSUPPORTED
    assert registry.require("save_permissionless_pools").status == LenderCapabilityStatus.UNSUPPORTED


def test_wildcard_combination_and_identity_are_denied():
    with pytest.raises(ExpansionError, match="wildcard"):
        LenderCapability.from_mapping(
            {
                "capability_id": "kamino",
                "profile": "x",
                "status": "research",
                "blockers": [],
                "combination_ids": ["*"],
            }
        )
    with pytest.raises(ExpansionError, match="wildcard"):
        LenderCombinationIdentity.from_mapping(
            {
                "protocol": "kamino",
                "cluster": "mainnet-beta",
                "genesis_hash": "genesis",
                "program_id": "program",
                "market": "all_markets",
                "reserve": "reserve",
                "mint": "mint",
                "token_program": "token",
                "liquidity_supply": "supply",
                "oracle_accounts": ["oracle"],
                "flash_borrow_family": "borrow",
                "flash_repay_family": "repay",
                "generation": "g1",
            }
        )


def test_exact_fee_math_rejects_bool_float_and_mismatch():
    for value in (True, 1.5):
        with pytest.raises(ExpansionError):
            LenderFeeObligation(value, 1010, 10, 10)
    with pytest.raises(ExpansionError, match="arithmetic mismatch"):
        LenderFeeObligation(1000, 1011, 10, 11)


def test_unqualified_better_gross_edge_cannot_win():
    marginfi = capability(cid="marginfi", combo="m1")
    kamino = capability(status="research", cid="kamino_klend", combo="k1")
    a = candidate(cap=marginfi, combo="m1", cid="a", gross=80, cost=20)
    b = candidate(cap=kamino, combo="k1", cid="b", gross=1000, cost=20)
    assert select_best_qualified_lender([b, a]) is a


def test_candidate_lender_or_reserve_mutation_changes_semantic_identity():
    marginfi = capability(cid="marginfi", combo="m1")
    kamino = capability(cid="kamino_klend", combo="k1")
    a = candidate(cap=marginfi, combo="m1", cid="a", gross=80, cost=20)
    b = candidate(cap=kamino, combo="k1", cid="a", gross=80, cost=20)
    assert a.identity.semantic_digest != b.identity.semantic_digest


def test_final_simulation_must_bind_exact_final_message():
    cap = capability()
    c = candidate(cap=cap, combo="m1", cid="a", gross=80, cost=20, sim=H3)
    assert not c.selectable
    with pytest.raises(ExpansionError, match="no independently qualified"):
        select_best_qualified_lender([c])


def test_pre_effect_fallback_requires_new_identity_and_post_effect_is_forbidden():
    a_cap = capability(cid="marginfi", combo="m1")
    b_cap = capability(cid="kamino_klend", combo="k1")
    a = candidate(cap=a_cap, combo="m1", cid="a", gross=80, cost=20)
    b = candidate(cap=b_cap, combo="k1", cid="b", gross=90, cost=20)
    require_fresh_fallback_identity(a, b)
    issued = candidate(
        cap=a_cap, combo="m1", cid="a-issued", gross=80, cost=20, effect=True
    )
    with pytest.raises(ExpansionError, match="after effect"):
        require_fresh_fallback_identity(issued, b)
