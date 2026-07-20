from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import time
from typing import Mapping
from uuid import uuid4

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

import src.submission as submission
from src.submission import (
    CanonicalPermitBoundSender,
    CanonicalSenderConfig,
    HttpResponse,
    JitoCredentialMode,
    JitoUuidAuth,
    SignedPayload,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionObservation,
    SubmissionState,
    TransportKind,
    consolidate_submission_observations,
    inspect_exactly_one_system_tip,
    permit_request_from_payload,
)

PAYER = Keypair.from_seed(bytes([11]) * 32)
RECIPIENT = Keypair.from_seed(bytes([12]) * 32).pubkey()
TIP = Keypair.from_seed(bytes([13]) * 32).pubkey()
BLOCKHASH = Hash.from_bytes(bytes(reversed(range(32))))


class FakeHttp:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    async def post_json(
        self,
        url: str,
        body: Mapping[str, object],
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls.append((url, body, dict(headers), timeout_seconds))
        return self.responder(url, body, headers)


def payload_with_tip() -> SignedPayload:
    instructions = [
        transfer(
            TransferParams(
                from_pubkey=PAYER.pubkey(),
                to_pubkey=RECIPIENT,
                lamports=1,
            )
        ),
        transfer(
            TransferParams(
                from_pubkey=PAYER.pubkey(),
                to_pubkey=TIP,
                lamports=1_000,
            )
        ),
    ]
    message = MessageV0.try_compile(PAYER.pubkey(), instructions, [], BLOCKHASH)
    raw = bytes(VersionedTransaction(message, [PAYER]))
    initial = SignedPayload.from_wire_transactions([raw])
    evidence = inspect_exactly_one_system_tip(
        instructions=instructions,
        message_hash=initial.primary_message_hash,
        payer=PAYER.pubkey(),
        approved_accounts={str(TIP)},
        expected_account=TIP,
        expected_lamports=1_000,
        static_account_keys={str(key) for key in message.account_keys},
    )
    return SignedPayload.from_wire_transactions([raw], tip_evidence=evidence)


def permit_for(sender: CanonicalPermitBoundSender, payload: SignedPayload):
    return sender.issuer.issue(
        permit_request_from_payload(
            attempt_id="pr063-attempt",
            transport=sender.config.transport,
            exact_simulation_hash=payload.primary_message_hash,
            payload=payload,
            expires_at_ns=time.time_ns() + 10_000_000_000,
            last_valid_block_height=500,
            min_context_slot=100,
        )
    )


@pytest.mark.asyncio
async def test_default_jito_mode_emits_no_uuid_header() -> None:
    payload = payload_with_tip()

    def response(url, body, headers):
        assert url.endswith("/api/v1/transactions?bundleOnly=true")
        assert "x-jito-auth" not in headers
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": payload.signatures[0]},
            {"x-bundle-id": "a" * 64},
        )

    sender = CanonicalPermitBoundSender(
        CanonicalSenderConfig(
            transport=TransportKind.JITO_SINGLE,
            rpc_endpoint="https://rpc.example",
            jito_base_url="https://mainnet.block-engine.jito.wtf",
            compile_time_enabled=True,
            config_enabled=True,
        ),
        FakeHttp(response),
    )
    ack = await sender.submit(
        permit_for(sender, payload),
        payload,
        payload.primary_message_hash,
    )
    assert ack.state is SubmissionState.ACCEPTED
    assert ack.bundle_id == "a" * 64


@pytest.mark.asyncio
async def test_uuid_mode_requires_and_emits_uuid_header() -> None:
    with pytest.raises(ValueError, match="requires jito_uuid_auth"):
        CanonicalSenderConfig(
            transport=TransportKind.JITO_BUNDLE,
            rpc_endpoint="https://rpc.example",
            jito_base_url="https://mainnet.block-engine.jito.wtf",
            jito_credential_mode=JitoCredentialMode.UUID,
        )

    payload = payload_with_tip()
    auth_value = str(uuid4())

    def response(_url, body, headers):
        assert headers["x-jito-auth"] == auth_value
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": "b" * 64},
        )

    sender = CanonicalPermitBoundSender(
        CanonicalSenderConfig(
            transport=TransportKind.JITO_BUNDLE,
            rpc_endpoint="https://rpc.example",
            jito_base_url="https://mainnet.block-engine.jito.wtf",
            jito_credential_mode=JitoCredentialMode.UUID,
            jito_uuid_auth=JitoUuidAuth.parse(auth_value),
            compile_time_enabled=True,
            config_enabled=True,
        ),
        FakeHttp(response),
    )
    ack = await sender.submit(
        permit_for(sender, payload),
        payload,
        payload.primary_message_hash,
    )
    assert ack.bundle_id == "b" * 64


def test_default_mode_rejects_accidental_uuid_credential() -> None:
    with pytest.raises(ValueError, match="must not emit UUID credentials"):
        CanonicalSenderConfig(
            transport=TransportKind.JITO_SINGLE,
            rpc_endpoint="https://rpc.example",
            jito_base_url="https://mainnet.block-engine.jito.wtf",
            jito_uuid_auth=JitoUuidAuth.parse(str(uuid4())),
        )


@pytest.mark.asyncio
async def test_transport_mismatch_is_rejected_before_network() -> None:
    payload = payload_with_tip()

    def reject_network(_url, _body, _headers):
        raise AssertionError("network must not be called")

    sender = CanonicalPermitBoundSender(
        CanonicalSenderConfig(
            transport=TransportKind.JITO_SINGLE,
            rpc_endpoint="https://rpc.example",
            jito_base_url="https://mainnet.block-engine.jito.wtf",
            compile_time_enabled=True,
            config_enabled=True,
        ),
        FakeHttp(reject_network),
    )
    permit = replace(permit_for(sender, payload), transport=TransportKind.RPC)

    with pytest.raises(SubmissionError) as raised:
        await sender.submit(permit, payload, payload.primary_message_hash)
    assert raised.value.code is SubmissionErrorCode.PERMIT_INVALID


def test_jito_landed_without_signature_proof_stays_ambiguous() -> None:
    report = consolidate_submission_observations(
        TransportKind.JITO_BUNDLE,
        (
            SubmissionObservation(
                SubmissionState.UNKNOWN,
                "solana.getSignatureStatuses",
                1,
                reason="signature missing",
            ),
            SubmissionObservation(
                SubmissionState.LANDED,
                "jito.getInflightBundleStatuses",
                2,
                provider_status="Landed",
            ),
        ),
    )
    assert report.state is SubmissionState.UNKNOWN
    assert report.ambiguous is True
    assert report.automatic_resubmit_allowed is False


def test_onchain_landing_is_authoritative_but_never_auto_resubmits() -> None:
    report = consolidate_submission_observations(
        TransportKind.JITO_SINGLE,
        (
            SubmissionObservation(
                SubmissionState.LANDED,
                "solana.getSignatureStatuses",
                3,
                confirmation_status="confirmed",
            ),
            SubmissionObservation(
                SubmissionState.LANDED,
                "jito.getBundleStatuses",
                4,
                provider_status="confirmed",
            ),
        ),
    )
    assert report.state is SubmissionState.LANDED
    assert report.ambiguous is False
    assert report.automatic_resubmit_allowed is False


def test_package_all_prefers_canonical_sender_without_breaking_compat_imports() -> None:
    assert "CanonicalPermitBoundSender" in submission.__all__
    assert "CanonicalSenderConfig" in submission.__all__
    assert "RpcSender" not in submission.__all__
    assert "JitoSender" not in submission.__all__
    assert submission.RpcSender is not None
    assert submission.JitoSender is not None


def test_sanitized_contract_fixture_matches_canonical_policy() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "pr063"
            / "official_sender_contract.json"
        ).read_text(encoding="utf-8")
    )
    assert fixture["solana"]["submit_method"] == "sendTransaction"
    assert fixture["solana"]["successful_submit_is_landing_proof"] is False
    assert fixture["jito"]["default_send_requires_auth"] is False
    assert fixture["jito"]["bundle_transaction_min"] == 1
    assert fixture["jito"]["bundle_transaction_max"] == 5
    assert fixture["jito"]["minimum_tip_lamports"] == 1_000
    assert fixture["safety"] == {
        "automatic_duplicate_submission": False,
        "exactly_one_tip": True,
        "permit_bound_only": True,
        "transport_fallback": False,
    }
