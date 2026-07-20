from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.providers.orderbook import (
    OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
    OFFICIAL_PHOENIX_SOURCE_REPOSITORY,
    OFFICIAL_PHOENIX_VERIFY_COMMAND,
    OrderbookReject,
    OrderbookRejectCode,
    PhoenixPromotionEvidence,
    PhoenixPromotionGate,
    VenueKind,
    VenueRegistry,
    evaluate_phoenix_shadow_promotion,
    require_phoenix_shadow_promotion,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "docs" / "registry" / "orderbook_venues.json"
REQUIREMENTS = ROOT / "docs" / "registry" / "phoenix_pr066_promotion_requirements.json"

_GOOD_HASH = "sha256:" + "a" * 64


def _complete_evidence(market: str = "PHX_MAINNET_SOL_USDC") -> PhoenixPromotionEvidence:
    return PhoenixPromotionEvidence(
        market=market,
        program_id=OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
        source_repository=OFFICIAL_PHOENIX_SOURCE_REPOSITORY,
        verify_command=OFFICIAL_PHOENIX_VERIFY_COMMAND,
        market_owner=OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
        layout_sha256=_GOOD_HASH,
        golden_account_sha256=_GOOD_HASH,
        lot_fee_vector_sha256=_GOOD_HASH,
        ioc_postcondition_sha256=_GOOD_HASH,
        shadow_soak_evidence_sha256=_GOOD_HASH,
        gates={gate: True for gate in PhoenixPromotionGate},
    )


def _operator_promoted_phoenix_spec():
    registry = VenueRegistry.load(DEFAULT_REGISTRY)
    phoenix = registry.specs[VenueKind.PHOENIX_LEGACY_SPOT]
    return replace(
        phoenix,
        artifact_sha256=_GOOD_HASH,
        layout_discriminator=b"PHXLEG16",
        min_data_len=48,
        max_data_len=4096,
        enabled_shadow=True,
        enabled_live=False,
        status="operator_verified_shadow_only",
        markets=("PHX_MAINNET_SOL_USDC",),
    )


def test_pr066_requirements_document_matches_official_phoenix_scope() -> None:
    payload = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "pr066.phoenix_promotion_requirements.v1"
    assert payload["scope"] == "phoenix-first-shadow-only"
    assert payload["official_program_id"] == OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID
    assert payload["official_source_repository"] == OFFICIAL_PHOENIX_SOURCE_REPOSITORY
    assert payload["official_verify_command"] == OFFICIAL_PHOENIX_VERIFY_COMMAND
    assert "openbook-v2" in payload["non_scope"]
    assert "live-execution" in payload["non_scope"]
    assert set(payload["required_gates"]) == {gate.value for gate in PhoenixPromotionGate}


def test_pr066_default_registry_stays_fail_closed_until_operator_evidence() -> None:
    registry = VenueRegistry.load(DEFAULT_REGISTRY)
    phoenix = registry.specs[VenueKind.PHOENIX_LEGACY_SPOT]

    decision = evaluate_phoenix_shadow_promotion(phoenix, _complete_evidence())

    assert decision.shadow_allowed is False
    assert decision.live_allowed is False
    assert decision.missing_gates == ()
    assert decision.diagnostics["spec_shadow_enabled"] is False
    assert decision.diagnostics["market_allowlisted"] is False

    with pytest.raises(OrderbookReject) as exc:
        require_phoenix_shadow_promotion(phoenix, _complete_evidence())
    assert exc.value.code is OrderbookRejectCode.MARKET_UNSUPPORTED
    assert exc.value.diagnostics["missing_gates"] == ()


def test_pr066_complete_operator_spec_can_promote_only_to_shadow_not_live() -> None:
    phoenix = _operator_promoted_phoenix_spec()
    evidence = _complete_evidence("PHX_MAINNET_SOL_USDC")

    decision = require_phoenix_shadow_promotion(phoenix, evidence)

    assert decision.shadow_allowed is True
    assert decision.live_allowed is False
    assert decision.diagnostics["openbook_scope"] == "separate-follow-up"


def test_pr066_live_flag_blocks_even_complete_phoenix_evidence() -> None:
    phoenix = replace(_operator_promoted_phoenix_spec(), enabled_live=True)

    decision = evaluate_phoenix_shadow_promotion(
        phoenix, _complete_evidence("PHX_MAINNET_SOL_USDC")
    )

    assert decision.shadow_allowed is False
    assert decision.live_allowed is False
    assert decision.missing_gates == ()
    assert decision.diagnostics["spec_live_enabled"] is True


def test_pr066_missing_verified_build_and_hashes_block_shadow() -> None:
    phoenix = _operator_promoted_phoenix_spec()
    evidence = PhoenixPromotionEvidence(
        market="PHX_MAINNET_SOL_USDC",
        program_id=OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
        source_repository="https://example.invalid/not-official",
        verify_command="solana-verify skipped",
        market_owner=OFFICIAL_PHOENIX_MAINNET_PROGRAM_ID,
        layout_sha256="sha256:verification-required-before-shadow-enablement",
        golden_account_sha256="sha256:" + "b" * 64,
        lot_fee_vector_sha256="not-a-sha",
        ioc_postcondition_sha256="sha256:" + "c" * 64,
        shadow_soak_evidence_sha256="sha256:" + "d" * 64,
        gates={
            PhoenixPromotionGate.OFFICIAL_PROGRAM_ID: True,
            PhoenixPromotionGate.VERIFIED_BUILD: False,
            PhoenixPromotionGate.MARKET_OWNER: True,
            PhoenixPromotionGate.MARKET_LAYOUT: True,
            PhoenixPromotionGate.GOLDEN_RPC_ACCOUNT: True,
            PhoenixPromotionGate.LOT_AND_FEE_MATH: True,
            PhoenixPromotionGate.IOC_POSTCONDITIONS: True,
            PhoenixPromotionGate.SHADOW_SOAK: True,
        },
    )

    decision = evaluate_phoenix_shadow_promotion(phoenix, evidence)

    assert decision.shadow_allowed is False
    assert "verified-build" in decision.missing_gates
    assert "market-layout" in decision.missing_gates
    assert "lot-and-fee-math" in decision.missing_gates


def test_pr066_openbook_is_explicitly_outside_this_scope() -> None:
    registry = VenueRegistry.load(ROOT / "tests" / "fixtures" / "orderbook_venues_fixture.json")
    openbook = registry.specs[VenueKind.OPENBOOK_V2]

    with pytest.raises(OrderbookReject) as exc:
        evaluate_phoenix_shadow_promotion(
            openbook, _complete_evidence("OBV2_FIXTURE_SOL_USDC")
        )

    assert exc.value.code is OrderbookRejectCode.MARKET_UNSUPPORTED
    assert exc.value.diagnostics["venue_kind"] == "openbook_v2"
