"""SX-11 async/cross-domain settlement state machine (SIGNAL_ONLY, ASYNC).

Deterministic offline model of async settlement across domains (bridges,
IBC, shared sequencers, CEX settlement, TON async). This module is
SIGNAL_ONLY research and its exclusions are part of its contract:

- it executes no bridge calls, no relaying, no withdrawals, no signing
  and no transaction submission of any kind, and imports no execution or
  sender module;
- it produces settlement-state signals and inventory-lock accounting for
  research only (no live authority, no production promotion);
- cross-domain and shared-sequencer paths are never classified
  LOCAL_ATOMIC by default: the classification guard raises unless the
  explicit ``single_tx_settlement_proven=True`` input flag is supplied,
  and that flag is absent in research usage, so the guard always raises
  there;
- unknown finality parameters (``reorg_depth``,
  ``message_latency_bounds``) stay ``None`` and are never treated as
  zero ("unknown is not zero");
- inventory capital is locked from INITIATED until FINALIZED or
  RECOVERED, is released exactly once (double release raises), and
  total locked capital is conserved with no phantom capacity.

Family: BASIS-ASYNC (SIGNAL_ONLY) per
docs/strategy-expansion/2026-11-14/STRATEGY_ACCEPTANCE_MATRIX.json.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Mapping, Sequence

from .core import (
    EvolutionError,
    require_nonnegative,
    require_positive,
    require_text,
)

EXECUTION_CLASS = "SIGNAL_ONLY_ASYNC"
LIVE_EXECUTION_ENABLED = False


class SettlementError(EvolutionError):
    """Typed settlement error with a stable code and detail."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.detail = require_text(detail, "detail")


class InvalidTransitionError(SettlementError):
    """A transition outside the deterministic settlement transition table."""


class DoubleReleaseError(SettlementError):
    """An inventory lock was released more than once."""


class AtomicityClassificationError(SettlementError):
    """An async path was mislabeled LOCAL_ATOMIC without single-tx proof."""


class SettlementState(StrEnum):
    INITIATED = "INITIATED"
    CONFIRMED_LOCAL = "CONFIRMED_LOCAL"
    RELAYED = "RELAYED"
    FINALIZED = "FINALIZED"
    REORGED = "REORGED"
    TIMEOUT = "TIMEOUT"
    STRANDED_INVENTORY = "STRANDED_INVENTORY"
    RECOVERED = "RECOVERED"


ALLOWED_TRANSITIONS: Mapping[SettlementState, tuple[SettlementState, ...]] = {
    SettlementState.INITIATED: (
        SettlementState.CONFIRMED_LOCAL,
        SettlementState.REORGED,
        SettlementState.TIMEOUT,
    ),
    SettlementState.CONFIRMED_LOCAL: (
        SettlementState.RELAYED,
        SettlementState.REORGED,
        SettlementState.TIMEOUT,
    ),
    SettlementState.RELAYED: (
        SettlementState.FINALIZED,
        SettlementState.REORGED,
        SettlementState.TIMEOUT,
    ),
    SettlementState.REORGED: (
        SettlementState.STRANDED_INVENTORY,
        SettlementState.RECOVERED,
    ),
    SettlementState.TIMEOUT: (
        SettlementState.STRANDED_INVENTORY,
        SettlementState.RECOVERED,
    ),
    SettlementState.STRANDED_INVENTORY: (SettlementState.RECOVERED,),
    SettlementState.FINALIZED: (),
    SettlementState.RECOVERED: (),
}

RELEASE_STATES: tuple[SettlementState, ...] = (
    SettlementState.FINALIZED,
    SettlementState.RECOVERED,
)


@dataclass(frozen=True)
class SettlementDomain:
    """Settlement domain; unknown reorg depth / latency stay None."""

    chain_id: str
    finality_rule: str
    reorg_depth: int | None = None
    message_latency_bounds: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        require_text(self.chain_id, "chain_id")
        require_text(self.finality_rule, "finality_rule")
        if self.reorg_depth is not None:
            require_nonnegative(self.reorg_depth, "reorg_depth")
        if self.message_latency_bounds is not None:
            low, high = self.message_latency_bounds
            require_nonnegative(low, "latency_low")
            require_nonnegative(high, "latency_high")
            if high < low:
                raise EvolutionError("LATENCY_BOUNDS_INVALID")


@dataclass(frozen=True)
class SettlementTransition:
    """One applied transition, recorded deterministically."""

    step: int
    from_state: SettlementState
    to_state: SettlementState
    reason: str

    def __post_init__(self) -> None:
        require_nonnegative(self.step, "step")
        if not isinstance(self.from_state, SettlementState):
            raise EvolutionError("TRANSITION_STATE_UNTYPED")
        if not isinstance(self.to_state, SettlementState):
            raise EvolutionError("TRANSITION_STATE_UNTYPED")
        require_text(self.reason, "reason")


@dataclass(frozen=True)
class InventoryLock:
    """Capital locked from INITIATED until FINALIZED or RECOVERED.

    The frozen snapshot is structurally single-release: ``RELEASED``
    requires exactly one release record; ``LOCKED`` forbids one. Amounts
    are conserved: the locked amount never changes on release.
    """

    position_id: str
    amount_atoms: int
    source_chain_id: str
    target_chain_id: str
    status: str
    released_at_step: int | None = None
    release_reason: str | None = None
    release_count: int = 0

    def __post_init__(self) -> None:
        require_text(self.position_id, "position_id")
        require_positive(self.amount_atoms, "amount_atoms")
        require_text(self.source_chain_id, "source_chain_id")
        require_text(self.target_chain_id, "target_chain_id")
        if self.status not in {"LOCKED", "RELEASED"}:
            raise EvolutionError("LOCK_STATUS_INVALID")
        if self.status == "RELEASED":
            if (
                self.release_count != 1
                or self.released_at_step is None
                or self.release_reason is None
            ):
                raise EvolutionError("LOCK_RELEASE_RECORD_INVALID")
            require_nonnegative(self.released_at_step, "released_at_step")
        elif (
            self.release_count != 0
            or self.released_at_step is not None
            or (self.release_reason is not None)
        ):
            raise EvolutionError("LOCK_STATE_INVALID")

    @property
    def is_released(self) -> bool:
        return self.status == "RELEASED"


def assert_settlement_transition(
    current: SettlementState, target: SettlementState
) -> None:
    """Deterministic transition guard; invalid transitions are typed."""
    if target not in ALLOWED_TRANSITIONS.get(current, ()):
        raise InvalidTransitionError(
            "INVALID_TRANSITION",
            f"{current.value}->{target.value}",
        )


class AsyncSettlementMachine:
    """Deterministic settlement state machine over one inventory position."""

    def __init__(
        self,
        *,
        position_id: str,
        source_domain: SettlementDomain,
        target_domain: SettlementDomain,
        amount_atoms: int,
    ) -> None:
        self._position_id = require_text(position_id, "position_id")
        if not isinstance(source_domain, SettlementDomain) or not isinstance(
            target_domain, SettlementDomain
        ):
            raise SettlementError("DOMAIN_UNTYPED", "domains must be SettlementDomain")
        self._source_domain = source_domain
        self._target_domain = target_domain
        self._amount_atoms = require_positive(amount_atoms, "amount_atoms")
        self._state = SettlementState.INITIATED
        self._step = 0
        self._lock = InventoryLock(
            position_id=self._position_id,
            amount_atoms=self._amount_atoms,
            source_chain_id=source_domain.chain_id,
            target_chain_id=target_domain.chain_id,
            status="LOCKED",
        )
        self._visited: list[SettlementState] = [SettlementState.INITIATED]
        self._transitions: list[SettlementTransition] = []

    @property
    def position_id(self) -> str:
        return self._position_id

    @property
    def state(self) -> SettlementState:
        return self._state

    @property
    def step(self) -> int:
        return self._step

    @property
    def amount_atoms(self) -> int:
        return self._amount_atoms

    @property
    def source_domain(self) -> SettlementDomain:
        return self._source_domain

    @property
    def target_domain(self) -> SettlementDomain:
        return self._target_domain

    @property
    def visited_states(self) -> tuple[SettlementState, ...]:
        return tuple(self._visited)

    @property
    def transitions(self) -> tuple[SettlementTransition, ...]:
        return tuple(self._transitions)

    @property
    def recovery_transitions(self) -> tuple[SettlementTransition, ...]:
        return tuple(
            transition
            for transition in self._transitions
            if transition.to_state
            in {SettlementState.STRANDED_INVENTORY, SettlementState.RECOVERED}
        )

    def lock_snapshot(self) -> InventoryLock:
        return self._lock

    def transition(self, target: SettlementState, *, reason: str) -> InventoryLock:
        """Apply one validated transition; mutations happen only after validation."""
        if not isinstance(target, SettlementState):
            raise SettlementError(
                "TARGET_STATE_UNTYPED", "target must be SettlementState"
            )
        reason_text = require_text(reason, "reason")
        previous = self._state
        assert_settlement_transition(previous, target)
        self._step += 1
        if target in RELEASE_STATES:
            if self._lock.is_released:
                raise DoubleReleaseError(
                    "LOCK_DOUBLE_RELEASE",
                    f"position={self._position_id} already released",
                )
            self._lock = replace(
                self._lock,
                status="RELEASED",
                released_at_step=self._step,
                release_reason=reason_text,
                release_count=1,
            )
        self._state = target
        self._visited.append(target)
        self._transitions.append(
            SettlementTransition(
                step=self._step,
                from_state=previous,
                to_state=target,
                reason=reason_text,
            )
        )
        return self._lock

    def observe_reorg(self, *, reason: str) -> InventoryLock:
        return self.transition(SettlementState.REORGED, reason=reason)

    def observe_timeout(self, *, reason: str) -> InventoryLock:
        return self.transition(SettlementState.TIMEOUT, reason=reason)

    def release_lock(self, *, reason: str) -> InventoryLock:
        """Explicit release; allowed only once and only in a terminal state."""
        reason_text = require_text(reason, "reason")
        if self._state not in RELEASE_STATES:
            raise SettlementError(
                "LOCK_NOT_TERMINAL",
                f"position={self._position_id} state={self._state.value}",
            )
        if self._lock.is_released:
            raise DoubleReleaseError(
                "LOCK_DOUBLE_RELEASE",
                f"position={self._position_id} released_at_step={self._lock.released_at_step}",
            )
        self._lock = replace(
            self._lock,
            status="RELEASED",
            released_at_step=self._step,
            release_reason=reason_text,
            release_count=1,
        )
        return self._lock


KNOWN_SETTLEMENT_MECHANISMS: tuple[str, ...] = (
    "BRIDGE",
    "IBC",
    "SHARED_SEQUENCER",
    "CEX_SETTLEMENT",
    "TON_ASYNC",
    "SINGLE_DOMAIN",
)


@dataclass(frozen=True)
class SettlementPath:
    """A typed cross-domain settlement path used for execution-class guard."""

    path_id: str
    source_domain: SettlementDomain
    target_domain: SettlementDomain
    settlement_mechanism: str

    def __post_init__(self) -> None:
        require_text(self.path_id, "path_id")
        if not isinstance(self.source_domain, SettlementDomain) or not isinstance(
            self.target_domain, SettlementDomain
        ):
            raise SettlementError("DOMAIN_UNTYPED", "domains must be SettlementDomain")
        if self.settlement_mechanism not in KNOWN_SETTLEMENT_MECHANISMS:
            raise SettlementError(
                "MECHANISM_UNKNOWN",
                f"mechanism={self.settlement_mechanism}",
            )


def classify_execution_class(
    path: SettlementPath,
    *,
    claimed_class: str | None = None,
    single_tx_settlement_proven: bool = False,
) -> str:
    """Guard against mislabeling async paths as LOCAL_ATOMIC.

    Without a claim, every async path is honestly classified
    ``SIGNAL_ONLY_ASYNC``. Claiming LOCAL_ATOMIC raises
    ``AtomicityClassificationError`` unless the explicit
    ``single_tx_settlement_proven=True`` flag is supplied; in research
    usage that flag is always absent, so the guard always raises there.
    """
    if claimed_class is None:
        return EXECUTION_CLASS
    claimed = require_text(claimed_class, "claimed_class")
    if claimed == "LOCAL_ATOMIC":
        if not single_tx_settlement_proven:
            raise AtomicityClassificationError(
                "ATOMIC_MISLABEL_UNPROVEN",
                "LOCAL_ATOMIC requires single_tx_settlement_proven=True; "
                "cross-chain/shared-sequencer paths are never local atomic by default",
            )
        return "LOCAL_ATOMIC"
    raise SettlementError("CLAIMED_CLASS_UNKNOWN", f"claimed_class={claimed}")


@dataclass(frozen=True)
class SettlementAction:
    """One planned state transition used by deterministic fault injection."""

    target: SettlementState
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, SettlementState):
            raise SettlementError(
                "TARGET_STATE_UNTYPED", "target must be SettlementState"
            )
        require_text(self.reason, "reason")


def _inject_fault_at(
    plan: Sequence[SettlementAction],
    step: int,
    fault_state: SettlementState,
    reason: str,
) -> tuple[SettlementAction, ...]:
    actions = tuple(plan)
    step_value = require_nonnegative(step, "step")
    if step_value > len(actions):
        raise SettlementError(
            "INJECT_STEP_OUT_OF_RANGE",
            f"step={step_value} plan_size={len(actions)}",
        )
    fault = SettlementAction(target=fault_state, reason=reason)
    return actions[:step_value] + (fault,) + actions[step_value:]


def inject_reorg_at(
    plan: Sequence[SettlementAction], step: int
) -> tuple[SettlementAction, ...]:
    """Deterministically inject a REORGED fault action before plan index ``step``."""
    return _inject_fault_at(plan, step, SettlementState.REORGED, "injected_reorg_fault")


def inject_timeout_at(
    plan: Sequence[SettlementAction], step: int
) -> tuple[SettlementAction, ...]:
    """Deterministically inject a TIMEOUT fault action before plan index ``step``."""
    return _inject_fault_at(
        plan, step, SettlementState.TIMEOUT, "injected_timeout_fault"
    )


@dataclass(frozen=True)
class SettlementTrace:
    """Deterministic result of driving a machine over a plan."""

    position_id: str
    visited_states: tuple[SettlementState, ...]
    transitions: tuple[SettlementTransition, ...]
    final_state: SettlementState
    lock_released: bool
    lock_release_step: int | None
    stopped_reason: str
    remaining_actions: tuple[SettlementAction, ...]

    def __post_init__(self) -> None:
        require_text(self.position_id, "position_id")
        if not isinstance(self.final_state, SettlementState):
            raise EvolutionError("TRACE_STATE_UNTYPED")
        for state in self.visited_states:
            if not isinstance(state, SettlementState):
                raise EvolutionError("TRACE_STATE_UNTYPED")
        for transition in self.transitions:
            if not isinstance(transition, SettlementTransition):
                raise EvolutionError("TRACE_TRANSITION_UNTYPED")
        for action in self.remaining_actions:
            if not isinstance(action, SettlementAction):
                raise EvolutionError("TRACE_ACTION_UNTYPED")
        if self.stopped_reason not in {"PLAN_COMPLETE", "INVALID_TRANSITION"}:
            raise EvolutionError("TRACE_STOP_REASON_INVALID")


def execute_settlement_plan(
    machine: AsyncSettlementMachine,
    plan: Sequence[SettlementAction],
) -> SettlementTrace:
    """Drive the machine over the plan; stop at the first invalid transition.

    The machine is unchanged when a transition is rejected (validation
    happens before mutation), so the trace records the first not-applied
    action onward in ``remaining_actions``.
    """
    actions = tuple(plan)
    stopped_reason = "PLAN_COMPLETE"
    remaining: list[SettlementAction] = []
    for offset, action in enumerate(actions):
        if not isinstance(action, SettlementAction):
            raise SettlementError("ACTION_UNTYPED", f"index={offset}")
        try:
            machine.transition(action.target, reason=action.reason)
        except InvalidTransitionError:
            stopped_reason = "INVALID_TRANSITION"
            remaining = list(actions[offset:])
            break
    lock = machine.lock_snapshot()
    return SettlementTrace(
        position_id=machine.position_id,
        visited_states=machine.visited_states,
        transitions=machine.transitions,
        final_state=machine.state,
        lock_released=lock.is_released,
        lock_release_step=lock.released_at_step,
        stopped_reason=stopped_reason,
        remaining_actions=tuple(remaining),
    )


class CapitalLockLedger:
    """Aggregate inventory locks; registered capital is conserved exactly.

    Every lock is either fully locked or fully released with the same
    amount, so ``registered == released + outstanding`` always holds and
    no phantom capacity can be created (duplicate registration raises).
    """

    def __init__(self) -> None:
        self._machines: dict[str, AsyncSettlementMachine] = {}

    def register(self, machine: AsyncSettlementMachine) -> InventoryLock:
        if not isinstance(machine, AsyncSettlementMachine):
            raise SettlementError(
                "MACHINE_UNTYPED", "register expects an AsyncSettlementMachine"
            )
        if machine.position_id in self._machines:
            raise SettlementError(
                "LOCK_DUPLICATE_REGISTRATION",
                f"position={machine.position_id} already registered",
            )
        self._machines[machine.position_id] = machine
        return machine.lock_snapshot()

    def conservation_report(self) -> dict[str, int]:
        total_registered = 0
        total_released = 0
        total_outstanding = 0
        released_locks = 0
        for position_id, machine in sorted(self._machines.items()):
            lock = machine.lock_snapshot()
            if lock.position_id != position_id:
                raise SettlementError(
                    "CAPITAL_CONSERVATION_BROKEN",
                    f"position id drift for {position_id}",
                )
            total_registered += lock.amount_atoms
            if lock.is_released:
                total_released += lock.amount_atoms
                released_locks += 1
            else:
                total_outstanding += lock.amount_atoms
        if total_registered != total_released + total_outstanding:
            raise SettlementError(
                "CAPITAL_CONSERVATION_BROKEN",
                f"registered={total_registered} released={total_released} "
                f"outstanding={total_outstanding}",
            )
        return {
            "lock_count": len(self._machines),
            "released_lock_count": released_locks,
            "total_registered_atoms": total_registered,
            "total_released_atoms": total_released,
            "total_outstanding_atoms": total_outstanding,
        }
