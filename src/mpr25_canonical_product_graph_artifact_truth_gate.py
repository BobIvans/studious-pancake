"""MPR-25 canonical product graph, artifact truth and qualification gate.

Offline, side-effect-free acceptance contract for the V11 product-graph cutover.
It does not build artifacts, read files/env, inspect Docker/GitHub, call network,
import provider SDKs, open signer IPC, submit transactions, or enable live mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "mpr25.canonical-product-graph-artifact-truth-gate.v1"
ROADMAP_ID = "MPR-25"
REQUIRED_COMMANDS = (
    "flashloan-bot",
    "flashloan-bot-healthcheck",
    "flashloan-contracts",
    "flashloan-checks",
    "flashloan-release-evidence",
)
REQUIRED_AUTHORITIES = (
    "product_authority",
    "release_set_authority",
    "composition_root",
    "surface_policy",
    "reachability_manifest",
    "qualification_gate",
    "dependency_graph",
    "workflow_policy",
    "quality_inventory",
)
REQUIRED_WORKFLOW_PURPOSES = (
    "build",
    "unit",
    "integration",
    "security",
    "release-qualification",
)
REQUIRED_ARTIFACTS = (
    "source-tree",
    "main-wheel",
    "runtime-image",
    "lockfile",
    "wheelhouse",
    "sbom",
    "builder-provenance",
    "surface-manifest",
    "reachability-manifest",
    "release-qualification-log",
)
REQUIRED_FINDINGS = frozenset(
    [
        "V10-F-438",
        "V10-F-439",
        "V10-F-440",
        "V10-F-476",
        "V10-F-477",
        "V10-F-478",
        "V10-F-479",
        "V10-F-480",
        "V10-F-481",
        "V10-F-482",
        "V10-F-483",
        "V10-F-484",
        "V10-F-485",
        "V10-F-486",
        "V11-REACHABILITY-80-474",
        "V11-WORKFLOWS-68",
        "V11-MUTABLE-ACTIONS-145",
        "V11-FORMATTER-COVERAGE-192-859",
        "V11-PYTEST-COLLECTION-104",
        "V11-OLD-PR01-AUTHORITY-MAP",
        "V11-NOT-PRODUCTION-READY-MANIFEST",
        "V11-DECLARATION-ONLY-GATES",
    ]
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
SAFE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")
PLACEHOLDERS = {"0" * 64, "1" * 64, "a" * 64, "f" * 64, "deadbeef" * 8}


class MPR25Decision(str, Enum):
    READY_FOR_CUTOVER_REVIEW = "ready_for_cutover_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MPR25Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MPR25Report:
    schema_version: str
    roadmap: str
    decision: MPR25Decision
    blockers: tuple[MPR25Violation, ...]
    evidence_hash: str
    paper_readiness_allowed: bool
    shadow_readiness_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    mandatory_release_qualification_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roadmap": self.roadmap,
            "decision": self.decision.value,
            "blockers": [b.__dict__ for b in self.blockers],
            "evidence_hash": self.evidence_hash,
            "paper_readiness_allowed": self.paper_readiness_allowed,
            "shadow_readiness_allowed": self.shadow_readiness_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
            "mandatory_release_qualification_allowed": self.mandatory_release_qualification_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def evaluate_mpr25_evidence(evidence: Mapping[str, Any]) -> MPR25Report:
    blockers: list[MPR25Violation] = []
    _need(evidence.get("schema_version") == SCHEMA_VERSION, blockers, "MPR25_SCHEMA_VERSION", "schema_version")
    _need(evidence.get("roadmap") == ROADMAP_ID, blockers, "MPR25_ROADMAP_ID", "roadmap")

    graph = _map(evidence.get("product_graph"))
    surface = _map(evidence.get("surface_policy"))
    reach = _map(evidence.get("reachability"))
    build = _map(evidence.get("build"))
    workflows = _map(evidence.get("workflows"))
    quality = _map(evidence.get("quality"))
    artifacts = tuple(_map(item) for item in evidence.get("artifacts", ()))

    _forbid_live(evidence, graph, blockers)
    _findings(evidence.get("findings_closed", ()), blockers)
    _product_graph(graph, blockers)
    _surface(surface, blockers)
    _reachability(reach, blockers)
    _build(build, blockers)
    _workflows(workflows, blockers)
    _quality(quality, blockers)
    _artifacts(artifacts, blockers)
    _crosslinks(graph, surface, reach, build, quality, blockers)

    unique = tuple(_dedupe(blockers))
    accepted = not unique
    return MPR25Report(
        schema_version=SCHEMA_VERSION,
        roadmap=ROADMAP_ID,
        decision=MPR25Decision.READY_FOR_CUTOVER_REVIEW if accepted else MPR25Decision.BLOCKED,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        paper_readiness_allowed=accepted,
        shadow_readiness_allowed=accepted,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        mandatory_release_qualification_allowed=accepted,
    )


def _forbid_live(evidence: Mapping[str, Any], graph: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    for key in ("live_execution_requested", "signer_requested", "sender_requested", "network_submission_requested"):
        _need(not evidence.get(key), blockers, "MPR25_FORBIDDEN_REQUEST", key)
    for key in ("signer_namespace_in_main_wheel", "sender_namespace_in_main_wheel", "submission_transport_in_main_wheel", "live_canary_in_main_wheel"):
        _need(not graph.get(key), blockers, "MPR25_FORBIDDEN_NAMESPACE", key)


def _findings(findings: Iterable[Any], blockers: list[MPR25Violation]) -> None:
    observed = tuple(str(item) for item in findings)
    missing = sorted(REQUIRED_FINDINGS.difference(observed))
    extras = sorted(set(observed).difference(REQUIRED_FINDINGS))
    _need(not missing, blockers, "MPR25_FINDING_COVERAGE", ",".join(missing[:8]))
    _need(not extras, blockers, "MPR25_UNKNOWN_FINDING", ",".join(extras[:8]))
    _need(len(observed) == len(set(observed)), blockers, "MPR25_DUPLICATE_FINDING", "findings_closed")


def _product_graph(graph: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    for key in ("source_tree_sha256", "main_wheel_sha256", "release_set_sha256", "surface_manifest_sha256", "reachability_manifest_sha256", "qualification_log_sha256"):
        _need(_sha(graph.get(key)), blockers, "MPR25_BAD_PRODUCT_HASH", key)
    _need(_image(graph.get("runtime_image_digest")), blockers, "MPR25_BAD_IMAGE_DIGEST", "runtime_image_digest")
    _need(graph.get("generated_from") == "installed-wheel-console-scripts", blockers, "MPR25_GRAPH_NOT_INSTALLED", "generated_from")
    for key in (
        "one_product_authority", "one_release_set_manifest", "one_composition_root",
        "single_mandatory_qualification_gate", "safe_idle_diagnostic_only",
        "safe_idle_cannot_satisfy_readiness", "source_launchers_retired", "pm2_paths_retired",
        "legacy_gates_demoted", "declaration_only_gates_blocked", "old_pr01_pr10_authority_map_replaced",
    ):
        _need(graph.get(key) is True, blockers, "MPR25_PRODUCT_CUTOVER", key)
    _need(not tuple(graph.get("coequal_product_authorities", ())), blockers, "MPR25_COEQUAL_AUTHORITIES", "coequal_product_authorities")


def _surface(surface: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    _need(_sha(surface.get("policy_sha256")), blockers, "MPR25_SURFACE_POLICY_HASH", "policy_sha256")
    commands = _map(surface.get("commands"))
    missing = [command for command in REQUIRED_COMMANDS if command not in commands]
    _need(not missing, blockers, "MPR25_MISSING_COMMAND", ",".join(missing))
    for command in REQUIRED_COMMANDS:
        spec = _map(commands.get(command))
        for key, code in (
            ("in_surface_manifest", "MPR25_COMMAND_NOT_IN_SURFACE"),
            ("clean_install_invoked", "MPR25_COMMAND_NOT_CLEAN_INSTALLED"),
            ("structured_json_errors", "MPR25_COMMAND_ERRORS"),
            ("exit_codes_stable", "MPR25_COMMAND_EXIT_CODES"),
            ("stdout_stderr_contract_stable", "MPR25_COMMAND_IO_CONTRACT"),
        ):
            _need(spec.get(key) is True, blockers, code, command)
        _need(_safe(spec.get("entrypoint")), blockers, "MPR25_BAD_ENTRYPOINT", command)
    _need(surface.get("root_launcher_matches_console_scripts") is True, blockers, "MPR25_ROOT_LAUNCHER_DRIFT", "root_launcher")
    _need(surface.get("package_resources_only") is True, blockers, "MPR25_RESOURCE_LOADING", "resources")


def _reachability(reach: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    _need(_sha(reach.get("graph_sha256")), blockers, "MPR25_REACHABILITY_HASH", "graph_sha256")
    _need(reach.get("generated_from_installed_wheel") is True, blockers, "MPR25_REACHABILITY_NOT_INSTALLED", "generated_from_installed_wheel")
    total, accounted = reach.get("total_src_modules"), reach.get("accounted_src_modules")
    reachable, quarantined, experimental = reach.get("reachable_src_modules"), reach.get("quarantined_src_modules"), reach.get("experimental_src_modules")
    for key, value in (("total_src_modules", total), ("reachable_src_modules", reachable), ("quarantined_src_modules", quarantined), ("experimental_src_modules", experimental)):
        _need(_uint(value), blockers, "MPR25_BAD_MODULE_COUNT", key)
    _need(total == accounted, blockers, "MPR25_MODULE_ACCOUNTING", "accounted_src_modules")
    _need(total == reachable + quarantined + experimental, blockers, "MPR25_MODULE_CLOSURE", "src_modules")
    _need(reach.get("new_module_policy_enforced") is True, blockers, "MPR25_NEW_MODULE_POLICY", "new_module_policy")
    _need(reach.get("quarantine_has_expiry_and_owner") is True, blockers, "MPR25_BAD_QUARANTINE", "quarantine")
    callers = _map(reach.get("production_callers"))
    for authority in REQUIRED_AUTHORITIES:
        _need(callers.get(authority) == 1, blockers, "MPR25_AUTHORITY_CALLER_COUNT", authority)
    _need(reach.get("forbidden_import_edges") in ((), [], None), blockers, "MPR25_FORBIDDEN_IMPORT_EDGE", "forbidden_import_edges")
    _need(reach.get("import_cycles") in ((), [], None), blockers, "MPR25_IMPORT_CYCLE", "import_cycles")


def _build(build: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    for key in ("lock_sha256", "wheelhouse_sha256", "sbom_sha256", "builder_provenance_sha256", "dependency_graph_sha256"):
        _need(_sha(build.get(key)), blockers, "MPR25_BAD_BUILD_HASH", key)
    for key in (
        "network_disabled_build", "python_m_build_used", "docker_build_same_release_path", "signed_lockfile",
        "signed_wheelhouse", "offline_install_verified", "pip_check_disposable_release_env",
        "ambient_developer_pip_check_removed", "deterministic_rebuild_or_provenance_equivalence",
    ):
        _need(build.get(key) is True, blockers, "MPR25_BUILD_TRUTH", key)
    _need(build.get("resolver_count") == 1, blockers, "MPR25_MULTIPLE_RESOLVERS", "resolver_count")
    _need(build.get("runtime_lock_has_tooling_packages") is False, blockers, "MPR25_RUNTIME_LOCK_POLLUTED", "runtime_lock_has_tooling_packages")


def _workflows(workflows: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    purposes = tuple(str(item) for item in workflows.get("required_purposes", ()))
    missing = [purpose for purpose in REQUIRED_WORKFLOW_PURPOSES if purpose not in purposes]
    _need(not missing, blockers, "MPR25_MISSING_WORKFLOW_PURPOSE", ",".join(missing))
    _need(len(purposes) == len(set(purposes)), blockers, "MPR25_DUPLICATE_WORKFLOW_PURPOSE", "required_purposes")
    _need(isinstance(workflows.get("workflow_file_count"), int) and 1 <= workflows.get("workflow_file_count") <= 8, blockers, "MPR25_WORKFLOW_COUNT", "workflow_file_count")
    _need(workflows.get("required_workflow_count") == len(REQUIRED_WORKFLOW_PURPOSES), blockers, "MPR25_REQUIRED_WORKFLOW_COUNT", "required_workflow_count")
    refs = tuple(str(item) for item in workflows.get("external_action_refs", ()))
    _need(bool(refs), blockers, "MPR25_NO_ACTION_REFS", "external_action_refs")
    for ref in refs:
        _need(bool(ACTION_RE.fullmatch(ref)), blockers, "MPR25_MUTABLE_ACTION_REF", ref)
    for key, code in (("least_privilege_permissions", "MPR25_WORKFLOW_PERMISSIONS"), ("no_path_filter_gaps", "MPR25_PATH_FILTER_GAP"), ("no_writable_diagnostics", "MPR25_WRITABLE_DIAGNOSTICS")):
        _need(workflows.get(key) is True, blockers, code, key)
    _need(workflows.get("authoritative_branch_protection_check") == "release-qualification", blockers, "MPR25_BRANCH_CHECK", "authoritative_branch_protection_check")


def _quality(quality: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    for key in ("formatter_manifest_sha256", "type_manifest_sha256", "test_inventory_sha256", "verify_repo_dag_sha256"):
        _need(_sha(quality.get(key)), blockers, "MPR25_BAD_QUALITY_HASH", key)
    _need(quality.get("pytest_collection_errors") == 0, blockers, "MPR25_PYTEST_COLLECTION_ERRORS", "pytest_collection_errors")
    _need(quality.get("packaged_module_import_errors") == 0, blockers, "MPR25_IMPORT_ERRORS", "packaged_module_import_errors")
    _need(quality.get("reachable_production_assert_count") == 0, blockers, "MPR25_PRODUCTION_ASSERT", "reachable_production_assert_count")
    for key in (
        "formatter_inventory_generated_from_tracked_python", "formatter_inventory_complete", "type_lint_coverage_from_inventory",
        "black_box_installed_cli_tests", "python_optimized_mode_equivalent", "verify_repo_artifact_based_dag",
        "no_historical_subset_baseline", "duplicate_tests_removed_or_retired",
    ):
        _need(quality.get(key) is True, blockers, "MPR25_QUALITY_GATE", key)
    tracked = quality.get("tracked_python_files")
    _need(_positive_int(tracked), blockers, "MPR25_BAD_TRACKED_COUNT", "tracked_python_files")
    _need(tracked == quality.get("formatter_manifest_entries") == quality.get("type_manifest_entries") == quality.get("test_inventory_entries"), blockers, "MPR25_INVENTORY_COVERAGE", "tracked_python_files")


def _artifacts(artifacts: tuple[Mapping[str, Any], ...], blockers: list[MPR25Violation]) -> None:
    by_kind = {str(item.get("kind")): item for item in artifacts}
    missing = [kind for kind in REQUIRED_ARTIFACTS if kind not in by_kind]
    _need(not missing, blockers, "MPR25_MISSING_ARTIFACT", ",".join(missing))
    _need(len(by_kind) == len(artifacts), blockers, "MPR25_DUPLICATE_ARTIFACT", "artifacts")
    for kind in REQUIRED_ARTIFACTS:
        item = by_kind.get(kind, {})
        _need(_safe(item.get("path")), blockers, "MPR25_BAD_ARTIFACT_PATH", kind)
        _need(_sha(item.get("sha256")), blockers, "MPR25_BAD_ARTIFACT_HASH", kind)
        _need(_positive_int(item.get("size_bytes")), blockers, "MPR25_BAD_ARTIFACT_SIZE", kind)
        _need(item.get("materialized_from_bytes") is True, blockers, "MPR25_ARTIFACT_NOT_MATERIALIZED", kind)
        _need(item.get("signature_verified") is True, blockers, "MPR25_ARTIFACT_UNSIGNED", kind)
        _need(item.get("fresh_for_release") is True, blockers, "MPR25_ARTIFACT_STALE", kind)
        _need(item.get("caller_declared_only") is False, blockers, "MPR25_CALLER_DECLARED_ARTIFACT", kind)


def _crosslinks(graph: Mapping[str, Any], surface: Mapping[str, Any], reach: Mapping[str, Any], build: Mapping[str, Any], quality: Mapping[str, Any], blockers: list[MPR25Violation]) -> None:
    _need(graph.get("surface_manifest_sha256") == surface.get("policy_sha256"), blockers, "MPR25_SURFACE_HASH_DRIFT", "surface_manifest_sha256")
    _need(graph.get("reachability_manifest_sha256") == reach.get("graph_sha256"), blockers, "MPR25_REACHABILITY_HASH_DRIFT", "reachability_manifest_sha256")
    _need(build.get("dependency_graph_sha256") == quality.get("dependency_graph_sha256", build.get("dependency_graph_sha256")), blockers, "MPR25_DEPENDENCY_HASH_DRIFT", "dependency_graph_sha256")


def _need(condition: bool, blockers: list[MPR25Violation], code: str, detail: str) -> None:
    if not condition:
        blockers.append(MPR25Violation(code, detail))


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_RE.fullmatch(value))


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value)) and value not in PLACEHOLDERS


def _image(value: Any) -> bool:
    return isinstance(value, str) and bool(IMAGE_RE.fullmatch(value)) and value[7:] not in PLACEHOLDERS


def _uint(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _dedupe(blockers: Iterable[MPR25Violation]) -> Iterable[MPR25Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.detail)
        if key not in seen:
            seen.add(key)
            yield blocker


def _stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
