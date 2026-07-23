"""MPR-14 durable canary and authenticated operator-control gate.

Side-effect-free acceptance contract for the MPR-14 cutover.  The evaluator never
opens providers, signs payloads, submits transactions or mutates process state;
it only validates evidence that canary control has been moved to durable,
generation-fenced and operator-authenticated authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mpr14.durable-canary-operator-control.v1"
REQUIRED_FINDINGS: tuple[str, ...] = tuple(f"F-{n}" for n in range(327, 337))
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")

DURABLE_FLAGS = (
    "mode_durable",
    "review_durable",
    "acknowledgement_durable",
    "arming_durable",
    "decisions_durable",
    "latches_durable",
    "outstanding_submission_durable",
    "daily_pnl_durable",
    "failure_count_durable",
)
DECISION_FLAGS = (
    "decision_consumed_durably",
    "decision_unique_constraint_enforced",
    "reserve_rechecks_current_mode_generation",
    "reserve_to_permit_handoff_atomic",
    "same_decision_second_reserve_rejected",
    "rollback_invalidated_prior_decisions",
    "permit_handoff_generation_bound",
)
LATCH_FLAGS = (
    "latch_types_separated",
    "hard_latch_requires_machine_evidence",
    "hard_latch_requires_dual_approval",
    "hard_latch_bumps_generation",
    "manual_kill_survives_restart",
    "loss_latch_survives_restart",
    "rpc_divergence_latch_survives_restart",
    "reconciliation_ambiguity_latch_survives_restart",
)
RECONCILIATION_FLAGS = (
    "reconciliation_input_from_rooted_authority",
    "pnl_decoder_owned",
    "caller_declared_pnl_rejected",
    "outstanding_cleared_only_by_rooted_reconciliation",
    "daily_pnl_from_finalized_ledger",
    "failures_reset_only_by_attempt_outcome",
)
RISK_FLAGS = (
    "utc_day_ledger_durable",
    "rolling_24h_ledger_durable",
    "window_membership_from_trusted_time",
    "daily_loss_survives_restart",
    "counters_idempotent_by_finalized_entry",
    "bounded_event_log_enabled",
    "paginated_event_projection",
    "rolling_digest_o1",
)
AUTHORIZED_OPERATOR_ROLES = {"reviewer", "armer", "killswitch", "latch_admin"}
AUTHORIZED_SIGNATURE_SCHEMES = {"ed25519", "webauthn-ed25519", "hsm-ed25519"}


class MPR14GateState(str, Enum):
    READY_FOR_DURABLE_CANARY_CONTROL = "ready_for_durable_canary_control"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MPR14OperatorCommand:
    principal_id: str
    role: str
    command_hash: str
    signature_scheme: str
    signature_hash: str
    registry_entry_hash: str
    session_fresh_until_ns: int
    command_observed_at_ns: int
    command_generation: int
    mfa_bound: bool
    canonical_command_bound: bool
    replay_nonce_consumed: bool


@dataclass(frozen=True)
class MPR14ControlEvidence:
    release_artifact_hash: str
    policy_generation_hash: str
    operator_registry_hash: str
    control_store_schema_hash: str
    store_fence_token_hash: str
    projection_head_hash: str
    findings_covered: tuple[str, ...]
    durable_flags: Mapping[str, bool]
    process_local_authority_disabled: bool
    restart_recovered_generation: int
    failover_recovered_generation: int
    operator_commands: tuple[MPR14OperatorCommand, ...]
    causal_timestamps_ns: Mapping[str, int]
    max_decision_ttl_ns: int
    actual_decision_ttl_ns: int
    current_generation: int
    revocation_generation: int
    rollback_or_kill_generation_bumped: bool
    prior_decisions_revoked_on_generation_bump: bool
    decision_flags: Mapping[str, bool]
    latch_flags: Mapping[str, bool]
    reconciliation_flags: Mapping[str, bool]
    risk_flags: Mapping[str, bool]
    maximum_in_memory_events: int
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True)
class MPR14Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR14ControlReport:
    schema_version: str
    state: MPR14GateState
    blockers: tuple[MPR14Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


def evaluate_mpr14_control_evidence(
    evidence: MPR14ControlEvidence,
) -> MPR14ControlReport:
    blockers: list[MPR14Violation] = []
    _validate_hashes(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_runtime_enablement(evidence, blockers)
    _validate_durable_state(evidence, blockers)
    _validate_operator_commands(evidence.operator_commands, blockers)
    _validate_time_generation(evidence, blockers)
    _validate_flag_group(
        evidence.decision_flags, DECISION_FLAGS, "MPR14_DECISION_NOT_ONESHOT", blockers
    )
    _validate_flag_group(
        evidence.latch_flags, LATCH_FLAGS, "MPR14_LATCH_POLICY_INCOMPLETE", blockers
    )
    _validate_flag_group(
        evidence.reconciliation_flags,
        RECONCILIATION_FLAGS,
        "MPR14_RECONCILIATION_SELF_DECLARED",
        blockers,
    )
    _validate_flag_group(
        evidence.risk_flags, RISK_FLAGS, "MPR14_RISK_PROJECTION_UNSAFE", blockers
    )
    _validate_event_bound(evidence.maximum_in_memory_events, blockers)
    unique = tuple(_dedupe(blockers))
    return MPR14ControlReport(
        schema_version=SCHEMA_VERSION,
        state=(
            MPR14GateState.BLOCKED
            if unique
            else MPR14GateState.READY_FOR_DURABLE_CANARY_CONTROL
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_hashes(
    evidence: MPR14ControlEvidence,
    blockers: list[MPR14Violation],
) -> None:
    for field_name, value in (
        ("release_artifact_hash", evidence.release_artifact_hash),
        ("policy_generation_hash", evidence.policy_generation_hash),
        ("operator_registry_hash", evidence.operator_registry_hash),
        ("control_store_schema_hash", evidence.control_store_schema_hash),
        ("store_fence_token_hash", evidence.store_fence_token_hash),
        ("projection_head_hash", evidence.projection_head_hash),
    ):
        if not _is_hash(value):
            _add(blockers, "MPR14_BAD_HASH", f"{field_name} is not a strict sha256")


def _validate_findings(findings: Sequence[str], blockers: list[MPR14Violation]) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in set(findings)]
    if missing:
        _add(blockers, "MPR14_FINDINGS_INCOMPLETE", f"missing: {', '.join(missing)}")


def _validate_runtime_enablement(
    evidence: MPR14ControlEvidence,
    blockers: list[MPR14Violation],
) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "MPR14_LIVE_REQUESTED", "MPR-14 cannot enable live execution")
    if evidence.signer_requested:
        _add(blockers, "MPR14_SIGNER_REQUESTED", "MPR-14 cannot enable signing")
    if evidence.sender_requested:
        _add(blockers, "MPR14_SENDER_REQUESTED", "MPR-14 cannot enable sender IO")


def _validate_durable_state(
    evidence: MPR14ControlEvidence,
    blockers: list[MPR14Violation],
) -> None:
    _validate_flag_group(
        evidence.durable_flags,
        DURABLE_FLAGS,
        "MPR14_PROCESS_LOCAL_STATE",
        blockers,
    )
    if not evidence.process_local_authority_disabled:
        _add(
            blockers,
            "MPR14_PROCESS_LOCAL_AUTHORITY",
            "process-local canary authority remains enabled",
        )
    if evidence.restart_recovered_generation < 1:
        _add(blockers, "MPR14_BAD_RESTART_GENERATION", "restart generation is invalid")
    if evidence.failover_recovered_generation < evidence.restart_recovered_generation:
        _add(blockers, "MPR14_FAILOVER_REGRESSED", "failover generation regressed")


def _validate_operator_commands(
    commands: Sequence[MPR14OperatorCommand],
    blockers: list[MPR14Violation],
) -> None:
    if not commands:
        _add(blockers, "MPR14_NO_OPERATOR_COMMANDS", "operator evidence is required")
        return
    principals: set[str] = set()
    for command in commands:
        if command.principal_id.strip():
            principals.add(command.principal_id)
        else:
            _add(blockers, "MPR14_OPERATOR_PRINCIPAL_MISSING", "principal is required")
        if command.role not in AUTHORIZED_OPERATOR_ROLES:
            _add(
                blockers,
                "MPR14_OPERATOR_ROLE_INVALID",
                f"invalid role: {command.role}",
            )
        for value in (
            command.command_hash,
            command.signature_hash,
            command.registry_entry_hash,
        ):
            if not _is_hash(value):
                _add(
                    blockers,
                    "MPR14_OPERATOR_HASH_INVALID",
                    "operator hash is invalid",
                )
        if command.signature_scheme not in AUTHORIZED_SIGNATURE_SCHEMES:
            _add(
                blockers,
                "MPR14_OPERATOR_SIGNATURE_SCHEME",
                "signature scheme is invalid",
            )
        if command.session_fresh_until_ns <= command.command_observed_at_ns:
            _add(blockers, "MPR14_OPERATOR_SESSION_STALE", "operator session is stale")
        if command.command_generation < 1:
            _add(blockers, "MPR14_OPERATOR_GENERATION_INVALID", "generation is invalid")
        if not command.mfa_bound:
            _add(blockers, "MPR14_OPERATOR_MFA_MISSING", "operator command lacks MFA")
        if not command.canonical_command_bound:
            _add(
                blockers,
                "MPR14_OPERATOR_COMMAND_NOT_CANONICAL",
                "command is not canonical",
            )
        if not command.replay_nonce_consumed:
            _add(blockers, "MPR14_OPERATOR_REPLAY_NOT_FENCED", "nonce was not consumed")
    if len(principals) < 2:
        _add(
            blockers,
            "MPR14_OPERATOR_DUAL_CONTROL_MISSING",
            "two principals are required",
        )


def _validate_time_generation(
    evidence: MPR14ControlEvidence,
    blockers: list[MPR14Violation],
) -> None:
    ordered_names = ("review", "acknowledged", "armed", "decision", "reserve")
    ordered = tuple(
        evidence.causal_timestamps_ns.get(name, -1) for name in ordered_names
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in ordered
    ):
        _add(
            blockers,
            "MPR14_BAD_CAUSAL_TIME",
            "causal times must be non-negative integers",
        )
    if tuple(sorted(ordered)) != ordered:
        _add(
            blockers,
            "MPR14_CAUSAL_ORDER_BROKEN",
            "review <= ack <= arm <= decision <= reserve is required",
        )
    if evidence.max_decision_ttl_ns <= 0 or evidence.actual_decision_ttl_ns <= 0:
        _add(blockers, "MPR14_TTL_INVALID", "decision TTL must be positive")
    if evidence.actual_decision_ttl_ns > evidence.max_decision_ttl_ns:
        _add(blockers, "MPR14_TTL_UNBOUNDED", "decision TTL exceeds policy")
    if evidence.current_generation < 1 or evidence.revocation_generation < 1:
        _add(blockers, "MPR14_GENERATION_INVALID", "generations must be positive")
    if evidence.revocation_generation < evidence.current_generation:
        _add(blockers, "MPR14_REVOCATION_REGRESSED", "revocation generation regressed")
    if not evidence.rollback_or_kill_generation_bumped:
        _add(
            blockers,
            "MPR14_ROLLBACK_NO_GENERATION_BUMP",
            "rollback/kill must bump generation",
        )
    if not evidence.prior_decisions_revoked_on_generation_bump:
        _add(
            blockers,
            "MPR14_PRIOR_DECISIONS_NOT_REVOKED",
            "old decisions must be revoked",
        )


def _validate_flag_group(
    flags: Mapping[str, bool],
    required: Sequence[str],
    code: str,
    blockers: list[MPR14Violation],
) -> None:
    for flag in required:
        if flags.get(flag) is not True:
            _add(blockers, code, f"{flag} is required")


def _validate_event_bound(
    maximum_in_memory_events: int,
    blockers: list[MPR14Violation],
) -> None:
    if maximum_in_memory_events < 0:
        _add(blockers, "MPR14_EVENT_BOUND_INVALID", "event bound must be non-negative")
    if maximum_in_memory_events > 10_000:
        _add(
            blockers,
            "MPR14_EVENT_BOUND_TOO_LARGE",
            "event cache is not tightly bounded",
        )


def _add(blockers: list[MPR14Violation], code: str, message: str) -> None:
    blockers.append(MPR14Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPR14Violation]) -> Iterable[MPR14Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _stable_hash(value: MPR14ControlEvidence) -> str:
    payload = json.dumps(asdict(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _is_hash(value: str) -> bool:
    return isinstance(value, str) and HEX_64_RE.fullmatch(value) is not None
