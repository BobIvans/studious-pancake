"""OCA-W13 tests: registry invariants, contracts, compatibility evaluation."""

from __future__ import annotations

import pytest

from src.intelligence.provider_contracts import (
    COMPATIBLE,
    DataContract,
    INCOMPATIBLE,
    KNOWN_MODES,
    MODE_ONE_SHOT,
    MODE_POLL_ONLY,
    PARTIAL,
    ProviderCapability,
    ProviderCapabilityRegistry,
    UNKNOWN,
    evaluate_compatibility,
)


def test_registry_entries_always_disabled() -> None:
    registry = ProviderCapabilityRegistry()
    registry.declare(
        ProviderCapability(
            provider_id="raydium",
            capability="exact_venue_state",
            mode=MODE_POLL_ONLY,
            contract=DataContract(
                contract_id="raydium.cpmm.state.v1",
                units="quote-atom",
                decimals=9,
                timestamp_semantics="slot",
                cursor_field="slot",
                replay_capable=True,
            ),
        )
    )
    with pytest.raises(ValueError):
        ProviderCapability(
            provider_id="jupiter",
            capability="quotes",
            mode=MODE_POLL_ONLY,
            enabled=True,
        )
    assert registry.enabled_count() == 0
    assert registry.providers() == ["raydium"]
    record = registry.get("raydium", "exact_venue_state")
    assert record is not None and record.to_record()["contract"]["decimals"] == 9


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        ProviderCapability(
            provider_id="x", capability="quotes", mode="LIVE_STREAM"  # type: ignore[arg-type]
        )
    assert KNOWN_MODES == {"STREAMING", "POLL_ONLY", "ONE_SHOT", "UNAVAILABLE"}


def test_compatibility_unknown_and_declared_only() -> None:
    # Undeclared capability -> UNKNOWN, never zero/compatible.
    verdict = evaluate_compatibility({"mode": MODE_POLL_ONLY}, None)
    assert verdict == {"status": UNKNOWN, "reason_codes": ["CAPABILITY_NOT_DECLARED"]}
    capability = ProviderCapability(
        provider_id="native_cpmm_capture",
        capability="venue_state",
        mode=MODE_ONE_SHOT,
    )
    verdict = evaluate_compatibility({"mode": MODE_POLL_ONLY}, capability)
    assert verdict["status"] == PARTIAL
    assert any(code.startswith("MODE_MISMATCH") for code in verdict["reason_codes"])
    # A second severity reason pushes to INCOMPATIBLE.
    harder = evaluate_compatibility(
        {"mode": MODE_POLL_ONLY, "replay": True}, capability
    )
    assert harder["status"] == INCOMPATIBLE
    # Declared-only evidence keeps even a clean evaluation explicit.
    clean = evaluate_compatibility({"mode": MODE_ONE_SHOT}, capability)
    assert clean["status"] == COMPATIBLE
    assert "DECLARED_ONLY_NO_OBSERVED_EVIDENCE" in clean["reason_codes"]


def test_replay_and_freshness_contract_gaps() -> None:
    capability = ProviderCapability(
        provider_id="fixture",
        capability="quotes",
        mode=MODE_POLL_ONLY,
        contract=DataContract(contract_id="fixture.quotes.v1", replay_capable=False),
    )
    verdict = evaluate_compatibility(
        {"mode": MODE_POLL_ONLY, "replay": True}, capability
    )
    assert verdict["status"] == PARTIAL
    assert "REPLAY_NOT_CONTRACTED" in verdict["reason_codes"]
    no_contract = ProviderCapability(
        provider_id="fixture-no-contract", capability="quotes", mode=MODE_POLL_ONLY
    )
    stale = evaluate_compatibility(
        {"mode": MODE_POLL_ONLY, "max_staleness_seconds": 5}, no_contract
    )
    assert "NO_DATA_CONTRACT_FOR_FRESHNESS_EVALUATION" in stale["reason_codes"]
    assert stale["status"] == PARTIAL
