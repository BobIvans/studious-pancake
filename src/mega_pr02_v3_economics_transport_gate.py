"""MEGA-PR-02 V3 economics and provider HTTP qualification gate.

This additive gate absorbs V3 findings IMPL-40 and IMPL-41 without enabling
provider IO, signing, sender submission, key loading, Docker or release builds.
It is a side-effect-free evidence contract layered on top of the merged
MEGA-PR-02 protocol/hermetic-release gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping


SCHEMA_VERSION = "mega-pr02.v3-economics-transport.v1"
REQUIRED_FINDINGS: tuple[str, ...] = ("IMPL-40", "IMPL-41")
REQUIRED_MONETARY_FUZZ_CASES: tuple[str, ...] = (
    "float_rejected",
    "rounding_boundary_rejected",
    "negative_fee_rejected",
    "duplicate_profit_truth_rejected",
    "repayment_default_rejected",
)
REQUIRED_PROVIDER_FAILURE_CASES: tuple[str, ...] = (
    "oversized_response",
    "malformed_json",
    "wrong_content_type",
    "schema_violation",
    "slow_response_deadline",
    "retry_after_backoff",
    "non_idempotent_no_retry",
)
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class MegaPR02V3State(str, Enum):
    READY = "ready_for_v3_paper_qualification"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class IntegerEconomicsEvidence:
    immutable_economics_object_hash: str
    opportunity_profit_lamports: int
    admission_profit_lamports: int
    terminal_profit_lamports: int
    integer_denominated_only: bool
    float_inputs_rejected: bool
    metadata_profit_truth_absent: bool
    expected_profit_bound_to_object: bool
    min_out_bound_to_object: bool
    repayment_bound_to_protocol_evidence: bool
    protocol_fee_bound_to_protocol_evidence: bool
    silent_principal_default_forbidden: bool
    monetary_fuzz_cases: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalProviderHttpEvidence:
    canonical_transport_hash: str
    host_allowlist_hash: str
    retry_policy_hash: str
    all_provider_clients_use_canonical_transport: bool
    streamed_response_size_limit_bytes: int
    content_type_limits_enforced: bool
    schema_limits_enforced_before_business_logic: bool
    method_aware_idempotent_retry_policy: bool
    retry_after_and_jitter_proven: bool
    non_idempotent_requests_not_retried: bool
    deadline_budget_enforced: bool
    oversized_response_fails_closed_before_decode: bool
    malformed_response_fails_closed: bool
    slow_response_fails_closed: bool
    no_oom_or_duplicate_side_effects: bool
    provider_failure_cases: tuple[str, ...]


@dataclass(frozen=True)
class MegaPR02V3Evidence:
    merged_mega_pr02_gate_hash: str
    findings_covered: tuple[str, ...]
    economics: IntegerEconomicsEvidence
    provider_http: CanonicalProviderHttpEvidence
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class MegaPR02V3Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MegaPR02V3Report:
    schema_version: str
    state: MegaPR02V3State
    blockers: tuple[MegaPR02V3Violation, ...]
    evidence_hash: str
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool


def evaluate_mega_pr02_v3_evidence(evidence: MegaPR02V3Evidence) -> MegaPR02V3Report:
    blockers: list[MegaPR02V3Violation] = []
    _validate_safety_boundary(evidence, blockers)
    _validate_required_findings(evidence, blockers)
    _validate_economics(evidence.economics, blockers)
    _validate_provider_http(evidence.provider_http, blockers)
    if not _is_sha256(evidence.merged_mega_pr02_gate_hash):
        _add(
            blockers,
            "MEGA_PR02_V3_BAD_BASE_GATE_HASH",
            "merged MEGA-PR-02 gate hash must be strict sha256",
        )

    unique = tuple(_dedupe(blockers))
    return MegaPR02V3Report(
        schema_version=SCHEMA_VERSION,
        state=MegaPR02V3State.BLOCKED if unique else MegaPR02V3State.READY,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
    )


def blockers_by_code(report: MegaPR02V3Report) -> Mapping[str, MegaPR02V3Violation]:
    return {blocker.code: blocker for blocker in report.blockers}


def _validate_safety_boundary(
    evidence: MegaPR02V3Evidence,
    blockers: list[MegaPR02V3Violation],
) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "MEGA_PR02_V3_LIVE_REQUESTED", "V3 gate cannot enable live")
    if evidence.signer_requested:
        _add(blockers, "MEGA_PR02_V3_SIGNER_REQUESTED", "V3 gate cannot enable signer")
    if evidence.sender_requested:
        _add(blockers, "MEGA_PR02_V3_SENDER_REQUESTED", "V3 gate cannot enable sender")
    if evidence.private_key_material_present:
        _add(blockers, "MEGA_PR02_V3_PRIVATE_KEY_PRESENT", "private key material is forbidden")


def _validate_required_findings(
    evidence: MegaPR02V3Evidence,
    blockers: list[MegaPR02V3Violation],
) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in set(evidence.findings_covered)]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_V3_FINDINGS_INCOMPLETE",
            f"missing V3 findings: {', '.join(missing)}",
        )


def _validate_economics(
    evidence: IntegerEconomicsEvidence,
    blockers: list[MegaPR02V3Violation],
) -> None:
    if not _is_sha256(evidence.immutable_economics_object_hash):
        _add(blockers, "MEGA_PR02_V3_ECONOMICS_BAD_HASH", "economics object hash must be strict sha256")
    for field_name, value in (
        ("opportunity_profit_lamports", evidence.opportunity_profit_lamports),
        ("admission_profit_lamports", evidence.admission_profit_lamports),
        ("terminal_profit_lamports", evidence.terminal_profit_lamports),
    ):
        if not _is_nonnegative_int(value):
            _add(blockers, "MEGA_PR02_V3_NON_INTEGER_AMOUNT", f"{field_name} must be a non-negative int")
    if not (
        evidence.opportunity_profit_lamports
        == evidence.admission_profit_lamports
        == evidence.terminal_profit_lamports
    ):
        _add(
            blockers,
            "MEGA_PR02_V3_DUPLICATE_PROFIT_TRUTH",
            "opportunity/admission/terminal profit must be the same immutable integer truth",
        )
    if not evidence.integer_denominated_only:
        _add(blockers, "MEGA_PR02_V3_NOT_INTEGER_ONLY", "monetary model must be integer-only")
    if not evidence.float_inputs_rejected:
        _add(blockers, "MEGA_PR02_V3_FLOAT_ACCEPTED", "float monetary inputs must fail closed")
    if not evidence.metadata_profit_truth_absent:
        _add(blockers, "MEGA_PR02_V3_METADATA_PROFIT_TRUTH", "second metadata profit truth is forbidden")
    if not evidence.expected_profit_bound_to_object:
        _add(blockers, "MEGA_PR02_V3_EXPECTED_PROFIT_UNBOUND", "expected profit must bind to economics object")
    if not evidence.min_out_bound_to_object:
        _add(blockers, "MEGA_PR02_V3_MIN_OUT_UNBOUND", "min-out must bind to economics object")
    if not evidence.repayment_bound_to_protocol_evidence:
        _add(blockers, "MEGA_PR02_V3_REPAYMENT_UNBOUND", "repayment must bind to protocol evidence")
    if not evidence.protocol_fee_bound_to_protocol_evidence:
        _add(blockers, "MEGA_PR02_V3_PROTOCOL_FEE_UNBOUND", "protocol fee must bind to protocol evidence")
    if not evidence.silent_principal_default_forbidden:
        _add(blockers, "MEGA_PR02_V3_SILENT_PRINCIPAL_DEFAULT", "silent principal default is forbidden")
    missing = [case for case in REQUIRED_MONETARY_FUZZ_CASES if case not in set(evidence.monetary_fuzz_cases)]
    if missing:
        _add(blockers, "MEGA_PR02_V3_MONETARY_FUZZ_INCOMPLETE", f"missing monetary fuzz cases: {', '.join(missing)}")


def _validate_provider_http(
    evidence: CanonicalProviderHttpEvidence,
    blockers: list[MegaPR02V3Violation],
) -> None:
    for field_name, value in (
        ("canonical_transport_hash", evidence.canonical_transport_hash),
        ("host_allowlist_hash", evidence.host_allowlist_hash),
        ("retry_policy_hash", evidence.retry_policy_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_V3_TRANSPORT_BAD_HASH", f"{field_name} must be strict sha256")
    if not evidence.all_provider_clients_use_canonical_transport:
        _add(blockers, "MEGA_PR02_V3_TRANSPORT_FRAGMENTED", "all providers must use one canonical transport")
    if not _is_positive_int(evidence.streamed_response_size_limit_bytes):
        _add(blockers, "MEGA_PR02_V3_RESPONSE_LIMIT_INVALID", "response-size limit must be a positive integer")
    if not evidence.content_type_limits_enforced:
        _add(blockers, "MEGA_PR02_V3_CONTENT_TYPE_UNBOUNDED", "content-type limits must be enforced")
    if not evidence.schema_limits_enforced_before_business_logic:
        _add(blockers, "MEGA_PR02_V3_SCHEMA_LIMITS_LATE", "schema limits must run before business logic")
    if not evidence.method_aware_idempotent_retry_policy:
        _add(blockers, "MEGA_PR02_V3_RETRY_NOT_IDEMPOTENT_AWARE", "retry policy must be method/idempotency aware")
    if not evidence.retry_after_and_jitter_proven:
        _add(blockers, "MEGA_PR02_V3_RETRY_AFTER_JITTER_MISSING", "Retry-After and jitter must be proven")
    if not evidence.non_idempotent_requests_not_retried:
        _add(blockers, "MEGA_PR02_V3_NON_IDEMPOTENT_RETRY", "non-idempotent requests must not be retried")
    if not evidence.deadline_budget_enforced:
        _add(blockers, "MEGA_PR02_V3_DEADLINE_UNBOUNDED", "provider deadline budget must be enforced")
    if not evidence.oversized_response_fails_closed_before_decode:
        _add(blockers, "MEGA_PR02_V3_OVERSIZED_NOT_FAIL_CLOSED", "oversized response must fail before decode")
    if not evidence.malformed_response_fails_closed:
        _add(blockers, "MEGA_PR02_V3_MALFORMED_NOT_FAIL_CLOSED", "malformed response must fail closed")
    if not evidence.slow_response_fails_closed:
        _add(blockers, "MEGA_PR02_V3_SLOW_NOT_FAIL_CLOSED", "slow response must fail closed")
    if not evidence.no_oom_or_duplicate_side_effects:
        _add(blockers, "MEGA_PR02_V3_OOM_OR_SIDE_EFFECT_RISK", "failure cases cannot OOM or duplicate side effects")
    missing = [case for case in REQUIRED_PROVIDER_FAILURE_CASES if case not in set(evidence.provider_failure_cases)]
    if missing:
        _add(blockers, "MEGA_PR02_V3_PROVIDER_CASES_INCOMPLETE", f"missing provider failure cases: {', '.join(missing)}")


def _stable_hash(value: object) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(v) for v in value]
    return value


def _is_sha256(value: str) -> bool:
    return isinstance(value, str) and bool(HEX_64_RE.fullmatch(value))


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _add(blockers: list[MegaPR02V3Violation], code: str, message: str) -> None:
    blockers.append(MegaPR02V3Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MegaPR02V3Violation]) -> tuple[MegaPR02V3Violation, ...]:
    seen: set[str] = set()
    unique: list[MegaPR02V3Violation] = []
    for blocker in blockers:
        key = f"{blocker.code}:{blocker.message}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)
    return tuple(unique)
