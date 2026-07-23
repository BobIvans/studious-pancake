"""MPR-12 post-completion cutover qualification and regression lock.

This module is intentionally offline and sender-free.  It validates that a
post-completion qualification bundle was produced from the installed artifact
boundary after MPR-08..MPR-11, rather than accepting source-only or test-only
proof modules as promotion evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

SCHEMA_VERSION = "mpr12.post-completion-qualification.v1"
ROADMAP_ID = "MPR-12"

REQUIRED_DEPENDENCIES = frozenset({"MPR-08", "MPR-09", "MPR-10", "MPR-11"})
REQUIRED_INSTALLED_ARTIFACTS = frozenset({"source_export", "wheel", "image"})
REQUIRED_INSTALLED_CLIS = frozenset(
    {
        "flashloan-bot",
        "flashloan-bot-healthcheck",
        "flashloan-contracts",
        "flashloan-checks",
        "flashloan-release-evidence",
    }
)
REQUIRED_PROBES = frozenset(
    {
        "completion_truth",
        "old_schema_reintroduction",
        "installed_cli_surface",
        "release_evidence_replay",
        "migration_rollback",
        "deployment_rollback",
        "credential_rotation",
        "queue_pressure",
        "provider_substitution",
        "sandbox_attestation",
    }
)
REQUIRED_BUNDLE_MEMBERS = frozenset(
    {
        "completion_ledger",
        "source_export_manifest",
        "wheel_manifest",
        "image_manifest",
        "installed_cli_report",
        "adversarial_probe_report",
        "migration_report",
        "rollback_rehearsal_report",
        "sandbox_attestation",
        "release_evidence_report",
    }
)
OLD_SCHEMA_IDS = frozenset(
    {
        "pr01.authority-map.v1",
        "pr194.production-surface.v1",
        "pr195.product-contract.v1",
        "pr200.production-cutover.v1",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class MPR12QualificationReport:
    """Deterministic summary for the MPR-12 gate."""

    schema_version: str
    roadmap: str
    qualification_passed: bool
    promotion_review_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    blockers: tuple[str, ...]
    evidence_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roadmap": self.roadmap,
            "qualification_passed": self.qualification_passed,
            "promotion_review_allowed": self.promotion_review_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
        }


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, field: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"MPR12_SECTION_MISSING:{field}")
        return {}
    return value


def _sequence(value: object, field: str, blockers: list[str]) -> tuple[object, ...]:
    if not isinstance(value, list):
        blockers.append(f"MPR12_LIST_MISSING:{field}")
        return ()
    return tuple(value)


def _string_set(value: object, field: str, blockers: list[str]) -> frozenset[str]:
    items = _sequence(value, field, blockers)
    result = {item for item in items if isinstance(item, str)}
    if len(result) != len(items):
        blockers.append(f"MPR12_LIST_CONTAINS_NON_STRING:{field}")
    return frozenset(result)


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or not _SHA256_RE.match(value):
        return False
    if len(set(value)) <= 1:
        return False
    return True


def _valid_commit(value: object) -> bool:
    return isinstance(value, str) and bool(_COMMIT_RE.match(value))


def _finite_non_negative(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def evaluate_mpr12_qualification(evidence: Mapping[str, Any]) -> MPR12QualificationReport:
    """Evaluate an offline MPR-12 post-completion qualification bundle.

    A passing report permits only promotion review.  It never enables live
    execution, signer access, sender access or automatic cutover.
    """

    blockers: list[str] = []

    if evidence.get("schema_version") != SCHEMA_VERSION:
        blockers.append("MPR12_SCHEMA_MISMATCH")
    if evidence.get("roadmap") != ROADMAP_ID:
        blockers.append("MPR12_ROADMAP_ID_MISMATCH")

    capabilities = _mapping(evidence.get("capabilities"), "capabilities", blockers)
    if capabilities.get("live_execution_allowed") is not False:
        blockers.append("MPR12_LIVE_EXECUTION_CAPABILITY_ENABLED")
    if capabilities.get("signer_allowed") is not False:
        blockers.append("MPR12_SIGNER_CAPABILITY_ENABLED")
    if capabilities.get("sender_allowed") is not False:
        blockers.append("MPR12_SENDER_CAPABILITY_ENABLED")
    if capabilities.get("automatic_cutover_allowed") is not False:
        blockers.append("MPR12_AUTOMATIC_CUTOVER_ALLOWED")

    deps = _sequence(evidence.get("dependencies"), "dependencies", blockers)
    seen_deps: set[str] = set()
    for item in deps:
        if not isinstance(item, Mapping):
            blockers.append("MPR12_DEPENDENCY_ENTRY_NOT_OBJECT")
            continue
        work_package = item.get("work_package")
        if not isinstance(work_package, str):
            blockers.append("MPR12_DEPENDENCY_ID_INVALID")
            continue
        if work_package in seen_deps:
            blockers.append(f"MPR12_DUPLICATE_DEPENDENCY:{work_package}")
        seen_deps.add(work_package)
        if work_package in REQUIRED_DEPENDENCIES:
            if item.get("status") != "accepted_materialized":
                blockers.append(f"MPR12_DEPENDENCY_NOT_ACCEPTED:{work_package}")
            if not _valid_commit(item.get("source_commit")):
                blockers.append(f"MPR12_DEPENDENCY_SOURCE_COMMIT_INVALID:{work_package}")
            if not _valid_sha256(item.get("installed_generation_digest")):
                blockers.append(
                    f"MPR12_DEPENDENCY_INSTALLED_DIGEST_INVALID:{work_package}"
                )
    for missing in sorted(REQUIRED_DEPENDENCIES - seen_deps):
        blockers.append(f"MPR12_REQUIRED_DEPENDENCY_MISSING:{missing}")

    artifacts = _sequence(evidence.get("installed_artifacts"), "installed_artifacts", blockers)
    artifact_roles: set[str] = set()
    for item in artifacts:
        if not isinstance(item, Mapping):
            blockers.append("MPR12_ARTIFACT_ENTRY_NOT_OBJECT")
            continue
        role = item.get("role")
        if not isinstance(role, str):
            blockers.append("MPR12_ARTIFACT_ROLE_INVALID")
            continue
        if role in artifact_roles:
            blockers.append(f"MPR12_DUPLICATE_ARTIFACT_ROLE:{role}")
        artifact_roles.add(role)
        if not _valid_sha256(item.get("sha256")):
            blockers.append(f"MPR12_ARTIFACT_DIGEST_INVALID:{role}")
        if item.get("installed_boundary") is not True:
            blockers.append(f"MPR12_ARTIFACT_NOT_INSTALLED_BOUNDARY:{role}")
        if item.get("built_from_clean_source_export") is not True:
            blockers.append(f"MPR12_ARTIFACT_NOT_CLEAN_SOURCE_EXPORT:{role}")
        if not _valid_sha256(item.get("completion_ledger_digest")):
            blockers.append(f"MPR12_ARTIFACT_LEDGER_DIGEST_INVALID:{role}")
    for missing in sorted(REQUIRED_INSTALLED_ARTIFACTS - artifact_roles):
        blockers.append(f"MPR12_REQUIRED_ARTIFACT_MISSING:{missing}")

    installed_clis = _sequence(evidence.get("installed_cli_results"), "installed_cli_results", blockers)
    cli_names: set[str] = set()
    for item in installed_clis:
        if not isinstance(item, Mapping):
            blockers.append("MPR12_CLI_ENTRY_NOT_OBJECT")
            continue
        name = item.get("name")
        if not isinstance(name, str):
            blockers.append("MPR12_CLI_NAME_INVALID")
            continue
        if name in cli_names:
            blockers.append(f"MPR12_DUPLICATE_CLI:{name}")
        cli_names.add(name)
        if item.get("artifact_role") not in {"wheel", "image"}:
            blockers.append(f"MPR12_CLI_NOT_FROM_INSTALLED_ARTIFACT:{name}")
        if item.get("no_network_smoke") != "passed":
            blockers.append(f"MPR12_CLI_NO_NETWORK_SMOKE_NOT_PASSED:{name}")
        if item.get("exit_contract") != "consistent":
            blockers.append(f"MPR12_CLI_EXIT_CONTRACT_DRIFT:{name}")
        if not _valid_sha256(item.get("policy_digest")):
            blockers.append(f"MPR12_CLI_POLICY_DIGEST_INVALID:{name}")
    for missing in sorted(REQUIRED_INSTALLED_CLIS - cli_names):
        blockers.append(f"MPR12_REQUIRED_CLI_MISSING:{missing}")

    probes = _sequence(evidence.get("adversarial_probes"), "adversarial_probes", blockers)
    probe_names: set[str] = set()
    for item in probes:
        if not isinstance(item, Mapping):
            blockers.append("MPR12_PROBE_ENTRY_NOT_OBJECT")
            continue
        name = item.get("name")
        if not isinstance(name, str):
            blockers.append("MPR12_PROBE_NAME_INVALID")
            continue
        probe_names.add(name)
        if item.get("target") != "installed_artifact":
            blockers.append(f"MPR12_PROBE_NOT_INSTALLED_ARTIFACT:{name}")
        if item.get("result") != "passed_fail_closed":
            blockers.append(f"MPR12_PROBE_NOT_FAIL_CLOSED:{name}")
        if not _valid_sha256(item.get("evidence_digest")):
            blockers.append(f"MPR12_PROBE_DIGEST_INVALID:{name}")
        if not _finite_non_negative(item.get("duration_ms")):
            blockers.append(f"MPR12_PROBE_DURATION_INVALID:{name}")
    for missing in sorted(REQUIRED_PROBES - probe_names):
        blockers.append(f"MPR12_REQUIRED_PROBE_MISSING:{missing}")

    regression = _mapping(evidence.get("regression_lock"), "regression_lock", blockers)
    if regression.get("source_only_evidence_allowed") is not False:
        blockers.append("MPR12_SOURCE_ONLY_EVIDENCE_ALLOWED")
    if regression.get("test_only_evidence_allowed") is not False:
        blockers.append("MPR12_TEST_ONLY_EVIDENCE_ALLOWED")
    if regression.get("old_schemas_can_reappear") is not False:
        blockers.append("MPR12_OLD_SCHEMAS_CAN_REAPPEAR")
    if regression.get("promotion_authority") != "mpr12_offline_bundle_only":
        blockers.append("MPR12_PROMOTION_AUTHORITY_NOT_BUNDLE_ONLY")
    observed_old_schemas = _string_set(
        regression.get("observed_old_schema_ids"),
        "regression_lock.observed_old_schema_ids",
        blockers,
    )
    for schema_id in sorted(OLD_SCHEMA_IDS & observed_old_schemas):
        blockers.append(f"MPR12_OLD_SCHEMA_REAPPEARED:{schema_id}")

    rollback = _mapping(evidence.get("rollback_rehearsal"), "rollback_rehearsal", blockers)
    if rollback.get("migration_preserves_previous_generation") is not True:
        blockers.append("MPR12_MIGRATION_ROLLBACK_NOT_GENERATION_SAFE")
    if rollback.get("failed_deployment_blocks_promotion") is not True:
        blockers.append("MPR12_FAILED_DEPLOYMENT_DOES_NOT_BLOCK_PROMOTION")
    if rollback.get("previous_generation_restored") is not True:
        blockers.append("MPR12_PREVIOUS_GENERATION_NOT_RESTORED")
    if rollback.get("manual_recovery_required") is not False:
        blockers.append("MPR12_ROLLBACK_REQUIRES_MANUAL_RECOVERY")
    if not _valid_sha256(rollback.get("rehearsal_digest")):
        blockers.append("MPR12_ROLLBACK_REHEARSAL_DIGEST_INVALID")

    bundle = _mapping(evidence.get("offline_bundle"), "offline_bundle", blockers)
    if bundle.get("signed") is not True:
        blockers.append("MPR12_OFFLINE_BUNDLE_NOT_SIGNED")
    if bundle.get("offline_verifiable") is not True:
        blockers.append("MPR12_OFFLINE_BUNDLE_NOT_VERIFIABLE")
    if bundle.get("immutable") is not True:
        blockers.append("MPR12_OFFLINE_BUNDLE_NOT_IMMUTABLE")
    if not _valid_sha256(bundle.get("bundle_digest")):
        blockers.append("MPR12_OFFLINE_BUNDLE_DIGEST_INVALID")
    bundle_members = _string_set(bundle.get("members"), "offline_bundle.members", blockers)
    for missing in sorted(REQUIRED_BUNDLE_MEMBERS - bundle_members):
        blockers.append(f"MPR12_BUNDLE_MEMBER_MISSING:{missing}")
    if bundle.get("verifier_entrypoint") != "flashloan-release-evidence verify-mpr12":
        blockers.append("MPR12_VERIFIER_ENTRYPOINT_DRIFT")
    if bundle.get("source_tree_acceptance") != "clean_installed_artifact_only":
        blockers.append("MPR12_SOURCE_TREE_ACCEPTANCE_NOT_FORBIDDEN")

    unique_blockers = tuple(sorted(dict.fromkeys(blockers)))
    passed = not unique_blockers
    return MPR12QualificationReport(
        schema_version=SCHEMA_VERSION,
        roadmap=ROADMAP_ID,
        qualification_passed=passed,
        promotion_review_allowed=passed,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        blockers=unique_blockers,
        evidence_hash=_stable_hash(evidence),
    )


def evaluate(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility helper returning a JSON-serializable dict."""

    return evaluate_mpr12_qualification(evidence).as_dict()
