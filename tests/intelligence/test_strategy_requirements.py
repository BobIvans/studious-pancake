"""OCA-W14 tests: requirements registry, UNKNOWN gating, separate states."""

from __future__ import annotations

from src.intelligence.provider_contracts import (
    DataContract,
    MODE_ONE_SHOT,
    MODE_POLL_ONLY,
    ProviderCapability,
    ProviderCapabilityRegistry,
)
from src.intelligence.strategy_requirements import (
    DATA_COMPATIBLE,
    DATA_INCOMPATIBLE,
    DATA_PARTIAL,
    DATA_UNKNOWN,
    QUALIFICATION_DATA_READY,
    QUALIFICATION_NOT_QUALIFIED,
    StrategyDataRequirement,
    StrategyRequirementRegistry,
    evaluate_strategy,
)


def _registry_with_raydium() -> ProviderCapabilityRegistry:
    providers = ProviderCapabilityRegistry()
    providers.declare(
        ProviderCapability(
            provider_id="raydium",
            capability="exact_venue_state",
            mode=MODE_POLL_ONLY,
            contract=DataContract(
                contract_id="raydium.cpmm.state.v1", replay_capable=True
            ),
        )
    )
    providers.declare(
        ProviderCapability(
            provider_id="native_cpmm_capture",
            capability="venue_state",
            mode=MODE_ONE_SHOT,
        )
    )
    return providers


def test_unknown_capability_never_reaches_data_ready() -> None:
    providers = _registry_with_raydium()
    requirements = StrategyRequirementRegistry()
    requirements.declare(
        StrategyDataRequirement(
            strategy_id="sx-fixture",
            provider_id="unknown-provider",
            capability="exact_venue_state",
            mode=MODE_POLL_ONLY,
        )
    )
    result = evaluate_strategy(requirements.for_strategy("sx-fixture")[0], providers)
    assert result["verdict"]["status"] == "UNKNOWN"
    assert result["data_state"] == DATA_UNKNOWN
    assert result["qualification_state"] == QUALIFICATION_NOT_QUALIFIED


def test_compatible_and_incompatible_paths() -> None:
    providers = _registry_with_raydium()
    requirements = StrategyRequirementRegistry()
    requirements.declare(
        StrategyDataRequirement(
            strategy_id="sx-good",
            provider_id="raydium",
            capability="exact_venue_state",
            mode=MODE_POLL_ONLY,
            replay=True,
        )
    )
    requirements.declare(
        StrategyDataRequirement(
            strategy_id="sx-bad",
            provider_id="native_cpmm_capture",
            capability="venue_state",
            mode=MODE_POLL_ONLY,
        )
    )
    good = evaluate_strategy(requirements.for_strategy("sx-good")[0], providers)
    bad = evaluate_strategy(requirements.for_strategy("sx-bad")[0], providers)
    assert good["data_state"] == DATA_COMPATIBLE
    assert good["qualification_state"] == QUALIFICATION_DATA_READY
    assert "DECLARED_ONLY" in " ".join(good["verdict"]["reason_codes"])
    # One severity reason (mode mismatch) => PARTIAL data state, still NOT_QUALIFIED.
    assert bad["data_state"] == DATA_PARTIAL
    assert bad["qualification_state"] == QUALIFICATION_NOT_QUALIFIED


def test_requirements_registry_deterministic() -> None:
    requirements = StrategyRequirementRegistry()
    requirements.declare(
        StrategyDataRequirement(
            strategy_id="s1", provider_id="p2", capability="c", mode=MODE_POLL_ONLY
        )
    )
    requirements.declare(
        StrategyDataRequirement(
            strategy_id="s1", provider_id="p1", capability="c", mode=MODE_POLL_ONLY
        )
    )
    assert [r.provider_id for r in requirements.for_strategy("s1")] == ["p1", "p2"]
    assert requirements.records() == requirements.records()
