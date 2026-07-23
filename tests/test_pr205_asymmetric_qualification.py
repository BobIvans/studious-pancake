from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from src.release_gate.asymmetric_qualification import (
    PROFILE_POLICY_DOMAIN,
    RELEASE_CLAIM_DOMAIN,
    AsymmetricQualificationClaim,
    AsymmetricQualificationError,
    QualificationProfilePolicy,
    ReleaseArtifact,
    read_json_object_under_root,
    release_digest_for,
    verify_asymmetric_qualification,
)
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
    signable_payload_bytes,
)

_NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


class _AcceptingVerifier:
    def verify(self, *, public_key_base58, signature_base58, message):
        return bool(public_key_base58 and signature_base58 and message)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _anchor(
    *,
    usages: tuple[TrustUsage, ...] = (TrustUsage.RELEASE,),
    state: TrustAnchorState = TrustAnchorState.ACTIVE,
) -> TrustAnchor:
    return TrustAnchor(
        key_id="release-key-2026-07",
        algorithm="ed25519",
        public_key_base58="11111111111111111111111111111111",
        usages=usages,
        issuer="release-security",
        environment="production",
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=30),
        state=state,
        revoked_at=_NOW if state is TrustAnchorState.REVOKED else None,
    )


def _registry(anchor: TrustAnchor | None = None) -> TrustAnchorRegistry:
    return TrustAnchorRegistry(
        (anchor or _anchor(),),
        generation="release-trust-2026-07",
        verifier=_AcceptingVerifier(),
    )


def _policy() -> QualificationProfilePolicy:
    return QualificationProfilePolicy(
        policy_id="production-release-v1",
        environment="production",
        mandatory_profiles=("core", "wheel"),
        required_artifact_roles=(
            "image",
            "provenance",
            "sbom",
            "wheel",
            "wheelhouse",
        ),
        policy_bundle_hash="a" * 64,
        minimum_clean_environments=2,
        max_envelope_ttl_seconds=1800,
    )


def _run_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "pr186.qualification-run.v1",
        "run_id": "run-1",
        "plan_hash": "1" * 64,
        "source": {"digest": "b" * 64},
        "interpreter": {
            "isolated_environment": True,
            "global_site_packages_enabled": False,
        },
        "dependency_closure": {
            "missing_packages": [],
            "non_importable_packages": [],
            "undeclared_packages": [],
        },
        "wheel": {"sha256": "c" * 64, "size_bytes": 100},
        "wheelhouse_manifest_hash": "d" * 64,
        "profiles": [
            {"name": "core", "exit_code": 0},
            {"name": "wheel", "exit_code": 0},
        ],
        "selected_profiles": ["core", "wheel"],
        "network_disabled_after_bootstrap": True,
        "source_import_leakage_detected": False,
    }
    payload["run_hash"] = _digest(payload)
    return payload


def _artifacts() -> tuple[ReleaseArtifact, ...]:
    return (
        ReleaseArtifact("image", "e" * 64, 100),
        ReleaseArtifact("provenance", "f" * 64, 100),
        ReleaseArtifact("sbom", "1" * 64, 100),
        ReleaseArtifact("wheel", "c" * 64, 100),
        ReleaseArtifact("wheelhouse", "d" * 64, 100),
    )


def _claim(
    run: dict[str, object],
    policy: QualificationProfilePolicy,
) -> AsymmetricQualificationClaim:
    artifacts = _artifacts()
    release_digest = release_digest_for(
        source_commit="2" * 64,
        policy_bundle_hash=policy.policy_bundle_hash,
        environment="production",
        artifacts=artifacts,
    )
    return AsymmetricQualificationClaim(
        environment="production",
        source_commit="2" * 64,
        policy_bundle_hash=policy.policy_bundle_hash,
        run_hash=str(run["run_hash"]),
        source_digest="b" * 64,
        profile_policy_sha256=policy.digest,
        artifacts=artifacts,
        clean_environment_run_hashes=(str(run["run_hash"]), "3" * 64),
        release_digest=release_digest,
        claimed_release_allowed=True,
    )


def _envelope(payload: bytes, *, domain: str) -> SignedEnvelope:
    return SignedEnvelope(
        domain=domain,
        schema_version="pr205.signed-evidence.v1",
        environment="production",
        key_id="release-key-2026-07",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=10),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        signature_base58="2" * 88,
    )


def _verify(
    run: dict[str, object],
    claim: AsymmetricQualificationClaim,
    policy: QualificationProfilePolicy,
    *,
    registry: TrustAnchorRegistry | None = None,
):
    return verify_asymmetric_qualification(
        run_payload=run,
        claim=claim,
        claim_envelope=_envelope(
            signable_payload_bytes(claim.to_dict()), domain=RELEASE_CLAIM_DOMAIN
        ),
        profile_policy=policy,
        profile_policy_envelope=_envelope(
            signable_payload_bytes(policy.to_dict()), domain=PROFILE_POLICY_DOMAIN
        ),
        trust_registry=registry or _registry(),
        evaluated_at=_NOW,
        expected_environment="production",
        expected_source_commit="2" * 64,
        expected_policy_bundle_hash="a" * 64,
        expected_release_digest=claim.release_digest,
    )


def test_two_asymmetric_signatures_and_semantic_recompute_allow_release() -> None:
    policy = _policy()
    run = _run_payload()
    claim = _claim(run, policy)

    result = _verify(run, claim, policy)

    assert result.release_claim_allowed is True
    assert result.signature_verified is True
    assert result.profile_policy_signature_verified is True
    assert result.semantic_verification_passed is True
    assert result.blockers == ()


def test_signed_claim_cannot_hide_materialized_run_tampering() -> None:
    policy = _policy()
    run = _run_payload()
    claim = _claim(run, policy)
    run["network_disabled_after_bootstrap"] = False

    result = _verify(run, claim, policy)

    assert result.release_claim_allowed is False
    assert "RUN_HASH_RECOMPUTATION_MISMATCH" in result.blockers
    assert "NETWORK_NOT_DISABLED_AFTER_BOOTSTRAP" in result.blockers


def test_signed_policy_prevents_caller_reducing_mandatory_profiles() -> None:
    policy = _policy()
    run = _run_payload()
    run["selected_profiles"] = ["core"]
    run["profiles"] = [{"name": "core", "exit_code": 0}]
    raw = dict(run)
    raw.pop("run_hash")
    run["run_hash"] = _digest(raw)
    claim = _claim(run, policy)

    result = _verify(run, claim, policy)

    assert result.release_claim_allowed is False
    assert "MANDATORY_PROFILE_SELECTION_INCOMPLETE" in result.blockers
    assert "MANDATORY_PROFILE_EXECUTION_FAILED" in result.blockers


def test_revoked_or_wrong_purpose_anchor_cannot_authorize_release() -> None:
    policy = _policy()
    run = _run_payload()
    claim = _claim(run, policy)
    revoked = _registry(_anchor(state=TrustAnchorState.REVOKED))

    revoked_result = _verify(run, claim, policy, registry=revoked)

    assert revoked_result.release_claim_allowed is False
    assert "TRUST_ANCHOR_REVOKED" in revoked_result.blockers

    evidence_only = _registry(_anchor(usages=(TrustUsage.EVIDENCE,)))
    purpose_result = _verify(run, claim, policy, registry=evidence_only)

    assert purpose_result.release_claim_allowed is False
    assert "TRUST_ANCHOR_USAGE_NOT_ALLOWED" in purpose_result.blockers


def test_secure_artifact_reader_rejects_traversal_symlink_and_hardlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    safe = root / "run.json"
    safe.write_text('{"run": 1}\n', encoding="utf-8")

    assert read_json_object_under_root(root, "run.json") == {"run": 1}
    with pytest.raises(AsymmetricQualificationError, match="below artifact root"):
        read_json_object_under_root(root, "../run.json")

    target = tmp_path / "outside.json"
    target.write_text('{"outside": true}\n', encoding="utf-8")
    (root / "link.json").symlink_to(target)
    with pytest.raises(OSError):
        read_json_object_under_root(root, "link.json")

    if hasattr(os, "link"):
        hardlink = root / "hardlink.json"
        os.link(safe, hardlink)
        with pytest.raises(AsymmetricQualificationError, match="hard-linked"):
            read_json_object_under_root(root, "hardlink.json")


def test_real_ed25519_release_and_policy_signatures() -> None:
    keypair_module = pytest.importorskip("solders.keypair")
    keypair = keypair_module.Keypair()
    policy = _policy()
    run = _run_payload()
    claim = _claim(run, policy)
    anchor = TrustAnchor(
        key_id="real-release-key",
        algorithm="ed25519",
        public_key_base58=str(keypair.pubkey()),
        usages=(TrustUsage.RELEASE,),
        issuer="unit-test",
        environment="production",
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=1),
        state=TrustAnchorState.ACTIVE,
    )

    def signed(payload: bytes, domain: str) -> SignedEnvelope:
        unsigned = SignedEnvelope(
            domain=domain,
            schema_version="pr205.signed-evidence.v1",
            environment="production",
            key_id=anchor.key_id,
            issued_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(minutes=10),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            signature_base58="2" * 88,
        )
        return SignedEnvelope(
            domain=unsigned.domain,
            schema_version=unsigned.schema_version,
            environment=unsigned.environment,
            key_id=unsigned.key_id,
            issued_at=unsigned.issued_at,
            expires_at=unsigned.expires_at,
            payload_sha256=unsigned.payload_sha256,
            signature_base58=str(keypair.sign_message(unsigned.canonical_message())),
        )

    result = verify_asymmetric_qualification(
        run_payload=run,
        claim=claim,
        claim_envelope=signed(
            signable_payload_bytes(claim.to_dict()), RELEASE_CLAIM_DOMAIN
        ),
        profile_policy=policy,
        profile_policy_envelope=signed(
            signable_payload_bytes(policy.to_dict()), PROFILE_POLICY_DOMAIN
        ),
        trust_registry=TrustAnchorRegistry((anchor,), generation="real-ed25519"),
        evaluated_at=_NOW,
        expected_environment="production",
        expected_source_commit="2" * 64,
        expected_policy_bundle_hash="a" * 64,
        expected_release_digest=claim.release_digest,
    )

    assert result.release_claim_allowed is True
