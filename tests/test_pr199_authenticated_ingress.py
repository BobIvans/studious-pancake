from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.providers.helius import (
    CredentialBinding,
    CredentialState,
    IngressConnectionMetadata,
    IngressGatewayPolicy,
    IngressRejectReason,
    authenticate_inbound_request,
)
from src.providers.helius.delivery import (
    DeliveryDecision,
    HeliusDeliveryConfig,
    HeliusDeliveryPlane,
)


def _policy(
    *credentials: CredentialBinding,
    allow_direct_peers: bool = False,
) -> IngressGatewayPolicy:
    return IngressGatewayPolicy(
        expected_webhook_id="expected-wh",
        config_generation="helius-mainnet/gen-7",
        credentials=credentials
        or (
            CredentialBinding(
                "helius-ingress",
                "v7",
                "Bearer rotated",
            ),
        ),
        trusted_proxy_cidrs=("10.20.0.0/16",),
        allowed_source_cidrs=("203.0.113.0/24",),
        required_peer_identities=("gateway/helius-prod",),
        network="mainnet-genesis",
        webhook_type="enhanced_transaction",
        allow_direct_peers=allow_direct_peers,
    )


def _metadata(
    *,
    immediate_peer: str = "10.20.0.5",
    transport_tls: bool = False,
    generation: str = "helius-mainnet/gen-7",
    observed_webhook_id: str | None = "expected-wh",
    provider_delivery_id: str | None = "delivery-1",
    peer_identity: str | None = "gateway/helius-prod",
) -> IngressConnectionMetadata:
    return IngressConnectionMetadata(
        immediate_peer=immediate_peer,
        transport_tls=transport_tls,
        config_generation=generation,
        observed_webhook_id=observed_webhook_id,
        peer_identity=peer_identity,
        provider_delivery_id=provider_delivery_id,
        received_monotonic_ns=100,
        received_utc_ns=1_800_000_000_000_000_000,
    )


def _headers(authorization: str = "Bearer rotated") -> dict[str, str]:
    return {
        "authorization": authorization,
        "x-forwarded-for": "203.0.113.42",
        "x-forwarded-proto": "https",
    }


def _body(signature: str = "SIG-1") -> bytes:
    return json.dumps([{"signature": signature, "slot": 100}]).encode()


def _plane(tmp_path: Path, policy: IngressGatewayPolicy | None) -> HeliusDeliveryPlane:
    return HeliusDeliveryPlane(
        HeliusDeliveryConfig(
            auth_header="Bearer primary",
            store_path=tmp_path / "helius.sqlite3",
            webhook_id="expected-wh",
            cluster_genesis="mainnet-genesis",
        ),
        ingress_policy=policy,
    )


def test_direct_delivery_import_receives_pr199_boundary() -> None:
    assert "request_metadata" in HeliusDeliveryPlane.accept_delivery.__annotations__


def test_arbitrary_caller_webhook_id_is_rejected_before_store(tmp_path: Path) -> None:
    plane = _plane(tmp_path, _policy())

    outcome = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body(),
        webhook_id="attacker-wh",
        request_metadata=_metadata(),
    )

    assert outcome.decision is DeliveryDecision.REJECTED
    assert outcome.http_status == 403
    assert outcome.reason == IngressRejectReason.WEBHOOK_ID_MISMATCH.value
    assert plane.store.inbox_count() == 0
    assert plane.inbound_request_count() == 0


def test_static_header_without_gateway_context_is_not_origin_proof(
    tmp_path: Path,
) -> None:
    plane = _plane(tmp_path, _policy())

    outcome = plane.accept_delivery(headers=_headers(), raw_body=_body())

    assert outcome.http_status == 403
    assert outcome.reason == IngressRejectReason.MISSING_REQUEST_METADATA.value
    assert plane.store.inbox_count() == 0


def test_trusted_gateway_context_is_durable_and_secret_safe(tmp_path: Path) -> None:
    plane = _plane(tmp_path, _policy())

    outcome = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body(),
        request_metadata=_metadata(),
    )

    assert outcome.http_status == 200
    assert outcome.delivery_id is not None
    assert plane.inbound_request_count() == 1
    context = plane.request_context_for_delivery(outcome.delivery_id)
    assert context is not None
    assert context["webhook_id"] == "expected-wh"
    assert context["config_generation"] == "helius-mainnet/gen-7"
    assert context["credential_id"] == "helius-ingress"
    assert context["credential_version"] == "v7"
    assert context["client_ip"] == "203.0.113.42"
    assert context["trusted_proxy_chain"] == ("203.0.113.42", "10.20.0.5")
    assert context["tls_verified"] is True
    assert context["provider_origin_cryptographically_proven"] is False
    assert "Bearer rotated" not in repr(context)


def test_untrusted_forwarded_headers_cannot_change_direct_client_identity() -> None:
    policy = IngressGatewayPolicy(
        expected_webhook_id="expected-wh",
        config_generation="gen-1",
        credentials=(CredentialBinding("direct", "v1", "Bearer direct"),),
        trusted_proxy_cidrs=("10.0.0.0/8",),
        allowed_source_cidrs=("198.51.100.0/24",),
        network="mainnet-genesis",
        allow_direct_peers=True,
    )
    context = authenticate_inbound_request(
        policy=policy,
        headers={
            "authorization": "Bearer direct",
            "x-forwarded-for": "203.0.113.99",
            "x-forwarded-proto": "http",
        },
        raw_body=_body(),
        metadata=IngressConnectionMetadata(
            immediate_peer="198.51.100.10",
            transport_tls=True,
            config_generation="gen-1",
            observed_webhook_id="expected-wh",
            received_monotonic_ns=1,
            received_utc_ns=2,
        ),
    )

    assert context.client_ip == "198.51.100.10"
    assert context.trusted_proxy_chain == ()
    assert context.tls_verified is True


def test_direct_bypass_around_required_gateway_is_rejected(tmp_path: Path) -> None:
    plane = _plane(tmp_path, _policy())

    outcome = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body(),
        request_metadata=_metadata(
            immediate_peer="198.51.100.10",
            transport_tls=True,
            peer_identity="gateway/helius-prod",
        ),
    )

    assert outcome.http_status == 403
    assert outcome.reason == IngressRejectReason.UNTRUSTED_GATEWAY.value


def test_tls_and_config_generation_are_fail_closed(tmp_path: Path) -> None:
    plane = _plane(tmp_path, _policy())
    insecure_headers = _headers()
    insecure_headers["x-forwarded-proto"] = "http"

    insecure = plane.accept_delivery(
        headers=insecure_headers,
        raw_body=_body(),
        request_metadata=_metadata(provider_delivery_id="delivery-tls"),
    )
    wrong_generation = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body("SIG-2"),
        request_metadata=_metadata(
            generation="helius-mainnet/gen-6",
            provider_delivery_id="delivery-generation",
        ),
    )

    assert insecure.reason == IngressRejectReason.TLS_REQUIRED.value
    assert (
        wrong_generation.reason == IngressRejectReason.CONFIG_GENERATION_MISMATCH.value
    )
    assert plane.store.inbox_count() == 0


def test_credential_rotation_overlap_and_immediate_revocation(tmp_path: Path) -> None:
    old = CredentialBinding("helius-ingress", "v6", "Bearer old")
    new_overlap = CredentialBinding(
        "helius-ingress",
        "v7",
        "Bearer new",
        state=CredentialState.OVERLAP,
    )
    plane = _plane(tmp_path, _policy(old, new_overlap))

    accepted_old = plane.accept_delivery(
        headers=_headers("Bearer old"),
        raw_body=_body("SIG-OLD"),
        request_metadata=_metadata(provider_delivery_id="delivery-old"),
    )
    assert accepted_old.http_status == 200

    plane.replace_ingress_policy(
        _policy(
            CredentialBinding(
                "helius-ingress",
                "v6",
                "Bearer old",
                state=CredentialState.REVOKED,
            ),
            CredentialBinding("helius-ingress", "v7", "Bearer new"),
        )
    )
    revoked = plane.accept_delivery(
        headers=_headers("Bearer old"),
        raw_body=_body("SIG-REVOKED"),
        request_metadata=_metadata(provider_delivery_id="delivery-revoked"),
    )
    accepted_new = plane.accept_delivery(
        headers=_headers("Bearer new"),
        raw_body=_body("SIG-NEW"),
        request_metadata=_metadata(provider_delivery_id="delivery-new"),
    )

    assert revoked.http_status == 401
    assert revoked.reason == IngressRejectReason.CREDENTIAL_REVOKED.value
    assert accepted_new.http_status == 200
    assert plane.inbound_request_count() == 2


def test_provider_delivery_id_cannot_be_rebound_to_different_body(
    tmp_path: Path,
) -> None:
    plane = _plane(tmp_path, _policy())
    first = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body("SIG-A"),
        request_metadata=_metadata(provider_delivery_id="provider-id-1"),
    )
    conflict = plane.accept_delivery(
        headers=_headers(),
        raw_body=_body("SIG-B"),
        request_metadata=_metadata(provider_delivery_id="provider-id-1"),
    )

    assert first.http_status == 200
    assert conflict.http_status == 409
    assert conflict.reason == IngressRejectReason.DELIVERY_METADATA_CONFLICT.value
    assert plane.store.inbox_count() == 1


def test_compatibility_mode_keeps_server_owned_identity(tmp_path: Path) -> None:
    plane = _plane(tmp_path, None)
    accepted = plane.accept_delivery(
        headers={"authorization": "Bearer primary"},
        raw_body=_body(),
    )
    rejected = plane.accept_delivery(
        headers={"authorization": "Bearer primary"},
        raw_body=_body("SIG-2"),
        webhook_id="other-wh",
    )

    assert accepted.http_status == 200
    assert rejected.http_status == 403
    assert rejected.reason == IngressRejectReason.WEBHOOK_ID_MISMATCH.value


def test_policy_rejects_duplicate_credential_authority() -> None:
    with pytest.raises(ValueError, match="authorization values"):
        _policy(
            CredentialBinding("helius", "v1", "Bearer duplicate"),
            CredentialBinding("helius", "v2", "Bearer duplicate"),
        )
