"""PR-143 policy/config governance and privacy-safe evidence envelopes.

This module is intentionally side-effect free.  It does not read environment
variables, contact providers, load private keys, sign, submit, or mutate active
runtime state.  It provides the reusable primitives that later integration work
can use to bind attempts/plans/simulations/authorizations to one immutable
PolicyBundle and one typed redaction/evidence system.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class PolicyGovernanceError(ValueError):
    """Raised when policy/evidence material is unsafe or non-canonical."""


class GovernanceState(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    SHADOW_APPROVED = "shadow_approved"
    CANARY_APPROVED = "canary_approved"
    ACTIVE = "active"
    REVOKED = "revoked"
    ROLLED_BACK = "rolled_back"


class RetryDisposition(str, Enum):
    NEVER = "never"
    AFTER_REVIEW = "after_review"
    AFTER_ROTATION = "after_rotation"
    AFTER_REBUILD = "after_rebuild"


class DataClassification(str, Enum):
    SECRET = "secret"
    SENSITIVE = "sensitive"
    PUBLIC_CHAIN_IDENTIFIER = "public_chain_identifier"
    OPERATIONAL = "operational"
    SAFE_AGGREGATE = "safe_aggregate"


POLICY_BUNDLE_DOMAIN = "flashloan-bot/policy-bundle"
ATTEMPT_SNAPSHOT_DOMAIN = "flashloan-bot/attempt-policy-snapshot"
SECRET_LOCATOR_DOMAIN = "flashloan-bot/secret-locator-identity"
DIAGNOSTIC_DOMAIN = "flashloan-bot/typed-diagnostic"
GOVERNANCE_EVENT_DOMAIN = "flashloan-bot/policy-governance-event"
CANONICAL_SCHEMA_VERSION = "pr143.canonical-envelope.v1"
MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991

REQUIRED_POLICY_COMPONENTS: tuple[str, ...] = (
    "runtime_config",
    "secret_locator_identities",
    "risk_capital_policy",
    "provider_endpoints_capabilities",
    "credential_availability",
    "external_contract_evidence",
    "chain_program_attestations",
    "marginfi_protocol_evidence",
    "asset_mint_registry",
    "jupiter_quota_route_policy",
    "compute_fee_policy",
    "signer_policy",
    "sender_policy",
    "build_image_sbom_identity",
    "schema_versions",
)

_SECRET_KEY_RE = re.compile(
    r"(secret|private[_-]?key|api[_-]?key|token|authorization|auth|password|seed|mnemonic)",
    re.IGNORECASE,
)
_SENSITIVE_KEY_RE = re.compile(
    r"(url|endpoint|path|account|wallet|signature|tx|transaction|locator)",
    re.IGNORECASE,
)
_URL_SECRET_RE = re.compile(
    r"([?&](?:api[_-]?key|token|auth|signature|secret|password)=)[^&#\s]+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_LONG_BASE58_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,}\b")


@dataclass(frozen=True, slots=True)
class HashRef:
    """Domain-qualified reference to an immutable evidence object."""

    domain: str
    digest: str
    schema_version: str = CANONICAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.domain:
            raise PolicyGovernanceError("hash reference domain must be non-empty")
        if not _is_sha256_hex(self.digest):
            raise PolicyGovernanceError("hash reference digest must be SHA-256 hex")


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Domain-separated canonical hash envelope."""

    domain: str
    schema_version: str
    cluster_genesis: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.domain:
            raise PolicyGovernanceError("domain must be non-empty")
        if not self.schema_version:
            raise PolicyGovernanceError("schema_version must be non-empty")
        if not self.cluster_genesis:
            raise PolicyGovernanceError("cluster_genesis must be non-empty")

    def to_payload(self) -> Mapping[str, Any]:
        return {
            "domain": self.domain,
            "schema_version": self.schema_version,
            "cluster_genesis": self.cluster_genesis,
            "payload": self.payload,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_payload())

    @property
    def digest(self) -> str:
        prefix = f"{CANONICAL_SCHEMA_VERSION}\0{self.domain}\0".encode("utf-8")
        return hashlib.sha256(prefix + self.canonical_bytes).hexdigest()

    def to_hash_ref(self) -> HashRef:
        return HashRef(
            domain=self.domain,
            digest=self.digest,
            schema_version=self.schema_version,
        )


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    """Immutable policy snapshot used to bind attempts and evidence."""

    cluster_genesis: str
    components: Mapping[str, HashRef]
    generation: int = 1
    operator_approval: HashRef | None = None
    schema_version: str = "pr143.policy-bundle.v1"

    def __post_init__(self) -> None:
        if not self.cluster_genesis:
            raise PolicyGovernanceError("cluster_genesis must be non-empty")
        if self.generation < 1:
            raise PolicyGovernanceError("generation must be positive")
        missing = sorted(set(REQUIRED_POLICY_COMPONENTS) - set(self.components))
        if missing:
            raise PolicyGovernanceError(f"missing policy components: {missing}")

    @property
    def payload(self) -> Mapping[str, Any]:
        return {
            "generation": self.generation,
            "components": {
                key: {
                    "domain": ref.domain,
                    "schema_version": ref.schema_version,
                    "digest": ref.digest,
                }
                for key, ref in sorted(self.components.items())
            },
            "operator_approval": (
                None
                if self.operator_approval is None
                else {
                    "domain": self.operator_approval.domain,
                    "schema_version": self.operator_approval.schema_version,
                    "digest": self.operator_approval.digest,
                }
            ),
        }

    @property
    def envelope(self) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            domain=POLICY_BUNDLE_DOMAIN,
            schema_version=self.schema_version,
            cluster_genesis=self.cluster_genesis,
            payload=self.payload,
        )

    @property
    def digest(self) -> str:
        return self.envelope.digest


@dataclass(frozen=True, slots=True)
class AttemptPolicySnapshot:
    attempt_id: str
    attempt_generation: int
    policy_bundle_hash: str
    config_version: str
    evidence_max_age_slots: int
    registry_versions: Mapping[str, str]
    model_version: str
    operator_approval_version: str
    cluster_genesis: str
    schema_version: str = "pr143.attempt-policy-snapshot.v1"

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise PolicyGovernanceError("attempt_id must be non-empty")
        if self.attempt_generation < 1:
            raise PolicyGovernanceError("attempt_generation must be positive")
        if not _is_sha256_hex(self.policy_bundle_hash):
            raise PolicyGovernanceError("policy_bundle_hash must be SHA-256 hex")
        if self.evidence_max_age_slots < 0:
            raise PolicyGovernanceError("evidence_max_age_slots must be non-negative")

    @property
    def envelope(self) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            domain=ATTEMPT_SNAPSHOT_DOMAIN,
            schema_version=self.schema_version,
            cluster_genesis=self.cluster_genesis,
            payload={
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "policy_bundle_hash": self.policy_bundle_hash,
                "config_version": self.config_version,
                "evidence_max_age_slots": self.evidence_max_age_slots,
                "registry_versions": dict(sorted(self.registry_versions.items())),
                "model_version": self.model_version,
                "operator_approval_version": self.operator_approval_version,
            },
        )

    @property
    def digest(self) -> str:
        return self.envelope.digest


@dataclass(frozen=True, slots=True)
class PolicyCompatibilityDecision:
    submission_allowed: bool
    requires_rebuild: bool
    reason: str
    attempt_policy_hash: str
    current_policy_hash: str


@dataclass(frozen=True, slots=True)
class TypedDiagnostic:
    code: str
    category: str
    retry: RetryDisposition
    correlation_id: str
    safe_context: Mapping[str, Any]
    exception_type: str | None = None
    internal_debug_ref: str | None = None
    schema_version: str = "pr143.typed-diagnostic.v1"

    @property
    def envelope(self) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            domain=DIAGNOSTIC_DOMAIN,
            schema_version=self.schema_version,
            cluster_genesis="diagnostic-local",
            payload={
                "code": self.code,
                "category": self.category,
                "retry": self.retry.value,
                "correlation_id": self.correlation_id,
                "safe_context": self.safe_context,
                "exception_type": self.exception_type,
                "internal_debug_ref": self.internal_debug_ref,
            },
        )


@dataclass(frozen=True, slots=True)
class GovernanceRecord:
    bundle_hash: str
    state: GovernanceState
    operator_identity_hash: str
    reason: str
    review_record_hash: str | None = None
    expires_at_utc: str | None = None
    previous_bundle_hash: str | None = None
    live_impacting: bool = False
    dual_approval_hash: str | None = None
    schema_version: str = "pr143.governance-record.v1"

    def __post_init__(self) -> None:
        if not _is_sha256_hex(self.bundle_hash):
            raise PolicyGovernanceError("bundle_hash must be SHA-256 hex")
        if not _is_sha256_hex(self.operator_identity_hash):
            raise PolicyGovernanceError("operator_identity_hash must be SHA-256 hex")
        if self.review_record_hash is not None and not _is_sha256_hex(
            self.review_record_hash
        ):
            raise PolicyGovernanceError("review_record_hash must be SHA-256 hex")
        if self.previous_bundle_hash is not None and not _is_sha256_hex(
            self.previous_bundle_hash
        ):
            raise PolicyGovernanceError("previous_bundle_hash must be SHA-256 hex")
        if self.dual_approval_hash is not None and not _is_sha256_hex(
            self.dual_approval_hash
        ):
            raise PolicyGovernanceError("dual_approval_hash must be SHA-256 hex")


class AtomicPolicyActivator:
    """In-memory atomic activation model for reviewable policy transitions."""

    def __init__(self, initial_active: GovernanceRecord | None = None) -> None:
        self._active = initial_active
        self._history: list[GovernanceRecord] = []
        if initial_active is not None:
            if initial_active.state is not GovernanceState.ACTIVE:
                raise PolicyGovernanceError("initial_active must have ACTIVE state")
            self._history.append(initial_active)

    @property
    def active(self) -> GovernanceRecord | None:
        return self._active

    @property
    def history(self) -> tuple[GovernanceRecord, ...]:
        return tuple(self._history)

    def activate(self, proposed: GovernanceRecord) -> GovernanceRecord:
        if proposed.state not in {
            GovernanceState.SHADOW_APPROVED,
            GovernanceState.CANARY_APPROVED,
        }:
            raise PolicyGovernanceError("only approved policy bundles can be activated")
        if proposed.live_impacting and proposed.dual_approval_hash is None:
            raise PolicyGovernanceError("live-impacting policy requires dual approval")

        active = GovernanceRecord(
            bundle_hash=proposed.bundle_hash,
            state=GovernanceState.ACTIVE,
            operator_identity_hash=proposed.operator_identity_hash,
            reason=proposed.reason,
            review_record_hash=proposed.review_record_hash,
            expires_at_utc=proposed.expires_at_utc,
            previous_bundle_hash=(
                None if self._active is None else self._active.bundle_hash
            ),
            live_impacting=proposed.live_impacting,
            dual_approval_hash=proposed.dual_approval_hash,
        )
        self._active = active
        self._history.append(active)
        return active

    def rollback(self, operator_identity_hash: str, reason: str) -> GovernanceRecord:
        if self._active is None:
            raise PolicyGovernanceError("cannot rollback without active policy")
        previous = self._active.previous_bundle_hash
        if previous is None:
            raise PolicyGovernanceError("no previous known-good policy bundle")
        rolled_back = GovernanceRecord(
            bundle_hash=previous,
            state=GovernanceState.ROLLED_BACK,
            operator_identity_hash=operator_identity_hash,
            reason=reason,
            previous_bundle_hash=self._active.bundle_hash,
        )
        self._active = rolled_back
        self._history.append(rolled_back)
        return rolled_back


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JCS-compatible, security-safe JSON subset.

    Binary floats are rejected. Integers outside interoperable JSON range are
    represented as tagged decimal strings so cross-language implementations do
    not round money/slot values.
    """

    normalized = _normalize_canonical(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_json_no_duplicate_keys(raw: str) -> Any:
    def pairs_hook(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PolicyGovernanceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=pairs_hook, parse_float=_reject_float)


def domain_hash(
    *,
    domain: str,
    payload: Mapping[str, Any],
    cluster_genesis: str,
    schema_version: str = CANONICAL_SCHEMA_VERSION,
) -> str:
    return EvidenceEnvelope(
        domain=domain,
        schema_version=schema_version,
        cluster_genesis=cluster_genesis,
        payload=payload,
    ).digest


def require_hash_domain(ref: HashRef, expected_domain: str) -> None:
    if ref.domain != expected_domain:
        raise PolicyGovernanceError(
            f"hash domain mismatch: expected {expected_domain}, got {ref.domain}"
        )


def fingerprint_secret_locator(locator: str) -> HashRef:
    """Fingerprint locator identity without hashing or exposing secret value.

    `env:KEY_A` and `env:KEY_B` intentionally produce different fingerprints
    while only the non-secret locator name is hashed.
    """

    scheme, _, name = locator.partition(":")
    if not scheme or not name:
        raise PolicyGovernanceError("secret locator must use scheme:name form")
    if scheme not in {"env", "file", "keychain", "vault"}:
        raise PolicyGovernanceError("unsupported secret locator scheme")
    safe_name = str(Path(name).name) if scheme == "file" else name
    envelope = EvidenceEnvelope(
        domain=SECRET_LOCATOR_DOMAIN,
        schema_version="pr143.secret-locator.v1",
        cluster_genesis="locator-local",
        payload={"scheme": scheme, "locator_identity": safe_name},
    )
    return envelope.to_hash_ref()


def classify_field(key: str) -> DataClassification:
    if _SECRET_KEY_RE.search(key):
        return DataClassification.SECRET
    if _SENSITIVE_KEY_RE.search(key):
        return DataClassification.SENSITIVE
    if key.endswith("_pubkey") or key.endswith("_program_id") or key in {
        "mint",
        "owner",
        "program_id",
    }:
        return DataClassification.PUBLIC_CHAIN_IDENTIFIER
    return DataClassification.OPERATIONAL


def redact_value(key: str, value: Any) -> Any:
    classification = classify_field(key)
    if classification is DataClassification.SECRET:
        return "<redacted:secret>"
    if classification is DataClassification.SENSITIVE:
        return _redact_sensitive(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_value(str(child_key), child)
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_value(key, child) for child in value]
    return value


def redact_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return {str(key): redact_value(str(key), value) for key, value in values.items()}


def safe_diagnostic_from_exception(
    *,
    code: str,
    category: str,
    retry: RetryDisposition,
    correlation_id: str,
    exc: BaseException,
    context: Mapping[str, Any] | None = None,
    internal_debug_ref: str | None = None,
) -> TypedDiagnostic:
    """Create diagnostic evidence without persisting raw ``str(exc)``."""

    return TypedDiagnostic(
        code=code,
        category=category,
        retry=retry,
        correlation_id=correlation_id,
        safe_context=redact_mapping(context or {}),
        exception_type=type(exc).__name__,
        internal_debug_ref=internal_debug_ref,
    )


def validate_attempt_policy(
    snapshot: AttemptPolicySnapshot,
    current_policy: PolicyBundle,
    *,
    live_submission_requested: bool = False,
) -> PolicyCompatibilityDecision:
    current_hash = current_policy.digest
    if snapshot.policy_bundle_hash != current_hash:
        return PolicyCompatibilityDecision(
            submission_allowed=False,
            requires_rebuild=True,
            reason="policy_bundle_hash_changed",
            attempt_policy_hash=snapshot.policy_bundle_hash,
            current_policy_hash=current_hash,
        )
    if live_submission_requested and current_policy.operator_approval is None:
        return PolicyCompatibilityDecision(
            submission_allowed=False,
            requires_rebuild=False,
            reason="live_submission_requires_operator_approval",
            attempt_policy_hash=snapshot.policy_bundle_hash,
            current_policy_hash=current_hash,
        )
    return PolicyCompatibilityDecision(
        submission_allowed=True,
        requires_rebuild=False,
        reason="policy_compatible",
        attempt_policy_hash=snapshot.policy_bundle_hash,
        current_policy_hash=current_hash,
    )


def assert_no_hot_env_decision(source_text: str) -> None:
    """Static guard for production behavior code snippets."""

    forbidden = ("os.getenv(", "os.environ[", "os.environ.get(")
    if any(token in source_text for token in forbidden):
        raise PolicyGovernanceError("hot environment decision detected")


def assert_no_raw_exception_persistence(source_text: str) -> None:
    forbidden = ("str(exc)", "str(error)", "repr(exc)", "repr(error)")
    if any(token in source_text for token in forbidden):
        raise PolicyGovernanceError("raw exception persistence detected")


def _normalize_canonical(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_JSON_INTEGER:
            return {"$int": str(value)}
        return value
    if isinstance(value, float):
        raise PolicyGovernanceError(
            "binary float values are not canonical policy evidence"
        )
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PolicyGovernanceError("canonical JSON object keys must be strings")
            if key in normalized:
                raise PolicyGovernanceError(f"duplicate canonical key: {key}")
            normalized[key] = _normalize_canonical(item)
        return normalized
    if isinstance(value, tuple):
        return [_normalize_canonical(item) for item in value]
    if isinstance(value, list):
        return [_normalize_canonical(item) for item in value]
    raise PolicyGovernanceError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def _reject_float(_: str) -> Any:
    raise PolicyGovernanceError("JSON floats are not accepted in policy evidence")


def _is_sha256_hex(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    text = str(value)
    text = _URL_SECRET_RE.sub(r"\1<redacted>", text)
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _LONG_BASE58_RE.sub("<redacted:identifier>", text)
    if len(text) > 128:
        text = f"{text[:64]}…<truncated:{len(text)}>"
    return text


__all__ = [
    "ATTEMPT_SNAPSHOT_DOMAIN",
    "CANONICAL_SCHEMA_VERSION",
    "DIAGNOSTIC_DOMAIN",
    "GOVERNANCE_EVENT_DOMAIN",
    "MAX_SAFE_JSON_INTEGER",
    "POLICY_BUNDLE_DOMAIN",
    "REQUIRED_POLICY_COMPONENTS",
    "SECRET_LOCATOR_DOMAIN",
    "AtomicPolicyActivator",
    "AttemptPolicySnapshot",
    "DataClassification",
    "EvidenceEnvelope",
    "GovernanceRecord",
    "GovernanceState",
    "HashRef",
    "PolicyBundle",
    "PolicyCompatibilityDecision",
    "PolicyGovernanceError",
    "RetryDisposition",
    "TypedDiagnostic",
    "assert_no_hot_env_decision",
    "assert_no_raw_exception_persistence",
    "canonical_json_bytes",
    "classify_field",
    "domain_hash",
    "fingerprint_secret_locator",
    "parse_json_no_duplicate_keys",
    "redact_mapping",
    "redact_value",
    "require_hash_domain",
    "safe_diagnostic_from_exception",
    "validate_attempt_policy",
]
