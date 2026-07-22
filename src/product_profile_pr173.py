"""PR-173 minimal production profile and plugin isolation gate.

This module is intentionally offline and side-effect free.  It models the
review contract for the production artifact boundary without importing or
constructing any optional strategy, signer, sender, provider, or runtime module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Iterable, Mapping

SCHEMA_VERSION = "pr173.product-profile.v1"
RESULT_SCHEMA_VERSION = "pr173.product-profile-result.v1"
CORE_PROFILE_IDS = frozenset({"core-flashloan-paper", "core-flashloan-live"})
OPTIONAL_PLUGIN_PROFILES = frozenset(
    {
        "liquidation-plugin",
        "orderbook-plugin",
        "pump-plugin",
        "ai-advisory-plugin",
    }
)
BANNED_CORE_DOMAINS = frozenset(
    {
        "ai_advisory",
        "lending",
        "lending_indexer",
        "liquidation",
        "providers/orderbook",
        "orderbook",
        "pump",
        "venues/pump",
        "kamino_liquidation",
        "lst_depeg",
        "lst_unstake",
        "circular_arbitrage",
    }
)
REQUIRED_LIFECYCLE_STATES = (
    "not_installed",
    "installed_disabled",
    "fixture_only",
    "recorded_shadow",
    "live_shadow",
    "reviewed_executable",
    "revoked",
)
REQUIRED_PLUGIN_API_SURFACES = frozenset(
    {
        "candidate_observation",
        "quote_request",
        "evidence_output",
        "reason_codes",
        "health",
        "shutdown",
    }
)
DEFAULT_DENIED_PLUGIN_PERMISSIONS = frozenset(
    {
        "signer_access",
        "sender_access",
        "treasury_mutation",
    }
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ProfileDecision(str, Enum):
    REVIEW_READY = "REVIEW_READY"
    BLOCKED = "BLOCKED"


class PluginLifecycleState(str, Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED_DISABLED = "installed_disabled"
    FIXTURE_ONLY = "fixture_only"
    RECORDED_SHADOW = "recorded_shadow"
    LIVE_SHADOW = "live_shadow"
    REVIEWED_EXECUTABLE = "reviewed_executable"
    REVOKED = "revoked"


@dataclass(frozen=True)
class ProductProfile:
    profile_id: str
    signed_profile_hash: str
    signature_verified: bool
    allowed_core_domains: tuple[str, ...]
    allowed_plugin_profiles: tuple[str, ...] = ()
    first_canary_profile_id: str = "core-flashloan-paper"
    production_default: bool = True


@dataclass(frozen=True)
class CoreArtifactEvidence:
    package_name: str
    included_domains: tuple[str, ...]
    explicitly_excluded_domains: tuple[str, ...]
    constructs_only_profile_features: bool
    optional_absence_breaks_import_or_health: bool
    core_sbom_hash: str
    dependencies_are_core_only: bool
    product_docs_distinguish_modes: bool
    capability_status_from_installed_profile_and_admission: bool
    required_in_installed_package_flags: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginMetadata:
    plugin_id: str
    distribution_name: str
    version: str
    wheel_hash: str
    signer: str
    provenance_hash: str
    api_version: str
    permissions: tuple[str, ...]
    supported_clusters: tuple[str, ...]
    strategy_capabilities: tuple[str, ...]
    evidence_hash: str
    allowlisted: bool
    signature_verified: bool
    lifecycle_state: PluginLifecycleState | str
    process_isolated: bool
    separate_dependency_environment: bool
    bounded_ipc: bool
    crash_isolated_from_core_health: bool
    sbom_hash: str
    license_inventory_hash: str
    revoked: bool = False
    attempts_arbitrary_import_path: bool = False
    attempts_internal_object_return: bool = False


@dataclass(frozen=True)
class PluginApiContract:
    api_version: str
    surfaces: tuple[str, ...]
    accepts_arbitrary_internal_objects: bool
    versioned_protocol_hash: str


@dataclass(frozen=True)
class ProductProfileEvidence:
    schema_version: str
    active_profile: ProductProfile
    core_artifact: CoreArtifactEvidence
    plugin_api: PluginApiContract
    plugin_lifecycle_states: tuple[str, ...]
    plugins: tuple[PluginMetadata, ...] = ()
    live_claim_requested: bool = False
    sender_submission_requested: bool = False
    expected_evidence_hash: str | None = None


@dataclass(frozen=True)
class ProductProfileDecision:
    schema_version: str
    decision: ProfileDecision
    blockers: tuple[str, ...]
    evidence_hash: str
    review_ready: bool
    production_artifact_allowed: bool
    first_canary_core_only: bool
    live_claim_allowed: bool
    sender_submission_allowed: bool


def _canonicalize(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, tuple):
        return [_canonicalize(v) for v in value]
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _canonicalize(
            {name: getattr(value, name) for name in value.__dataclass_fields__}
        )
    return value


def sha256_json(value: object) -> str:
    payload = json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _is_hash(value: str | None) -> bool:
    return bool(value and _HASH_RE.fullmatch(value))


def _norm_many(values: Iterable[str]) -> set[str]:
    return {str(v).strip().lower().replace("-", "_") for v in values if str(v).strip()}


def _add(blockers: list[str], code: str) -> None:
    if code not in blockers:
        blockers.append(code)


def evaluate_product_profile(evidence: ProductProfileEvidence) -> ProductProfileDecision:
    blockers: list[str] = []

    if evidence.schema_version != SCHEMA_VERSION:
        _add(blockers, "SCHEMA_VERSION_MISMATCH")

    profile = evidence.active_profile
    if profile.profile_id not in CORE_PROFILE_IDS:
        _add(blockers, "PRODUCTION_PROFILE_NOT_CORE")
    if not profile.production_default:
        _add(blockers, "DEFAULT_PRODUCTION_PROFILE_NOT_MARKED")
    if not _is_hash(profile.signed_profile_hash):
        _add(blockers, "PROFILE_HASH_MISSING_OR_MALFORMED")
    if not profile.signature_verified:
        _add(blockers, "PROFILE_SIGNATURE_NOT_VERIFIED")
    if profile.first_canary_profile_id not in CORE_PROFILE_IDS:
        _add(blockers, "FIRST_CANARY_NOT_CORE_PROFILE")
    if set(profile.allowed_plugin_profiles) - OPTIONAL_PLUGIN_PROFILES:
        _add(blockers, "UNKNOWN_PLUGIN_PROFILE_ALLOWED")

    core = evidence.core_artifact
    if not core.package_name or core.package_name in {"src", "flashloan-bot-all"}:
        _add(blockers, "CORE_PACKAGE_NAME_NOT_MINIMAL")
    included = _norm_many(core.included_domains)
    excluded = _norm_many(core.explicitly_excluded_domains)
    banned_domains = _norm_many(BANNED_CORE_DOMAINS)
    if included.intersection(banned_domains):
        _add(blockers, "OPTIONAL_DOMAIN_INCLUDED_IN_CORE")
    if not banned_domains.issubset(included.union(excluded)):
        _add(blockers, "OPTIONAL_DOMAIN_SEPARATION_INCOMPLETE")
    if not core.constructs_only_profile_features:
        _add(blockers, "CORE_CONSTRUCTS_ABSENT_OR_DISABLED_FEATURES")
    if core.optional_absence_breaks_import_or_health:
        _add(blockers, "OPTIONAL_ABSENCE_BREAKS_CORE")
    if not _is_hash(core.core_sbom_hash):
        _add(blockers, "CORE_SBOM_HASH_MISSING")
    if not core.dependencies_are_core_only:
        _add(blockers, "CORE_DEPENDENCIES_NOT_CORE_ONLY")
    if not core.product_docs_distinguish_modes:
        _add(blockers, "PRODUCT_DOCS_DO_NOT_DISTINGUISH_MODES")
    if not core.capability_status_from_installed_profile_and_admission:
        _add(blockers, "CAPABILITY_STATUS_NOT_PROFILE_ADMISSION_DERIVED")
    for feature, required in sorted(core.required_in_installed_package_flags.items()):
        if required and feature.strip().lower().replace("-", "_") in banned_domains:
            _add(blockers, "QUARANTINED_FEATURE_REQUIRED_IN_INSTALLED_PACKAGE")

    api = evidence.plugin_api
    if not _is_hash(api.versioned_protocol_hash):
        _add(blockers, "PLUGIN_API_PROTOCOL_HASH_MISSING")
    if not REQUIRED_PLUGIN_API_SURFACES.issubset(set(api.surfaces)):
        _add(blockers, "PLUGIN_API_SURFACES_INCOMPLETE")
    if api.accepts_arbitrary_internal_objects:
        _add(blockers, "PLUGIN_API_ACCEPTS_INTERNAL_OBJECTS")

    if not set(REQUIRED_LIFECYCLE_STATES).issubset(set(evidence.plugin_lifecycle_states)):
        _add(blockers, "PLUGIN_LIFECYCLE_STATES_INCOMPLETE")

    seen_plugins: set[str] = set()
    for plugin in evidence.plugins:
        if plugin.plugin_id in seen_plugins:
            _add(blockers, "DUPLICATE_PLUGIN_ID")
        seen_plugins.add(plugin.plugin_id)
        if not plugin.distribution_name.startswith("flashloan-bot-plugin-"):
            _add(blockers, "PLUGIN_DISTRIBUTION_NOT_SEPARATE")
        if not plugin.version or not plugin.api_version:
            _add(blockers, "PLUGIN_VERSION_MISSING")
        for field_name in (
            "wheel_hash",
            "provenance_hash",
            "evidence_hash",
            "sbom_hash",
            "license_inventory_hash",
        ):
            if not _is_hash(getattr(plugin, field_name)):
                _add(blockers, f"{field_name.upper()}_MISSING")
        if not plugin.signer:
            _add(blockers, "PLUGIN_SIGNER_MISSING")
        if not plugin.allowlisted or not plugin.signature_verified:
            _add(blockers, "PLUGIN_NOT_SIGNED_AND_ALLOWLISTED")
        if plugin.revoked and plugin.lifecycle_state != PluginLifecycleState.REVOKED:
            _add(blockers, "REVOKED_PLUGIN_NOT_IN_REVOKED_STATE")
        if plugin.lifecycle_state == PluginLifecycleState.REVIEWED_EXECUTABLE and plugin.revoked:
            _add(blockers, "REVOKED_PLUGIN_EXECUTABLE")
        if DEFAULT_DENIED_PLUGIN_PERMISSIONS.intersection(set(plugin.permissions)):
            _add(blockers, "PLUGIN_HAS_DEFAULT_DENIED_PERMISSION")
        if not plugin.process_isolated or not plugin.separate_dependency_environment or not plugin.bounded_ipc:
            _add(blockers, "PLUGIN_PROCESS_ISOLATION_INCOMPLETE")
        if not plugin.crash_isolated_from_core_health:
            _add(blockers, "PLUGIN_CRASH_CAN_BREAK_CORE_HEALTH")
        if plugin.attempts_arbitrary_import_path:
            _add(blockers, "PLUGIN_ARBITRARY_IMPORT_PATH")
        if plugin.attempts_internal_object_return:
            _add(blockers, "PLUGIN_INTERNAL_OBJECT_RETURN")

    if evidence.live_claim_requested:
        _add(blockers, "LIVE_CLAIM_REQUESTED_IN_REVIEW_GATE")
    if evidence.sender_submission_requested:
        _add(blockers, "SENDER_SUBMISSION_REQUESTED_IN_REVIEW_GATE")

    evidence_hash = sha256_json({"schema": evidence.schema_version, "evidence": evidence})
    if evidence.expected_evidence_hash is not None and evidence.expected_evidence_hash != evidence_hash:
        _add(blockers, "EVIDENCE_HASH_MISMATCH")

    review_ready = not blockers
    return ProductProfileDecision(
        schema_version=RESULT_SCHEMA_VERSION,
        decision=ProfileDecision.REVIEW_READY if review_ready else ProfileDecision.BLOCKED,
        blockers=tuple(blockers),
        evidence_hash=evidence_hash,
        review_ready=review_ready,
        production_artifact_allowed=review_ready,
        first_canary_core_only=review_ready and profile.first_canary_profile_id in CORE_PROFILE_IDS,
        live_claim_allowed=False,
        sender_submission_allowed=False,
    )


def assert_product_profile_review_ready(
    evidence: ProductProfileEvidence,
) -> ProductProfileDecision:
    decision = evaluate_product_profile(evidence)
    if not decision.review_ready:
        raise AssertionError("PR-173 product profile blocked: " + ", ".join(decision.blockers))
    return decision
