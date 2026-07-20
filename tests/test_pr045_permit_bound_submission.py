from __future__ import annotations

from dataclasses import dataclass
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

from src.execution.models import ExecutionState
from src.submission import (
    ErrorDisposition,
    HttpResponse,
    JitoSender,
    JitoUuidAuth,
    LivePermitIssuer,
    LiveSubmissionPolicy,
    PermitBoundSubmissionService,
    RpcSender,
    SignedPayload,
    SubmissionError,
    SubmissionErrorCode,
    SubmissionState,
    SubmissionStatusClient,
    TransportKind,
    classify_jito_bundle_status,
    classify_jito_inflight_status,
    classify_signature_statuses,
    inspect_exactly_one_system_tip,
    inspect_exactly_one_system_tip_across_transactions,
    permit_request_from_payload,
    resubmission_decision,
)

PAYER = Keypair.from_seed(bytes([1]) * 32)
RECIPIENT = Keypair.from_seed(bytes([2]) * 32).pubkey()
TIP = Keypair.from_seed(bytes([3]) * 32).pubkey()
BLOCKHASH = Hash.from_bytes(bytes(range(32)))


def wire(
    *, tip_count: int = 0, transfer_lamports: int = 1
) -> tuple[bytes, tuple[object, ...], MessageV0]:
    instructions = [
        transfer(
            TransferParams(
                from_pubkey=PAYER.pubkey(),
                to_pubkey=RECIPIENT,
                lamports=transfer_lamports,
            )
        )
    ]
    for _ in range(tip_count):
        instructions.append(
            transfer(
                TransferParams(
                    from_pubkey=PAYER.pubkey(),
                    to_pubkey=TIP,
                    lamports=1_000,
                )
            )
        )
    message = MessageV0.try_compile(PAYER.pubkey(), instructions, [], BLOCKHASH)
    tx = VersionedTransaction(message, [PAYER])
    return bytes(tx), tuple(instructions), message


def payload_for(transport: TransportKind, *, tip: bool = False) -> SignedPayload:
    raw, instructions, message = wire(tip_count=1 if tip else 0)
    initial = SignedPayload.from_wire_transactions([raw])
    evidence = None
    if tip:
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


def issuer(transport: TransportKind) -> LivePermitIssuer:
    return LivePermitIssuer(
        LiveSubmissionPolicy(
            compile_time_enabled=True,
            config_enabled=True,
            allowed_transports=(transport,),
            require_jito_uuid_auth=transport is not TransportKind.RPC,
        )
    )


def permit_for(
    active: LivePermitIssuer,
    payload: SignedPayload,
    transport: TransportKind,
):
    request = permit_request_from_payload(
        attempt_id="attempt-1",
        transport=transport,
        exact_simulation_hash=payload.primary_message_hash,
        payload=payload,
        expires_at_ns=time.time_ns() + 10_000_000_000,
        last_valid_block_height=999,
        min_context_slot=10,
    )
    return active.issue(request)


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


def test_default_policy_cannot_issue_permit() -> None:
    payload = payload_for(TransportKind.RPC)
    request = permit_request_from_payload(
        attempt_id="blocked",
        transport=TransportKind.RPC,
        exact_simulation_hash=payload.primary_message_hash,
        payload=payload,
        expires_at_ns=time.time_ns() + 1_000_000_000,
        last_valid_block_height=10,
        min_context_slot=1,
    )
    with pytest.raises(SubmissionError) as raised:
        LivePermitIssuer().issue(request)
    assert raised.value.code is SubmissionErrorCode.LIVE_GATE_CLOSED


@pytest.mark.asyncio
async def test_rpc_ack_is_accepted_not_landed_and_identity_bound() -> None:
    payload = payload_for(TransportKind.RPC)
    active = issuer(TransportKind.RPC)
    permit = permit_for(active, payload, TransportKind.RPC)

    def response(_url, body, _headers):
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": payload.signatures[0]},
        )

    http = FakeHttp(response)
    ack = await RpcSender("https://rpc.example", http, active).submit(
        permit, payload, payload.primary_message_hash
    )
    assert ack.state is SubmissionState.ACCEPTED
    assert not ack.landed
    _, body, _, _ = http.calls[0]
    config = body["params"][1]
    assert config["encoding"] == "base64"
    assert config["preflightCommitment"] == "confirmed"
    assert config["skipPreflight"] is False
    assert config["minContextSlot"] == 10


@pytest.mark.asyncio
async def test_fake_rpc_accepted_signature_is_ambiguous_not_success() -> None:
    payload = payload_for(TransportKind.RPC)
    active = issuer(TransportKind.RPC)
    permit = permit_for(active, payload, TransportKind.RPC)

    def response(_url, body, _headers):
        return HttpResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": str(Keypair().sign_message(b"x")),
            },
        )

    with pytest.raises(SubmissionError) as raised:
        await RpcSender("https://rpc.example", FakeHttp(response), active).submit(
            permit, payload, payload.primary_message_hash
        )
    assert raised.value.code is SubmissionErrorCode.IDENTITY_MISMATCH
    assert raised.value.disposition is ErrorDisposition.AMBIGUOUS


@pytest.mark.asyncio
async def test_permit_is_one_time_and_wire_mutation_is_rejected() -> None:
    payload = payload_for(TransportKind.RPC)
    active = issuer(TransportKind.RPC)
    permit = permit_for(active, payload, TransportKind.RPC)

    def response(_url, body, _headers):
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": payload.signatures[0]},
        )

    sender = RpcSender("https://rpc.example", FakeHttp(response), active)
    await sender.submit(permit, payload, payload.primary_message_hash)
    with pytest.raises(SubmissionError) as raised:
        await sender.submit(permit, payload, payload.primary_message_hash)
    assert raised.value.code is SubmissionErrorCode.PERMIT_INVALID


@pytest.mark.asyncio
async def test_jito_single_uses_fixed_path_uuid_auth_and_exact_tip() -> None:
    payload = payload_for(TransportKind.JITO_SINGLE, tip=True)
    active = issuer(TransportKind.JITO_SINGLE)
    permit = permit_for(active, payload, TransportKind.JITO_SINGLE)
    bundle_id = "a" * 64

    def response(url, body, headers):
        assert url.endswith("/api/v1/transactions?bundleOnly=true")
        assert headers["x-jito-auth"] == auth_value
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": payload.signatures[0]},
            {"x-bundle-id": bundle_id},
        )

    auth_value = str(uuid4())
    sender = JitoSender(
        "https://mainnet.block-engine.jito.wtf",
        FakeHttp(response),
        active,
        auth=JitoUuidAuth.parse(auth_value),
    )
    ack = await sender.submit(permit, payload, payload.primary_message_hash)
    assert ack.state is SubmissionState.ACCEPTED
    assert ack.bundle_id == bundle_id
    assert not ack.landed


def test_duplicate_or_alt_tip_account_fails_closed() -> None:
    raw, instructions, message = wire(tip_count=2)
    payload = SignedPayload.from_wire_transactions([raw])
    with pytest.raises(SubmissionError) as raised:
        inspect_exactly_one_system_tip(
            instructions=instructions,
            message_hash=payload.primary_message_hash,
            payer=PAYER.pubkey(),
            approved_accounts={str(TIP)},
            expected_account=TIP,
            expected_lamports=1_000,
            static_account_keys={str(key) for key in message.account_keys},
        )
    assert raised.value.code is SubmissionErrorCode.TIP_POLICY_INVALID


def test_bundle_wide_duplicate_tips_fail_closed() -> None:
    raw_a, ixs_a, message_a = wire(tip_count=1)
    raw_b, ixs_b, message_b = wire(tip_count=1, transfer_lamports=2)
    payload = SignedPayload.from_wire_transactions([raw_a, raw_b])

    with pytest.raises(SubmissionError) as raised:
        inspect_exactly_one_system_tip_across_transactions(
            instruction_sets=(ixs_a, ixs_b),
            message_hashes=payload.message_hashes,
            payer=PAYER.pubkey(),
            approved_accounts={str(TIP)},
            expected_account=TIP,
            expected_lamports=1_000,
            static_account_keys_by_message=(
                {str(key) for key in message_a.account_keys},
                {str(key) for key in message_b.account_keys},
            ),
        )
    assert raised.value.code is SubmissionErrorCode.TIP_POLICY_INVALID


def test_status_reconciliation_never_promotes_ack_or_ambiguity() -> None:
    signature = payload_for(TransportKind.RPC).signatures[0]
    accepted = classify_signature_statuses(
        {"result": {"context": {"slot": 50}, "value": [None]}},
        expected_signatures=(signature,),
        current_block_height=90,
        last_valid_block_height=100,
        observed_at_ns=1,
    )
    assert accepted.state is SubmissionState.UNKNOWN
    assert not resubmission_decision(accepted).allowed

    landed = classify_signature_statuses(
        {
            "result": {
                "context": {"slot": 51},
                "value": [
                    {
                        "slot": 50,
                        "err": None,
                        "confirmationStatus": "confirmed",
                    }
                ],
            }
        },
        expected_signatures=(signature,),
        current_block_height=91,
        last_valid_block_height=100,
        observed_at_ns=2,
    )
    assert landed.state is SubmissionState.LANDED

    expired = classify_signature_statuses(
        {"result": {"context": {"slot": 52}, "value": [None]}},
        expected_signatures=(signature,),
        current_block_height=101,
        last_valid_block_height=100,
        observed_at_ns=3,
    )
    assert expired.state is SubmissionState.EXPIRED
    assert resubmission_decision(expired).requires_new_permit


def test_jito_failed_or_invalid_stays_unknown_until_signature_reconciliation() -> None:
    bundle_id = "b" * 64
    observation = classify_jito_inflight_status(
        {
            "result": {
                "context": {"slot": 10},
                "value": [
                    {"bundle_id": bundle_id, "status": "Failed", "landed_slot": None}
                ],
            }
        },
        bundle_id=bundle_id,
        observed_at_ns=4,
    )
    assert observation.state is SubmissionState.UNKNOWN
    assert not resubmission_decision(observation).allowed


def test_jito_bundle_status_checks_exact_signature_identity() -> None:
    payload = payload_for(TransportKind.JITO_BUNDLE, tip=True)
    bundle_id = "c" * 64
    observation = classify_jito_bundle_status(
        {
            "result": {
                "context": {"slot": 20},
                "value": [
                    {
                        "bundle_id": bundle_id,
                        "transactions": list(payload.signatures),
                        "slot": 19,
                        "confirmation_status": "finalized",
                        "err": {"Ok": None},
                    }
                ],
            }
        },
        bundle_id=bundle_id,
        expected_signatures=payload.signatures,
        observed_at_ns=5,
    )
    assert observation.state is SubmissionState.LANDED


@dataclass
class FakeAttempt:
    attempt_id: str
    state: ExecutionState
    revision: int


class FakeStore:
    def __init__(self):
        self.attempt = FakeAttempt("attempt-1", ExecutionState.SIGNED, 7)
        self.events = []

    def record_submission_intent(self, attempt_id, **kwargs):
        assert attempt_id == self.attempt.attempt_id
        assert kwargs["expected_revision"] == 7
        self.attempt = FakeAttempt(
            attempt_id, ExecutionState.SUBMISSION_INTENT_RECORDED, 8
        )
        self.events.append(("intent", kwargs))
        return self.attempt

    def get_attempt(self, attempt_id):
        return self.attempt if attempt_id == self.attempt.attempt_id else None

    def transition(self, attempt_id, **kwargs):
        assert kwargs["expected_revision"] == self.attempt.revision
        self.attempt = FakeAttempt(
            attempt_id, kwargs["target"], self.attempt.revision + 1
        )
        self.events.append(("transition", kwargs))
        return self.attempt


@pytest.mark.asyncio
async def test_durable_service_records_intent_before_ack_and_ack_not_landing() -> None:
    payload = payload_for(TransportKind.RPC)
    active = issuer(TransportKind.RPC)
    permit = permit_for(active, payload, TransportKind.RPC)

    def response(_url, body, _headers):
        return HttpResponse(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": payload.signatures[0]},
        )

    store = FakeStore()
    service = PermitBoundSubmissionService(store)  # type: ignore[arg-type]
    result = await service.submit(
        attempt_id="attempt-1",
        expected_revision=7,
        lease=object(),  # type: ignore[arg-type]
        permit=permit,
        payload=payload,
        message_hash=payload.primary_message_hash,
        sender=RpcSender("https://rpc.example", FakeHttp(response), active),
        idempotency_key="submit-1",
    )
    assert [event[0] for event in store.events] == ["intent", "transition"]
    assert result.attempt.state is ExecutionState.ACCEPTED
    assert result.ack is not None and not result.ack.landed


@pytest.mark.asyncio
async def test_status_client_uses_official_paths_and_status_shapes() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "pr045"
            / "official_transport_shapes.json"
        ).read_text(encoding="utf-8")
    )
    payload = payload_for(TransportKind.JITO_SINGLE, tip=True)
    bundle_id = "d" * 64
    ack = type(
        "Ack",
        (),
        {
            "transaction_signatures": payload.signatures,
            "bundle_id": bundle_id,
        },
    )()

    def response(url, body, _headers):
        method = body["method"]
        if method == fixture["solana"]["status_method"]:
            assert body["params"][1][fixture["solana"]["status_history_field"]]
            return HttpResponse(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "context": {"slot": 31},
                        "value": [
                            {
                                "slot": 30,
                                "err": None,
                                "confirmationStatus": "confirmed",
                            }
                        ],
                    },
                },
            )
        if method == "getInflightBundleStatuses":
            assert url.endswith(fixture["jito"]["inflight_path"])
            return HttpResponse(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "context": {"slot": 32},
                        "value": [
                            {
                                "bundle_id": bundle_id,
                                "status": "Pending",
                                "landed_slot": None,
                            }
                        ],
                    },
                },
            )
        if method == "getBundleStatuses":
            assert url.endswith(fixture["jito"]["bundle_status_path"])
            return HttpResponse(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "context": {"slot": 33},
                        "value": [
                            {
                                "bundle_id": bundle_id,
                                "transactions": list(payload.signatures),
                                "slot": 32,
                                "confirmation_status": "finalized",
                                "err": {"Ok": None},
                            }
                        ],
                    },
                },
            )
        if method == "getTipAccounts":
            assert url.endswith(fixture["jito"]["tip_accounts_path"])
            return HttpResponse(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": [str(TIP)],
                },
            )
        raise AssertionError(method)

    client = SubmissionStatusClient(
        FakeHttp(response),
        rpc_endpoint="https://rpc.example",
        jito_base_url="https://mainnet.block-engine.jito.wtf",
        clock_ns=lambda: 100,
    )
    signature_observation = await client.signature_statuses(
        ack,  # type: ignore[arg-type]
        current_block_height=20,
        last_valid_block_height=40,
    )
    assert signature_observation.state is SubmissionState.LANDED
    assert (await client.jito_inflight_status(ack)).state is SubmissionState.ACCEPTED  # type: ignore[arg-type]
    assert (await client.jito_bundle_status(ack)).state is SubmissionState.LANDED  # type: ignore[arg-type]
    tips = await client.jito_tip_accounts()
    assert tips.accounts == frozenset({str(TIP)})
    assert len(tips.response_hash) == 64
