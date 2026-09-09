from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "isolated_signer_service" / "src"
sys.path.insert(0, str(PACKAGE_SRC))

from flashloan_isolated_signer.mpr2608 import (  # noqa: E402
    ApprovedIntent,
    IsolatedSignerServer,
    MPR2608Error,
    MPR2608Store,
    OutcomeState,
    SignRequest,
    build_sign_request_frame,
    parse_sign_receipt,
)


def h(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def make_intent(message: bytes = b"approved-message", **overrides: object) -> ApprovedIntent:
    values: dict[str, object] = {
        "permit_id": "permit-1",
        "intent_id": "intent-1",
        "attempt_id": "attempt-1",
        "reservation_id": "reservation-1",
        "release_id": "release-1",
        "config_hash": h("config"),
        "policy_hash": h("policy"),
        "genesis_hash": h("genesis"),
        "signer_service_id": "signer-v1",
        "signer_generation": 1,
        "payer": "payer-1",
        "message_sha256": h(message),
        "simulation_sha256": h("simulation"),
        "transport": "rpc",
        "expires_at_ns": time.time_ns() + 10_000_000_000,
    }
    values.update(overrides)
    return ApprovedIntent(**values)


class FixtureBackend:
    def sign_approved_transaction(self, unsigned_message: bytes) -> tuple[str, bytes]:
        return "fixture-signature", b"signed:" + unsigned_message


class FixtureValidator:
    def __call__(self, *, unsigned_message: bytes, intent: ApprovedIntent) -> None:
        if hashlib.sha256(unsigned_message).hexdigest() != intent.message_sha256:
            raise MPR2608Error("message mismatch")
        if intent.payer != "payer-1":
            raise MPR2608Error("payer denied")


def test_atomic_permit_consumption_and_intent_replay(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    now = time.time_ns()
    store.consume_permit_and_create_intent(intent, now_ns=now)
    store.consume_permit_and_create_intent(intent, now_ns=now + 1)
    row = store.get_intent(intent.intent_id)
    assert row["state"] == OutcomeState.NOT_ISSUED.value
    assert row["capital_hold"] == 1


def test_same_permit_cannot_authorize_changed_message(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    changed = make_intent(message=b"changed", intent_id="intent-2")
    with pytest.raises(MPR2608Error, match="semantic conflict|already consumed"):
        store.consume_permit_and_create_intent(changed, now_ns=time.time_ns())


def test_two_consumers_race_one_permit(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    first = make_intent(intent_id="intent-a")
    second = make_intent(intent_id="intent-b")
    store.seed_permit(first.permit_id, first.semantic_hash)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def consume(intent: ApprovedIntent) -> None:
        barrier.wait()
        try:
            store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
            results.append("ok")
        except MPR2608Error:
            results.append("denied")

    threads = [threading.Thread(target=consume, args=(first,)), threading.Thread(target=consume, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["denied", "ok"]


def test_dispatch_marker_is_uncertainty_linearization_point(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    before = store.get_intent(intent.intent_id)
    assert before["state"] == OutcomeState.NOT_ISSUED.value
    store.mark_dispatching(
        intent_id=intent.intent_id,
        signed_wire_sha256=h("wire"),
        primary_signature="signature-1",
        now_ns=time.time_ns(),
    )
    after = store.get_intent(intent.intent_id)
    assert after["state"] == OutcomeState.ISSUED_UNKNOWN.value
    assert after["capital_hold"] == 1


def test_ack_is_not_finality_and_unknown_holds_capital(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    store.mark_dispatching(
        intent_id=intent.intent_id,
        signed_wire_sha256=h("wire"),
        primary_signature="signature-1",
        now_ns=time.time_ns(),
    )
    store.record_ack(intent_id=intent.intent_id, ack_payload={"signature": "signature-1"}, now_ns=time.time_ns())
    row = store.get_intent(intent.intent_id)
    assert row["state"] == OutcomeState.ACKNOWLEDGED.value
    assert row["capital_hold"] == 1


def test_finalized_success_waits_for_economics(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    store.mark_dispatching(
        intent_id=intent.intent_id,
        signed_wire_sha256=h("wire"),
        primary_signature="signature-1",
        now_ns=time.time_ns(),
    )
    state = store.record_finality(
        intent_id=intent.intent_id,
        finalized=True,
        err=False,
        evidence={"commitment": "finalized", "signature": "signature-1"},
        economics_settled=False,
        now_ns=time.time_ns(),
    )
    assert state is OutcomeState.FINALIZED_PENDING_ECONOMICS
    row = store.get_intent(intent.intent_id)
    assert row["capital_hold"] == 1


def test_finalized_failure_releases_hold(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    store.mark_dispatching(
        intent_id=intent.intent_id,
        signed_wire_sha256=h("wire"),
        primary_signature="signature-1",
        now_ns=time.time_ns(),
    )
    state = store.record_finality(
        intent_id=intent.intent_id,
        finalized=True,
        err=True,
        evidence={"commitment": "finalized", "err": "InstructionError"},
        economics_settled=False,
        now_ns=time.time_ns(),
    )
    assert state is OutcomeState.FINALIZED_FAILURE
    assert store.get_intent(intent.intent_id)["capital_hold"] == 0


def test_confirmed_is_not_terminal(tmp_path: Path) -> None:
    store = MPR2608Store(tmp_path / "state.sqlite3")
    intent = make_intent()
    store.seed_permit(intent.permit_id, intent.semantic_hash)
    store.consume_permit_and_create_intent(intent, now_ns=time.time_ns())
    store.mark_dispatching(
        intent_id=intent.intent_id,
        signed_wire_sha256=h("wire"),
        primary_signature="signature-1",
        now_ns=time.time_ns(),
    )
    with pytest.raises(MPR2608Error, match="not terminal"):
        store.record_finality(
            intent_id=intent.intent_id,
            finalized=False,
            err=False,
            evidence={"commitment": "confirmed"},
            economics_settled=False,
            now_ns=time.time_ns(),
        )


def test_strict_signer_ipc_rejects_unknown_field_and_generic_method() -> None:
    intent = make_intent()
    server = IsolatedSignerServer(
        socket_path="/tmp/mpr2608-unused.sock",
        service_id="signer-v1",
        generation=1,
        validator=FixtureValidator(),
        backend=FixtureBackend(),
    )
    request = SignRequest(intent=intent, request_id="request-1", request_nonce="nonce-1", unsigned_message=b"approved-message")
    payload = json.loads(build_sign_request_frame(request))
    payload["unknown"] = True
    with pytest.raises(MPR2608Error, match="unknown or missing"):
        server.handle_payload(json.dumps(payload).encode())
    payload.pop("unknown")
    payload["method"] = "sign_bytes"
    with pytest.raises(MPR2608Error, match="unsupported"):
        server.handle_payload(json.dumps(payload).encode())


def test_signer_independently_validates_and_returns_bounded_receipt() -> None:
    intent = make_intent()
    server = IsolatedSignerServer(
        socket_path="/tmp/mpr2608-unused.sock",
        service_id="signer-v1",
        generation=1,
        validator=FixtureValidator(),
        backend=FixtureBackend(),
    )
    request = SignRequest(intent=intent, request_id="request-1", request_nonce="nonce-1", unsigned_message=b"approved-message")
    receipt = parse_sign_receipt(server.handle_payload(build_sign_request_frame(request)))
    assert receipt.intent_id == intent.intent_id
    assert receipt.message_sha256 == intent.message_sha256
    assert receipt.signed_wire == b"signed:approved-message"
    assert receipt.signed_wire_sha256 == h(receipt.signed_wire)


def test_signer_rejects_expired_or_wrong_service() -> None:
    server = IsolatedSignerServer(
        socket_path="/tmp/mpr2608-unused.sock",
        service_id="signer-v1",
        generation=1,
        validator=FixtureValidator(),
        backend=FixtureBackend(),
        now_ns=lambda: 100,
    )
    expired = make_intent(expires_at_ns=99)
    payload = {
        "method": "sign_approved_solana_transaction",
        "request_id": "request-1",
        "request_nonce": "nonce-1",
        "intent": {name: getattr(expired, name) for name in expired.__dataclass_fields__},
        "unsigned_message_hex": b"approved-message".hex(),
    }
    with pytest.raises(MPR2608Error, match="expired"):
        server.handle_payload(json.dumps(payload).encode())

    wrong = make_intent(signer_service_id="signer-v2", expires_at_ns=101)
    payload["intent"] = {name: getattr(wrong, name) for name in wrong.__dataclass_fields__}
    with pytest.raises(MPR2608Error, match="wrong signer"):
        server.handle_payload(json.dumps(payload).encode())
