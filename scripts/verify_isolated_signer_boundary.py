#!/usr/bin/env python3
"""Verify the MPR-CLOSE-05 isolated signer boundary offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from isolated_signer_service.boundary import (  # noqa: E402
    InMemoryAuditLog,
    InMemoryNonceStore,
    IsolatedSignerService,
    SignerBoundaryError,
    SignerBoundaryFailure,
    SignerBoundaryRequest,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class DeterministicBackend:
    def __init__(self) -> None:
        self.signed_messages: list[bytes] = []

    def sign_exact_message(self, message: bytes) -> bytes:
        self.signed_messages.append(bytes(message))
        return hashlib.sha512(b"mpr-close-05:" + message).digest()


def _request(*, nonce: str = "nonce-a", message: bytes = b"message-v0") -> SignerBoundaryRequest:
    return SignerBoundaryRequest(
        authorization_id="auth-1",
        opportunity_id="opp-1",
        message_sha256=hashlib.sha256(message).hexdigest(),
        policy_identity_hash=_hash("policy"),
        config_generation_hash=_hash("config"),
        reservation_hash=_hash("reservation"),
        requester_identity_hash=_hash("requester"),
        nonce_digest=_hash(nonce),
        issued_at_ns=10,
        not_before_ns=20,
        expires_at_ns=200,
    )


def verify() -> dict[str, object]:
    backend = DeterministicBackend()
    audit = InMemoryAuditLog()
    service = IsolatedSignerService(
        backend=backend,
        nonce_store=InMemoryNonceStore(),
        audit_log=audit,
        clock_ns=lambda: 100,
    )
    message = b"message-v0"
    receipt = service.sign_authorized_message(_request(message=message), exact_message_bytes=message)

    replay_blocked = False
    try:
        service.sign_authorized_message(_request(message=message), exact_message_bytes=message)
    except SignerBoundaryError as exc:
        replay_blocked = exc.failure is SignerBoundaryFailure.REPLAY

    mismatch_blocked = False
    try:
        service.sign_authorized_message(
            _request(nonce="nonce-b", message=message),
            exact_message_bytes=b"mutated-message",
        )
    except SignerBoundaryError as exc:
        mismatch_blocked = exc.failure is SignerBoundaryFailure.BAD_MESSAGE_BYTES

    audit_blocked = False
    failing_audit = InMemoryAuditLog(fail_writes=True)
    failing_service = IsolatedSignerService(
        backend=DeterministicBackend(),
        nonce_store=InMemoryNonceStore(),
        audit_log=failing_audit,
        clock_ns=lambda: 100,
    )
    try:
        failing_service.sign_authorized_message(
            _request(nonce="nonce-c", message=message),
            exact_message_bytes=message,
        )
    except SignerBoundaryError as exc:
        audit_blocked = exc.failure is SignerBoundaryFailure.AUDIT_NOT_DURABLE

    accepted = bool(
        receipt.message_sha256 == hashlib.sha256(message).hexdigest()
        and len(audit.events) == 1
        and backend.signed_messages == [message]
        and replay_blocked
        and mismatch_blocked
        and audit_blocked
    )
    return {
        "schema_version": "mpr-close-05.verify-isolated-signer-boundary.v1",
        "accepted": accepted,
        "runtime_private_key_access": False,
        "signed_message_count": len(backend.signed_messages),
        "audit_before_signing": len(audit.events) == 1,
        "replay_blocked": replay_blocked,
        "mismatched_bytes_blocked": mismatch_blocked,
        "audit_failure_blocks_signing": audit_blocked,
        "receipt": receipt.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = verify()
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print("accepted=" + str(report["accepted"]).lower())
    return 0 if report["accepted"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
