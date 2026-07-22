from __future__ import annotations

import pytest

from src.providers import (
    AuthMode,
    OfficialReference,
    PromotionState,
    ProviderConformanceError,
    ProviderConformanceManifest,
    ProviderId,
    ProviderProtocolEvidence,
    Purpose,
    evaluate_provider_conformance,
    required_pr_b_readonly_surfaces,
)

pytestmark = pytest.mark.unit

_HASH = "a" * 64
_REF = OfficialReference(
    source_url="https://developers.jup.ag/docs/api-reference/swap/build",
    reviewed_on="2026-07-22",
    reviewer="pr-b-review",
)


def _evidence(
    provider: ProviderId,
    purpose: Purpose,
    *,
    endpoint: str,
    method: str = "GET",
    auth_mode: AuthMode = AuthMode.API_KEY,
    promotion_state: PromotionState = PromotionState.PROTECTED_PROBE,
    freshness_contract: str = "rooted-slot-and-expiry-bound",
    quota_contract: str = "bounded shared quota",
    consistency_contract: str = "replay fixture and drift revocation",
) -> ProviderProtocolEvidence:
    return ProviderProtocolEvidence(
        provider=provider,
        purpose=purpose,
        endpoint=endpoint,
        method=method,
        auth_mode=auth_mode,
        request_schema_sha256=_HASH,
        response_schema_sha256="b" * 64,
        credentialed_probe_sha256="c" * 64,
        negative_fixture_sha256="d" * 64,
        max_body_bytes=1_000_000,
        timeout_ms=5_000,
        retry_budget=2,
        freshness_contract=freshness_contract,
        quota_contract=quota_contract,
        consistency_contract=consistency_contract,
        promotion_state=promotion_state,
        official_reference=_REF,
    )


def _complete_manifest() -> ProviderConformanceManifest:
    return ProviderConformanceManifest(
        schema_version="mega-pr-b.provider-conformance.v1",
        evidences=(
            _evidence(
                ProviderId.JUPITER,
                Purpose.ROUTE_BUILD,
                endpoint="https://api.jup.ag/swap/v2/build",
                method="POST",
            ),
            _evidence(
                ProviderId.MARGINFI,
                Purpose.PROGRAM_ATTESTATION,
                endpoint="https://docs.marginfi.com/protocol-design",
                method="programdata-attestation",
                auth_mode=AuthMode.PROGRAM_DEPLOYMENT,
                freshness_contract="coherent rooted slot with ProgramData evidence",
                consistency_contract="fee and repayment from protocol evidence",
            ),
            _evidence(
                ProviderId.HELIUS,
                Purpose.WEBHOOK_DELIVERY,
                endpoint="https://api.helius.xyz/v0/webhooks",
                method="POST",
                auth_mode=AuthMode.HEADER,
            ),
            _evidence(
                ProviderId.JITO,
                Purpose.TIP_ACCOUNT_DISCOVERY,
                endpoint="https://mainnet.block-engine.jito.wtf/api/v1/bundles",
                method="getTipAccounts",
                auth_mode=AuthMode.NONE,
            ),
            _evidence(
                ProviderId.SOLANA_RPC,
                Purpose.ROOTED_RPC_READ,
                endpoint="https://rpc.example.invalid",
                method="getTransaction",
                auth_mode=AuthMode.RPC_PROVIDER_KEY,
            ),
            _evidence(
                ProviderId.KAMINO,
                Purpose.UNSUPPORTED_REGISTRY,
                endpoint="https://github.com/Kamino-Finance/klend-sdk",
                method="supported-combinations-registry",
                promotion_state=PromotionState.BLOCKED,
            ),
        ),
    )


def test_pr_b_complete_readonly_manifest_is_admitted() -> None:
    report = evaluate_provider_conformance(
        _complete_manifest(),
        required=required_pr_b_readonly_surfaces(),
    )

    assert report.admitted is True
    assert report.blockers == ()
    assert report.provider_states["jupiter:route-build"] == "protected-probe"
    assert report.provider_states["kamino:unsupported-registry"] == "blocked"


def test_pr_b_blocks_legacy_jupiter_endpoint() -> None:
    with pytest.raises(ProviderConformanceError, match="Jupiter"):
        _evidence(
            ProviderId.JUPITER,
            Purpose.ROUTE_BUILD,
            endpoint="https://api.jup.ag/swap/v1/quote",
            method="GET",
        )


def test_pr_b_blocks_jito_rest_tip_account_shape() -> None:
    with pytest.raises(ProviderConformanceError, match="Jito"):
        _evidence(
            ProviderId.JITO,
            Purpose.TIP_ACCOUNT_DISCOVERY,
            endpoint="https://mainnet.block-engine.jito.wtf/api/v1/tip_accounts",
            method="GET",
            auth_mode=AuthMode.NONE,
        )


def test_pr_b_helius_delivery_requires_authorization_header() -> None:
    with pytest.raises(ProviderConformanceError, match="Helius"):
        _evidence(
            ProviderId.HELIUS,
            Purpose.WEBHOOK_DELIVERY,
            endpoint="https://api.helius.xyz/v0/webhooks",
            method="POST",
            auth_mode=AuthMode.API_KEY,
        )


def test_pr_b_marginfi_env_fee_truth_blocks_admission() -> None:
    manifest = ProviderConformanceManifest(
        schema_version="mega-pr-b.provider-conformance.v1",
        evidences=(
            _evidence(
                ProviderId.MARGINFI,
                Purpose.PROGRAM_ATTESTATION,
                endpoint="https://docs.marginfi.com/protocol-design",
                method="programdata-attestation",
                auth_mode=AuthMode.PROGRAM_DEPLOYMENT,
                consistency_contract="uses env percentage for flash loan fee",
            ),
        ),
    )

    report = evaluate_provider_conformance(manifest)

    assert report.admitted is False
    assert report.blockers == ("marginfi:fee-repayment-truth-not-evidence-bound",)


def test_pr_b_kamino_unsupported_registry_cannot_be_promoted() -> None:
    manifest = ProviderConformanceManifest(
        schema_version="mega-pr-b.provider-conformance.v1",
        evidences=(
            _evidence(
                ProviderId.KAMINO,
                Purpose.UNSUPPORTED_REGISTRY,
                endpoint="https://github.com/Kamino-Finance/klend-sdk",
                method="supported-combinations-registry",
                promotion_state=PromotionState.PROTECTED_PROBE,
            ),
        ),
    )

    report = evaluate_provider_conformance(manifest)

    assert report.admitted is False
    assert report.blockers == ("kamino:unsupported-combination-promoted",)


def test_pr_b_rejects_placeholder_hashes() -> None:
    with pytest.raises(ProviderConformanceError, match="sha256"):
        ProviderProtocolEvidence(
            provider=ProviderId.SOLANA_RPC,
            purpose=Purpose.ROOTED_RPC_READ,
            endpoint="https://rpc.example.invalid",
            method="getTransaction",
            auth_mode=AuthMode.RPC_PROVIDER_KEY,
            request_schema_sha256="0" * 64,
            response_schema_sha256="b" * 64,
            credentialed_probe_sha256="c" * 64,
            negative_fixture_sha256="d" * 64,
            max_body_bytes=1_000_000,
            timeout_ms=5_000,
            retry_budget=2,
            freshness_contract="rooted slot",
            quota_contract="bounded quota",
            consistency_contract="quorum fixture",
            promotion_state=PromotionState.PROTECTED_PROBE,
            official_reference=_REF,
        )
