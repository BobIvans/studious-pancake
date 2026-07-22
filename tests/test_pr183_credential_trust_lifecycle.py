from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config.secret_resolver import (
    CredentialLifecycleRegistry,
    CredentialRecord,
    CredentialState,
    SecretResolutionError,
    SecretResolutionPolicy,
    resolve_secret_reference,
)
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorError,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
)

_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _ref(scheme: str, locator: str):
    return SimpleNamespace(scheme=scheme, locator=locator)


def test_file_secret_path_swap_reads_original_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    safe = tmp_path / "safe.secret"
    attacker = tmp_path / "attacker.secret"
    safe.write_text("safe-value\n", encoding="utf-8")
    attacker.write_text("attacker-value\n", encoding="utf-8")
    os.chmod(safe, 0o600)
    os.chmod(attacker, 0o600)
    real_open = os.open

    def open_then_swap(path, flags, *args):
        descriptor = real_open(path, flags, *args)
        original = Path(path)
        original.rename(original.with_suffix(".preserved"))
        original.symlink_to(attacker)
        return descriptor

    monkeypatch.setattr(os, "open", open_then_swap)
    handle = resolve_secret_reference(_ref("file", str(safe)), environ={})

    assert handle.reveal() == "safe-value"
    assert safe.is_symlink()
    assert "safe-value" not in repr(handle)


def test_production_policy_denies_environment_secrets() -> None:
    policy = SecretResolutionPolicy.production_default(
        consumer_id="provider/jupiter", usage_scope="provider-build"
    )
    with pytest.raises(SecretResolutionError, match="environment secrets"):
        resolve_secret_reference(
            _ref("env", "JUPITER_API_KEY"),
            environ={"JUPITER_API_KEY": "secret-value"},
            policy=policy,
        )


def test_secret_lease_scope_max_use_and_revocation() -> None:
    policy = SecretResolutionPolicy(
        consumer_id="probe/jupiter",
        usage_scope="credentialed-readonly-probe",
        version="v2",
        max_uses=1,
    )
    handle = resolve_secret_reference(
        _ref("env", "JUPITER_API_KEY"),
        environ={"JUPITER_API_KEY": "secret-value"},
        policy=policy,
        clock_ns=lambda: 1_000_000_000,
    )

    assert handle.lease.version == "v2"
    assert handle.lease.consumer_id == "probe/jupiter"
    assert handle.reveal() == "secret-value"
    with pytest.raises(SecretResolutionError, match="exhausted"):
        handle.reveal()
    handle.revoke()
    assert handle.lease.revoked is True


def test_credential_rotation_and_revocation_state_machine() -> None:
    registry = CredentialLifecycleRegistry()
    record = CredentialRecord(
        secret_id="provider-jupiter",
        version="v2",
        backend="managed-secret-manager",
        usage_scope="provider-build",
        consumer_id="paper-runtime",
        issued_at_ns=10,
        expires_at_ns=100,
    )
    registry.register(record)
    for state in (
        CredentialState.STAGED,
        CredentialState.VALIDATED,
        CredentialState.ACTIVE,
    ):
        registry.transition(record.secret_id, record.version, state)
    assert registry.is_usable(record.secret_id, record.version, now_ns=50)
    registry.revoke(record.secret_id, record.version)
    assert not registry.is_usable(record.secret_id, record.version, now_ns=50)


class _AcceptingVerifier:
    def verify(self, *, public_key_base58, signature_base58, message):
        return bool(public_key_base58 and signature_base58 and message)


def _anchor(state: TrustAnchorState = TrustAnchorState.ACTIVE) -> TrustAnchor:
    return TrustAnchor(
        key_id="release-key-2026-07",
        algorithm="ed25519",
        public_key_base58="11111111111111111111111111111111",
        usages=(TrustUsage.RELEASE, TrustUsage.EVIDENCE),
        issuer="security-team",
        environment="production",
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=30),
        state=state,
        revoked_at=_NOW if state is TrustAnchorState.REVOKED else None,
    )


def _envelope(payload: bytes, signature: str = "2" * 88) -> SignedEnvelope:
    return SignedEnvelope(
        domain="release-manifest",
        schema_version="release.v1",
        environment="production",
        key_id="release-key-2026-07",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=10),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_base58=signature,
    )


def test_trust_registry_verifies_bound_payload() -> None:
    payload = b'{"release":"candidate-1"}'
    registry = TrustAnchorRegistry(
        (_anchor(),), generation="trust-registry-2026-07", verifier=_AcceptingVerifier()
    )
    result = registry.verify(
        _envelope(payload),
        payload,
        usage=TrustUsage.RELEASE,
        evaluated_at=_NOW,
        expected_domain="release-manifest",
        expected_environment="production",
    )
    assert result.verified is True
    assert result.blockers == ()


def test_trust_registry_blocks_payload_drift_and_revocation() -> None:
    payload = b'{"release":"candidate-1"}'
    registry = TrustAnchorRegistry(
        (_anchor(TrustAnchorState.REVOKED),),
        generation="trust-registry-2026-07",
        verifier=_AcceptingVerifier(),
    )
    result = registry.verify(
        _envelope(payload),
        b'{"release":"candidate-2"}',
        usage=TrustUsage.RELEASE,
        evaluated_at=_NOW,
        expected_domain="release-manifest",
        expected_environment="production",
    )
    assert "SIGNED_PAYLOAD_HASH_MISMATCH" in result.blockers
    assert "TRUST_ANCHOR_REVOKED" in result.blockers


def test_hash_shaped_signature_is_rejected() -> None:
    with pytest.raises(TrustAnchorError, match="not a signature"):
        _envelope(b"payload", signature="a" * 64)


def test_real_solders_ed25519_signature() -> None:
    keypair_module = pytest.importorskip("solders.keypair")
    keypair = keypair_module.Keypair()
    payload = b'{"release":"candidate-real"}'
    anchor = TrustAnchor(
        key_id="real-key",
        algorithm="ed25519",
        public_key_base58=str(keypair.pubkey()),
        usages=(TrustUsage.RELEASE,),
        issuer="unit-test",
        environment="production",
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=1),
        state=TrustAnchorState.ACTIVE,
    )
    unsigned = SignedEnvelope(
        domain="release-manifest",
        schema_version="release.v1",
        environment="production",
        key_id=anchor.key_id,
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=10),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_base58="2" * 88,
    )
    envelope = SignedEnvelope(
        domain=unsigned.domain,
        schema_version=unsigned.schema_version,
        environment=unsigned.environment,
        key_id=unsigned.key_id,
        issued_at=unsigned.issued_at,
        expires_at=unsigned.expires_at,
        payload_sha256=unsigned.payload_sha256,
        signature_base58=str(keypair.sign_message(unsigned.canonical_message())),
    )
    result = TrustAnchorRegistry((anchor,), generation="real-ed25519").verify(
        envelope,
        payload,
        usage=TrustUsage.RELEASE,
        evaluated_at=_NOW,
        expected_domain="release-manifest",
        expected_environment="production",
    )
    assert result.verified is True
