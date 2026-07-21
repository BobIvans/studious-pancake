"""Production-grade paper/shadow runner boundary for PR-038.

The package is intentionally sender-free.  It records durable lifecycle evidence
for the same high-level stages that live will later use, while fail-closing when
an upstream stage from PR-033..PR-037 is not present on the current branch.
"""

from src.paper_shadow.atomic_runtime_stages import (
    AtomicRuntimeStageError,
    AtomicRuntimeStageErrorCode,
    AtomicVerticalCandidateAdapter,
    AtomicVerticalRuntimeInputs,
    AtomicVerticalRuntimeStageSuite,
    AtomicVerticalStageRecord,
)
from src.paper_shadow.atomic_vertical import (
    AtomicPlannerSimulationReconciliationVertical,
    AtomicVerticalCandidate,
    AtomicVerticalError,
    AtomicVerticalRejectionCode,
    AtomicVerticalResult,
    AtomicVerticalTrace,
)
from src.paper_shadow.journal import JsonlPaperShadowJournal, PaperShadowEvent
from src.paper_shadow.runner import (
    PAPER_SHADOW_REQUIRED_STAGES,
    PaperShadowRunStatus,
    PaperShadowRunSummary,
    PaperShadowRunner,
    PaperShadowRunnerConfig,
    PaperShadowStageContext,
    PaperShadowStageName,
)

__all__ = [
    "AtomicPlannerSimulationReconciliationVertical",
    "AtomicRuntimeStageError",
    "AtomicRuntimeStageErrorCode",
    "AtomicVerticalCandidate",
    "AtomicVerticalCandidateAdapter",
    "AtomicVerticalError",
    "AtomicVerticalRejectionCode",
    "AtomicVerticalResult",
    "AtomicVerticalRuntimeInputs",
    "AtomicVerticalRuntimeStageSuite",
    "AtomicVerticalStageRecord",
    "AtomicVerticalTrace",
    "JsonlPaperShadowJournal",
    "PAPER_SHADOW_REQUIRED_STAGES",
    "PaperShadowEvent",
    "PaperShadowRunStatus",
    "PaperShadowRunSummary",
    "PaperShadowRunner",
    "PaperShadowRunnerConfig",
    "PaperShadowStageContext",
    "PaperShadowStageName",
]
