"""PR-205 asymmetric qualification and independently recomputed release evidence.

The executed PR-186 run remains useful qualification evidence, but an HMAC verdict
is not a production release authority.  This module binds the materialized run,
a signed mandatory-profile policy and the complete release artifact identity to
Ed25519 trust anchors.  A release claim is allowed only after both signatures and
the semantic qualification result are independently recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping, Sequence

from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
    signable_payload_bytes,
)

PR205_PROFILE_POLICY_SCHEMA = "pr205.qualification-profile-policy.v1"
PR205_RELEASE_CLAIM_SCHEMA = "pr205.asymmetric-release-claim.v1"
PR205_VERIFICATION_SCHEMA = "pr205.asymmetric-release-verification.v1"
PROFILE_POLICY_DOMAIN = "studious-pancake.qualification-profile-policy"
RELEASE_CLAIM_DOMAIN = "studious-pancake.release-qualification"
REQUIRED_ARTIFACT_ROLES = ("image", "provenance", "sbom", "wheel", "wheelhouse")
_SHA256_LENGTH = 64
_MAX_JSON_BYTES = 2 * 1024 * 1024


class AsymmetricQualificationError(ValueError):
    """Raised when qualification evidence is malformed or unsafe to inspect."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(label: str, value: str) -> None:
    if len(value) != _SHA256_LENGTH:
        raise AsymmetricQualificationError(f"{label} must be lowercase SHA-256")
    try:
        parsed = bytes.fromhex(value)
    except ValueError as exc:
        raise AsymmetricQualificationError(
            f"{label} must be lowercase SHA-256"
        ) from exc
    if parsed.hex() != value:
        raise AsymmetricQualificationError(f"{label} must be lowercase SHA-256")


def _require_non_empty(label: str, value: str) -> None:
    if not value.strip():
        raise AsymmetricQualificationError(f"{label} is required")


def _tuple_of_strings(label: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AsymmetricQualificationError(f"{label} must be a non-empty list")
    rendered = tuple(str(item) for item in value)
    if any(not item.strip() for item in rendered):
        raise AsymmetricQualificationError(f"{label} contains an empty value")
    return rendered


@dataclass(frozen=True, slots=True)
class QualificationProfilePolicy:
    policy_id: str
    environment: str
    mandatory_profiles: tuple[str, ...]
    required_artifact_roles: tuple[str, ...]
    policy_bundle_hash: str
    minimum_clean_environments: int = 2
    max_envelope_ttl_seconds: int = 3600
    schema_version: str = PR205_PROFILE_POLICY_SCHEMA

    def __post_init__(self) -> None:
        _require_non_empty("policy_id", self.policy_id)
        _require_non_empty("environment", self.environment)
        if not self.mandatory_profiles:
            raise AsymmetricQualificationError("mandatory_profiles cannot be empty")
        if len(set(self.mandatory_profiles)) != len(self.mandatory_profiles):
            raise AsymmetricQualificationError("mandatory_profiles must be unique")
        if not self.required_artifact_roles:
            raise AsymmetricQualificationError(
                "required_artifact_roles cannot be empty"
            )
        if len(set(self.required_artifact_roles)) != len(self.required_artifact_roles):
            raise AsymmetricQualificationError("required_artifact_roles must be unique")
        _require_sha256("policy_bundle_hash", self.policy_bundle_hash)
        if self.minimum_clean_environments < 2:
            raise AsymmetricQualificationError(
                "minimum_clean_environments must be at least two"
            )
        if not 1 <= self.max_envelope_ttl_seconds <= 86_400:
            raise AsymmetricQualificationError(
                "max_envelope_ttl_seconds is outside reviewed bounds"
            )
        if self.schema_version != PR205_PROFILE_POLICY_SCHEMA:
            raise AsymmetricQualificationError("unsupported profile policy schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "environment": self.environment,
            "mandatory_profiles": list(self.mandatory_profiles),
            "required_artifact_roles": list(self.required_artifact_roles),
            "policy_bundle_hash": self.policy_bundle_hash,
            "minimum_clean_environments": self.minimum_clean_environments,
            "max_envelope_ttl_seconds": self.max_envelope_ttl_seconds,
        }

    @property
    def digest(self) -> str:
        return _sha256(_canonical_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    role: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require_non_empty("artifact role", self.role)
        _require_sha256(f"artifact {self.role} sha256", self.sha256)
        if self.size_bytes <= 0:
            raise AsymmetricQualificationError(
                f"artifact {self.role} size_bytes must be positive"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class AsymmetricQualificationClaim:
    environment: str
    source_commit: str
    policy_bundle_hash: str
    run_hash: str
    source_digest: str
    profile_policy_sha256: str
    artifacts: tuple[ReleaseArtifact, ...]
    clean_environment_run_hashes: tuple[str, ...]
    release_digest: str
    claimed_release_allowed: bool
    schema_version: str = PR205_RELEASE_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        _require_non_empty("environment", self.environment)
        _require_sha256("source_commit", self.source_commit)
        _require_sha256("policy_bundle_hash", self.policy_bundle_hash)
        _require_sha256("run_hash", self.run_hash)
        _require_sha256("source_digest", self.source_digest)
        _require_sha256("profile_policy_sha256", self.profile_policy_sha256)
        _require_sha256("release_digest", self.release_digest)
        if not self.artifacts:
            raise AsymmetricQualificationError("release artifacts cannot be empty")
        roles = [item.role for item in self.artifacts]
        if len(set(roles)) != len(roles):
            raise AsymmetricQualificationError("release artifact roles must be unique")
        if len(set(self.clean_environment_run_hashes)) != len(
            self.clean_environment_run_hashes
        ):
            raise AsymmetricQualificationError(
                "clean environment run hashes must be distinct"
            )
        for value in self.clean_environment_run_hashes:
            _require_sha256("clean environment run hash", value)
        if self.schema_version != PR205_RELEASE_CLAIM_SCHEMA:
            raise AsymmetricQualificationError("unsupported release claim schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "environment": self.environment,
            "source_commit": self.source_commit,
            "policy_bundle_hash": self.policy_bundle_hash,
            "run_hash": self.run_hash,
            "source_digest": self.source_digest,
            "profile_policy_sha256": self.profile_policy_sha256,
            "artifacts": [
                item.to_dict() for item in sorted(self.artifacts, key=lambda x: x.role)
            ],
            "clean_environment_run_hashes": sorted(self.clean_environment_run_hashes),
            "release_digest": self.release_digest,
            "claimed_release_allowed": self.claimed_release_allowed,
        }


@dataclass(frozen=True, slots=True)
class AsymmetricQualificationVerification:
    release_claim_allowed: bool
    signature_verified: bool
    profile_policy_signature_verified: bool
    semantic_verification_passed: bool
    blockers: tuple[str, ...]
    run_hash: str
    source_commit: str
    release_digest: str
    trust_registry_generation: str
    schema_version: str = PR205_VERIFICATION_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_claim_allowed": self.release_claim_allowed,
            "signature_verified": self.signature_verified,
            "profile_policy_signature_verified": (
                self.profile_policy_signature_verified
            ),
            "semantic_verification_passed": self.semantic_verification_passed,
            "blockers": list(self.blockers),
            "run_hash": self.run_hash,
            "source_commit": self.source_commit,
            "release_digest": self.release_digest,
            "trust_registry_generation": self.trust_registry_generation,
        }


def release_digest_for(
    *,
    source_commit: str,
    policy_bundle_hash: str,
    environment: str,
    artifacts: Sequence[ReleaseArtifact],
) -> str:
    _require_sha256("source_commit", source_commit)
    _require_sha256("policy_bundle_hash", policy_bundle_hash)
    _require_non_empty("environment", environment)
    payload = {
        "domain": "studious-pancake.release-artifact-set.v1",
        "source_commit": source_commit,
        "policy_bundle_hash": policy_bundle_hash,
        "environment": environment,
        "artifacts": [
            item.to_dict() for item in sorted(artifacts, key=lambda item: item.role)
        ],
    }
    return _sha256(_canonical_bytes(payload))


def _recompute_run_hash(run_payload: Mapping[str, object]) -> tuple[str, str]:
    raw = dict(run_payload)
    observed = str(raw.pop("run_hash", ""))
    _require_sha256("run_hash", observed)
    return observed, _sha256(_canonical_bytes(raw))


def _semantic_blockers(
    *,
    run_payload: Mapping[str, object],
    claim: AsymmetricQualificationClaim,
    profile_policy: QualificationProfilePolicy,
    expected_environment: str,
    expected_source_commit: str,
    expected_policy_bundle_hash: str,
    expected_release_digest: str,
) -> list[str]:
    blockers: list[str] = []
    try:
        observed_run_hash, recomputed_run_hash = _recompute_run_hash(run_payload)
    except AsymmetricQualificationError:
        observed_run_hash = ""
        recomputed_run_hash = ""
        blockers.append("RUN_HASH_MALFORMED")
    if observed_run_hash != recomputed_run_hash:
        blockers.append("RUN_HASH_RECOMPUTATION_MISMATCH")
    if claim.run_hash != observed_run_hash:
        blockers.append("CLAIM_RUN_HASH_MISMATCH")

    if str(run_payload.get("schema_version", "")) != "pr186.qualification-run.v1":
        blockers.append("UNSUPPORTED_QUALIFICATION_RUN_SCHEMA")
    source = run_payload.get("source")
    source_digest = str(source.get("digest", "")) if isinstance(source, Mapping) else ""
    if source_digest != claim.source_digest:
        blockers.append("SOURCE_DIGEST_MISMATCH")

    selected_raw = run_payload.get("selected_profiles")
    selected = (
        {str(item) for item in selected_raw}
        if isinstance(selected_raw, list)
        else set()
    )
    mandatory = set(profile_policy.mandatory_profiles)
    if not mandatory.issubset(selected):
        blockers.append("MANDATORY_PROFILE_SELECTION_INCOMPLETE")

    profiles_raw = run_payload.get("profiles")
    passed_profiles: set[str] = set()
    if isinstance(profiles_raw, list):
        for item in profiles_raw:
            if isinstance(item, Mapping) and int(item.get("exit_code", 1)) == 0:
                passed_profiles.add(str(item.get("name", "")))
    if not mandatory.issubset(passed_profiles):
        blockers.append("MANDATORY_PROFILE_EXECUTION_FAILED")

    closure = run_payload.get("dependency_closure")
    if not isinstance(closure, Mapping):
        blockers.append("DEPENDENCY_CLOSURE_MISSING")
    else:
        for field in (
            "missing_packages",
            "non_importable_packages",
            "undeclared_packages",
        ):
            value = closure.get(field)
            if not isinstance(value, list) or value:
                blockers.append("INSTALLED_DEPENDENCY_CLOSURE_INCOMPLETE")
                break

    interpreter = run_payload.get("interpreter")
    if not isinstance(interpreter, Mapping):
        blockers.append("INTERPRETER_IDENTITY_MISSING")
    else:
        if interpreter.get("isolated_environment") is not True:
            blockers.append("INTERPRETER_NOT_ISOLATED")
        if interpreter.get("global_site_packages_enabled") is not False:
            blockers.append("GLOBAL_SITE_PACKAGES_ENABLED")

    if run_payload.get("network_disabled_after_bootstrap") is not True:
        blockers.append("NETWORK_NOT_DISABLED_AFTER_BOOTSTRAP")
    if run_payload.get("source_import_leakage_detected") is not False:
        blockers.append("SOURCE_IMPORT_LEAKAGE_DETECTED")

    artifact_by_role = {item.role: item for item in claim.artifacts}
    missing_roles = set(profile_policy.required_artifact_roles).difference(
        artifact_by_role
    )
    if missing_roles:
        blockers.append("REQUIRED_RELEASE_ARTIFACT_MISSING")
    wheel = run_payload.get("wheel")
    wheel_sha256 = str(wheel.get("sha256", "")) if isinstance(wheel, Mapping) else ""
    if artifact_by_role.get("wheel") is None:
        blockers.append("PRODUCTION_WHEEL_MISSING")
    elif artifact_by_role["wheel"].sha256 != wheel_sha256:
        blockers.append("PRODUCTION_WHEEL_IDENTITY_MISMATCH")

    if not run_payload.get("wheelhouse_manifest_hash"):
        blockers.append("WHEELHOUSE_IDENTITY_MISSING")

    if claim.profile_policy_sha256 != profile_policy.digest:
        blockers.append("PROFILE_POLICY_DIGEST_MISMATCH")
    if claim.environment != expected_environment:
        blockers.append("CLAIM_ENVIRONMENT_MISMATCH")
    if profile_policy.environment != expected_environment:
        blockers.append("PROFILE_POLICY_ENVIRONMENT_MISMATCH")
    if claim.source_commit != expected_source_commit:
        blockers.append("SOURCE_COMMIT_MISMATCH")
    if claim.policy_bundle_hash != expected_policy_bundle_hash:
        blockers.append("POLICY_BUNDLE_HASH_MISMATCH")
    if profile_policy.policy_bundle_hash != expected_policy_bundle_hash:
        blockers.append("PROFILE_POLICY_BUNDLE_HASH_MISMATCH")
    if claim.release_digest != expected_release_digest:
        blockers.append("EXPECTED_RELEASE_DIGEST_MISMATCH")

    recomputed_release_digest = release_digest_for(
        source_commit=claim.source_commit,
        policy_bundle_hash=claim.policy_bundle_hash,
        environment=claim.environment,
        artifacts=claim.artifacts,
    )
    if claim.release_digest != recomputed_release_digest:
        blockers.append("RELEASE_DIGEST_RECOMPUTATION_MISMATCH")

    clean_hashes = set(claim.clean_environment_run_hashes)
    if len(clean_hashes) < profile_policy.minimum_clean_environments:
        blockers.append("INDEPENDENT_CLEAN_ENVIRONMENTS_INSUFFICIENT")
    if observed_run_hash and observed_run_hash not in clean_hashes:
        blockers.append("CURRENT_RUN_NOT_IN_CLEAN_ENVIRONMENT_SET")
    if claim.claimed_release_allowed is not True:
        blockers.append("CLAIM_DOES_NOT_REQUEST_RELEASE")
    return blockers


def _ttl_seconds(envelope: SignedEnvelope) -> float:
    return (envelope.expires_at - envelope.issued_at).total_seconds()


def verify_asymmetric_qualification(
    *,
    run_payload: Mapping[str, object],
    claim: AsymmetricQualificationClaim,
    claim_envelope: SignedEnvelope,
    profile_policy: QualificationProfilePolicy,
    profile_policy_envelope: SignedEnvelope,
    trust_registry: TrustAnchorRegistry,
    evaluated_at: datetime,
    expected_environment: str,
    expected_source_commit: str,
    expected_policy_bundle_hash: str,
    expected_release_digest: str,
) -> AsymmetricQualificationVerification:
    claim_payload = signable_payload_bytes(claim.to_dict())
    policy_payload = signable_payload_bytes(profile_policy.to_dict())
    claim_verification = trust_registry.verify(
        claim_envelope,
        claim_payload,
        usage=TrustUsage.RELEASE,
        evaluated_at=evaluated_at,
        expected_domain=RELEASE_CLAIM_DOMAIN,
        expected_environment=expected_environment,
    )
    policy_verification = trust_registry.verify(
        profile_policy_envelope,
        policy_payload,
        usage=TrustUsage.RELEASE,
        evaluated_at=evaluated_at,
        expected_domain=PROFILE_POLICY_DOMAIN,
        expected_environment=expected_environment,
    )
    blockers = list(claim_verification.blockers)
    blockers.extend(f"PROFILE_POLICY_{value}" for value in policy_verification.blockers)
    if _ttl_seconds(claim_envelope) > profile_policy.max_envelope_ttl_seconds:
        blockers.append("RELEASE_CLAIM_TTL_EXCEEDS_POLICY")
    if _ttl_seconds(profile_policy_envelope) > profile_policy.max_envelope_ttl_seconds:
        blockers.append("PROFILE_POLICY_TTL_EXCEEDS_POLICY")
    semantic_blockers = _semantic_blockers(
        run_payload=run_payload,
        claim=claim,
        profile_policy=profile_policy,
        expected_environment=expected_environment,
        expected_source_commit=expected_source_commit,
        expected_policy_bundle_hash=expected_policy_bundle_hash,
        expected_release_digest=expected_release_digest,
    )
    blockers.extend(semantic_blockers)
    unique_blockers = tuple(dict.fromkeys(blockers))
    semantic_passed = not semantic_blockers
    return AsymmetricQualificationVerification(
        release_claim_allowed=(
            claim_verification.verified
            and policy_verification.verified
            and not unique_blockers
        ),
        signature_verified=claim_verification.verified,
        profile_policy_signature_verified=policy_verification.verified,
        semantic_verification_passed=semantic_passed,
        blockers=unique_blockers,
        run_hash=claim.run_hash,
        source_commit=claim.source_commit,
        release_digest=claim.release_digest,
        trust_registry_generation=trust_registry.generation,
    )


def profile_policy_from_dict(value: Mapping[str, object]) -> QualificationProfilePolicy:
    return QualificationProfilePolicy(
        policy_id=str(value.get("policy_id", "")),
        environment=str(value.get("environment", "")),
        mandatory_profiles=_tuple_of_strings(
            "mandatory_profiles", value.get("mandatory_profiles")
        ),
        required_artifact_roles=_tuple_of_strings(
            "required_artifact_roles", value.get("required_artifact_roles")
        ),
        policy_bundle_hash=str(value.get("policy_bundle_hash", "")),
        minimum_clean_environments=int(str(value.get("minimum_clean_environments", 2))),
        max_envelope_ttl_seconds=int(str(value.get("max_envelope_ttl_seconds", 3600))),
        schema_version=str(value.get("schema_version", "")),
    )


def release_claim_from_dict(
    value: Mapping[str, object],
) -> AsymmetricQualificationClaim:
    raw_artifacts = value.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise AsymmetricQualificationError("artifacts must be a list")
    artifacts = tuple(
        ReleaseArtifact(
            role=str(item.get("role", "")),
            sha256=str(item.get("sha256", "")),
            size_bytes=int(item.get("size_bytes", 0)),
        )
        for item in raw_artifacts
        if isinstance(item, Mapping)
    )
    if len(artifacts) != len(raw_artifacts):
        raise AsymmetricQualificationError("artifact entries must be objects")
    clean_hashes = value.get("clean_environment_run_hashes")
    if not isinstance(clean_hashes, list):
        raise AsymmetricQualificationError(
            "clean_environment_run_hashes must be a list"
        )
    return AsymmetricQualificationClaim(
        environment=str(value.get("environment", "")),
        source_commit=str(value.get("source_commit", "")),
        policy_bundle_hash=str(value.get("policy_bundle_hash", "")),
        run_hash=str(value.get("run_hash", "")),
        source_digest=str(value.get("source_digest", "")),
        profile_policy_sha256=str(value.get("profile_policy_sha256", "")),
        artifacts=artifacts,
        clean_environment_run_hashes=tuple(str(item) for item in clean_hashes),
        release_digest=str(value.get("release_digest", "")),
        claimed_release_allowed=value.get("claimed_release_allowed") is True,
        schema_version=str(value.get("schema_version", "")),
    )


def signed_envelope_from_dict(value: Mapping[str, object]) -> SignedEnvelope:
    return SignedEnvelope(
        domain=str(value.get("domain", "")),
        schema_version=str(value.get("schema_version", "")),
        environment=str(value.get("environment", "")),
        key_id=str(value.get("key_id", "")),
        issued_at=datetime.fromisoformat(str(value.get("issued_at", ""))),
        expires_at=datetime.fromisoformat(str(value.get("expires_at", ""))),
        payload_sha256=str(value.get("payload_sha256", "")),
        signature_base58=str(value.get("signature_base58", "")),
    )


def trust_registry_from_dict(value: Mapping[str, object]) -> TrustAnchorRegistry:
    raw_anchors = value.get("anchors")
    if not isinstance(raw_anchors, list) or not raw_anchors:
        raise AsymmetricQualificationError("trust registry anchors are required")
    anchors: list[TrustAnchor] = []
    for item in raw_anchors:
        if not isinstance(item, Mapping):
            raise AsymmetricQualificationError("trust anchor entry must be an object")
        usages = item.get("usages")
        if not isinstance(usages, list):
            raise AsymmetricQualificationError("trust anchor usages must be a list")
        revoked_raw = item.get("revoked_at")
        anchors.append(
            TrustAnchor(
                key_id=str(item.get("key_id", "")),
                algorithm=str(item.get("algorithm", "")),
                public_key_base58=str(item.get("public_key_base58", "")),
                usages=tuple(TrustUsage(str(usage)) for usage in usages),
                issuer=str(item.get("issuer", "")),
                environment=str(item.get("environment", "")),
                valid_from=datetime.fromisoformat(str(item.get("valid_from", ""))),
                valid_until=datetime.fromisoformat(str(item.get("valid_until", ""))),
                state=TrustAnchorState(str(item.get("state", ""))),
                revoked_at=(
                    None
                    if revoked_raw in (None, "")
                    else datetime.fromisoformat(str(revoked_raw))
                ),
                minimum_security_level=int(item.get("minimum_security_level", 128)),
            )
        )
    return TrustAnchorRegistry(
        tuple(anchors), generation=str(value.get("generation", ""))
    )


def read_json_object_under_root(
    root: Path,
    relative_path: str,
    *,
    max_bytes: int = _MAX_JSON_BYTES,
) -> Mapping[str, object]:
    """Read one bounded regular JSON file without symlink/hardlink traversal."""

    if max_bytes <= 0:
        raise AsymmetricQualificationError("max_bytes must be positive")
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise AsymmetricQualificationError(
            "artifact path must stay below artifact root"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | getattr(os, "O_DIRECTORY", 0) | nofollow
    descriptor = os.open(root, directory_flags)
    try:
        for component in relative.parts[:-1]:
            next_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(
            relative.parts[-1], flags | nofollow, dir_fd=descriptor
        )
    finally:
        os.close(descriptor)
    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AsymmetricQualificationError("artifact is not a regular file")
        if before.st_nlink != 1:
            raise AsymmetricQualificationError("hard-linked artifacts are not accepted")
        if before.st_size <= 0 or before.st_size > max_bytes:
            raise AsymmetricQualificationError(
                "artifact size is outside reviewed bounds"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 65_536))
            if not chunk:
                raise AsymmetricQualificationError("artifact changed during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(file_descriptor, 1):
            raise AsymmetricQualificationError("artifact grew during read")
        after = os.fstat(file_descriptor)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise AsymmetricQualificationError("artifact identity changed during read")
    finally:
        os.close(file_descriptor)
    try:
        decoded = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AsymmetricQualificationError("artifact must be UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise AsymmetricQualificationError("artifact JSON root must be an object")
    return decoded


__all__ = [
    "AsymmetricQualificationClaim",
    "AsymmetricQualificationError",
    "AsymmetricQualificationVerification",
    "PROFILE_POLICY_DOMAIN",
    "PR205_PROFILE_POLICY_SCHEMA",
    "PR205_RELEASE_CLAIM_SCHEMA",
    "PR205_VERIFICATION_SCHEMA",
    "QualificationProfilePolicy",
    "RELEASE_CLAIM_DOMAIN",
    "REQUIRED_ARTIFACT_ROLES",
    "ReleaseArtifact",
    "profile_policy_from_dict",
    "read_json_object_under_root",
    "release_claim_from_dict",
    "release_digest_for",
    "signed_envelope_from_dict",
    "trust_registry_from_dict",
    "verify_asymmetric_qualification",
]
