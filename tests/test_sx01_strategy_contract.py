"""SX-01 deterministic offline tests for the canonical strategy contract.

Covers: round-trip identity, fail-closed unknown/missing fields (including
nested), per-asset vector conservation, UNKNOWN-stays-None economics, the
execution-class restriction ladder, promotion no-skip monotonicity, the
EXCLUDED no-upgrade rule, stable serialization/content hashing, absence of a
runtime registry, and vocabulary parity with STRATEGY_ACCEPTANCE_MATRIX.json.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.strategy.strategy_contract import (
    PROMOTION_LADDER,
    SCHEMA_VERSION,
    AssetClaim,
    ConservationError,
    ContractStatus,
    ContractTypeError,
    CostLedger,
    ExecutionClass,
    ExpectedSign,
    FundingRequirement,
    MarketDependency,
    MissingContractFieldError,
    PromotionEvidence,
    PromotionTier,
    PromotionTierError,
    QuoteRequirement,
    ReplaySpec,
    ResourceManifest,
    RiskFlag,
    SharedResourceCost,
    StrategyContractError,
    StrategyContractV1,
    TierEvidence,
    TypedBlocker,
    TypedBlockerReason,
    UnknownContractFieldError,
    claims_conserved,
    strictest_execution_class,
)

# ---------------------------------------------------------------------------
# Deterministic builders (no randomness, no clocks, no network).
# ---------------------------------------------------------------------------


def _claim(**overrides: object) -> AssetClaim:
    values: dict[str, object] = {
        "chain": "solana",
        "address": "MINTA",
        "representation_kind": "spl_token",
        "decimals": 6,
        "issuer": None,
        "amount": 1_000,
    }
    values.update(overrides)
    return AssetClaim(**values)  # type: ignore[arg-type]


def _market_dependency(**overrides: object) -> MarketDependency:
    values: dict[str, object] = {
        "venue": "raydium_cpmm",
        "program_revision": "program-hash-1",
        "pool_or_book_id": "pool-1",
        "underlying_resource_ids": ("pool-1",),
        "state_generation": "gen-42",
        "max_freshness_seconds": 2,
    }
    values.update(overrides)
    return MarketDependency(**values)  # type: ignore[arg-type]


def _quote_requirement(**overrides: object) -> QuoteRequirement:
    values: dict[str, object] = {
        "side": "exact_in",
        "input_asset": _claim(amount=1_000),
        "output_asset": _claim(address="MINTB", amount=990),
        "exact_input_amount": 1_000,
        "exact_output_amount": 990,
        "fee_bps": 30,
        "max_slippage_bps": 10,
        "rounding": "floor",
        "partial_fill_allowed": False,
        "dust_tolerance": 0,
        "ttl_seconds": 30,
        "consumed_input_assets": (),
        "residual_assets": (),
    }
    values.update(overrides)
    return QuoteRequirement(**values)  # type: ignore[arg-type]


def _funding_requirement(**overrides: object) -> FundingRequirement:
    values: dict[str, object] = {
        "provider": "flash_capital_graph",
        "asset": _claim(amount=1_000),
        "caller_eligible": None,
        "borrow_amount": 1_000,
        "fee_amount": 5,
        "capacity_amount": None,
        "repayment_asset": _claim(amount=1_005),
        "repayment_amount": 1_005,
        "callback_required": True,
        "atomicity_proof": None,
    }
    values.update(overrides)
    return FundingRequirement(**values)  # type: ignore[arg-type]


def _cost_ledger(**overrides: object) -> CostLedger:
    values: dict[str, object] = {
        "unit": "lamports",
        "dex_fee": 3_000,
        "maker_fee": None,
        "taker_fee": None,
        "flash_fee": None,
        "network_fee": 5_000,
        "priority_fee": None,
        "tip_amount": None,
        "compute_cost": None,
        "rent_cost": None,
        "provider_api_cost": None,
        "hedge_cost": None,
        "funding_cost": None,
        "borrow_cost": None,
        "inventory_markout": None,
        "failed_attempt_cost": None,
    }
    values.update(overrides)
    return CostLedger(**values)  # type: ignore[arg-type]


def _resources(**overrides: object) -> ResourceManifest:
    values: dict[str, object] = {
        "read_resources": ("book-2", "pool-1"),
        "consumed_resources": ("pool-1",),
        "exclusive_resources": (),
        "shared_costs": (
            SharedResourceCost(resource_id="pool-1", amount=100, unit="lamports"),
        ),
    }
    values.update(overrides)
    return ResourceManifest(**values)  # type: ignore[arg-type]


def _replay(**overrides: object) -> ReplaySpec:
    values: dict[str, object] = {
        "corpus_hash": "corpus-abc-123",
        "replay_inputs": ("snapshot-42.json",),
        "data_lineage": ("rpc-slot-42",),
        "source_rights": ("public_rpc",),
        "test_refs": ("tests/test_sx01_strategy_contract.py",),
        "no_trade_reasons": ("spread_below_fees",),
        "holdout": ("holdout-week-46",),
    }
    values.update(overrides)
    return ReplaySpec(**values)  # type: ignore[arg-type]


def _evidence_through(tier: PromotionTier) -> tuple[TierEvidence, ...]:
    return tuple(
        TierEvidence(entry, f"proof::{entry.value}")
        for entry in PROMOTION_LADDER[: tier.ladder_rank + 1]
    )


def _promotion(**overrides: object) -> PromotionEvidence:
    values: dict[str, object] = {
        "claimed_tier": PromotionTier.RESEARCH_SEED,
        "evidence": _evidence_through(PromotionTier.RESEARCH_SEED),
        "blockers": (
            TypedBlocker(
                TypedBlockerReason.STATE_READ_UNPROVEN, "no rooted state read yet"
            ),
        ),
        "issued_by": "sx01-worker",
        "issued_at": "2026-11-14T00:00:00+00:00",
    }
    values.update(overrides)
    return PromotionEvidence(**values)  # type: ignore[arg-type]


def _contract(**overrides: object) -> StrategyContractV1:
    values: dict[str, object] = {
        "strategy_id": "sx01-sample",
        "family_id": "ARB-CORE",
        "version": "1.0.0",
        "owner": "sx01-worker",
        "status": ContractStatus.NEW_GAP,
        "source_task_ids": ("SX-01",),
        "hypothesis": "Two-leg CPMM spread closes within one transaction",
        "expected_sign": ExpectedSign.POSITIVE,
        "null_hypothesis": "Net outcome after costs is not positive",
        "controls": ("same-snapshot single-leg baseline",),
        "counterexamples": ("fee-dominated small size",),
        "input_claims": (_claim(amount=1_000_000),),
        "output_claims": (_claim(address="MINTB", amount=999_000),),
        "execution_class": ExecutionClass.LOCAL_ATOMIC_CANDIDATE,
        "market_dependencies": (_market_dependency(),),
        "cost_ledger": _cost_ledger(),
        "resources": _resources(),
        "replay": _replay(),
        "promotion": _promotion(),
        "settlement_domain": "solana",
        "transaction_boundary": "single_ptb",
        "finality": "confirmed",
        "max_holding_horizon_seconds": 0,
        "quote_requirements": (_quote_requirement(),),
        "funding_requirements": (_funding_requirement(),),
        "capacity_curve_ref": None,
        "sizing_owner": None,
        "risk_flags": (RiskFlag.PARTIAL_FILL, RiskFlag.STALE_OR_REORG),
    }
    values.update(overrides)
    return StrategyContractV1(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Round-trip identity and fail-closed parsing.
# ---------------------------------------------------------------------------


def test_round_trip_preserves_contract_identity() -> None:
    contract = _contract()
    restored = StrategyContractV1.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.to_dict() == contract.to_dict()
    assert restored.corpus_hash == contract.corpus_hash
    # idempotent: a second round changes nothing
    twice = StrategyContractV1.from_dict(restored.to_dict())
    assert twice == contract


def test_full_payload_round_trips_every_nested_section() -> None:
    contract = _contract(
        resources=_resources(
            exclusive_resources=("pool-1",),
            shared_costs=(
                SharedResourceCost(resource_id="pool-1", amount=100, unit="lamports"),
                SharedResourceCost(resource_id="blockspace", amount=None, unit=None),
            ),
        ),
        risk_flags=(RiskFlag.MEV_COMPETITION, RiskFlag.CAP, RiskFlag.PAUSE),
        quote_requirements=(
            _quote_requirement(
                consumed_input_assets=(_claim(amount=1_000),),
                residual_assets=(_claim(address="MINTB", amount=1),),
            ),
        ),
    )
    restored = StrategyContractV1.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.resources.exclusive_resources == ("pool-1",)
    # shared_costs are canonically sorted; look them up by resource id
    by_resource = {cost.resource_id: cost for cost in restored.resources.shared_costs}
    assert by_resource["pool-1"].amount == 100
    assert by_resource["blockspace"].amount is None  # UNKNOWN preserved
    assert by_resource["blockspace"].unit is None
    assert restored.risk_flags == (
        RiskFlag.CAP,
        RiskFlag.MEV_COMPETITION,
        RiskFlag.PAUSE,
    )


def test_unknown_top_level_field_fails_closed() -> None:
    payload = _contract().to_dict()
    payload["expected_alpha"] = 999
    with pytest.raises(UnknownContractFieldError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert "contract.expected_alpha" in str(excinfo.value)


def test_unknown_nested_field_fails_closed() -> None:
    payload = _contract().to_dict()
    payload["input_claims"][0]["symbol"] = "SOL"
    with pytest.raises(UnknownContractFieldError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert "contract.input_claims[0].symbol" in str(excinfo.value)

    payload = _contract().to_dict()
    payload["cost_ledger"]["gas_cost"] = 5
    with pytest.raises(UnknownContractFieldError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert "contract.cost_ledger.gas_cost" in str(excinfo.value)


@pytest.mark.parametrize(
    "missing_key",
    [
        "schema_version",
        "strategy_id",
        "family_id",
        "version",
        "owner",
        "status",
        "source_task_ids",
        "hypothesis",
        "expected_sign",
        "null_hypothesis",
        "input_claims",
        "output_claims",
        "execution_class",
        "market_dependencies",
        "cost_ledger",
        "resources",
        "replay",
        "promotion",
    ],
)
def test_missing_required_top_level_field_fails_closed(missing_key: str) -> None:
    payload = _contract().to_dict()
    del payload[missing_key]
    with pytest.raises(MissingContractFieldError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert f"contract.{missing_key}" in str(excinfo.value)


def test_missing_required_nested_field_fails_closed() -> None:
    payload = _contract().to_dict()
    del payload["input_claims"][0]["chain"]
    with pytest.raises(MissingContractFieldError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert "contract.input_claims[0].chain" in str(excinfo.value)

    payload = _contract().to_dict()
    del payload["promotion"]["claimed_tier"]
    with pytest.raises(MissingContractFieldError):
        StrategyContractV1.from_dict(payload)


def test_schema_version_mismatch_fails_closed() -> None:
    payload = _contract().to_dict()
    payload["schema_version"] = "studious-pancake.strategy-contract.v2"
    with pytest.raises(ContractTypeError) as excinfo:
        StrategyContractV1.from_dict(payload)
    assert SCHEMA_VERSION in str(excinfo.value)


# ---------------------------------------------------------------------------
# Per-asset vector conservation (catalog section 4).
# ---------------------------------------------------------------------------


def test_conservation_balanced_with_explicit_fees_passes() -> None:
    # per-asset rebalance: each asset's inputs equal its outputs plus fees
    # (a swap that consumes one asset to mint another is NOT conservative
    # per asset and is exactly what this invariant must reject elsewhere)
    inputs = (_claim(amount=1_000_000), _claim(address="SOL", amount=5))
    outputs = (_claim(amount=999_000), _claim(address="SOL", amount=5))
    fees = (_claim(amount=700), _claim(amount=300))
    assert claims_conserved(inputs, outputs, fees) is True
    # fee-free balanced vectors pass as well
    assert claims_conserved((_claim(amount=5),), (_claim(amount=5),)) is True
    # liabilities (negative claims) conserve too
    debt = _claim(representation_kind="debt", amount=-500)
    assert claims_conserved((debt,), (debt,)) is True


def test_conservation_unbalanced_raises() -> None:
    with pytest.raises(ConservationError) as excinfo:
        claims_conserved(
            (_claim(amount=1_000),),
            (_claim(amount=900),),
            (_claim(amount=50),),
        )
    assert "net delta 50" in str(excinfo.value)


def test_conservation_is_per_asset_and_never_scalarized() -> None:
    # total magnitude matches (3000 == 3000) but is shifted across two assets
    with pytest.raises(ConservationError):
        claims_conserved(
            (
                _claim(address="MINTA", amount=1_000),
                _claim(address="MINTB", amount=2_000),
            ),
            (_claim(address="MINTA", amount=3_000),),
        )
    # the same address on a different chain is a distinct claim
    with pytest.raises(ConservationError):
        claims_conserved(
            (_claim(amount=1_000),),
            (_claim(chain="ethereum", amount=1_000),),
        )
    # differing representation provenance is never silently merged
    with pytest.raises(ConservationError) as excinfo:
        claims_conserved(
            (_claim(decimals=6, amount=1_000),),
            (_claim(decimals=None, amount=1_000),),
        )
    assert "provenance mismatch" in str(excinfo.value)


def test_conservation_unknown_amount_fails_closed() -> None:
    with pytest.raises(ConservationError) as excinfo:
        claims_conserved((_claim(amount=None),), (_claim(amount=None),))
    assert "unknown is not zero" in str(excinfo.value)
    # one unknown amount poisons its whole asset bucket even if others balance
    with pytest.raises(ConservationError):
        claims_conserved(
            (_claim(amount=100), _claim(amount=None)),
            (_claim(amount=100),),
        )


# ---------------------------------------------------------------------------
# UNKNOWN stays None, never 0 (catalog section 4).
# ---------------------------------------------------------------------------


def test_unknown_costs_stay_none_through_round_trip() -> None:
    ledger = _cost_ledger()
    contract = _contract(cost_ledger=ledger)
    restored = StrategyContractV1.from_dict(contract.to_dict())
    assert restored == contract
    assert restored.cost_ledger.unit == "lamports"
    assert restored.cost_ledger.dex_fee == 3_000
    assert restored.cost_ledger.maker_fee is None
    assert restored.cost_ledger.flash_fee is None
    assert restored.cost_ledger.inventory_markout is None
    assert restored.to_dict()["cost_ledger"]["maker_fee"] is None
    # an explicit zero is distinct from unknown and survives the round trip
    explicit_zero = _cost_ledger(maker_fee=0)
    restored_zero = StrategyContractV1.from_dict(
        _contract(cost_ledger=explicit_zero).to_dict()
    )
    assert restored_zero.cost_ledger.maker_fee == 0


def test_cost_total_refuses_to_sum_unknown_components() -> None:
    partial = _cost_ledger()
    assert partial.total() is None  # unknown components are never 0-padded
    # a fully measured ledger (explicit zero included) sums exactly
    full = _cost_ledger(
        maker_fee=0,
        taker_fee=10,
        flash_fee=250,
        priority_fee=20,
        tip_amount=30,
        compute_cost=40,
        rent_cost=50,
        provider_api_cost=60,
        hedge_cost=70,
        funding_cost=80,
        borrow_cost=90,
        inventory_markout=-15,
        failed_attempt_cost=100,
    )
    assert full.total() == (
        3_000 + 0 + 10 + 250 + 5_000 + 20 + 30 + 40 + 50 + 60 + 70 + 80 + 90 - 15 + 100
    )
    # a unitless known cost fails closed
    with pytest.raises(ContractTypeError):
        CostLedger(unit=None, dex_fee=10)
    # inventory markout may be adverse (negative); payment costs may not
    adverse = _cost_ledger(inventory_markout=-120)
    assert adverse.inventory_markout == -120
    with pytest.raises(ContractTypeError):
        _cost_ledger(dex_fee=-1)


# ---------------------------------------------------------------------------
# Execution-class restriction ladder (catalog section 2).
# ---------------------------------------------------------------------------


def test_strictest_execution_class_ladder_order() -> None:
    ladder = (
        ExecutionClass.LOCAL_ATOMIC_CANDIDATE,
        ExecutionClass.CONDITIONAL_HYPEREDGE,
        ExecutionClass.HEDGED_NON_ATOMIC,
        ExecutionClass.CONTROL_PLANE,
        ExecutionClass.SIGNAL_ONLY,
        ExecutionClass.RESEARCH_ONLY,
        ExecutionClass.EXCLUDED,
    )
    for index, weaker in enumerate(ladder):
        for stronger in ladder[index + 1 :]:
            assert (
                strictest_execution_class((weaker, stronger)) is stronger
            ), f"{stronger.value} must dominate {weaker.value}"
    for member in ExecutionClass:
        assert strictest_execution_class((member,)) is member
    # a mixed route inherits the strictest leg class
    route = (
        ExecutionClass.LOCAL_ATOMIC_CANDIDATE,
        ExecutionClass.CONDITIONAL_HYPEREDGE,
        ExecutionClass.SIGNAL_ONLY,
    )
    assert strictest_execution_class(route) is ExecutionClass.SIGNAL_ONLY


def test_strictest_execution_class_empty_leg_set_fails_closed() -> None:
    with pytest.raises(StrategyContractError):
        strictest_execution_class(())


# ---------------------------------------------------------------------------
# Promotion ladder monotonicity (catalog section 5) and EXCLUDED no-upgrade.
# ---------------------------------------------------------------------------


def test_promotion_evidence_must_not_skip_tiers() -> None:
    partial = _evidence_through(PromotionTier.EXACT_QUOTE)
    with pytest.raises(PromotionTierError) as excinfo:
        PromotionEvidence(claimed_tier=PromotionTier.PAPER_QUALIFIED, evidence=partial)
    assert "SIMULATION_PASS" in str(excinfo.value)
    # a gap in the middle of the ladder is rejected too
    with pytest.raises(PromotionTierError):
        PromotionEvidence(
            claimed_tier=PromotionTier.EXACT_QUOTE,
            evidence=(
                TierEvidence(PromotionTier.RESEARCH_SEED, "proof::seed"),
                TierEvidence(PromotionTier.IDENTITY_VERIFIED, "proof::identity"),
                TierEvidence(PromotionTier.EXACT_QUOTE, "proof::quote"),
            ),
        )
    # full prefix passes and evidence is canonically ordered by the ladder
    full = PromotionEvidence(
        claimed_tier=PromotionTier.PAPER_QUALIFIED,
        evidence=_evidence_through(PromotionTier.PAPER_QUALIFIED),
    )
    assert [item.tier for item in full.evidence] == list(PROMOTION_LADDER)
    contract = _contract(promotion=full)
    assert StrategyContractV1.from_dict(contract.to_dict()) == contract


def test_promotion_evidence_above_claim_and_duplicates_fail() -> None:
    with pytest.raises(PromotionTierError):
        PromotionEvidence(
            claimed_tier=PromotionTier.RESEARCH_SEED,
            evidence=_evidence_through(PromotionTier.IDENTITY_VERIFIED),
        )
    with pytest.raises(ContractTypeError):
        PromotionEvidence(
            claimed_tier=PromotionTier.RESEARCH_SEED,
            evidence=(
                TierEvidence(PromotionTier.RESEARCH_SEED, "proof::a"),
                TierEvidence(PromotionTier.RESEARCH_SEED, "proof::b"),
            ),
        )


def test_excluded_execution_class_cannot_be_upgraded() -> None:
    with pytest.raises(PromotionTierError) as excinfo:
        _contract(
            execution_class=ExecutionClass.EXCLUDED,
            status=ContractStatus.EXCLUDED,
            promotion=PromotionEvidence(
                claimed_tier=PromotionTier.EXACT_QUOTE,
                evidence=_evidence_through(PromotionTier.EXACT_QUOTE),
            ),
        )
    assert "EXCLUDED" in str(excinfo.value)
    # EXCLUDED at the seed tier is the only accepted shape
    excluded = _contract(
        execution_class=ExecutionClass.EXCLUDED, status=ContractStatus.EXCLUDED
    )
    assert excluded.promotion.claimed_tier is PromotionTier.RESEARCH_SEED
    # an EXCLUDED leg makes the whole route EXCLUDED
    assert (
        strictest_execution_class(
            (ExecutionClass.LOCAL_ATOMIC_CANDIDATE, ExecutionClass.EXCLUDED)
        )
        is ExecutionClass.EXCLUDED
    )


def test_contracts_are_frozen_so_no_upgrade_path_exists() -> None:
    contract = _contract()
    with pytest.raises(FrozenInstanceError):
        contract.execution_class = ExecutionClass.RESEARCH_ONLY  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        contract.promotion.claimed_tier = PromotionTier.PAPER_QUALIFIED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Stable serialization and content addressing.
# ---------------------------------------------------------------------------


def test_serialization_is_stable_and_content_addressed() -> None:
    first = _contract()
    second = _contract()  # independently built, equal by value
    assert first is not second
    assert first.to_dict() == second.to_dict()
    assert first.canonical_json() == second.canonical_json()
    assert first.corpus_hash == second.corpus_hash
    assert (
        first.corpus_hash == StrategyContractV1.from_dict(first.to_dict()).corpus_hash
    )
    # any semantic change produces a different hash
    changed = _contract(execution_class=ExecutionClass.HEDGED_NON_ATOMIC)
    assert changed.corpus_hash != first.corpus_hash
    # canonical JSON is pure, parseable JSON
    assert json.loads(first.canonical_json())["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# No runtime registry; advisory schema only.
# ---------------------------------------------------------------------------


def test_module_has_no_runtime_registry_store() -> None:
    module = importlib.import_module("src.strategy.strategy_contract")
    mutable_containers = (dict, list, set, bytearray)
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        assert not isinstance(
            value, mutable_containers
        ), f"module-level mutable store detected: {name}"
    assert not any("register" in name.lower() for name in vars(module))


def test_contract_grants_no_execution_rights() -> None:
    contract = _contract()
    forbidden = ("execute", "send", "sign", "submit", "borrow", "deploy", "promote")
    for attribute in dir(contract):
        assert attribute.lower() not in forbidden, attribute
    assert "grants no execution rights" in StrategyContractV1.__doc__


# ---------------------------------------------------------------------------
# Vocabulary parity and type confusion.
# ---------------------------------------------------------------------------


def test_enum_vocabularies_match_acceptance_matrix() -> None:
    matrix_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "strategy-expansion"
        / "2026-11-14"
        / "STRATEGY_ACCEPTANCE_MATRIX.json"
    )
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    assert {member.value for member in ExecutionClass} == set(
        matrix["execution_classes"]
    )
    assert {member.value for member in ContractStatus} == set(matrix["statuses"])
    assert [tier.value for tier in PROMOTION_LADDER] == [
        "RESEARCH_SEED",
        "IDENTITY_VERIFIED",
        "STATE_READ_PROVEN",
        "EXACT_QUOTE",
        "CAPACITY_PROVEN",
        "BUILD_CONFORMANT",
        "SIMULATION_PASS",
        "PAPER_QUALIFIED",
    ]


def test_expected_sign_unknown_is_distinct_from_zero() -> None:
    unknown = _contract(expected_sign=ExpectedSign.UNKNOWN)
    zero = _contract(expected_sign=ExpectedSign.ZERO)
    assert unknown.expected_sign is not zero.expected_sign
    assert unknown.expected_sign.value == "unknown"
    assert zero.expected_sign.value == "zero"


@pytest.mark.parametrize(
    ("builder", "error_type"),
    [
        (
            lambda: AssetClaim(
                chain="solana",
                address="A",
                representation_kind="spl_token",
                amount="100",
            ),
            ContractTypeError,
        ),
        (
            lambda: AssetClaim(
                chain="solana",
                address="A",
                representation_kind="spl_token",
                decimals=1.5,
            ),
            ContractTypeError,
        ),
        (
            lambda: AssetClaim(
                chain="solana",
                address="A",
                representation_kind="spl_token",
                decimals=True,
            ),
            ContractTypeError,
        ),
        (lambda: CostLedger(unit="lamports", dex_fee=-1), ContractTypeError),
        (lambda: ResourceManifest(read_resources="pool-1"), ContractTypeError),
        (
            lambda: PromotionEvidence(
                claimed_tier=PromotionTier.RESEARCH_SEED, evidence=()
            ),
            PromotionTierError,
        ),
        (
            lambda: _contract(execution_class="LOCAL_ATOMIC_CANDIDATE"),
            ContractTypeError,
        ),
        (lambda: _contract(max_holding_horizon_seconds=-1), ContractTypeError),
        (lambda: _contract(source_task_ids=()), ContractTypeError),
        (lambda: _contract(promotion="seed"), ContractTypeError),
    ],
)
def test_type_confusion_fails_closed(
    builder: object, error_type: type[StrategyContractError]
) -> None:
    with pytest.raises(error_type):
        builder()


def test_from_dict_type_confusion_fails_closed() -> None:
    payload = _contract().to_dict()
    payload["execution_class"] = "MEGA_ALPHA"
    with pytest.raises(ContractTypeError):
        StrategyContractV1.from_dict(payload)

    payload = _contract().to_dict()
    payload["input_claims"] = "not-a-list"
    with pytest.raises(ContractTypeError):
        StrategyContractV1.from_dict(payload)

    payload = _contract().to_dict()
    payload["source_task_ids"] = []
    with pytest.raises(ContractTypeError):
        StrategyContractV1.from_dict(payload)

    payload = _contract().to_dict()
    payload["promotion"]["evidence"] = [{"tier": "RESEARCH_SEED"}]
    with pytest.raises(MissingContractFieldError):
        StrategyContractV1.from_dict(payload)
