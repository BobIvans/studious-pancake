"""PR-089 active sender-free paper/shadow composition root.

The runner and atomic stage suite already exist in earlier roadmap slices.  This
module is the supported CLI composition root that binds discovery evidence to the
paper/shadow runner and, when the required verified dependencies are supplied,
binds the PR-075 atomic runtime stages without importing a sender.

A missing atomic dependency is an explicit blocked paper/shadow dependency, not a
synthetic fill and not ``blocked_missing_stage_capital_sizing``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.config.runtime import RuntimeConfig
from src.paper_shadow.atomic_runtime_stages import AtomicVerticalRuntimeStageSuite
from src.paper_shadow.runner import (
    PAPER_SHADOW_REQUIRED_STAGES,
    PaperShadowRunSummary,
    PaperShadowRunner,
    PaperShadowRunnerConfig,
    PaperShadowStage,
    PaperShadowStageContext,
    PaperShadowStageName,
    paper_shadow_stage_blocked,
)
from src.runtime_discovery import RuntimeDiscoveryCoordinator, build_runtime_discovery


PR089_COMPOSITION_SCHEMA = "pr089.paper-shadow-composition.v1"
PR089_MISSING_ATOMIC_DEPENDENCIES = "blocked_pr089_atomic_dependencies_missing"

_REQUIRED_ACTIVE_DEPENDENCIES = (
    "atomic_stage_suite",
    "exact_fee_workflow",
    "verified_marginfi_provider",
    "jupiter_v2_build",
)


@dataclass(frozen=True, slots=True)
class PaperShadowRuntimeDependencies:
    """External dependencies needed for active PR-089 atomic stage wiring.

    The default value is intentionally incomplete: it keeps the CLI branch-safe
    while PR-086/087/088 are being applied in parallel.  A production composition
    may pass a fully verified ``AtomicVerticalRuntimeStageSuite`` plus reviewed
    MarginFi/Jupiter/capital evidence to activate all runner stages.
    """

    atomic_stage_suite: AtomicVerticalRuntimeStageSuite | None = None
    exact_fee_workflow: Any | None = None
    verified_marginfi_provider: Any | None = None
    jupiter_v2_build: Any | None = None

    def missing(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.atomic_stage_suite is None:
            missing.append("atomic_stage_suite")
        if self.exact_fee_workflow is None:
            missing.append("exact_fee_workflow")
        if self.verified_marginfi_provider is None:
            missing.append("verified_marginfi_provider")
        if self.jupiter_v2_build is None:
            missing.append("jupiter_v2_build")
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing()


class PaperShadowDependencyGate:
    """Stage handler that records a blocked dependency without live side effects."""

    def __init__(self, missing_dependencies: Sequence[str]) -> None:
        self.missing_dependencies = tuple(missing_dependencies)

    async def __call__(self, context: PaperShadowStageContext) -> Mapping[str, Any]:
        return paper_shadow_stage_blocked(
            PR089_MISSING_ATOMIC_DEPENDENCIES,
            details={
                "schema_version": PR089_COMPOSITION_SCHEMA,
                "stage": context.stage.value,
                "missing_dependencies": list(self.missing_dependencies),
                "required_dependencies": list(_REQUIRED_ACTIVE_DEPENDENCIES),
                "sender_imported": False,
                "live_mutation_allowed": False,
            },
        )


@dataclass(slots=True)
class PaperShadowRuntime:
    """Runnable PR-089 composition: discovery -> paper/shadow runner."""

    config: RuntimeConfig
    discovery: RuntimeDiscoveryCoordinator
    runner: PaperShadowRunner
    dependency_reasons_on_candidates: tuple[str, ...] = ()

    async def run_once(self) -> PaperShadowRunSummary:
        report = await self.discovery.run_cycle()
        dependency_reasons = list(_paper_shadow_dependency_reasons(report.evidence))
        if report.opportunities:
            dependency_reasons.extend(self.dependency_reasons_on_candidates)
        return await self.runner.run_once(
            report.opportunities,
            upstream_cycle_completed=report.evidence.cycle_succeeded,
            upstream_dependency_reasons=tuple(dependency_reasons),
            upstream_cycle_evidence=report.evidence.to_dict(),
        )


def build_paper_shadow_runtime(
    config: RuntimeConfig,
    *,
    journal_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    dependencies: PaperShadowRuntimeDependencies | None = None,
    discovery: RuntimeDiscoveryCoordinator | None = None,
) -> PaperShadowRuntime:
    """Build the supported sender-free paper/shadow runtime from ``config``."""

    active_dependencies = dependencies or PaperShadowRuntimeDependencies()
    stages = _stage_mapping(active_dependencies)
    dependency_reasons = _dependency_reasons(active_dependencies)
    runner = PaperShadowRunner(
        PaperShadowRunnerConfig(
            journal_path=(
                Path(journal_path)
                if journal_path is not None
                else Path(".runtime/paper-shadow-journal.jsonl")
            )
        ),
        stages=stages,
    )
    active_discovery = discovery or build_runtime_discovery(
        config,
        environ=dict(os.environ if environ is None else environ),
    )
    return PaperShadowRuntime(
        config=config,
        discovery=active_discovery,
        runner=runner,
        dependency_reasons_on_candidates=dependency_reasons,
    )


def _stage_mapping(
    dependencies: PaperShadowRuntimeDependencies,
) -> Mapping[PaperShadowStageName, PaperShadowStage]:
    if dependencies.complete and dependencies.atomic_stage_suite is not None:
        return dependencies.atomic_stage_suite.stage_handlers()

    missing = dependencies.missing()
    gate = PaperShadowDependencyGate(missing)
    return {stage: gate for stage in PAPER_SHADOW_REQUIRED_STAGES}


def _dependency_reasons(
    dependencies: PaperShadowRuntimeDependencies,
) -> tuple[str, ...]:
    if dependencies.complete:
        return ()
    return (
        PR089_MISSING_ATOMIC_DEPENDENCIES,
        *tuple(f"missing_{name}" for name in dependencies.missing()),
    )


def _paper_shadow_dependency_reasons(evidence: Any) -> tuple[str, ...]:
    reasons: list[str] = []
    if not evidence.cycle_succeeded:
        reasons.append(str(evidence.terminal_reason))
    reasons.extend(
        str(reason) for reason in getattr(evidence, "degraded_reasons", ())
    )
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


__all__ = [
    "PR089_COMPOSITION_SCHEMA",
    "PR089_MISSING_ATOMIC_DEPENDENCIES",
    "PaperShadowDependencyGate",
    "PaperShadowRuntime",
    "PaperShadowRuntimeDependencies",
    "build_paper_shadow_runtime",
]
