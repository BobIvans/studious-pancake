"""Canonical sender-free execution truth and durable-state invariants.

MPR-SYS-02 binds one rooted candidate to one plan, one compiled message,
one exact simulation, one conservative reconciliation, and one durable terminal
attempt. The module is intentionally side-effect free: it does not open a
database, load keys, sign, submit, call RPC/Jito, or enable live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import IntEnum, StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

EXECUTION_TRUTH_SCHEMA_ID = "mpr-sys-02.execution-truth.v1"
EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID = "mpr-sys-02.execution-truth-evidence.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ZERO_HASH = "0" * 64


class ExecutionTruthError(ValueError):
    """Raised when execution or durable-state evidence fails closed."""


class ExecutionStage(IntEnum):
    ROOTED = 10
    PLANNED = 20
    COMPILED = 30
    SIMULATED = 40
    RECONCILED = 50
    TERMINAL = 60


class TerminalState(StrEnum):
    NONE = "none"
    SUCCESS = "success"
    FAILURE = "failure"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RootedCandidateRef:
    candidate_id: str
    candidate_truth_hash: str
    cluster_genesis_hash: str
    admission_hash: str
    root_slot: int

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        _digest(self.candidate_truth_hash, "candidate_truth_hash")
        _digest(self.cluster_genesis_hash, "cluster_genesis_hash")
        _digest(self.admission_hash, "admission_hash")
        _non_negative_int(self.root_slot, "root_slot")


@dataclass(frozen=True, slots=True)
class PlanRef:
    plan_hash: str
    candidate_truth_hash: str
    principal_lamports: int
    expires_block_height: int

    def __post_init__(self) -> None:
        _digest(self.plan_hash, "plan_hash")
        _digest(self.candidate_truth_hash, "candidate_truth_hash")
        _positive_int(self.principal_lamports, "principal_lamports")
        _positive_int(self.expires_block_height, "expires_block_height")


@dataclass(frozen=True, slots=True)
class CompiledMessageRef:
    message_hash: str
    plan_hash: str
    blockhash: str
    last_valid_block_height: int
    alt_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.message_hash, "message_hash")
        _digest(self.plan_hash, "plan_hash")
        _text(self.blockhash, "blockhash")
        _positive_int(self.last_valid_block_height, "last_valid_block_height")
        object.__setattr__(
            self,
            "alt_hashes",
            _unique_digests(self.alt_hashes, "alt_hash"),
        )


@dataclass(frozen=True, slots=True)
class SimulationRef:
    simulation_hash: str
    message_hash: str
    context_slot: int
    fee_lamports: int
    units_consumed: int
    logs_hash: str
    successful: bool

    def __post_init__(self) -> None:
        _digest(self.simulation_hash, "simulation_hash")
        _digest(self.message_hash, "message_hash")
        _non_negative_int(self.context_slot, "context_slot")
        _non_negative_int(self.fee_lamports, "fee_lamports")
        _non_negative_int(self.units_consumed, "units_consumed")
        _digest(self.logs_hash, "logs_hash")
        _strict_bool(self.successful, "successful")


@dataclass(frozen=True, slots=True)
class ReconciliationRef:
    reconciliation_hash: str
    simulation_hash: str
    message_hash: str
    principal_lamports: int
    gross_proceeds_lamports: int
    flash_repayment_lamports: int
    network_fee_lamports: int
    rent_delta_lamports: int
    tip_lamports: int
    uncertainty_buffer_lamports: int
    conservative_surplus_lamports: int

    def __post_init__(self) -> None:
        _digest(self.reconciliation_hash, "reconciliation_hash")
        _digest(self.simulation_hash, "simulation_hash")
        _digest(self.message_hash, "message_hash")
        for name in (
            "principal_lamports",
            "gross_proceeds_lamports",
            "flash_repayment_lamports",
            "network_fee_lamports",
            "rent_delta_lamports",
            "tip_lamports",
            "uncertainty_buffer_lamports",
        ):
            _non_negative_int(getattr(self, name), name)
        _strict_int(
            self.conservative_surplus_lamports,
            "conservative_surplus_lamports",
        )
        expected = (
            self.gross_proceeds_lamports
            - self.principal_lamports
            - self.flash_repayment_lamports
            - self.network_fee_lamports
            - self.rent_delta_lamports
            - self.tip_lamports
            - self.uncertainty_buffer_lamports
        )
        if self.conservative_surplus_lamports != expected:
            raise ExecutionTruthError("MPR_SYS_02_RECONCILIATION_ARITHMETIC_MISMATCH")


@dataclass(frozen=True, slots=True)
class DurableAttemptRef:
    attempt_id: str
    generation: int
    lifecycle_revision: int
    stage: ExecutionStage
    terminal_state: TerminalState
    writer_fence: int
    event_head_hash: str
    idempotency_hash: str
    reservation_hash: str
    candidate_truth_hash: str
    plan_hash: str | None = None
    message_hash: str | None = None
    simulation_hash: str | None = None
    reconciliation_hash: str | None = None
    ambiguity_quarantined: bool = False

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        _positive_int(self.generation, "generation")
        _positive_int(self.lifecycle_revision, "lifecycle_revision")
        if not isinstance(self.stage, ExecutionStage):
            raise ExecutionTruthError("MPR_SYS_02_STAGE_REQUIRED")
        if not isinstance(self.terminal_state, TerminalState):
            raise ExecutionTruthError("MPR_SYS_02_TERMINAL_STATE_REQUIRED")
        _positive_int(self.writer_fence, "writer_fence")
        _digest(self.event_head_hash, "event_head_hash")
        _digest(self.idempotency_hash, "idempotency_hash")
        _digest(self.reservation_hash, "reservation_hash")
        _digest(self.candidate_truth_hash, "candidate_truth_hash")
        for name in (
            "plan_hash",
            "message_hash",
            "simulation_hash",
            "reconciliation_hash",
        ):
            value = getattr(self, name)
            if value is not None:
                _digest(value, name)
        _strict_bool(self.ambiguity_quarantined, "ambiguity_quarantined")
        self._validate_stage_fields()

    def _validate_stage_fields(self) -> None:
        if self.stage is ExecutionStage.TERMINAL:
            required = (
                (self.plan_hash, "plan_hash"),
                (self.message_hash, "message_hash"),
                (self.simulation_hash, "simulation_hash"),
            )
        else:
            required_by_stage = (
                (ExecutionStage.PLANNED, self.plan_hash, "plan_hash"),
                (ExecutionStage.COMPILED, self.message_hash, "message_hash"),
                (
                    ExecutionStage.SIMULATED,
                    self.simulation_hash,
                    "simulation_hash",
                ),
                (
                    ExecutionStage.RECONCILED,
                    self.reconciliation_hash,
                    "reconciliation_hash",
                ),
            )
            required = tuple(
                (value, name)
                for minimum, value, name in required_by_stage
                if self.stage >= minimum
            )
        for value, name in required:
            if value is None:
                raise ExecutionTruthError(f"MPR_SYS_02_STAGE_REQUIRES_{name.upper()}")
        if self.stage is ExecutionStage.TERMINAL:
            if self.terminal_state is TerminalState.NONE:
                raise ExecutionTruthError("MPR_SYS_02_TERMINAL_OUTCOME_REQUIRED")
        elif self.terminal_state is not TerminalState.NONE:
            raise ExecutionTruthError("MPR_SYS_02_NON_TERMINAL_HAS_OUTCOME")
        if self.terminal_state is TerminalState.SUCCESS:
            if self.reconciliation_hash is None:
                raise ExecutionTruthError("MPR_SYS_02_SUCCESS_REQUIRES_RECONCILIATION")
            if self.ambiguity_quarantined:
                raise ExecutionTruthError("MPR_SYS_02_SUCCESS_CANNOT_BE_AMBIGUOUS")
        if self.terminal_state is TerminalState.AMBIGUOUS:
            if not self.ambiguity_quarantined:
                raise ExecutionTruthError(
                    "MPR_SYS_02_AMBIGUITY_MUST_QUARANTINE_CAPITAL"
                )
        elif self.ambiguity_quarantined:
            raise ExecutionTruthError(
                "MPR_SYS_02_QUARANTINE_REQUIRES_AMBIGUOUS_OUTCOME"
            )


@dataclass(frozen=True, slots=True)
class ExecutionTruthBundle:
    rooted: RootedCandidateRef
    plan: PlanRef
    compiled: CompiledMessageRef
    simulation: SimulationRef
    reconciliation: ReconciliationRef | None
    durable: DurableAttemptRef
    sender_free: bool = True
    live_enabled: bool = False

    def __post_init__(self) -> None:
        for value, expected, reason in (
            (self.rooted, RootedCandidateRef, "ROOTED_REFERENCE"),
            (self.plan, PlanRef, "PLAN_REFERENCE"),
            (self.compiled, CompiledMessageRef, "COMPILED_REFERENCE"),
            (self.simulation, SimulationRef, "SIMULATION_REFERENCE"),
            (self.durable, DurableAttemptRef, "DURABLE_REFERENCE"),
        ):
            if not isinstance(value, expected):
                raise ExecutionTruthError(f"MPR_SYS_02_{reason}_REQUIRED")
        if self.reconciliation is not None and not isinstance(
            self.reconciliation,
            ReconciliationRef,
        ):
            raise ExecutionTruthError("MPR_SYS_02_RECONCILIATION_REFERENCE_REQUIRED")
        _strict_bool(self.sender_free, "sender_free")
        _strict_bool(self.live_enabled, "live_enabled")
        if not self.sender_free or self.live_enabled:
            raise ExecutionTruthError("MPR_SYS_02_LIVE_OR_SENDER_FORBIDDEN")
        self._validate_hash_chain()
        self._validate_terminal_truth()

    def _validate_hash_chain(self) -> None:
        if self.plan.candidate_truth_hash != self.rooted.candidate_truth_hash:
            raise ExecutionTruthError("MPR_SYS_02_PLAN_CANDIDATE_MISMATCH")
        if self.compiled.plan_hash != self.plan.plan_hash:
            raise ExecutionTruthError("MPR_SYS_02_MESSAGE_PLAN_MISMATCH")
        if self.compiled.last_valid_block_height > self.plan.expires_block_height:
            raise ExecutionTruthError("MPR_SYS_02_MESSAGE_OUTLIVES_CANDIDATE")
        if self.simulation.message_hash != self.compiled.message_hash:
            raise ExecutionTruthError("MPR_SYS_02_SIMULATION_MESSAGE_MISMATCH")
        if self.simulation.context_slot < self.rooted.root_slot:
            raise ExecutionTruthError("MPR_SYS_02_SIMULATION_PRECEDES_ROOTED_CANDIDATE")
        if self.durable.candidate_truth_hash != self.rooted.candidate_truth_hash:
            raise ExecutionTruthError("MPR_SYS_02_DURABLE_CANDIDATE_MISMATCH")
        if self.durable.plan_hash != self.plan.plan_hash:
            raise ExecutionTruthError("MPR_SYS_02_DURABLE_PLAN_MISMATCH")
        if self.durable.message_hash != self.compiled.message_hash:
            raise ExecutionTruthError("MPR_SYS_02_DURABLE_MESSAGE_MISMATCH")
        if self.durable.simulation_hash != self.simulation.simulation_hash:
            raise ExecutionTruthError("MPR_SYS_02_DURABLE_SIMULATION_MISMATCH")
        if self.reconciliation is not None:
            if self.reconciliation.simulation_hash != self.simulation.simulation_hash:
                raise ExecutionTruthError(
                    "MPR_SYS_02_RECONCILIATION_SIMULATION_MISMATCH"
                )
            if self.reconciliation.message_hash != self.compiled.message_hash:
                raise ExecutionTruthError("MPR_SYS_02_RECONCILIATION_MESSAGE_MISMATCH")
            if self.reconciliation.principal_lamports != self.plan.principal_lamports:
                raise ExecutionTruthError(
                    "MPR_SYS_02_RECONCILIATION_PRINCIPAL_MISMATCH"
                )
            if (
                self.durable.reconciliation_hash
                != self.reconciliation.reconciliation_hash
            ):
                raise ExecutionTruthError("MPR_SYS_02_DURABLE_RECONCILIATION_MISMATCH")
        elif self.durable.reconciliation_hash is not None:
            raise ExecutionTruthError(
                "MPR_SYS_02_DURABLE_RECONCILIATION_WITHOUT_EVIDENCE"
            )

    def _validate_terminal_truth(self) -> None:
        if self.durable.stage is not ExecutionStage.TERMINAL:
            raise ExecutionTruthError("MPR_SYS_02_TERMINAL_ATTEMPT_REQUIRED")
        state = self.durable.terminal_state
        if state is TerminalState.SUCCESS:
            if not self.simulation.successful or self.reconciliation is None:
                raise ExecutionTruthError(
                    "MPR_SYS_02_SUCCESS_REQUIRES_SUCCESSFUL_SIMULATION"
                )
            if self.reconciliation.conservative_surplus_lamports <= 0:
                raise ExecutionTruthError(
                    "MPR_SYS_02_SUCCESS_REQUIRES_POSITIVE_SURPLUS"
                )
        if state is TerminalState.FAILURE and self.simulation.successful:
            if self.reconciliation is None:
                raise ExecutionTruthError(
                    "MPR_SYS_02_POST_SIMULATION_FAILURE_NEEDS_RECONCILIATION"
                )
        if state is TerminalState.CANCELLED:
            raise ExecutionTruthError(
                "MPR_SYS_02_POST_COMPILE_CANCELLATION_IS_AMBIGUOUS"
            )

    @property
    def bundle_hash(self) -> str:
        return _hash_json(asdict(self))


def validate_transition(
    previous: DurableAttemptRef,
    current: DurableAttemptRef,
) -> None:
    """Validate one append-only lifecycle transition."""

    if previous.attempt_id != current.attempt_id:
        raise ExecutionTruthError("MPR_SYS_02_ATTEMPT_ID_CHANGED")
    if previous.generation != current.generation:
        raise ExecutionTruthError("MPR_SYS_02_GENERATION_CHANGED")
    if previous.writer_fence != current.writer_fence:
        raise ExecutionTruthError("MPR_SYS_02_WRITER_FENCE_CHANGED")
    if previous.candidate_truth_hash != current.candidate_truth_hash:
        raise ExecutionTruthError("MPR_SYS_02_CANDIDATE_IDENTITY_CHANGED")
    if previous.reservation_hash != current.reservation_hash:
        raise ExecutionTruthError("MPR_SYS_02_RESERVATION_IDENTITY_CHANGED")
    if current.lifecycle_revision != previous.lifecycle_revision + 1:
        raise ExecutionTruthError("MPR_SYS_02_REVISION_NOT_CONTIGUOUS")
    if previous.stage is ExecutionStage.TERMINAL:
        raise ExecutionTruthError("MPR_SYS_02_TERMINAL_STATE_IS_IMMUTABLE")
    if current.stage < previous.stage:
        raise ExecutionTruthError("MPR_SYS_02_STAGE_REGRESSION")
    for name in (
        "plan_hash",
        "message_hash",
        "simulation_hash",
        "reconciliation_hash",
    ):
        old = getattr(previous, name)
        new = getattr(current, name)
        if old is not None and old != new:
            raise ExecutionTruthError(f"MPR_SYS_02_{name.upper()}_MUTATED")


def terminalize_ambiguous(
    attempt: DurableAttemptRef,
) -> DurableAttemptRef:
    """Produce the only safe terminal outcome for an unknown side effect."""

    return replace(
        attempt,
        lifecycle_revision=attempt.lifecycle_revision + 1,
        stage=ExecutionStage.TERMINAL,
        terminal_state=TerminalState.AMBIGUOUS,
        ambiguity_quarantined=True,
    )


def evaluate_bundle(bundle: ExecutionTruthBundle) -> Mapping[str, object]:
    """Return deterministic repository-internal qualification evidence."""

    return {
        "schema_version": EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID,
        "accepted": True,
        "execution_truth_ready": True,
        "durable_terminal_recorded": True,
        "sender_free": True,
        "live_enabled": False,
        "production_ready": False,
        "bundle_hash": bundle.bundle_hash,
        "attempt_id": bundle.durable.attempt_id,
        "terminal_state": bundle.durable.terminal_state.value,
        "reason_codes": (
            "MPR_SYS_02_REPOSITORY_CONTRACT_ACCEPTED",
            "MPR_SYS_02_EXTERNAL_RUNTIME_CUTOVER_NOT_CLAIMED",
        ),
    }


def _canonicalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(raw)
            for key, raw in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (ExecutionStage, TerminalState)):
        return value.value
    if isinstance(value, float):
        raise ExecutionTruthError("MPR_SYS_02_FLOAT_NOT_CANONICAL")
    return value


def _hash_json(value: object) -> str:
    payload = json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionTruthError(f"{name} is required")
    return value.strip()


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ExecutionTruthError(f"{name} must be lowercase sha256")
    if value == _ZERO_HASH:
        raise ExecutionTruthError(f"{name} cannot be placeholder digest")
    return value


def _strict_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionTruthError(f"{name} must be a non-bool integer")


def _positive_int(value: int, name: str) -> None:
    _strict_int(value, name)
    if value <= 0:
        raise ExecutionTruthError(f"{name} must be positive")


def _non_negative_int(value: int, name: str) -> None:
    _strict_int(value, name)
    if value < 0:
        raise ExecutionTruthError(f"{name} must be non-negative")


def _strict_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise ExecutionTruthError(f"{name} must be bool")


def _unique_digests(
    values: Sequence[str],
    name: str,
) -> tuple[str, ...]:
    normalized = tuple(_digest(value, name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ExecutionTruthError(f"duplicate {name}")
    return normalized


__all__ = [
    "CompiledMessageRef",
    "DurableAttemptRef",
    "EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID",
    "EXECUTION_TRUTH_SCHEMA_ID",
    "ExecutionStage",
    "ExecutionTruthBundle",
    "ExecutionTruthError",
    "PlanRef",
    "ReconciliationRef",
    "RootedCandidateRef",
    "SimulationRef",
    "TerminalState",
    "evaluate_bundle",
    "terminalize_ambiguous",
    "validate_transition",
]
