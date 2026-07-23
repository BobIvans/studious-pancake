"""PR-219 canonical product, artifact and quality truth gate.

This module is intentionally side-effect free.  It validates evidence that the
repository has one installed sender-free product, one CLI/composition root and
one release artifact truth before downstream PR-220...PR-224 work can depend on
the checkout.  It does not build wheels, inspect the host, read secrets, open a
signer, submit transactions or enable live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "pr219.canonical-product-artifact-quality-truth.v1"
LIVE_EXECUTION_ALLOWED = False
SENDER_ALLOWED = False
SIGNER_ALLOWED = False

REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-001", "F-002", "F-003", "F-004", "F-005", "F-006", "F-007",
    "F-009", "F-010", "F-011", "F-027", "F-028", "F-031", "F-032",
    "F-033", "F-034", "F-036", "F-037", "F-041", "F-058", "F-060",
    "F-077", "F-078", "F-079", "F-080", "F-081", "F-082", "F-083",
    "F-084", "F-085", "F-086", "F-087", "F-088", "F-089", "F-090",
    "F-091", "F-217", "F-218", "F-219", "F-220", "F-221", "F-222",
    "F-223", "F-224", "F-225", "F-226", "F-227", "F-228", "F-261",
    "F-262", "F-263", "F-264", "F-265", "F-266", "F-267", "F-268",
    "F-269", "F-270", "F-271", "F-272", "F-273", "F-274", "F-276",
    "F-277", "F-278", "F-279", "F-280", "F-281", "F-282", "F-284",
    "F-285", "F-286", "F-287", "F-288", "F-296", "F-297", "F-298",
    "F-299", "F-300", "F-301", "F-302", "F-307",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/=-]{0,159}$")


class PR219State(str, Enum):
    """High-level PR-219 qualification state."""

    READY_FOR_PR220_AND_PR221 = "ready_for_pr220_and_pr221"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ProductAuthorityEvidence:
    """Evidence for one product/release-set authority."""

    product_manifest_sha256: str
    release_set_manifest_sha256: str
    runtime_authority_manifest_sha256: str
    sender_free_product_id: str
    isolated_signer_product_id: str
    active_product_count: int
    backlog_decoupled_from_runtime_authority: bool
    historical_modules_retired_or_quarantined: bool
    source_only_modules_outside_production_graph: bool


@dataclass(frozen=True)
class CLICompositionEvidence:
    """Evidence that source and installed entrypoints expose one CLI contract."""

    root_launcher_contract_sha256: str
    installed_console_contract_sha256: str
    command_contract_manifest_sha256: str
    public_commands: tuple[str, ...]
    root_and_console_stdout_stderr_exit_match: bool
    structured_json_errors_for_all_commands: bool
    stable_exit_codes_for_all_commands: bool
    no_heavy_eager_imports_from_status_or_capabilities: bool


@dataclass(frozen=True)
class InstalledWheelEvidence:
    """Evidence for installed-wheel closure and sender-free package separation."""

    fresh_checkout_wheel_sha256: str
    installed_reachability_trace_sha256: str
    package_data_manifest_sha256: str
    required_control_trace_sha256: str
    source_wheel_parity_verified: bool
    all_packaged_modules_imported_from_installed_wheel: bool
    required_controls_reachable_from_composition_root: bool
    sender_free_wheel_excludes_signer_sender_live_namespaces: bool
    forbidden_namespace_scan_uses_real_package_contents: bool


@dataclass(frozen=True)
class ArchitectureConfigEvidence:
    """Evidence for canonical schemas, config and retirement."""

    schema_registry_sha256: str
    enum_registry_sha256: str
    typed_config_snapshot_sha256: str
    activation_signature_policy_sha256: str
    active_import_graph_sha256: str
    active_import_time_monkeypatching_absent: bool
    production_import_cycles_absent: bool
    version_by_filename_not_used_for_selection: bool
    duplicate_canonical_schemas_retired: bool
    direct_env_reads_blocked_outside_bootstrap: bool
    unknown_config_keys_rejected: bool
    conflicting_defaults_absent: bool
    signed_activation_required: bool


@dataclass(frozen=True)
class SupplyChainQualityEvidence:
    """Evidence for hermetic dependency, CI and behavioral quality truth."""

    runtime_lock_sha256: str
    signer_lock_sha256: str
    dev_lock_sha256: str
    offline_wheelhouse_manifest_sha256: str
    sbom_sha256: str
    provenance_sha256: str
    quality_trace_sha256: str
    actions_pinned_to_full_sha: bool
    base_images_pinned_to_digest: bool
    no_placeholder_hashes_or_caller_inventories: bool
    ci_gates_execute_installed_graph: bool
    dependency_profiles_resolved_by_one_owner: bool
    coverage_threshold_enforced: bool
    mypy_has_no_broad_quarantine_for_proof_modules: bool
    lint_and_black_follow_production_graph: bool
    production_assert_count_zero_under_optimized_python: bool
    duplicate_tests_retired: bool


@dataclass(frozen=True)
class PR219Evidence:
    """Complete PR-219 evidence envelope."""

    finding_coverage: tuple[str, ...]
    product: ProductAuthorityEvidence
    cli: CLICompositionEvidence
    wheel: InstalledWheelEvidence
    architecture_config: ArchitectureConfigEvidence
    supply_chain_quality: SupplyChainQualityEvidence
    live_namespace_reachable: bool = False
    sender_namespace_reachable: bool = False
    signer_namespace_in_main_wheel_reachable: bool = False


@dataclass(frozen=True)
class PR219Violation:
    """One fail-closed PR-219 blocker."""

    code: str
    message: str


@dataclass(frozen=True)
class PR219Report:
    """Deterministic PR-219 gate report."""

    schema_version: str
    state: PR219State
    blockers: tuple[PR219Violation, ...]
    evidence_hash: str
    pr220_pr221_unblocked: bool
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    sender_allowed: bool = SENDER_ALLOWED
    signer_allowed: bool = SIGNER_ALLOWED
    required_findings: tuple[str, ...] = REQUIRED_FINDINGS

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "evidence_hash": self.evidence_hash,
            "pr220_pr221_unblocked": self.pr220_pr221_unblocked,
            "live_execution_allowed": self.live_execution_allowed,
            "sender_allowed": self.sender_allowed,
            "signer_allowed": self.signer_allowed,
            "required_findings": list(self.required_findings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


def evaluate_pr219_evidence(evidence: PR219Evidence) -> PR219Report:
    """Evaluate PR-219 canonical product/artifact/quality evidence."""

    blockers: list[PR219Violation] = []
    _coverage(evidence.finding_coverage, blockers)
    _product(evidence.product, blockers)
    _cli(evidence.cli, blockers)
    _wheel(evidence.wheel, blockers)
    _architecture_config(evidence.architecture_config, blockers)
    _supply_chain_quality(evidence.supply_chain_quality, blockers)

    if evidence.live_namespace_reachable:
        _add(blockers, "PR219_LIVE_NAMESPACE_REACHABLE", "live namespace must be absent before PR-224")
    if evidence.sender_namespace_reachable:
        _add(blockers, "PR219_SENDER_NAMESPACE_REACHABLE", "sender namespace must be absent before PR-223")
    if evidence.signer_namespace_in_main_wheel_reachable:
        _add(
            blockers,
            "PR219_SIGNER_IN_MAIN_WHEEL_REACHABLE",
            "main sender-free wheel must not expose signer namespaces",
        )

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return PR219Report(
        schema_version=SCHEMA_VERSION,
        state=PR219State.READY_FOR_PR220_AND_PR221 if ready else PR219State.BLOCKED,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        pr220_pr221_unblocked=ready,
    )


def blockers_by_code(report: PR219Report) -> Mapping[str, tuple[PR219Violation, ...]]:
    """Group blockers by stable code for tests and release tooling."""

    grouped: dict[str, list[PR219Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def _coverage(items: Sequence[str], blockers: list[PR219Violation]) -> None:
    if tuple(sorted(items)) != tuple(sorted(set(items))):
        _add(blockers, "PR219_DUPLICATE_FINDING_COVERAGE", "finding coverage must not contain duplicates")
    missing = [item for item in REQUIRED_FINDINGS if item not in items]
    extra = [item for item in items if item not in REQUIRED_FINDINGS]
    if missing:
        _add(blockers, "PR219_MISSING_FINDING_COVERAGE", f"missing PR-219 findings: {missing}")
    if extra:
        _add(blockers, "PR219_UNKNOWN_FINDING_COVERAGE", f"unknown PR-219 findings: {extra}")


def _product(evidence: ProductAuthorityEvidence, blockers: list[PR219Violation]) -> None:
    _hash_fields(
        blockers,
        "PR219_BAD_PRODUCT_HASH",
        product_manifest_sha256=evidence.product_manifest_sha256,
        release_set_manifest_sha256=evidence.release_set_manifest_sha256,
        runtime_authority_manifest_sha256=evidence.runtime_authority_manifest_sha256,
    )
    _identifier(evidence.sender_free_product_id, "sender_free_product_id", blockers)
    _identifier(evidence.isolated_signer_product_id, "isolated_signer_product_id", blockers)
    if evidence.sender_free_product_id == evidence.isolated_signer_product_id:
        _add(blockers, "PR219_PRODUCT_ISOLATION_MISSING", "main and signer products must be separate")
    if evidence.active_product_count != 1:
        _add(blockers, "PR219_MULTIPLE_ACTIVE_PRODUCTS", "exactly one sender-free product may be active")
    _require_flags(
        blockers,
        "PR219_PRODUCT_AUTHORITY_INCOMPLETE",
        backlog_decoupled_from_runtime_authority=evidence.backlog_decoupled_from_runtime_authority,
        historical_modules_retired_or_quarantined=evidence.historical_modules_retired_or_quarantined,
        source_only_modules_outside_production_graph=evidence.source_only_modules_outside_production_graph,
    )


def _cli(evidence: CLICompositionEvidence, blockers: list[PR219Violation]) -> None:
    _hash_fields(
        blockers,
        "PR219_BAD_CLI_HASH",
        root_launcher_contract_sha256=evidence.root_launcher_contract_sha256,
        installed_console_contract_sha256=evidence.installed_console_contract_sha256,
        command_contract_manifest_sha256=evidence.command_contract_manifest_sha256,
    )
    if not evidence.public_commands:
        _add(blockers, "PR219_EMPTY_PUBLIC_COMMANDS", "public command contract must be non-empty")
    if len(set(evidence.public_commands)) != len(evidence.public_commands):
        _add(blockers, "PR219_DUPLICATE_PUBLIC_COMMANDS", "public commands must be unique")
    for command in evidence.public_commands:
        _identifier(command, "public_command", blockers)
    _require_flags(
        blockers,
        "PR219_CLI_CONTRACT_INCOMPLETE",
        root_and_console_stdout_stderr_exit_match=evidence.root_and_console_stdout_stderr_exit_match,
        structured_json_errors_for_all_commands=evidence.structured_json_errors_for_all_commands,
        stable_exit_codes_for_all_commands=evidence.stable_exit_codes_for_all_commands,
        no_heavy_eager_imports_from_status_or_capabilities=(
            evidence.no_heavy_eager_imports_from_status_or_capabilities
        ),
    )


def _wheel(evidence: InstalledWheelEvidence, blockers: list[PR219Violation]) -> None:
    _hash_fields(
        blockers,
        "PR219_BAD_WHEEL_HASH",
        fresh_checkout_wheel_sha256=evidence.fresh_checkout_wheel_sha256,
        installed_reachability_trace_sha256=evidence.installed_reachability_trace_sha256,
        package_data_manifest_sha256=evidence.package_data_manifest_sha256,
        required_control_trace_sha256=evidence.required_control_trace_sha256,
    )
    _require_flags(
        blockers,
        "PR219_INSTALLED_WHEEL_CLOSURE_INCOMPLETE",
        source_wheel_parity_verified=evidence.source_wheel_parity_verified,
        all_packaged_modules_imported_from_installed_wheel=(
            evidence.all_packaged_modules_imported_from_installed_wheel
        ),
        required_controls_reachable_from_composition_root=(
            evidence.required_controls_reachable_from_composition_root
        ),
        sender_free_wheel_excludes_signer_sender_live_namespaces=(
            evidence.sender_free_wheel_excludes_signer_sender_live_namespaces
        ),
        forbidden_namespace_scan_uses_real_package_contents=(
            evidence.forbidden_namespace_scan_uses_real_package_contents
        ),
    )


def _architecture_config(evidence: ArchitectureConfigEvidence, blockers: list[PR219Violation]) -> None:
    _hash_fields(
        blockers,
        "PR219_BAD_ARCHITECTURE_CONFIG_HASH",
        schema_registry_sha256=evidence.schema_registry_sha256,
        enum_registry_sha256=evidence.enum_registry_sha256,
        typed_config_snapshot_sha256=evidence.typed_config_snapshot_sha256,
        activation_signature_policy_sha256=evidence.activation_signature_policy_sha256,
        active_import_graph_sha256=evidence.active_import_graph_sha256,
    )
    _require_flags(
        blockers,
        "PR219_ARCHITECTURE_CONFIG_INCOMPLETE",
        active_import_time_monkeypatching_absent=evidence.active_import_time_monkeypatching_absent,
        production_import_cycles_absent=evidence.production_import_cycles_absent,
        version_by_filename_not_used_for_selection=evidence.version_by_filename_not_used_for_selection,
        duplicate_canonical_schemas_retired=evidence.duplicate_canonical_schemas_retired,
        direct_env_reads_blocked_outside_bootstrap=evidence.direct_env_reads_blocked_outside_bootstrap,
        unknown_config_keys_rejected=evidence.unknown_config_keys_rejected,
        conflicting_defaults_absent=evidence.conflicting_defaults_absent,
        signed_activation_required=evidence.signed_activation_required,
    )


def _supply_chain_quality(evidence: SupplyChainQualityEvidence, blockers: list[PR219Violation]) -> None:
    _hash_fields(
        blockers,
        "PR219_BAD_SUPPLY_CHAIN_QUALITY_HASH",
        runtime_lock_sha256=evidence.runtime_lock_sha256,
        signer_lock_sha256=evidence.signer_lock_sha256,
        dev_lock_sha256=evidence.dev_lock_sha256,
        offline_wheelhouse_manifest_sha256=evidence.offline_wheelhouse_manifest_sha256,
        sbom_sha256=evidence.sbom_sha256,
        provenance_sha256=evidence.provenance_sha256,
        quality_trace_sha256=evidence.quality_trace_sha256,
    )
    _require_flags(
        blockers,
        "PR219_SUPPLY_CHAIN_QUALITY_INCOMPLETE",
        actions_pinned_to_full_sha=evidence.actions_pinned_to_full_sha,
        base_images_pinned_to_digest=evidence.base_images_pinned_to_digest,
        no_placeholder_hashes_or_caller_inventories=evidence.no_placeholder_hashes_or_caller_inventories,
        ci_gates_execute_installed_graph=evidence.ci_gates_execute_installed_graph,
        dependency_profiles_resolved_by_one_owner=evidence.dependency_profiles_resolved_by_one_owner,
        coverage_threshold_enforced=evidence.coverage_threshold_enforced,
        mypy_has_no_broad_quarantine_for_proof_modules=(
            evidence.mypy_has_no_broad_quarantine_for_proof_modules
        ),
        lint_and_black_follow_production_graph=evidence.lint_and_black_follow_production_graph,
        production_assert_count_zero_under_optimized_python=(
            evidence.production_assert_count_zero_under_optimized_python
        ),
        duplicate_tests_retired=evidence.duplicate_tests_retired,
    )


def _require_flags(blockers: list[PR219Violation], code: str, **flags: bool) -> None:
    missing = [name for name, value in flags.items() if value is not True]
    if missing:
        _add(blockers, code, f"missing required evidence flags: {missing}")


def _hash_fields(blockers: list[PR219Violation], code: str, **values: str) -> None:
    bad = [name for name, value in values.items() if not _sha(value)]
    if bad:
        _add(blockers, code, f"invalid or placeholder sha256 fields: {bad}")


def _identifier(value: object, name: str, blockers: list[PR219Violation]) -> None:
    if not isinstance(value, str) or not IDENTIFIER_RE.match(value):
        _add(blockers, "PR219_BAD_IDENTIFIER", f"{name} must be a stable identifier")


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.match(value)) and value not in {"0" * 64, "f" * 64}


def _stable_hash(value: object) -> str:
    encoded = json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _add(blockers: list[PR219Violation], code: str, message: str) -> None:
    blockers.append(PR219Violation(code=code, message=message))


def _dedupe(blockers: Iterable[PR219Violation]) -> Iterable[PR219Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker
