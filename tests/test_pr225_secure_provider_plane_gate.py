from __future__ import annotations

from dataclasses import replace

from src.pr225_secure_provider_plane_gate import (
    PR225FailureCode,
    PR225EvidenceBundle,
    ProviderCapabilities,
    ProviderContract,
    QuoteRequest,
    RawResponseProvenance,
    RetryPolicyEvidence,
    TransportPolicyEvidence,
    QuotaAuthorityEvidence,
    NormalizedQuote,
    DiscoveryCandidate,
    InstalledProviderCycleEvidence,
    evaluate_pr225_evidence,
    semantic_quote_identity,
    SCHEMA_VERSION,
    REQUIRED_FINDINGS,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64
HASH_4 = "4" * 64
HASH_5 = "5" * 64
HASH_6 = "6" * 64
HASH_7 = "7" * 64
HASH_8 = "8" * 64
MINT_A = "So11111111111111111111111111111111111111112"
MINT_B = "11111111111111111111111111111111"


def valid_quote(provider: str = "jupiter") -> NormalizedQuote:
    request = QuoteRequest(
        provider=provider,
        input_mint=MINT_A,
        output_mint=MINT_B,
        amount=1_000_000,
        slippage_bps=50,
        request_policy_sha256=HASH_A,
    )
    provenance = RawResponseProvenance(
        provider=provider,
        endpoint=f"https://api.{provider}.example/quote",
        credential_generation_sha256=HASH_B,
        request_sha256=HASH_C,
        raw_response_sha256=HASH_D,
        status_code=200,
        header_digest_sha256=HASH_E,
        received_at_unix_ns=1_000,
        context_slot=99,
        provider_timestamp_unix_ns=990,
        parsed_keys=("routePlan", "outAmount", "otherAmountThreshold"),
        schema_generation_sha256=HASH_1,
    )
    capabilities = ProviderCapabilities(
        provider=provider,
        exact_in_supported=True,
        guaranteed_minimum_output_supported=True,
        explicit_expiry_supported=True,
        executable_artifact_supported=True,
    )
    return NormalizedQuote(
        request=request,
        provenance=provenance,
        capabilities=capabilities,
        minimum_output_amount=1_010_000,
        expected_output_amount=1_020_000,
        expires_at_unix_ns=2_000,
        executable_artifact_sha256=HASH_2,
        route_plan_sha256=HASH_3,
        fee_identity_sha256=HASH_4,
    )


def valid_bundle() -> PR225EvidenceBundle:
    quote = valid_quote()
    identity = semantic_quote_identity(quote)
    return PR225EvidenceBundle(
        schema_version=SCHEMA_VERSION,
        covered_findings=REQUIRED_FINDINGS,
        installed_cycle=InstalledProviderCycleEvidence(
            installed_wheel_sha256=HASH_A,
            command_surface_sha256=HASH_B,
            configured_endpoint="https://api.jupiter.example/quote",
            transport_owner="owned-hardened-transport",
            provider_cycle_non_empty=True,
            missing_transport_blocks_startup=True,
            sender_free=True,
        ),
        providers=(
            ProviderContract(
                provider="jupiter",
                endpoint="https://api.jupiter.example/quote",
                credential_generation_sha256=HASH_B,
                schema_generation_sha256=HASH_1,
                allowed_methods=("GET", "POST"),
            ),
        ),
        transport=TransportPolicyEvidence(
            owner="owned-hardened-transport",
            deny_by_default=True,
            allowed_hosts=("api.jupiter.example",),
            resolved_ip_classes_denied=("private", "loopback", "link-local"),
            redirect_policy="revalidate-each-hop",
            tls_peer_fingerprint_sha256=HASH_5,
            ca_bundle_sha256=HASH_6,
            total_deadline_ms=2_000,
            max_response_bytes=65_536,
            strict_json_duplicate_keys_rejected=True,
            redaction_policy_sha256=HASH_7,
        ),
        retry_policy=RetryPolicyEvidence(
            retries_non_idempotent_post=False,
            provider_idempotency_contract_sha256=None,
            retry_after_http_date_supported=True,
            jitter_enabled=True,
            total_deadline_covers_retries=True,
            cancellation_cleanup_proven=True,
        ),
        quota=QuotaAuthorityEvidence(
            authority="durable-account-wide-quota",
            durable=True,
            account_wide=True,
            credential_generation_sha256=HASH_B,
            endpoint_generation_sha256=HASH_C,
            account_plan_sha256=HASH_D,
            serialized_cross_process=True,
            unknown_purpose_fails_closed=True,
            unknown_token_fails_closed=True,
            two_process_race_proof_sha256=HASH_E,
            persisted_cooldown_proof_sha256=HASH_8,
            exact_once_mark_used=True,
        ),
        quotes=(quote,),
        discovery_candidates=(
            DiscoveryCandidate(
                quote_identity_sha256=identity,
                guaranteed_profit_base_units=1_000,
                risk_bps=15,
                executable_artifact_sha256=HASH_2,
            ),
        ),
        selected_quote_identity_sha256=identity,
        runtime_capabilities={
            "live_enabled": False,
            "sender_loaded": False,
            "signer_loaded": False,
        },
    )


def test_valid_evidence_is_review_ready() -> None:
    report = evaluate_pr225_evidence(valid_bundle())
    assert report.ok
    assert report.provider_plane_review_allowed is True
    assert report.provider_network_allowed is False
    assert report.live_execution_allowed is False


def test_bool_amount_is_rejected() -> None:
    bundle = valid_bundle()
    bad_quote = replace(bundle.quotes[0], request=replace(bundle.quotes[0].request, amount=True))
    report = evaluate_pr225_evidence(replace(bundle, quotes=(bad_quote,)))
    assert not report.ok
    assert PR225FailureCode.INVALID_QUOTE_DOMAIN in {item.code for item in report.violations}


def test_same_input_and_output_mint_is_rejected() -> None:
    bundle = valid_bundle()
    request = replace(bundle.quotes[0].request, output_mint=MINT_A)
    bad_quote = replace(bundle.quotes[0], request=request)
    report = evaluate_pr225_evidence(replace(bundle, quotes=(bad_quote,)))
    assert not report.ok
    assert "input_mint and output_mint" in report.violations[0].detail


def test_dangerous_unknown_provider_response_field_blocks() -> None:
    bundle = valid_bundle()
    provenance = replace(
        bundle.quotes[0].provenance,
        parsed_keys=("routePlan", "swapTransaction"),
    )
    bad_quote = replace(bundle.quotes[0], provenance=provenance)
    report = evaluate_pr225_evidence(replace(bundle, quotes=(bad_quote,)))
    assert not report.ok
    assert PR225FailureCode.INVALID_QUOTE_DOMAIN in {item.code for item in report.violations}


def test_quote_identity_separates_provider_and_artifact() -> None:
    q1 = valid_quote("jupiter")
    q2 = replace(valid_quote("jupiter"), executable_artifact_sha256="9" * 64)
    q3 = replace(valid_quote("okx"), executable_artifact_sha256=q1.executable_artifact_sha256)
    identities = {semantic_quote_identity(q1), semantic_quote_identity(q2), semantic_quote_identity(q3)}
    assert len(identities) == 3


def test_injected_client_bypass_fails_closed() -> None:
    bundle = valid_bundle()
    transport = replace(bundle.transport, injected_client_can_bypass=True)
    report = evaluate_pr225_evidence(replace(bundle, transport=transport))
    assert not report.ok
    assert PR225FailureCode.UNSAFE_TRANSPORT in {item.code for item in report.violations}


def test_unknown_quota_purpose_and_token_must_fail_closed() -> None:
    bundle = valid_bundle()
    quota = replace(bundle.quota, unknown_purpose_fails_closed=False)
    report = evaluate_pr225_evidence(replace(bundle, quota=quota))
    assert not report.ok
    assert PR225FailureCode.NON_DURABLE_QUOTA in {item.code for item in report.violations}


def test_discovery_order_uses_guaranteed_minimum_output() -> None:
    bundle = valid_bundle()
    low = bundle.discovery_candidates[0]
    high = replace(
        low,
        guaranteed_profit_base_units=2_000,
        quote_identity_sha256=low.quote_identity_sha256,
    )
    report = evaluate_pr225_evidence(
        replace(
            bundle,
            discovery_candidates=(low, high),
            selected_quote_identity_sha256=low.quote_identity_sha256,
        )
    )
    assert not report.ok
    assert PR225FailureCode.INVALID_DISCOVERY_SELECTION in {
        item.code for item in report.violations
    }
