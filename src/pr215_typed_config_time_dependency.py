"""PR-215 typed configuration, trusted time and dependency ownership gate.

This module is intentionally offline and sender-free. It gives Pass 7 PR-215 a
single deterministic acceptance contract for configuration, clock and dependency
profile evidence without reading environment variables, touching secrets,
connecting to providers, submitting transactions or claiming production readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "pr215.typed-config-time-dependency.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ENV_BOOTSTRAP_PREFIXES = (
    "src/config/",
    "src/secrets/",
    "src/runtime_config/",
    "scripts/",
)
_REQUIRED_PROFILES = frozenset({"runtime", "service", "analytics", "dev"})
_FORBIDDEN_RUNTIME_ROOTS = frozenset(
    {
        "prometheus-client",
        "psutil",
        "httptools",
        "pytest",
        "black",
        "mypy",
        "flake8",
        "pandas",
        "notebook",
        "jupyter",
    }
)


class PR215EvidenceError(ValueError):
    """Raised when PR-215 evidence is malformed."""


@dataclass(frozen=True, slots=True)
class ConfigContractEvidence:
    """Evidence that one typed configuration schema owns env materialization."""

    typed_schema_generates_env_reference: bool
    env_reference_hash: str
    runtime_observed_env_keys: tuple[str, ...]
    example_documented_env_keys: tuple[str, ...]
    quarantined_legacy_env_keys: tuple[str, ...]
    unknown_env_keys_detected: bool
    stale_example_keys_detected: bool
    no_conflicting_defaults: bool
    conflicting_default_keys: tuple[str, ...]
    env_access_bootstrap_only: bool
    direct_env_read_sites: tuple[str, ...]
    root_config_fingerprint: str
    installed_config_fingerprint: str
    config_fingerprint_materialized_from_schema: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ConfigContractEvidence":
        required = {
            "typed_schema_generates_env_reference",
            "env_reference_hash",
            "runtime_observed_env_keys",
            "example_documented_env_keys",
            "quarantined_legacy_env_keys",
            "unknown_env_keys_detected",
            "stale_example_keys_detected",
            "no_conflicting_defaults",
            "conflicting_default_keys",
            "env_access_bootstrap_only",
            "direct_env_read_sites",
            "root_config_fingerprint",
            "installed_config_fingerprint",
            "config_fingerprint_materialized_from_schema",
        }
        _reject_unknown(payload, required, "config")
        return cls(
            typed_schema_generates_env_reference=_bool(
                payload, "typed_schema_generates_env_reference"
            ),
            env_reference_hash=_sha(payload, "env_reference_hash"),
            runtime_observed_env_keys=_strings(payload, "runtime_observed_env_keys"),
            example_documented_env_keys=_strings(payload, "example_documented_env_keys"),
            quarantined_legacy_env_keys=_strings(payload, "quarantined_legacy_env_keys"),
            unknown_env_keys_detected=_bool(payload, "unknown_env_keys_detected"),
            stale_example_keys_detected=_bool(payload, "stale_example_keys_detected"),
            no_conflicting_defaults=_bool(payload, "no_conflicting_defaults"),
            conflicting_default_keys=_strings(payload, "conflicting_default_keys"),
            env_access_bootstrap_only=_bool(payload, "env_access_bootstrap_only"),
            direct_env_read_sites=_strings(payload, "direct_env_read_sites"),
            root_config_fingerprint=_sha(payload, "root_config_fingerprint"),
            installed_config_fingerprint=_sha(payload, "installed_config_fingerprint"),
            config_fingerprint_materialized_from_schema=_bool(
                payload, "config_fingerprint_materialized_from_schema"
            ),
        )


@dataclass(frozen=True, slots=True)
class TrustedTimeEvidence:
    """Evidence that runtime time is accessed through explicit clock domains."""

    duration_clock_port: bool
    trusted_utc_clock_port: bool
    chain_context_clock_port: bool
    direct_wall_clock_banned: bool
    direct_wall_clock_sites: tuple[str, ...]
    finite_duration_validation: bool
    maximum_duration_bound_seconds: float
    wall_clock_fault_injection_passed: bool
    chain_slot_height_context_bound: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "TrustedTimeEvidence":
        required = {
            "duration_clock_port",
            "trusted_utc_clock_port",
            "chain_context_clock_port",
            "direct_wall_clock_banned",
            "direct_wall_clock_sites",
            "finite_duration_validation",
            "maximum_duration_bound_seconds",
            "wall_clock_fault_injection_passed",
            "chain_slot_height_context_bound",
        }
        _reject_unknown(payload, required, "time")
        return cls(
            duration_clock_port=_bool(payload, "duration_clock_port"),
            trusted_utc_clock_port=_bool(payload, "trusted_utc_clock_port"),
            chain_context_clock_port=_bool(payload, "chain_context_clock_port"),
            direct_wall_clock_banned=_bool(payload, "direct_wall_clock_banned"),
            direct_wall_clock_sites=_strings(payload, "direct_wall_clock_sites"),
            finite_duration_validation=_bool(payload, "finite_duration_validation"),
            maximum_duration_bound_seconds=_finite_positive_float(
                payload, "maximum_duration_bound_seconds"
            ),
            wall_clock_fault_injection_passed=_bool(
                payload, "wall_clock_fault_injection_passed"
            ),
            chain_slot_height_context_bound=_bool(payload, "chain_slot_height_context_bound"),
        )


@dataclass(frozen=True, slots=True)
class DependencyOwnershipEvidence:
    """Evidence that dependency profiles are minimal, exact and owned."""

    separated_lock_profiles: tuple[str, ...]
    runtime_lock_hash: str
    service_lock_hash: str
    analytics_lock_hash: str
    dev_lock_hash: str
    exact_sync_tested: bool
    runtime_lock_excludes_non_runtime_roots: bool
    runtime_direct_roots: tuple[str, ...]
    optional_extras_require_explicit_selection: bool
    dependency_graph_compared_to_allowlist: bool
    direct_dependency_owners: Mapping[str, str]
    direct_dependency_import_evidence: Mapping[str, tuple[str, ...]]
    declared_direct_dependencies: tuple[str, ...]
    directly_imported_dependencies: tuple[str, ...]
    transitive_imports_forbidden: bool
    unmanaged_requirement_aliases_absent: bool
    certifi_direct_dependency_declared: bool

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "DependencyOwnershipEvidence":
        required = {
            "separated_lock_profiles",
            "runtime_lock_hash",
            "service_lock_hash",
            "analytics_lock_hash",
            "dev_lock_hash",
            "exact_sync_tested",
            "runtime_lock_excludes_non_runtime_roots",
            "runtime_direct_roots",
            "optional_extras_require_explicit_selection",
            "dependency_graph_compared_to_allowlist",
            "direct_dependency_owners",
            "direct_dependency_import_evidence",
            "declared_direct_dependencies",
            "directly_imported_dependencies",
            "transitive_imports_forbidden",
            "unmanaged_requirement_aliases_absent",
            "certifi_direct_dependency_declared",
        }
        _reject_unknown(payload, required, "dependency")
        return cls(
            separated_lock_profiles=_strings(payload, "separated_lock_profiles"),
            runtime_lock_hash=_sha(payload, "runtime_lock_hash"),
            service_lock_hash=_sha(payload, "service_lock_hash"),
            analytics_lock_hash=_sha(payload, "analytics_lock_hash"),
            dev_lock_hash=_sha(payload, "dev_lock_hash"),
            exact_sync_tested=_bool(payload, "exact_sync_tested"),
            runtime_lock_excludes_non_runtime_roots=_bool(
                payload, "runtime_lock_excludes_non_runtime_roots"
            ),
            runtime_direct_roots=_strings(payload, "runtime_direct_roots"),
            optional_extras_require_explicit_selection=_bool(
                payload, "optional_extras_require_explicit_selection"
            ),
            dependency_graph_compared_to_allowlist=_bool(
                payload, "dependency_graph_compared_to_allowlist"
            ),
            direct_dependency_owners=_string_map(payload, "direct_dependency_owners"),
            direct_dependency_import_evidence=_string_tuple_map(
                payload, "direct_dependency_import_evidence"
            ),
            declared_direct_dependencies=_strings(payload, "declared_direct_dependencies"),
            directly_imported_dependencies=_strings(payload, "directly_imported_dependencies"),
            transitive_imports_forbidden=_bool(payload, "transitive_imports_forbidden"),
            unmanaged_requirement_aliases_absent=_bool(
                payload, "unmanaged_requirement_aliases_absent"
            ),
            certifi_direct_dependency_declared=_bool(
                payload, "certifi_direct_dependency_declared"
            ),
        )


@dataclass(frozen=True, slots=True)
class PR215Evidence:
    """Complete PR-215 acceptance evidence."""

    schema_version: str
    config: ConfigContractEvidence
    time: TrustedTimeEvidence
    dependencies: DependencyOwnershipEvidence
    live_capability_allowed: bool = False
    signer_capability_allowed: bool = False
    sender_capability_allowed: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "PR215Evidence":
        required = {
            "schema_version",
            "config",
            "time",
            "dependencies",
            "live_capability_allowed",
            "signer_capability_allowed",
            "sender_capability_allowed",
        }
        _reject_unknown(payload, required, "pr215")
        schema_version = payload.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise PR215EvidenceError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {schema_version!r}"
            )
        return cls(
            schema_version=SCHEMA_VERSION,
            config=ConfigContractEvidence.from_mapping(_mapping(payload, "config")),
            time=TrustedTimeEvidence.from_mapping(_mapping(payload, "time")),
            dependencies=DependencyOwnershipEvidence.from_mapping(
                _mapping(payload, "dependencies")
            ),
            live_capability_allowed=_bool(payload, "live_capability_allowed"),
            signer_capability_allowed=_bool(payload, "signer_capability_allowed"),
            sender_capability_allowed=_bool(payload, "sender_capability_allowed"),
        )


@dataclass(frozen=True, slots=True)
class RequirementResult:
    """One deterministic PR-215 requirement result."""

    requirement_id: str
    finding_ids: tuple[str, ...]
    satisfied: bool
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "finding_ids": list(self.finding_ids),
            "satisfied": self.satisfied,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class PR215Report:
    """Deterministic evaluation report for PR-215."""

    schema_version: str
    ready: bool
    reason_codes: tuple[str, ...]
    requirement_results: tuple[RequirementResult, ...]
    live_capability_allowed: bool = False
    signer_capability_allowed: bool = False
    sender_capability_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
            "requirement_results": [item.to_dict() for item in self.requirement_results],
            "live_capability_allowed": self.live_capability_allowed,
            "signer_capability_allowed": self.signer_capability_allowed,
            "sender_capability_allowed": self.sender_capability_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class _Requirement:
    requirement_id: str
    finding_ids: tuple[str, ...]
    checker: str


REQUIREMENTS: tuple[_Requirement, ...] = (
    _Requirement(
        "TYPED_CONFIGURATION_SCHEMA",
        ("F-280", "F-281", "F-282"),
        "_check_config_schema",
    ),
    _Requirement(
        "CONFIG_FINGERPRINT_PARITY",
        ("F-280", "F-281"),
        "_check_config_fingerprint",
    ),
    _Requirement(
        "TRUSTED_TIME_BOUNDARY",
        ("F-283",),
        "_check_time_boundary",
    ),
    _Requirement(
        "DEPENDENCY_PROFILE_SEPARATION",
        ("F-284", "F-285", "F-286"),
        "_check_dependency_profiles",
    ),
    _Requirement(
        "DEPENDENCY_OWNER_AND_IMPORT_EVIDENCE",
        ("F-287", "F-288"),
        "_check_dependency_ownership",
    ),
    _Requirement(
        "SENDER_FREE_CAPABILITY_BOUNDARY",
        ("F-280", "F-288"),
        "_check_sender_free_boundary",
    ),
)


def evaluate_pr215_evidence(evidence: PR215Evidence) -> PR215Report:
    """Evaluate PR-215 evidence and return a stable fail-closed report."""

    results: list[RequirementResult] = []
    reasons: list[str] = []
    for requirement in REQUIREMENTS:
        checker = globals()[requirement.checker]
        requirement_reasons = tuple(checker(evidence))
        if requirement_reasons:
            reasons.extend(
                f"{requirement.requirement_id}:{reason}" for reason in requirement_reasons
            )
        results.append(
            RequirementResult(
                requirement_id=requirement.requirement_id,
                finding_ids=requirement.finding_ids,
                satisfied=not requirement_reasons,
                reason_codes=requirement_reasons,
            )
        )
    return PR215Report(
        schema_version=SCHEMA_VERSION,
        ready=not reasons,
        reason_codes=tuple(reasons),
        requirement_results=tuple(results),
        live_capability_allowed=False,
        signer_capability_allowed=False,
        sender_capability_allowed=False,
    )


def evaluate_pr215_mapping(payload: Mapping[str, object]) -> PR215Report:
    """Strictly parse and evaluate JSON-like PR-215 evidence."""

    return evaluate_pr215_evidence(PR215Evidence.from_mapping(payload))


def _check_config_schema(evidence: PR215Evidence) -> list[str]:
    config = evidence.config
    reasons: list[str] = []
    runtime = set(config.runtime_observed_env_keys)
    documented = set(config.example_documented_env_keys)
    quarantined = set(config.quarantined_legacy_env_keys)
    undocumented_runtime = runtime - documented - quarantined
    stale_documented = documented - runtime - quarantined

    if not config.typed_schema_generates_env_reference:
        reasons.append("ENV_REFERENCE_NOT_SCHEMA_GENERATED")
    if undocumented_runtime and not config.unknown_env_keys_detected:
        reasons.append("UNKNOWN_RUNTIME_ENV_KEYS_NOT_DETECTED")
    if stale_documented and not config.stale_example_keys_detected:
        reasons.append("STALE_EXAMPLE_ENV_KEYS_NOT_DETECTED")
    if not config.no_conflicting_defaults or config.conflicting_default_keys:
        reasons.append("CONFLICTING_DEFAULTS_PRESENT")
    if not config.env_access_bootstrap_only:
        reasons.append("ENV_ACCESS_NOT_BOOTSTRAP_ONLY")
    bad_sites = [
        site
        for site in config.direct_env_read_sites
        if not site.startswith(_ALLOWED_ENV_BOOTSTRAP_PREFIXES)
    ]
    if bad_sites:
        reasons.append("DIRECT_ENV_READ_OUTSIDE_BOOTSTRAP")
    if not config.config_fingerprint_materialized_from_schema:
        reasons.append("CONFIG_FINGERPRINT_NOT_SCHEMA_MATERIALIZED")
    return reasons


def _check_config_fingerprint(evidence: PR215Evidence) -> list[str]:
    config = evidence.config
    if config.root_config_fingerprint != config.installed_config_fingerprint:
        return ["ROOT_AND_INSTALLED_CONFIG_FINGERPRINT_MISMATCH"]
    return []


def _check_time_boundary(evidence: PR215Evidence) -> list[str]:
    clock = evidence.time
    reasons: list[str] = []
    if not clock.duration_clock_port:
        reasons.append("MISSING_DURATION_CLOCK_PORT")
    if not clock.trusted_utc_clock_port:
        reasons.append("MISSING_TRUSTED_UTC_CLOCK_PORT")
    if not clock.chain_context_clock_port or not clock.chain_slot_height_context_bound:
        reasons.append("MISSING_CHAIN_CONTEXT_CLOCK_PORT")
    if not clock.direct_wall_clock_banned:
        reasons.append("DIRECT_WALL_CLOCK_NOT_BANNED")
    if clock.direct_wall_clock_sites:
        reasons.append("DIRECT_WALL_CLOCK_SITES_PRESENT")
    if not clock.finite_duration_validation:
        reasons.append("FINITE_DURATION_VALIDATION_MISSING")
    if clock.maximum_duration_bound_seconds > 86_400:
        reasons.append("DURATION_BOUND_TOO_LARGE")
    if not clock.wall_clock_fault_injection_passed:
        reasons.append("WALL_CLOCK_FAULT_INJECTION_MISSING")
    return reasons


def _check_dependency_profiles(evidence: PR215Evidence) -> list[str]:
    deps = evidence.dependencies
    reasons: list[str] = []
    profiles = set(deps.separated_lock_profiles)
    if not _REQUIRED_PROFILES.issubset(profiles):
        reasons.append("MISSING_REQUIRED_LOCK_PROFILES")
    if not deps.exact_sync_tested:
        reasons.append("EXACT_SYNC_NOT_TESTED")
    if not deps.runtime_lock_excludes_non_runtime_roots:
        reasons.append("RUNTIME_LOCK_NOT_PROFILE_CLEAN")
    forbidden_runtime = set(deps.runtime_direct_roots) & _FORBIDDEN_RUNTIME_ROOTS
    if forbidden_runtime:
        reasons.append("NON_RUNTIME_ROOTS_IN_RUNTIME_LOCK")
    if not deps.optional_extras_require_explicit_selection:
        reasons.append("OPTIONAL_EXTRAS_NOT_EXPLICIT")
    if not deps.dependency_graph_compared_to_allowlist:
        reasons.append("DEPENDENCY_GRAPH_NOT_ALLOWLISTED")
    if not deps.unmanaged_requirement_aliases_absent:
        reasons.append("UNMANAGED_REQUIREMENT_ALIAS_PRESENT")
    return reasons


def _check_dependency_ownership(evidence: PR215Evidence) -> list[str]:
    deps = evidence.dependencies
    reasons: list[str] = []
    declared = set(deps.declared_direct_dependencies)
    imported = set(deps.directly_imported_dependencies)
    owners = set(deps.direct_dependency_owners)
    import_evidence = set(deps.direct_dependency_import_evidence)
    if not imported.issubset(declared):
        reasons.append("DIRECT_IMPORT_NOT_DECLARED")
    if not declared.issubset(owners):
        reasons.append("DIRECT_DEPENDENCY_OWNER_MISSING")
    if not imported.issubset(import_evidence):
        reasons.append("DIRECT_IMPORT_EVIDENCE_MISSING")
    empty_import_evidence = [
        name for name in imported if not deps.direct_dependency_import_evidence.get(name)
    ]
    if empty_import_evidence:
        reasons.append("DIRECT_IMPORT_EVIDENCE_EMPTY")
    if "certifi" in imported and not deps.certifi_direct_dependency_declared:
        reasons.append("CERTIFI_DIRECT_IMPORT_NOT_DECLARED")
    if not deps.transitive_imports_forbidden:
        reasons.append("TRANSITIVE_IMPORTS_NOT_FORBIDDEN")
    return reasons


def _check_sender_free_boundary(evidence: PR215Evidence) -> list[str]:
    reasons: list[str] = []
    if evidence.live_capability_allowed:
        reasons.append("LIVE_CAPABILITY_MUST_REMAIN_DISABLED")
    if evidence.signer_capability_allowed:
        reasons.append("SIGNER_CAPABILITY_MUST_REMAIN_DISABLED")
    if evidence.sender_capability_allowed:
        reasons.append("SENDER_CAPABILITY_MUST_REMAIN_DISABLED")
    return reasons


def complete_pr215_evidence() -> PR215Evidence:
    """Return a complete offline fixture for focused tests and documentation."""

    sha_a = "1" + "a" * 63
    sha_b = "2" + "b" * 63
    sha_c = "3" + "c" * 63
    sha_d = "4" + "d" * 63
    sha_e = "5" + "e" * 63
    runtime_roots = (
        "aiohttp",
        "certifi",
        "httpx",
        "pydantic",
    )
    import_map = {
        "aiohttp": ("src/routing/http_client.py",),
        "certifi": ("src/routing/transport.py",),
        "httpx": ("src/routing/transport.py",),
        "pydantic": ("src/config/runtime.py",),
    }
    return PR215Evidence(
        schema_version=SCHEMA_VERSION,
        config=ConfigContractEvidence(
            typed_schema_generates_env_reference=True,
            env_reference_hash=sha_a,
            runtime_observed_env_keys=(
                "FLASHLOAN_RUNTIME_MODE",
                "SOLANA_RPC_HTTP",
                "JUPITER_QUOTE_API",
            ),
            example_documented_env_keys=(
                "FLASHLOAN_RUNTIME_MODE",
                "SOLANA_RPC_HTTP",
                "JUPITER_QUOTE_API",
            ),
            quarantined_legacy_env_keys=("LEGACY_PAPER_TRADING_ONLY",),
            unknown_env_keys_detected=True,
            stale_example_keys_detected=True,
            no_conflicting_defaults=True,
            conflicting_default_keys=(),
            env_access_bootstrap_only=True,
            direct_env_read_sites=("src/config/bootstrap.py", "scripts/verify_repo.py"),
            root_config_fingerprint=sha_b,
            installed_config_fingerprint=sha_b,
            config_fingerprint_materialized_from_schema=True,
        ),
        time=TrustedTimeEvidence(
            duration_clock_port=True,
            trusted_utc_clock_port=True,
            chain_context_clock_port=True,
            direct_wall_clock_banned=True,
            direct_wall_clock_sites=(),
            finite_duration_validation=True,
            maximum_duration_bound_seconds=3_600.0,
            wall_clock_fault_injection_passed=True,
            chain_slot_height_context_bound=True,
        ),
        dependencies=DependencyOwnershipEvidence(
            separated_lock_profiles=("runtime", "service", "analytics", "dev"),
            runtime_lock_hash=sha_c,
            service_lock_hash=sha_d,
            analytics_lock_hash=sha_e,
            dev_lock_hash="6" + "f" * 63,
            exact_sync_tested=True,
            runtime_lock_excludes_non_runtime_roots=True,
            runtime_direct_roots=runtime_roots,
            optional_extras_require_explicit_selection=True,
            dependency_graph_compared_to_allowlist=True,
            direct_dependency_owners={name: "runtime-platform" for name in runtime_roots},
            direct_dependency_import_evidence=import_map,
            declared_direct_dependencies=runtime_roots,
            directly_imported_dependencies=runtime_roots,
            transitive_imports_forbidden=True,
            unmanaged_requirement_aliases_absent=True,
            certifi_direct_dependency_declared=True,
        ),
    )


def _reject_unknown(
    payload: Mapping[str, object], allowed: Iterable[str], section: str
) -> None:
    unknown = sorted(set(payload).difference(set(allowed)))
    if unknown:
        raise PR215EvidenceError(
            f"unknown {section} evidence fields: {', '.join(unknown)}"
        )


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PR215EvidenceError(f"{key!r} must be a mapping")
    return value


def _bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise PR215EvidenceError(f"{key!r} must be boolean")
    return value


def _sha(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        raise PR215EvidenceError(f"{key!r} must be lowercase sha256")
    if len(set(value)) == 1:
        raise PR215EvidenceError(f"{key!r} must not be a placeholder digest")
    return value


def _strings(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PR215EvidenceError(f"{key!r} must be a string sequence")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PR215EvidenceError(f"{key!r} must contain non-empty strings")
        items.append(item)
    if len(set(items)) != len(items):
        raise PR215EvidenceError(f"{key!r} must not contain duplicates")
    return tuple(items)


def _string_map(payload: Mapping[str, object], key: str) -> Mapping[str, str]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PR215EvidenceError(f"{key!r} must be a mapping")
    normalized: dict[str, str] = {}
    for map_key, map_value in value.items():
        if not isinstance(map_key, str) or not map_key:
            raise PR215EvidenceError(f"{key!r} keys must be non-empty strings")
        if not isinstance(map_value, str) or not map_value:
            raise PR215EvidenceError(f"{key!r} values must be non-empty strings")
        normalized[map_key] = map_value
    return normalized


def _string_tuple_map(
    payload: Mapping[str, object], key: str
) -> Mapping[str, tuple[str, ...]]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PR215EvidenceError(f"{key!r} must be a mapping")
    normalized: dict[str, tuple[str, ...]] = {}
    for map_key, map_value in value.items():
        if not isinstance(map_key, str) or not map_key:
            raise PR215EvidenceError(f"{key!r} keys must be non-empty strings")
        normalized[map_key] = _coerce_string_sequence(map_value, key)
    return normalized


def _coerce_string_sequence(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PR215EvidenceError(f"{key!r} values must be string sequences")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PR215EvidenceError(f"{key!r} values must contain non-empty strings")
        items.append(item)
    if len(set(items)) != len(items):
        raise PR215EvidenceError(f"{key!r} values must not contain duplicates")
    return tuple(items)


def _finite_positive_float(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PR215EvidenceError(f"{key!r} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise PR215EvidenceError(f"{key!r} must be finite and positive")
    return number
