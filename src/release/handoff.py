"""Deterministic bounded release handoff state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class HandoffPhase(StrEnum):
    PREFLIGHT = "preflight"
    ADMISSION_STOPPED = "admission_stopped"
    DRAINED = "drained"
    BACKED_UP = "backed_up"
    MIGRATED = "migrated"
    ACTIVATED = "activated"
    VERIFIED = "verified"
    RESUMED = "resumed"
    ABORTED = "aborted"


_ALLOWED: dict[HandoffPhase, frozenset[HandoffPhase]] = {
    HandoffPhase.PREFLIGHT: frozenset(
        {HandoffPhase.ADMISSION_STOPPED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.ADMISSION_STOPPED: frozenset(
        {HandoffPhase.DRAINED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.DRAINED: frozenset(
        {HandoffPhase.BACKED_UP, HandoffPhase.ABORTED}
    ),
    HandoffPhase.BACKED_UP: frozenset(
        {HandoffPhase.MIGRATED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.MIGRATED: frozenset(
        {HandoffPhase.ACTIVATED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.ACTIVATED: frozenset(
        {HandoffPhase.VERIFIED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.VERIFIED: frozenset(
        {HandoffPhase.RESUMED, HandoffPhase.ABORTED}
    ),
    HandoffPhase.RESUMED: frozenset(),
    HandoffPhase.ABORTED: frozenset(),
}


class InvalidHandoffTransition(ValueError):
    """A release handoff transition violated the deterministic sequence."""


@dataclass(frozen=True, slots=True)
class HandoffState:
    operation_id: str
    source_generation: str
    target_generation: str
    phase: HandoffPhase = HandoffPhase.PREFLIGHT
    revision: int = 0

    def transition(self, target: HandoffPhase) -> "HandoffState":
        if target not in _ALLOWED[self.phase]:
            raise InvalidHandoffTransition(
                f"illegal handoff transition: {self.phase.value} -> {target.value}"
            )
        return replace(self, phase=target, revision=self.revision + 1)
