from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.super_mpr_a_runtime_gateway import (
    CANONICAL_ALLOWED_COMMANDS,
    CANONICAL_ENTRYPOINT,
    CANONICAL_MAIN_TARGET,
    LEGACY_EXECUTION_SURFACES,
    ProviderGatewayBudget,
    ProviderGatewayPolicy,
    ProviderGatewayRequest,
    SuperMprAError,
    assert_legacy_surface_quarantined,
    assert_paper_source_guard,
    canonical_runtime_report,
    normalize_provider_quote,
    rewrite_canonical_command,
)


MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _request() -> ProviderGatewayRequest:
    return ProviderGatewayRequest(
        provider_id="jupiter",
        method="POST",
        url_fingerprint=hashlib.sha256(b"https://api.jup.ag/swap/v2/build").hexdigest(),
        body_sha256=hashlib.sha256(b"{}").hexdigest(),
        purpose="paper_quote",
    )


def _raw_quote(**overrides: object) -> bytes:
    payload = {
        "provider_id": "jupiter",
        "provider_capability": "quote_route",
        "route_id": "route-1",
        "input_mint": MINT_A,
        "output_mint": MINT_B,
        "in_amount_base_units": 1_000_000,
        "out_amount_base_units": 1_010_000,
        "context_slot": 500,
        "expires_at_unix_ms": 2_000,
        "slippage_bps": 50,
        "provider_confidence_bps": 8_000,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _policy() -> ProviderGatewayPolicy:
    return ProviderGatewayPolicy(provider_id="jupiter", min_context_slot=480)


def test_single_canonical_runtime_entrypoint_contract() -> None:
    report = canonical_runtime_report()
    assert report.canonical_entrypoint == CANONICAL_ENTRYPOINT
    assert report.canonical_target == CANONICAL_MAIN_TARGET
    assert report.allowed_commands == CANONICAL_ALLOWED_COMMANDS
    assert report.live_trading_enabled is False
    assert report.signer_available_from_paper is False
    assert report.sender_available_from_paper is False
    assert report.jito_available_from_paper is False


def test_public_command_aliases_do_not_create_live_alias() -> None:
    assert rewrite_canonical_command(["paper", "--json"]) == [
        "run",
        "--mode",
        "paper",
        "--json",
    ]
    assert rewrite_canonical_command(["shadow"]) == ["run", "--mode", "shadow"]
    assert rewrite_canonical_command(["verify", "--json"]) == ["readiness", "--json"]
    assert rewrite_canonical_command(["live"]) == ["live"]


def test_cli_pr189_exposes_super_mpr_a_alias_hook_without_live_alias() -> None:
    source = Path("src/cli_pr189.py").read_text(encoding="utf-8")
    assert "_rewrite_super_mpr_a_command" in source
    assert "rewrite_canonical_command(args)" in source
    assert "rewritten_super_mpr_a" in source
    assert '"live"' not in source


def test_legacy_execution_surfaces_are_known_and_quarantined() -> None:
    assert "src.ingest.jito_shotgun" in LEGACY_EXECUTION_SURFACES
    assert "src.execution.senders" in LEGACY_EXECUTION_SURFACES
    with pytest.raises(SuperMprAError, match="LEGACY_SURFACE_NOT_QUARANTINED"):
        assert_legacy_surface_quarantined(
            "src.ingest.jito_shotgun",
            explicit_manual_flag=False,
        )
    assert_legacy_surface_quarantined(
        "src.ingest.jito_shotgun",
        explicit_manual_flag=True,
    )


def test_paper_runtime_does_not_import_sender_signer_jito() -> None:
    assert_paper_source_guard("paper_runtime", ["src.paper_shadow.runner"])
    with pytest.raises(SuperMprAError, match="PAPER_RUNTIME_FORBIDDEN_IMPORT"):
        assert_paper_source_guard(
            "paper_runtime",
            ["src.execution.senders.jito_sender"],
        )


def test_live_data_paper_candidate_normalization() -> None:
    quote = normalize_provider_quote(
        policy=_policy(),
        budget=ProviderGatewayBudget(requests_consumed=0, retries_consumed=0),
        request=_request(),
        raw_response=_raw_quote(),
        received_at_unix_ms=1_000,
    )
    assert quote.provider_id == "jupiter"
    assert quote.context_slot == 500
    assert quote.observed_at_unix_ms == 1_000
    assert quote.expires_at_unix_ms == 2_000
    assert quote.route_digest
    assert quote.request_digest == _request().digest


def test_provider_gateway_rejects_stale_slot() -> None:
    with pytest.raises(SuperMprAError, match="PROVIDER_CONTEXT_SLOT_TOO_OLD"):
        normalize_provider_quote(
            policy=_policy(),
            budget=ProviderGatewayBudget(requests_consumed=0, retries_consumed=0),
            request=_request(),
            raw_response=_raw_quote(context_slot=10),
            received_at_unix_ms=1_000,
        )


def test_provider_gateway_enforces_retry_budget() -> None:
    with pytest.raises(SuperMprAError, match="PROVIDER_RETRY_BUDGET_EXHAUSTED"):
        normalize_provider_quote(
            policy=_policy(),
            budget=ProviderGatewayBudget(requests_consumed=0, retries_consumed=3),
            request=_request(),
            raw_response=_raw_quote(),
            received_at_unix_ms=1_000,
        )


def test_provider_gateway_enforces_quota_budget() -> None:
    with pytest.raises(SuperMprAError, match="PROVIDER_QUOTA_BUDGET_EXHAUSTED"):
        normalize_provider_quote(
            policy=_policy(),
            budget=ProviderGatewayBudget(requests_consumed=1, retries_consumed=0),
            request=_request(),
            raw_response=_raw_quote(),
            received_at_unix_ms=1_000,
        )


def test_provider_gateway_rejects_unbounded_or_wrong_provider_json() -> None:
    with pytest.raises(SuperMprAError, match="PROVIDER_RESPONSE_TOO_LARGE"):
        normalize_provider_quote(
            policy=ProviderGatewayPolicy(
                provider_id="jupiter",
                min_context_slot=1,
                max_response_bytes=8,
            ),
            budget=ProviderGatewayBudget(requests_consumed=0, retries_consumed=0),
            request=_request(),
            raw_response=_raw_quote(),
            received_at_unix_ms=1_000,
        )

    with pytest.raises(SuperMprAError, match="PROVIDER_ID_ECHO_MISMATCH"):
        normalize_provider_quote(
            policy=_policy(),
            budget=ProviderGatewayBudget(requests_consumed=0, retries_consumed=0),
            request=_request(),
            raw_response=_raw_quote(provider_id="odos"),
            received_at_unix_ms=1_000,
        )
