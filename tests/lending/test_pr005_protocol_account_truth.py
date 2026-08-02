import json
from dataclasses import replace

import pytest

from src.discovery.bounded import DiscoveryLimits, bounded_requests
from src.lending.account_truth import (
    AccountTruthError,
    NATIVE_SOL,
    TOKEN_2022_PROGRAM,
    TokenMintEvidence,
    validate_mint,
    validate_route_amount,
)
from src.lending.protocol_registry import (
    GenesisBoundProtocolRegistry,
    ProtocolRegistryError,
)
from src.oracle.coherence import (
    CoherenceError,
    CrossSlotPolicy,
    RootedStateEvidence,
    require_coherent,
)
from src.strategy.admission import (
    AdmissionError,
    AdmissionEvidence,
    PersistentOpportunityLedger,
    admit_sender_free,
)

GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"


def test_unqualified_protocols_remain_named_and_blocked():
    registry = GenesisBoundProtocolRegistry.packaged()
    for name in ("marginfi", "kamino"):
        result = registry.qualify(name, genesis_hash=GENESIS, current_slot=1)
        assert not result.executable
        assert "DEPLOYED_IDENTITY_EVIDENCE_MISSING" in result.blockers
        assert "HUMAN_REVIEW_MISSING" in result.blockers
    with pytest.raises(ProtocolRegistryError, match="genesis"):
        registry.qualify("marginfi", genesis_hash="wrong", current_slot=1)
    combos = json.loads(
        open(
            "src/resources/kamino_supported_combinations.json", encoding="utf-8"
        ).read()
    )
    assert combos["combinations"] == []


def test_json_declaration_alone_cannot_claim_protocol_support(tmp_path):
    packaged = GenesisBoundProtocolRegistry.packaged()
    payload = json.loads(
        open(
            "src/resources/contracts/protocol/protocol_account_registry.json",
            encoding="utf-8",
        ).read()
    )
    entry = payload["protocols"]["marginfi"]
    entry.update(
        status="supported",
        program_id="11111111111111111111111111111111",
        programdata_account="11111111111111111111111111111111",
        idl_layout_version="v1",
        source_commit_build_hash="a" * 64,
        human_review=True,
        blockers=[],
        expires_at_slot=2,
    )
    registry = GenesisBoundProtocolRegistry(payload, root=tmp_path)
    result = registry.qualify(
        "marginfi", genesis_hash=packaged.genesis_hash, current_slot=1
    )
    assert not result.executable
    assert "JSON_DECLARATION_WITHOUT_MATERIALIZED_EVIDENCE" in result.blockers
    assert "INVALID_MINTS" in result.blockers
    assert "INVALID_TOKEN_PROGRAM" in result.blockers


def test_token_2022_is_fail_closed_and_native_sol_is_not_wsol():
    good = TokenMintEvidence(
        "So11111111111111111111111111111111111111112",
        TOKEN_2022_PROGRAM,
        9,
        False,
        ("transfer_fee",),
    )
    validate_mint(good, allowed_extensions=("transfer_fee",))
    with pytest.raises(AccountTruthError, match="unsupported"):
        validate_mint(good)
    with pytest.raises(AccountTruthError, match="sentinel"):
        validate_mint(replace(good, mint=NATIVE_SOL))
    with pytest.raises(AccountTruthError, match="wrong token"):
        validate_mint(replace(good, owner="11111111111111111111111111111111"))


def _states():
    kinds = ("reserve", "oracle", "mint", "alt", "blockhash", "protocol")
    return tuple(
        RootedStateEvidence(
            k,
            99 + (i % 2),
            101,
            GENESIS,
            "finalized",
            "fork-a",
            f"endpoint-{i % 2}",
            99,
        )
        for i, k in enumerate(kinds)
    )


def test_cross_slot_policy_rejects_stale_mixed_and_unrooted_evidence():
    policy = CrossSlotPolicy(GENESIS)
    assert len(require_coherent(_states(), policy=policy, current_root=101)) == 64
    for changed, message in (
        (replace(_states()[0], fork_hash="b"), "mixed fork"),
        (replace(_states()[0], genesis_hash="wrong"), "genesis"),
        (replace(_states()[0], commitment="confirmed"), "commitment"),
        (replace(_states()[0], min_context_slot=None), "minContextSlot"),
        (replace(_states()[0], slot=102), "unrooted"),
    ):
        values = (changed,) + _states()[1:]
        with pytest.raises(CoherenceError, match=message):
            require_coherent(values, policy=policy, current_root=101)
    with pytest.raises(CoherenceError, match="stale"):
        require_coherent(_states(), policy=policy, current_root=200)
    with pytest.raises(CoherenceError, match="incomplete"):
        require_coherent(
            _states() + (replace(_states()[0], endpoint_identity="endpoint-extra"),),
            policy=policy,
            current_root=101,
        )


def test_discovery_is_bounded_and_provider_order_independent():
    limits = DiscoveryLimits(max_requests=5)
    one = bounded_requests(
        tokens=("B", "A", "C"), amounts=(2, 1), providers=("z", "a"), limits=limits
    )
    two = bounded_requests(
        tokens=("C", "A", "B"), amounts=(1, 2), providers=("a", "z"), limits=limits
    )
    assert one == two and len(one) == 5
    directed = bounded_requests(
        tokens=("A", "B"), amounts=(1,), providers=("a",), limits=limits
    )
    assert {(item.input_asset, item.output_asset) for item in directed} == {
        ("A", "B"),
        ("B", "A"),
    }
    with pytest.raises(ValueError, match="bound"):
        bounded_requests(
            tokens=tuple(str(i) for i in range(17)),
            amounts=(1,),
            providers=("a",),
            limits=limits,
        )


def _evidence(**changes):
    values = dict(
        quota_reserved=True,
        provenance_verified=True,
        fresh=True,
        rooted_quorum=True,
        account_locks_reserved=True,
        oracle_coherent=True,
        protocol_accounts_verified=True,
        token_accounts_verified=True,
        economic_preconditions=True,
        durable_reservation=True,
    )
    values.update(changes)
    return AdmissionEvidence(**values)


def test_amount_and_strategy_admission_are_fail_closed():
    for value in (True, 1.0, float("nan"), 0, 2**64):
        with pytest.raises(AccountTruthError):
            validate_route_amount(value)
    identity = {
        "asset": "asset",
        "venue_program": "venue",
        "generation": 1,
        "rooted_snapshot": "root",
        "provider_request": "request",
        "route_evidence": "route",
        "policy_release": "policy",
    }
    first = admit_sender_free(
        provider="jupiter", amount=1, identity_parts=identity, evidence=_evidence()
    )
    assert first == admit_sender_free(
        provider="jupiter", amount=1, identity_parts=identity, evidence=_evidence()
    )
    with pytest.raises(AdmissionError, match="discovery-only"):
        admit_sender_free(
            provider="odos", amount=1, identity_parts=identity, evidence=_evidence()
        )
    with pytest.raises(AdmissionError, match="discovery-only"):
        admit_sender_free(
            provider="okx_dex", amount=1, identity_parts=identity, evidence=_evidence()
        )
    with pytest.raises(AdmissionError, match="advisory"):
        admit_sender_free(
            provider="jupiter",
            amount=1,
            identity_parts=identity,
            evidence=_evidence(model_or_research_origin=True),
        )
    with pytest.raises(AdmissionError, match="quota"):
        admit_sender_free(
            provider="jupiter",
            amount=1,
            identity_parts=identity,
            evidence=_evidence(quota_reserved=False),
        )


def test_opportunity_reservation_survives_restart(tmp_path):
    path = tmp_path / "admissions.sqlite"
    first = PersistentOpportunityLedger(path)
    assert first.reserve_once("a" * 64, admitted_at_ns=1)
    first.close()
    reopened = PersistentOpportunityLedger(path)
    assert not reopened.reserve_once("a" * 64, admitted_at_ns=2)
    reopened.close()
