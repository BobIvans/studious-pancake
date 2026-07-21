"""Production-grade paper/shadow runner boundary for PR-038/PR-089.

The package is intentionally sender-free.  It records durable lifecycle evidence
for the same high-level stages that live will later use, while fail-closing when
required upstream evidence is not present on the current branch.
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
from src.paper_shadow.composition import (
    PR089_COMPOSITION_SCHEMA,
    PR089_MISSING_ATOMIC_DEPENDENCIES,
    PaperShadowDependencyGate,
    PaperShadowRuntime,
    PaperShadowRuntimeDependencies,
    build_paper_shadow_runtime,
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
    paper_shadow_stage_blocked,
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
    "PR089_COMPOSITION_SCHEMA",
    "PR089_MISSING_ATOMIC_DEPENDENCIES",
    "PaperShadowDependencyGate",
    "PaperShadowEvent",
    "PaperShadowRunStatus",
    "PaperShadowRunSummary",
    "PaperShadowRunner",
    "PaperShadowRunnerConfig",
    "PaperShadowRuntime",
    "PaperShadowRuntimeDependencies",
    "PaperShadowStageContext",
    "PaperShadowStageName",
    "build_paper_shadow_runtime",
    "paper_shadow_stage_blocked",
]
