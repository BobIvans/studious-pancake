from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import threading

import pytest

from src.config.credential_lifecycle import (
    CredentialState,
    SecretHandle,
    SecretLease,
)
from src.security.credential_rotation import (
    CredentialRotationError,
    CredentialVersion,
    DurableCredentialAuthority,
    DurableTrustGenerationAuthority,
    FencedSecretHandle,
    RotationPlan,
    RotationReason,
)
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
)

H = "a" * 64
NOW = 1_000_000_000


def version(name: str, generation: int, *, supersedes: str | None = None) -> CredentialVersion:
    return CredentialVersion(
        secret_id="provider-jupiter",
        version=name,
        backend_ref=f"managed:{name}",
        consumer_id="provider-runtime",
        usage_scope="provider-auth",
        state=CredentialState.STAGED,
        generation=generation,
        issued_at_ns=NOW - 100,
        not_before_ns=NOW - 50,
        expires_at_ns=NOW + 10_000,
        supersedes_version=supersedes,
    )


def prepare_active(authority: DurableCredentialAuthority) -> None:
    authority.register(version("v1", 1), now_ns=NOW)
    authority.set_validated(
        secret_id="provider-jupiter",
        version="v1",
        validation_sha256=H,
        now_ns=NOW,
    )
    authority.activate_initial(secret_id="provider-jupiter", version="v1", now_ns=NOW)


def prepare_v2(authority: DurableCredentialAuthority) -> None:
    authority.register(version("v2", 2, supersedes="v1"), now_ns=NOW)
    authority.set_validated(
        secret_id="provider-jupiter",
        version="v2",
        validation_sha256=H,
        now_ns=NOW,
    )


def plan(rotation_id: str = "rot-1") -> RotationPlan:
    return RotationPlan(
        rotation_id=rotation_id,
        secret_id="provider-jupiter",
        expected_current_version="v1",
        new_version="v2",
        validation_sha256=H,
    )


def test_t2618_001_issued_handle_fails_after_durable_revoke(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    fence = authority.issue_fence(
        secret_id="provider-jupiter",
        version="v1",
        consumer_id="provider-runtime",
        usage_scope="provider-auth",
        now_ns=NOW,
    )
    lease = SecretLease(
        secret_id="provider-jupiter",
        version="v1",
        backend="managed",
        issued_at_ns=NOW - 10,
        expires_at_ns=NOW + 10_000,
        usage_scope="provider-auth",
        consumer_id="provider-runtime",
    )
    raw = SecretHandle("TEST_ONLY_SECRET", source_scheme="managed", lease=lease, clock_ns=lambda: NOW)
    handle = FencedSecretHandle(raw, authority=authority, fence=fence, clock_ns=lambda: NOW)
    assert handle.reveal() == "TEST_ONLY_SECRET"

    authority.revoke(
        incident_id="incident-1",
        secret_id="provider-jupiter",
        version="v1",
        reason=RotationReason.COMPROMISE,
        now_ns=NOW + 1,
    )
    with pytest.raises(CredentialRotationError, match="REVOKED_CURRENT_GENERATION"):
        handle.reveal()


def test_t2618_002_rotation_has_one_preferred_generation(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    prepare_v2(authority)
    receipt = authority.rotate(plan(), now_ns=NOW + 1)
    snapshot = authority.snapshot("provider-jupiter")
    assert snapshot["head"]["preferred_version"] == "v2"
    states = {row["version"]: row["state"] for row in snapshot["versions"]}
    assert states == {"v1": "retiring", "v2": "active"}
    assert receipt.rotation_epoch == 2


def test_t2618_003_stale_trust_registry_is_fenced(tmp_path: Path) -> None:
    authority = DurableTrustGenerationAuthority(tmp_path / "trust.db")
    authority.publish(generation="g1", revocation_epoch=0, now_ns=NOW)
    old = TrustAnchorRegistry((), generation="g1")
    authority.publish(generation="g2", revocation_epoch=1, now_ns=NOW + 1)

    now = datetime.now(timezone.utc)
    envelope = SignedEnvelope(
        domain="release",
        schema_version="v1",
        environment="prod",
        key_id="k1",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=1),
        payload_sha256=hashlib.sha256(b"payload").hexdigest(),
        signature_base58="2" * 88,
    )
    with pytest.raises(CredentialRotationError, match="STALE_TRUST_REGISTRY_GENERATION"):
        authority.verify_current(
            registry=old,
            envelope=envelope,
            payload=b"payload",
            usage=TrustUsage.RELEASE,
            evaluated_at=now,
            expected_domain="release",
            expected_environment="prod",
        )


def test_staged_and_validated_versions_are_not_usable(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    authority.register(version("v1", 1), now_ns=NOW)
    with pytest.raises(CredentialRotationError):
        authority.issue_fence(
            secret_id="provider-jupiter",
            version="v1",
            consumer_id="provider-runtime",
            usage_scope="provider-auth",
            now_ns=NOW,
        )
    authority.set_validated(secret_id="provider-jupiter", version="v1", validation_sha256=H, now_ns=NOW)
    with pytest.raises(CredentialRotationError):
        authority.issue_fence(
            secret_id="provider-jupiter",
            version="v1",
            consumer_id="provider-runtime",
            usage_scope="provider-auth",
            now_ns=NOW,
        )


def test_rotation_replay_is_idempotent_and_semantic_conflict_fails(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    prepare_v2(authority)
    first = authority.rotate(plan(), now_ns=NOW + 1)
    second = authority.rotate(plan(), now_ns=NOW + 2)
    assert second == first
    changed = RotationPlan(
        rotation_id="rot-1",
        secret_id="provider-jupiter",
        expected_current_version="v1",
        new_version="v2",
        validation_sha256="b" * 64,
    )
    with pytest.raises(CredentialRotationError, match="semantic conflict"):
        authority.rotate(changed, now_ns=NOW + 3)


def test_supersedes_mismatch_blocks_cutover(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    authority.register(version("v2", 2, supersedes="other"), now_ns=NOW)
    authority.set_validated(secret_id="provider-jupiter", version="v2", validation_sha256=H, now_ns=NOW)
    with pytest.raises(CredentialRotationError, match="supersedes_version mismatch"):
        authority.rotate(plan(), now_ns=NOW + 1)


def test_two_competing_rotations_have_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "authority.db"
    authority = DurableCredentialAuthority(path)
    prepare_active(authority)
    prepare_v2(authority)
    authority.register(version("v3", 3, supersedes="v1"), now_ns=NOW)
    authority.set_validated(secret_id="provider-jupiter", version="v3", validation_sha256=H, now_ns=NOW)
    errors: list[str] = []
    wins: list[str] = []

    def rotate_to(target: str) -> None:
        local = DurableCredentialAuthority(path)
        p = RotationPlan(
            rotation_id=f"rot-{target}",
            secret_id="provider-jupiter",
            expected_current_version="v1",
            new_version=target,
            validation_sha256=H,
        )
        try:
            wins.append(local.rotate(p, now_ns=NOW + 1).new_version)
        except CredentialRotationError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=rotate_to, args=(target,)) for target in ("v2", "v3")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(wins) == 1
    assert len(errors) == 1
    assert authority.snapshot("provider-jupiter")["head"]["preferred_version"] == wins[0]


def test_revocation_replay_is_idempotent_and_sticky(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    first = authority.revoke(
        incident_id="incident-1",
        secret_id="provider-jupiter",
        version="v1",
        reason=RotationReason.COMPROMISE,
        now_ns=NOW + 1,
    )
    second = authority.revoke(
        incident_id="incident-1",
        secret_id="provider-jupiter",
        version="v1",
        reason=RotationReason.COMPROMISE,
        now_ns=NOW + 2,
    )
    assert second == first
    snapshot = authority.snapshot("provider-jupiter")
    assert snapshot["head"]["preferred_version"] is None
    assert snapshot["versions"][0]["state"] == "revoked"


def test_old_fence_fails_after_unrelated_revocation_epoch_advance(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    fence = authority.issue_fence(
        secret_id="provider-jupiter",
        version="v1",
        consumer_id="provider-runtime",
        usage_scope="provider-auth",
        now_ns=NOW,
    )
    prepare_v2(authority)
    authority.rotate(plan(), now_ns=NOW + 1)
    authority.revoke(
        incident_id="incident-v1",
        secret_id="provider-jupiter",
        version="v1",
        reason=RotationReason.COMPROMISE,
        now_ns=NOW + 2,
    )
    with pytest.raises(CredentialRotationError, match="REVOKED_CURRENT_GENERATION"):
        authority.assert_current_use(fence, now_ns=NOW + 3)


def test_overlap_is_bounded_and_old_is_never_preferred(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    prepare_v2(authority)
    p = RotationPlan(
        rotation_id="rot-overlap",
        secret_id="provider-jupiter",
        expected_current_version="v1",
        new_version="v2",
        validation_sha256=H,
        allowed_overlap_until_ns=NOW + 50,
    )
    authority.rotate(p, now_ns=NOW + 1)
    old_fence = authority.issue_fence(
        secret_id="provider-jupiter",
        version="v1",
        consumer_id="provider-runtime",
        usage_scope="provider-auth",
        now_ns=NOW + 2,
    )
    assert old_fence.version == "v1"
    assert authority.snapshot("provider-jupiter")["head"]["preferred_version"] == "v2"
    with pytest.raises(CredentialRotationError):
        authority.assert_current_use(old_fence, now_ns=NOW + 51)


def test_bool_generation_is_rejected() -> None:
    with pytest.raises(ValueError, match="generation"):
        CredentialVersion(
            secret_id="provider-jupiter",
            version="v1",
            backend_ref="managed:v1",
            consumer_id="provider-runtime",
            usage_scope="provider-auth",
            state=CredentialState.STAGED,
            generation=True,
            issued_at_ns=1,
            not_before_ns=1,
            expires_at_ns=2,
        )


def test_receipts_and_snapshots_do_not_contain_secret_value(tmp_path: Path) -> None:
    authority = DurableCredentialAuthority(tmp_path / "authority.db")
    prepare_active(authority)
    prepare_v2(authority)
    receipt = authority.rotate(plan(), now_ns=NOW + 1)
    text = repr(receipt) + repr(authority.snapshot("provider-jupiter"))
    assert "TEST_ONLY_SECRET" not in text
    assert "Authorization" not in text


def test_trust_usage_stays_distinct_with_current_generation(tmp_path: Path) -> None:
    class AcceptingVerifier:
        def verify(self, **_: object) -> bool:
            return True

    now = datetime.now(timezone.utc)
    anchor = TrustAnchor(
        key_id="k1",
        algorithm="ed25519",
        public_key_base58="2" * 44,
        usages=(TrustUsage.RELEASE,),
        issuer="security",
        environment="prod",
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=1),
        state=TrustAnchorState.ACTIVE,
    )
    registry = TrustAnchorRegistry((anchor,), generation="g2", verifier=AcceptingVerifier())
    authority = DurableTrustGenerationAuthority(tmp_path / "trust.db")
    authority.publish(generation="g2", revocation_epoch=1, now_ns=NOW)
    payload = b"payload"
    envelope = SignedEnvelope(
        domain="signer-policy",
        schema_version="v1",
        environment="prod",
        key_id="k1",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(seconds=30),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_base58="2" * 88,
    )
    result = authority.verify_current(
        registry=registry,
        envelope=envelope,
        payload=payload,
        usage=TrustUsage.SIGNER_POLICY,
        evaluated_at=now,
        expected_domain="signer-policy",
        expected_environment="prod",
    )
    assert result.verified is False
    assert "TRUST_ANCHOR_USAGE_NOT_ALLOWED" in result.blockers


def test_trust_revocation_epoch_cannot_regress(tmp_path: Path) -> None:
    authority = DurableTrustGenerationAuthority(tmp_path / "trust.db")
    authority.publish(generation="g2", revocation_epoch=2, now_ns=NOW)
    with pytest.raises(CredentialRotationError, match="regression"):
        authority.publish(generation="g1", revocation_epoch=1, now_ns=NOW + 1)
