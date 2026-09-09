from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

from src.data_plane.mpr41_trusted_provider_data_plane import (
    MPR41_EVIDENCE_KIND,
    MPR41_ID,
    MPR41_SCHEMA_VERSION,
    MPR41EvidenceBundle,
    ProviderResponseEvidence,
    RuntimeSurfaceEvidence,
    TransportPolicyEvidence,
    WebhookIntakeEvidence,
    bundle_from_mapping,
    evaluate_mpr41_evidence,
    scan_text_for_network_bypasses,
    static_contract,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


def valid_bundle() -> MPR41EvidenceBundle:
    return MPR41EvidenceBundle(
        schema_version=MPR41_SCHEMA_VERSION,
        transport=TransportPolicyEvidence(
            authority="canonical-trusted-provider-gateway",
            deny_by_default=True,
            tls_required=True,
            ambient_proxy_trust=False,
            strict_json_duplicate_keys_rejected=True,
            durable_quota=True,
            retry_budget_persisted=True,
            max_response_bytes=65_536,
            total_timeout_ms=2_000,
            allowed_hosts=("api.jupiter.example", "rpc.solana.example"),
        ),
        providers=(
            ProviderResponseEvidence(
                provider="jupiter",
                endpoint="https://api.jupiter.example/swap/v2/build",
                credential_generation_sha256=HASH_A,
                request_sha256=HASH_B,
                response_sha256=HASH_C,
                tls_peer_fingerprint_sha256=HASH_D,
                received_at_unix_ns=1_000,
                context_slot=123,
                response_size_bytes=1024,
                provenance_persisted=True,
            ),
        ),
        webhook=WebhookIntakeEvidence(
            ack_after_durable_commit=True,
            durable_inbox_commit_sha256=HASH_E,
            dedupe_key_sha256=HASH_F,
            batch_atomic=True,
            durable_nack_or_dead_letter=True,
            trusted_forwarded_headers_only=True,
            timestamp_units_validated=True,
            routing_identity_authenticated=True,
            rate_limit_state_bounded=True,
        ),
        runtime_surface=RuntimeSurfaceEvidence(
            source_only=False,
            live_enabled=False,
            signer_loaded=False,
            sender_loaded=False,
            jito_settlement_authority=False,
        ),
        issued_at_ns=1_000,
        evidence_sha256=HASH_A,
    )


def test_valid_data_plane_evidence_is_default_off_accepted() -> None:
    decision = evaluate_mpr41_evidence(valid_bundle())

    assert decision.accepted
    assert decision.evidence_kind == MPR41_EVIDENCE_KIND
    assert decision.provider_network_allowed is True
    assert decision.webhook_ack_authorized is True
    assert decision.live_enabled is False
    assert decision.signer_loaded is False
    assert decision.sender_loaded is False
    assert decision.to_dict()["production_ready"] is False
    assert "MPR41_TRUSTED_DATA_PLANE_ACCEPTED_DEFAULT_OFF" in decision.reason_codes


def test_ambient_proxy_or_non_https_provider_blocks() -> None:
    bundle = valid_bundle()
    transport = replace(bundle.transport, ambient_proxy_trust=True)
    provider = replace(bundle.providers[0], endpoint="http://api.jupiter.example/quote")

    decision = evaluate_mpr41_evidence(
        replace(bundle, transport=transport, providers=(provider,))
    )

    assert not decision.accepted
    assert "MPR41_AMBIENT_PROXY_FORBIDDEN" in decision.reason_codes
    assert "MPR41_PROVIDER_ENDPOINT_HTTPS" in decision.reason_codes


def test_webhook_ack_must_be_durability_bound() -> None:
    bundle = valid_bundle()
    webhook = replace(
        bundle.webhook,
        ack_after_durable_commit=False,
        durable_nack_or_dead_letter=False,
    )

    decision = evaluate_mpr41_evidence(replace(bundle, webhook=webhook))

    assert not decision.accepted
    assert "MPR41_WEBHOOK_ACK_BEFORE_DURABILITY" in decision.reason_codes
    assert "MPR41_WEBHOOK_NACK_REQUIRED" in decision.reason_codes


def test_live_signer_sender_or_jito_settlement_claims_block() -> None:
    bundle = valid_bundle()
    surface = replace(
        bundle.runtime_surface,
        live_enabled=True,
        signer_loaded=True,
        sender_loaded=True,
        jito_settlement_authority=True,
    )

    decision = evaluate_mpr41_evidence(replace(bundle, runtime_surface=surface))

    assert not decision.accepted
    assert "MPR41_LIVE_FORBIDDEN" in decision.reason_codes
    assert "MPR41_SIGNER_FORBIDDEN" in decision.reason_codes
    assert "MPR41_SENDER_FORBIDDEN" in decision.reason_codes
    assert "MPR41_JITO_SETTLEMENT_FORBIDDEN" in decision.reason_codes


def test_network_bypass_scanner_finds_direct_clients() -> None:
    content = """
import aiohttp
import requests

async def fetch():
    aiohttp.ClientSession(trust_env=True)
    requests.get("https://example.invalid")
"""

    findings = scan_text_for_network_bypasses("src/legacy_provider.py", content)

    rules = {finding.rule for finding in findings}
    assert "MPR41_DIRECT_AIOHTTP_CLIENT" in rules
    assert "MPR41_DIRECT_REQUESTS_CALL" in rules
    assert "MPR41_AMBIENT_PROXY_TRUST" in rules


def test_network_bypass_scanner_allows_gateway_files() -> None:
    content = "aiohttp.ClientSession(trust_env=True)\n"

    findings = scan_text_for_network_bypasses("src/provider_gateway/client.py", content)

    assert findings == ()


def test_json_decoder_preserves_contract() -> None:
    bundle = valid_bundle()
    payload = {
        "schema_version": bundle.schema_version,
        "transport": asdict(bundle.transport),
        "providers": [asdict(provider) for provider in bundle.providers],
        "webhook": asdict(bundle.webhook),
        "runtime_surface": asdict(bundle.runtime_surface),
        "issued_at_ns": bundle.issued_at_ns,
        "evidence_sha256": bundle.evidence_sha256,
    }

    decoded = bundle_from_mapping(json.loads(json.dumps(payload, sort_keys=True)))
    decision = evaluate_mpr41_evidence(decoded)

    assert decision.accepted


def test_packaged_contract_matches_static_contract() -> None:
    path = Path("src/resources/mpr41_trusted_provider_data_plane_contract.json")
    packaged = json.loads(path.read_text(encoding="utf-8"))
    runtime = static_contract()

    assert packaged["schema_version"] == MPR41_SCHEMA_VERSION
    assert packaged["mpr_id"] == MPR41_ID
    assert packaged["evidence_kind"] == runtime["evidence_kind"]
    assert packaged["default_off"] is True
    assert packaged["production_ready"] is False
    assert set(packaged["network_bypass_rules"]) == set(runtime["network_bypass_rules"])
