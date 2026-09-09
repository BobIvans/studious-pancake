from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.human_intervention import (
    HumanInterventionRequest,
    InterventionAction,
    InterventionBlocked,
    InterventionTarget,
    evaluate_human_intervention,
)
from src.operator_signature_verifier import (
    DECISION_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    SSH_OPERATOR_NAMESPACE,
    OperatorTrustRegistry,
    OperatorVerificationError,
    SSHOperatorVerifier,
    SignedOperatorDecision,
)


H = {
    "subject": "1" * 64,
    "evidence": "2" * 64,
    "release": "3" * 64,
    "config": "4" * 64,
    "epoch": "5" * 64,
}


def _ssh_keygen() -> str:
    binary = shutil.which("ssh-keygen")
    assert binary is not None, "OpenSSH ssh-keygen is required for MPR-2603 verification"
    return binary


def _make_key(tmp_path: Path, name: str) -> tuple[Path, str]:
    private_key = tmp_path / name
    subprocess.run(
        [_ssh_keygen(), "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin"},
    )
    public_key = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    return private_key, public_key


def _registry(*entries: dict[str, object]) -> OperatorTrustRegistry:
    raw = json.dumps(
        {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "trust_epoch": H["epoch"],
            "principals": list(entries),
        },
        separators=(",", ":"),
    ).encode()
    return OperatorTrustRegistry.from_json_bytes(raw)


def _entry(
    *,
    principal: str,
    subject: str,
    credential: str,
    public_key: str,
    active: bool = True,
    roles: list[str] | None = None,
) -> dict[str, object]:
    return {
        "principal_id": principal,
        "subject_id": subject,
        "credential_id": credential,
        "roles": roles or ["SAFETY_REVIEWER"],
        "public_key": public_key,
        "active": active,
    }


def _decision(
    *,
    request_hash: str,
    principal: str,
    credential: str,
    decision: str = "APPROVE",
    namespace: str = SSH_OPERATOR_NAMESPACE,
    epoch: str = H["epoch"],
) -> SignedOperatorDecision:
    return SignedOperatorDecision(
        request_hash=request_hash,
        decision=decision,
        principal_id=principal,
        credential_id=credential,
        signed_at_utc="2026-09-09T12:00:00Z",
        expires_at_utc="2026-09-09T12:10:00Z",
        nonce=f"nonce-{principal}-{decision}",
        trust_epoch=epoch,
        namespace=namespace,
        schema_version=DECISION_SCHEMA_VERSION,
    )


def _sign(tmp_path: Path, private_key: Path, decision: SignedOperatorDecision) -> bytes:
    message = tmp_path / f"{decision.principal_id}-{decision.decision}.json"
    message.write_bytes(decision.canonical_bytes())
    subprocess.run(
        [
            _ssh_keygen(),
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            SSH_OPERATOR_NAMESPACE,
            str(message),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": "/usr/bin:/bin"},
    )
    return Path(f"{message}.sig").read_bytes()


def _target() -> InterventionTarget:
    return InterventionTarget(
        subject_type="pr195-latch",
        subject_id="provider-auth",
        subject_hash=H["subject"],
        evidence_hash=H["evidence"],
        release_hash=H["release"],
        config_hash=H["config"],
    )


def _request_hash() -> str:
    payload = {
        "schema": "mpr2603.human-intervention.v1",
        "action": InterventionAction.CLEAR_SAFETY_LATCH.value,
        "target": {
            "subject_type": "pr195-latch",
            "subject_id": "provider-auth",
            "subject_hash": H["subject"],
            "evidence_hash": H["evidence"],
            "release_hash": H["release"],
            "config_hash": H["config"],
        },
        "request_id": "incident-17",
        "nonce": "server-nonce-17",
        "requested_at_utc": "2026-09-09T12:00:00Z",
        "expires_at_utc": "2026-09-09T12:10:00Z",
        "trust_epoch": H["epoch"],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _request_with(approvals: tuple) -> HumanInterventionRequest:
    return HumanInterventionRequest(
        action=InterventionAction.CLEAR_SAFETY_LATCH,
        target=_target(),
        request_id="incident-17",
        nonce="server-nonce-17",
        requested_at_utc="2026-09-09T12:00:00Z",
        expires_at_utc="2026-09-09T12:10:00Z",
        trust_epoch=H["epoch"],
        approvals=approvals,
    )


def test_real_ssh_signatures_produce_two_independent_verified_approvals(
    tmp_path: Path,
) -> None:
    alice_key, alice_pub = _make_key(tmp_path, "alice")
    bob_key, bob_pub = _make_key(tmp_path, "bob")
    registry = _registry(
        _entry(
            principal="alice-key",
            subject="human:alice",
            credential="cred-a",
            public_key=alice_pub,
        ),
        _entry(
            principal="bob-key",
            subject="human:bob",
            credential="cred-b",
            public_key=bob_pub,
        ),
    )
    verifier = SSHOperatorVerifier(registry, ssh_keygen_path=_ssh_keygen())
    request_hash = _request_hash()
    alice = _decision(
        request_hash=request_hash, principal="alice-key", credential="cred-a"
    )
    bob = _decision(request_hash=request_hash, principal="bob-key", credential="cred-b")
    approval_a = verifier.verify(
        alice,
        signature=_sign(tmp_path, alice_key, alice),
        current_utc="2026-09-09T12:01:00Z",
        required_roles=frozenset({"SAFETY_REVIEWER"}),
    )
    approval_b = verifier.verify(
        bob,
        signature=_sign(tmp_path, bob_key, bob),
        current_utc="2026-09-09T12:01:00Z",
        required_roles=frozenset({"SAFETY_REVIEWER"}),
    )
    request = _request_with((approval_a, approval_b))
    assert request.request_hash == request_hash
    permit = evaluate_human_intervention(
        request, current_utc="2026-09-09T12:01:00Z"
    )
    assert permit.principal_ids == ("human:alice", "human:bob")


def test_tampered_payload_is_rejected_by_real_backend(tmp_path: Path) -> None:
    private_key, public_key = _make_key(tmp_path, "alice")
    registry = _registry(
        _entry(
            principal="alice-key",
            subject="human:alice",
            credential="cred-a",
            public_key=public_key,
        )
    )
    verifier = SSHOperatorVerifier(registry, ssh_keygen_path=_ssh_keygen())
    original = _decision(
        request_hash="6" * 64, principal="alice-key", credential="cred-a"
    )
    signature = _sign(tmp_path, private_key, original)
    tampered = _decision(
        request_hash="7" * 64, principal="alice-key", credential="cred-a"
    )
    with pytest.raises(OperatorVerificationError, match="SIGNATURE_INVALID"):
        verifier.verify(
            tampered, signature=signature, current_utc="2026-09-09T12:01:00Z"
        )


def test_wrong_namespace_cannot_be_constructed() -> None:
    with pytest.raises(OperatorVerificationError, match="namespace mismatch"):
        _decision(
            request_hash="6" * 64,
            principal="alice-key",
            credential="cred-a",
            namespace="file",
        )


def test_unknown_revoked_wrong_role_and_credential_fail_closed(tmp_path: Path) -> None:
    private_key, public_key = _make_key(tmp_path, "alice")
    request_hash = "6" * 64
    decision = _decision(
        request_hash=request_hash, principal="alice-key", credential="cred-a"
    )
    signature = _sign(tmp_path, private_key, decision)

    unknown = SSHOperatorVerifier(
        _registry(
            _entry(
                principal="other",
                subject="human:other",
                credential="cred-x",
                public_key=public_key,
            )
        ),
        ssh_keygen_path=_ssh_keygen(),
    )
    with pytest.raises(OperatorVerificationError, match="UNKNOWN_PRINCIPAL"):
        unknown.verify(
            decision, signature=signature, current_utc="2026-09-09T12:01:00Z"
        )

    revoked = SSHOperatorVerifier(
        _registry(
            _entry(
                principal="alice-key",
                subject="human:alice",
                credential="cred-a",
                public_key=public_key,
                active=False,
            )
        ),
        ssh_keygen_path=_ssh_keygen(),
    )
    with pytest.raises(OperatorVerificationError, match="PRINCIPAL_REVOKED"):
        revoked.verify(
            decision, signature=signature, current_utc="2026-09-09T12:01:00Z"
        )

    wrong_role = SSHOperatorVerifier(
        _registry(
            _entry(
                principal="alice-key",
                subject="human:alice",
                credential="cred-a",
                public_key=public_key,
                roles=["OBSERVER"],
            )
        ),
        ssh_keygen_path=_ssh_keygen(),
    )
    with pytest.raises(OperatorVerificationError, match="REQUIRED_ROLE_MISSING"):
        wrong_role.verify(
            decision,
            signature=signature,
            current_utc="2026-09-09T12:01:00Z",
            required_roles=frozenset({"SAFETY_REVIEWER"}),
        )

    mismatch = _decision(
        request_hash=request_hash,
        principal="alice-key",
        credential="cred-other",
    )
    mismatch_signature = _sign(tmp_path, private_key, mismatch)
    active = SSHOperatorVerifier(
        _registry(
            _entry(
                principal="alice-key",
                subject="human:alice",
                credential="cred-a",
                public_key=public_key,
            )
        ),
        ssh_keygen_path=_ssh_keygen(),
    )
    with pytest.raises(OperatorVerificationError, match="CREDENTIAL_MISMATCH"):
        active.verify(
            mismatch,
            signature=mismatch_signature,
            current_utc="2026-09-09T12:01:00Z",
        )


def test_two_keys_for_same_enrolled_human_do_not_satisfy_independence(
    tmp_path: Path,
) -> None:
    key_a, pub_a = _make_key(tmp_path, "alice-a")
    key_b, pub_b = _make_key(tmp_path, "alice-b")
    registry = _registry(
        _entry(
            principal="alice-a",
            subject="human:alice",
            credential="cred-a",
            public_key=pub_a,
        ),
        _entry(
            principal="alice-b",
            subject="human:alice",
            credential="cred-b",
            public_key=pub_b,
        ),
    )
    verifier = SSHOperatorVerifier(registry, ssh_keygen_path=_ssh_keygen())
    request_hash = _request_hash()
    d1 = _decision(request_hash=request_hash, principal="alice-a", credential="cred-a")
    d2 = _decision(request_hash=request_hash, principal="alice-b", credential="cred-b")
    a1 = verifier.verify(
        d1,
        signature=_sign(tmp_path, key_a, d1),
        current_utc="2026-09-09T12:01:00Z",
    )
    a2 = verifier.verify(
        d2,
        signature=_sign(tmp_path, key_b, d2),
        current_utc="2026-09-09T12:01:00Z",
    )
    request = _request_with((a1, a2))
    with pytest.raises(InterventionBlocked, match="APPROVERS_MUST_BE_INDEPENDENT"):
        evaluate_human_intervention(request, current_utc="2026-09-09T12:01:00Z")


def test_registry_rejects_duplicate_keys_unknown_fields_and_nan() -> None:
    public = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakePublicKeyForParserOnly"
    duplicate = (
        '{"schema_version":"%s","trust_epoch":"%s",'
        '"trust_epoch":"%s","principals":[]}'
        % (REGISTRY_SCHEMA_VERSION, H["epoch"], H["epoch"])
    ).encode()
    with pytest.raises(OperatorVerificationError, match="duplicate JSON key"):
        OperatorTrustRegistry.from_json_bytes(duplicate)

    with pytest.raises(OperatorVerificationError, match="fields do not match schema"):
        OperatorTrustRegistry.from_json_bytes(
            json.dumps(
                {
                    "schema_version": REGISTRY_SCHEMA_VERSION,
                    "trust_epoch": H["epoch"],
                    "principals": [
                        {
                            **_entry(
                                principal="p",
                                subject="s",
                                credential="c",
                                public_key=public,
                            ),
                            "client_role": "ADMIN",
                        }
                    ],
                }
            ).encode()
        )

    with pytest.raises(OperatorVerificationError, match="invalid JSON constant"):
        OperatorTrustRegistry.from_json_bytes(b'{"schema_version":NaN}')
