"""PR-217 installed behavioral quality baseline gate.

Side-effect free acceptance boundary for Pass 7 PR-217. It never imports the
production runtime, never opens network resources and never enables live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Sequence


SCHEMA_VERSION = "pr217.installed-behavioral-quality-baseline.v1"

REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-296",
    "F-297",
    "F-298",
    "F-299",
    "F-300",
    "F-301",
    "F-302",
)

REQUIRED_SUBPROCESS_CASES: tuple[str, ...] = (
    "clean_env",
    "missing_dependency",
    "corrupt_config",
    "unknown_command",
    "interrupted_output",
)

HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class PR217GateState(str, Enum):
    READY_FOR_INSTALLED_QUALITY_BASELINE = "ready_for_installed_quality_baseline"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DuplicateTestGroup:
    group_hash: str
    files: tuple[str, ...]
    behavioral_case_id: str
    parameterized_fixture_count: int


@dataclass(frozen=True)
class DuplicateTestEvidence:
    total_test_files: int
    total_test_functions: int
    unique_behavioral_case_count: int
    duplicate_hash_groups: tuple[DuplicateTestGroup, ...]
    duplicate_hashes_counted_as_independent_evidence: bool
    duplicate_groups_removed_or_parameterized: bool
    unique_case_count_published: bool


@dataclass(frozen=True)
class CoverageEvidence:
    line_coverage_enabled: bool
    branch_coverage_enabled: bool
    diff_coverage_enabled: bool
    measured_line_percent: float
    measured_branch_percent: float
    measured_diff_percent: float
    minimum_line_percent: float
    minimum_branch_percent: float
    minimum_diff_percent: float
    required_controls_map_hash: str
    installed_wheel_hash: str
    coverage_bound_to_installed_wheel: bool
    composition_trace_hash: str


@dataclass(frozen=True)
class LintTypeEvidence:
    complexity_signal_enabled: bool
    unused_import_signal_enabled: bool
    redefined_name_signal_enabled: bool
    wildcard_import_signal_enabled: bool
    wildcard_imports_forbidden: bool
    format_targets_from_installed_graph: bool
    quarantine_manifest_hash: str
    quarantine_entries_have_owner_issue_expiry: bool
    active_graph_mypy_ignore_errors_count: int
    active_graph_wildcard_import_count: int


@dataclass(frozen=True)
class WheelSubprocessEvidence:
    installed_console_targets: tuple[str, ...]
    production_surface_console_targets: tuple[str, ...]
    exercised_cases: tuple[str, ...]
    exact_exit_schema_assertions: bool
    no_traceback_without_debug: bool
    dependency_failure_structured: bool
    config_failure_structured: bool
    root_wrapper_parity_checked: bool
    installed_artifact_hash: str


@dataclass(frozen=True)
class PR217QualityEvidence:
    release_artifact_hash: str
    quality_manifest_hash: str
    installed_graph_manifest_hash: str
    pyproject_script_manifest_hash: str
    findings_covered: tuple[str, ...]
    duplicate_tests: DuplicateTestEvidence
    coverage: CoverageEvidence
    lint_type: LintTypeEvidence
    subprocess_matrix: WheelSubprocessEvidence
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True)
class PR217Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PR217QualityReport:
    schema_version: str
    state: PR217GateState
    blockers: tuple[PR217Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


def evaluate_pr217_quality_evidence(
    evidence: PR217QualityEvidence,
) -> PR217QualityReport:
    """Validate PR-217 installed quality evidence without side effects."""

    blockers: list[PR217Violation] = []
    _validate_top_level_hashes(evidence, blockers)
    _validate_no_runtime_enablement(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_duplicate_tests(evidence.duplicate_tests, blockers)
    _validate_coverage(evidence.coverage, blockers)
    _validate_lint_type(evidence.lint_type, blockers)
    _validate_subprocess_matrix(evidence.subprocess_matrix, blockers)

    unique = tuple(_dedupe(blockers))
    state = (
        PR217GateState.BLOCKED
        if unique
        else PR217GateState.READY_FOR_INSTALLED_QUALITY_BASELINE
    )
    return PR217QualityReport(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_top_level_hashes(
    evidence: PR217QualityEvidence,
    blockers: list[PR217Violation],
) -> None:
    for field_name, value in (
        ("release_artifact_hash", evidence.release_artifact_hash),
        ("quality_manifest_hash", evidence.quality_manifest_hash),
        ("installed_graph_manifest_hash", evidence.installed_graph_manifest_hash),
        ("pyproject_script_manifest_hash", evidence.pyproject_script_manifest_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "PR217_BAD_HASH", f"{field_name} is not a strict sha256")


def _validate_no_runtime_enablement(
    evidence: PR217QualityEvidence,
    blockers: list[PR217Violation],
) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "PR217_LIVE_REQUESTED", "quality baseline cannot enable live")
    if evidence.signer_requested:
        _add(blockers, "PR217_SIGNER_REQUESTED", "quality baseline cannot sign")
    if evidence.sender_requested:
        _add(blockers, "PR217_SENDER_REQUESTED", "quality baseline cannot submit")


def _validate_findings(
    findings_covered: Sequence[str],
    blockers: list[PR217Violation],
) -> None:
    covered = set(findings_covered)
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in covered]
    if missing:
        _add(
            blockers,
            "PR217_FINDINGS_INCOMPLETE",
            f"missing required findings: {', '.join(missing)}",
        )


def _validate_duplicate_tests(
    evidence: DuplicateTestEvidence,
    blockers: list[PR217Violation],
) -> None:
    for field_name, value in (
        ("total_test_files", evidence.total_test_files),
        ("total_test_functions", evidence.total_test_functions),
        ("unique_behavioral_case_count", evidence.unique_behavioral_case_count),
    ):
        if not _is_nonnegative_int(value):
            _add(blockers, "PR217_BAD_TEST_COUNT", f"{field_name} must be non-negative")
    if evidence.total_test_files == 0 or evidence.total_test_functions == 0:
        _add(blockers, "PR217_EMPTY_TEST_SURFACE", "test surface must be non-empty")
    if evidence.unique_behavioral_case_count == 0:
        _add(blockers, "PR217_EMPTY_BEHAVIORAL_CASES", "unique case count is required")
    if evidence.unique_behavioral_case_count > evidence.total_test_functions:
        _add(
            blockers,
            "PR217_UNIQUE_CASE_COUNT_IMPOSSIBLE",
            "unique case count cannot exceed total test functions",
        )
    if evidence.duplicate_hashes_counted_as_independent_evidence:
        _add(
            blockers,
            "PR217_DUPLICATE_HASH_COUNTED",
            "duplicate test hashes cannot count as independent evidence",
        )
    if evidence.duplicate_hash_groups and not evidence.duplicate_groups_removed_or_parameterized:
        _add(
            blockers,
            "PR217_DUPLICATE_GROUPS_UNREMEDIATED",
            "duplicate test groups must be removed or parameterized",
        )
    if not evidence.unique_case_count_published:
        _add(
            blockers,
            "PR217_UNIQUE_CASE_COUNT_NOT_PUBLISHED",
            "unique behavioral-case count must be published",
        )
    for group in evidence.duplicate_hash_groups:
        if not _is_strict_sha256(group.group_hash):
            _add(blockers, "PR217_BAD_DUPLICATE_GROUP_HASH", "bad duplicate hash")
        if len(group.files) < 2:
            _add(
                blockers,
                "PR217_DUPLICATE_GROUP_TOO_SMALL",
                "duplicate hash group must contain at least two files",
            )
        if group.parameterized_fixture_count < 1:
            _add(
                blockers,
                "PR217_DUPLICATE_GROUP_NOT_PARAMETERIZED",
                "duplicate group must name real parameterized fixtures",
            )


def _validate_coverage(
    evidence: CoverageEvidence,
    blockers: list[PR217Violation],
) -> None:
    if not evidence.line_coverage_enabled:
        _add(blockers, "PR217_LINE_COVERAGE_DISABLED", "line coverage is required")
    if not evidence.branch_coverage_enabled:
        _add(blockers, "PR217_BRANCH_COVERAGE_DISABLED", "branch coverage is required")
    if not evidence.diff_coverage_enabled:
        _add(blockers, "PR217_DIFF_COVERAGE_DISABLED", "diff coverage is required")
    for field_name, value in (
        ("measured_line_percent", evidence.measured_line_percent),
        ("measured_branch_percent", evidence.measured_branch_percent),
        ("measured_diff_percent", evidence.measured_diff_percent),
        ("minimum_line_percent", evidence.minimum_line_percent),
        ("minimum_branch_percent", evidence.minimum_branch_percent),
        ("minimum_diff_percent", evidence.minimum_diff_percent),
    ):
        if not _valid_percent(value):
            _add(blockers, "PR217_BAD_COVERAGE_PERCENT", f"{field_name} is invalid")
    if evidence.measured_line_percent < evidence.minimum_line_percent:
        _add(blockers, "PR217_LINE_COVERAGE_BELOW_MINIMUM", "line coverage too low")
    if evidence.measured_branch_percent < evidence.minimum_branch_percent:
        _add(
            blockers,
            "PR217_BRANCH_COVERAGE_BELOW_MINIMUM",
            "branch coverage too low",
        )
    if evidence.measured_diff_percent < evidence.minimum_diff_percent:
        _add(blockers, "PR217_DIFF_COVERAGE_BELOW_MINIMUM", "diff coverage too low")
    if not _is_strict_sha256(evidence.required_controls_map_hash):
        _add(blockers, "PR217_BAD_CONTROLS_MAP_HASH", "controls map hash is invalid")
    if not _is_strict_sha256(evidence.installed_wheel_hash):
        _add(blockers, "PR217_BAD_WHEEL_HASH", "wheel hash is invalid")
    if not _is_strict_sha256(evidence.composition_trace_hash):
        _add(blockers, "PR217_BAD_COMPOSITION_TRACE_HASH", "trace hash is invalid")
    if not evidence.coverage_bound_to_installed_wheel:
        _add(
            blockers,
            "PR217_COVERAGE_NOT_WHEEL_BOUND",
            "coverage must be bound to installed wheel/hash",
        )


def _validate_lint_type(
    evidence: LintTypeEvidence,
    blockers: list[PR217Violation],
) -> None:
    if not evidence.complexity_signal_enabled:
        _add(blockers, "PR217_COMPLEXITY_SIGNAL_DISABLED", "complexity lint required")
    if not evidence.unused_import_signal_enabled:
        _add(blockers, "PR217_UNUSED_IMPORT_SIGNAL_DISABLED", "unused imports required")
    if not evidence.redefined_name_signal_enabled:
        _add(blockers, "PR217_REDEFINED_NAME_SIGNAL_DISABLED", "redefined names required")
    if not evidence.wildcard_import_signal_enabled:
        _add(blockers, "PR217_WILDCARD_SIGNAL_DISABLED", "wildcard signal required")
    if not evidence.wildcard_imports_forbidden:
        _add(blockers, "PR217_WILDCARD_IMPORTS_ALLOWED", "wildcard imports forbidden")
    if not evidence.format_targets_from_installed_graph:
        _add(
            blockers,
            "PR217_FORMAT_TARGETS_NOT_GRAPH_DERIVED",
            "format targets must be derived from installed graph",
        )
    if not _is_strict_sha256(evidence.quarantine_manifest_hash):
        _add(blockers, "PR217_BAD_QUARANTINE_HASH", "quarantine hash invalid")
    if not evidence.quarantine_entries_have_owner_issue_expiry:
        _add(
            blockers,
            "PR217_QUARANTINE_MISSING_OWNER_EXPIRY",
            "quarantine entries need owner, issue and expiry",
        )
    if evidence.active_graph_mypy_ignore_errors_count != 0:
        _add(
            blockers,
            "PR217_ACTIVE_GRAPH_MYPY_IGNORE_ERRORS",
            "installed active graph cannot contain mypy ignore_errors",
        )
    if evidence.active_graph_wildcard_import_count != 0:
        _add(
            blockers,
            "PR217_ACTIVE_GRAPH_WILDCARD_IMPORTS",
            "installed active graph cannot contain wildcard imports",
        )


def _validate_subprocess_matrix(
    evidence: WheelSubprocessEvidence,
    blockers: list[PR217Violation],
) -> None:
    if not _is_strict_sha256(evidence.installed_artifact_hash):
        _add(blockers, "PR217_BAD_INSTALLED_ARTIFACT_HASH", "artifact hash invalid")
    if set(evidence.installed_console_targets) != set(
        evidence.production_surface_console_targets
    ):
        _add(
            blockers,
            "PR217_CONSOLE_TARGET_MISMATCH",
            "installed scripts must match production surface manifest",
        )
    if not evidence.installed_console_targets:
        _add(blockers, "PR217_NO_CONSOLE_TARGETS", "at least one console target needed")
    missing_cases = [
        case for case in REQUIRED_SUBPROCESS_CASES if case not in evidence.exercised_cases
    ]
    if missing_cases:
        _add(
            blockers,
            "PR217_SUBPROCESS_MATRIX_INCOMPLETE",
            f"missing subprocess cases: {', '.join(missing_cases)}",
        )
    if not evidence.exact_exit_schema_assertions:
        _add(blockers, "PR217_NO_EXIT_SCHEMA_ASSERTIONS", "exit/schema assertions required")
    if not evidence.no_traceback_without_debug:
        _add(blockers, "PR217_TRACEBACK_NOT_GATED", "tracebacks require explicit debug")
    if not evidence.dependency_failure_structured:
        _add(
            blockers,
            "PR217_DEPENDENCY_FAILURE_UNSTRUCTURED",
            "dependency failures need structured output",
        )
    if not evidence.config_failure_structured:
        _add(
            blockers,
            "PR217_CONFIG_FAILURE_UNSTRUCTURED",
            "config failures need structured output",
        )
    if not evidence.root_wrapper_parity_checked:
        _add(blockers, "PR217_ROOT_WRAPPER_PARITY_MISSING", "root wrapper parity required")


def _is_strict_sha256(value: str) -> bool:
    return isinstance(value, str) and bool(HEX_64_RE.match(value)) and value not in {
        "0" * 64,
        "f" * 64,
    }


def _is_nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _valid_percent(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 100


def _stable_hash(value: object) -> str:
    payload = json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return "<non-finite>"
    return value


def _add(blockers: list[PR217Violation], code: str, message: str) -> None:
    blockers.append(PR217Violation(code=code, message=message))


def _dedupe(blockers: Iterable[PR217Violation]) -> Iterable[PR217Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        identity = (blocker.code, blocker.message)
        if identity not in seen:
            seen.add(identity)
            yield blocker
