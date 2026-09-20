"""Generation-fenced release upgrade and rollback contracts."""

from .fencing import GenerationFenceError, GenerationFenceStore, StaleGenerationError
from .handoff import HandoffPhase, HandoffState, InvalidHandoffTransition
from .identity import ReleaseGenerationIdentity
from .rollback import RollbackClass, RollbackDecision, decide_rollback

__all__ = [
    "GenerationFenceError",
    "GenerationFenceStore",
    "StaleGenerationError",
    "HandoffPhase",
    "HandoffState",
    "InvalidHandoffTransition",
    "ReleaseGenerationIdentity",
    "RollbackClass",
    "RollbackDecision",
    "decide_rollback",
]
