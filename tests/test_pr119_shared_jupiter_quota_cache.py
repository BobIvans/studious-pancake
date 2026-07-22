from __future__ import annotations

import pytest

from src.providers.jupiter.pr119_quota_cache import (
    REQUIRED_CACHE_IDENTITY_FIELDS,
    REQUIRED_PURPOSES,
    REQUIRED_TELEMETRY,
    JupiterQuotaCacheIdentity,
    PR119QuotaCacheError,
    PR119QuotaCachePackage,
    assert_pr119_quota_cache_package,
    evaluate_pr119_quota_cache_package,
)

HASH = "a" * 64


def _complete_package(**overrides: object) -> PR119QuotaCachePackage:
    values: dict[str, object] = {
        "purpose_support": {name: True for name in REQUIRED_PURPOSES},
        "cache_identity_fields": {
            name: True for name in REQUIRED_CACHE_IDENTITY_FIELDS
        },
        "telemetry": {name: True for name in REQUIRED_TELEMETRY},
        "finalization_reserve_configured": True,
        "finalization_quota_reserved": True,
        "discovery_cannot_spend_finalization_reserve": True,
        "shared_quota_authority": "sqlite",
        "shared_quota_keyed_by_api_account": True,
        "cache_reused_before_quota_spend": True,
        "exact_final_build_required": True,
        "retry_after_numeric_supported": True,
        "retry_after_http_date_supported": True,
        "retry_after_propagated_to_quota": True,
        "cache_key_redacts_secret_values": True,
        "cache_key_includes_schema_pin": True,
        "parallel_process_tested": True,
        "chaos_429_tested": True,
        "live_allowed": False,
        "sender_enabled": False,
        "provider_promotion_enabled": False,
        "human_reviewed": True,
        "evidence_sha256": HASH,
    }
    values.update(overrides)
    return PR119QuotaCachePackage(**values)  # type: ignore[arg-type]


def test_pr119_complete_package_is_review_ready() -> None:
    result = assert_pr119_quota_cache_package(_complete_package())

    assert result.review_ready is True
    assert result.live_allowed is False
    assert result.sender_enabled is False
    assert result.provider_promotion_enabled is False
    assert result.blockers == ()
    assert result.state.value == "jupiter-quota-cache-review-ready"


def test_pr119_missing_purpose_blocks_review() -> None:
    purpose_support = {name: True for name in REQUIRED_PURPOSES}
    purpose_support["final_build"] = False

    result = evaluate_pr119_quota_cache_package(
        _complete_package(purpose_support=purpose_support)
    )

    assert result.review_ready is False
    assert "PURPOSE_MISSING:final_build" in result.blockers


def test_pr119_live_sender_or_promotion_flags_fail_closed() -> None:
    result = evaluate_pr119_quota_cache_package(
        _complete_package(
            live_allowed=True,
            sender_enabled=True,
            provider_promotion_enabled=True,
        )
    )

    assert result.review_ready is False
    assert "LIVE_ALLOWED" in result.blockers
    assert "SENDER_ENABLED" in result.blockers
    assert "PROVIDER_PROMOTION_ENABLED" in result.blockers


def test_pr119_retry_after_and_shared_quota_are_required() -> None:
    result = evaluate_pr119_quota_cache_package(
        _complete_package(
            retry_after_propagated_to_quota=False,
            shared_quota_keyed_by_api_account=False,
            parallel_process_tested=False,
        )
    )

    assert result.review_ready is False
    assert "RETRY_AFTER_NOT_PROPAGATED" in result.blockers
    assert "SHARED_QUOTA_NOT_KEYED_BY_API_ACCOUNT" in result.blockers
    assert "PARALLEL_PROCESS_NOT_TESTED" in result.blockers


def test_pr119_cache_identity_is_redaction_safe_and_exact() -> None:
    identity = JupiterQuotaCacheIdentity(
        api_account_identity_hash="sha256:" + HASH,
        request_fingerprint="request-a",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount_base_units=1000,
        taker="11111111111111111111111111111111",
        swap_mode="ExactIn",
        slippage_bps=50,
        purpose="final_build",
        schema_version_pin="jupiter-router-build-2026-07-19",
        max_accounts=64,
        dex_filters=("orca", "raydium"),
    )
    different = JupiterQuotaCacheIdentity(
        api_account_identity_hash="sha256:" + HASH,
        request_fingerprint="request-a",
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount_base_units=2000,
        taker="11111111111111111111111111111111",
        swap_mode="ExactIn",
        slippage_bps=50,
        purpose="final_build",
        schema_version_pin="jupiter-router-build-2026-07-19",
        max_accounts=64,
        dex_filters=("orca", "raydium"),
    )

    assert identity.cache_key.startswith("jupiter:v2:")
    assert identity.cache_key != different.cache_key
    assert HASH not in identity.cache_key


def test_pr119_rejects_invalid_identity_purpose() -> None:
    with pytest.raises(PR119QuotaCacheError):
        JupiterQuotaCacheIdentity(
            api_account_identity_hash="sha256:" + HASH,
            request_fingerprint="request-a",
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            amount_base_units=1000,
            taker="11111111111111111111111111111111",
            swap_mode="ExactIn",
            slippage_bps=50,
            purpose="unknown",
            schema_version_pin="pin",
        )
