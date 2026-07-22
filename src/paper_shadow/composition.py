"""PR-089/102 active sender-free paper/shadow composition root.

The runner and atomic stage suite already exist in earlier roadmap slices. This
module is the supported CLI composition root that binds discovery evidence to the
paper/shadow runner and, when the required verified dependencies are supplied,
binds the PR-075 atomic runtime stages without importing a sender.

PR-102 hardens the PR-089 dependency seam: arbitrary ``object()`` sentinels no
longer unlock paper outcomes. Dependencies must satisfy explicit runtime
contracts and carry the reviewed evidence needed by the atomic stage suite.

MEGA-PR A starts the active cutover: the default paper path now builds and
records a deterministic canonical-paper-vertical startup decision instead of
silently presenting a generic "all dependencies missing" placeholder.  The
supported CLI still fails closed until real provider/RPC/MarginFi/Jupiter/capital
dependencies are supplied, but the active runtime now owns a named integration
seam that later PR-A commits can satisfy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Protocol, runtime_checkable

from src.config.runtime import RuntimeConfig
from src.paper_shadow.atomic_runtime_stages import AtomicVerticalRuntimeStageSuite
from src.paper_shadow.canonical_paper_vertical import (
    CanonicalPaperVerticalStartup,
    MEGA_PR_A_SCHEMA,
    PR_A_CANONICAL_VERTICAL_INVALID,
    PR_A_CANONICAL_VERTICAL_UNWIRED,
    build_canonical_paper_vertical_startup,
)
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
PR102_COMPOSITION_SCHEMA = "pr102.type-safe-paper-composition.v1"
PR102_TYPE_SAFE_DEPENDENCY_REJECTED = "blocked_pr102_type_safe_dependency_rejected"

_REQUIRED_ACTIVE_DEPENDENCIES = (
    "atomic_stage_suite",
    "exact_fee_workflow",
    "verified_marginfi_provider",
    "jupiter_v2_build",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@runtime_checkable
class ExactFeeCapitalWorkflowDependency(Protocol):
    """PR-074 exact-fee workflow contract required by PR-102."""

    def finalize_reserved_attempt(self, *args: Any, **kwargs: Any) -> Any:
        """Finalize a durable reserved attempt for an exact message hash."""


@runtime_checkable
class VerifiedMarginfiProviderDependency(Protocol):
    """Reviewed PR-088 MarginFi dependency required by paper composition."""

    shadow_execution_capable: bool
    evidence_sha256: str


@runtime_checkable
class JupiterV2BuildDependency(Protocol):
    """Evidence-bound Jupiter V2 build dependency required by paper stages."""

    execution_allowed: bool
    contract_pin: str

    def build_swap_instructions(self, *args: Any, **kwargs: Any) -> Any:
        """Build sender-free swap instructions for the reviewed atomic plan."""


@dataclass(frozen=True, slots=True)
class PaperShadowRuntimeDependencies:
    """External dependencies needed for active PR-102 atomic stage wiring.

    The default value is intentionally incomplete: it keeps the CLI branch-safe
    while PR-099/100/101 are being applied in parallel. A production composition
    may pass a fully verified ``AtomicVerticalRuntimeStageSuite`` plus reviewed
    MarginFi/Jupiter/capital evidence to activate all runner stages.
    """

    atomic_stage_suite: AtomicVerticalRuntimeStageSuite | None = None
    exact_fee_workflow: ExactFeeCapitalWorkflowDependency | None = None
    verified_marginfi_provider: VerifiedMarginfiProviderDependency | None = None
    jupiter_v2_build: JupiterV2BuildDependency | None = None

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

    def invalid(self) -> tuple[str, ...]:
        invalid: list[str] = []
        if self.atomic_stage_suite is not None and not isinstance(
            self.atomic_stage_suite,
            AtomicVerticalRuntimeStageSuite,
        ):
            invalid.append("atomic_stage_suite_type")
        if self.exact_fee_workflow is not None and not isinstance(
            self.exact_fee_workflow,
            ExactFeeCapitalWorkflowDependency,
        ):
            invalid.append("exact_fee_workflow_contract")
        self._validate_marginfi_provider(invalid)
        self._validate_jupiter_build(invalid)
        return tuple(invalid)

    @property
    def complete(self) -> bool:
        return not self.missing() and not self.invalid()

    def _validate_marginfi_provider(self, invalid: list[str]) -> None:
        provider = self.verified_marginfi_provider
        if provider is None:
            return
        if not isinstance(provider, VerifiedMarginfiProviderDependency):
            invalid.append("verified_marginfi_provider_contract")
            return
        if not bool(provider.shadow_execution_capable):
            invalid.append("verified_marginfi_provider_not_shadow_capable")
        if not _is_sha256_hex(provider.evidence_sha256):
            invalid.append("verified_marginfi_provider_evidence_hash")

    def _validate_jupiter_build(self, invalid: list[str]) -> None:
        build = self.jupiter_v2_build
        if build is None:
            return
        if not isinstance(build, JupiterV2BuildDependency):
            invalid.append("jupiter_v2_build_contract")
            return
        if not bool(build.execution_allowed):
            invalid.append("jupiter_v2_build_execution_not_allowed")
        if not _is_sha256_hex(build.contract_pin):
            invalid.append("jupiter_v2_build_contract_pin")


class PaperShadowDependencyGate:
    """Stage handler that records a blocked dependency without live side effects."""

    def __init__(
        self,
        missing_dependencies: Sequence[str],
        invalid_dependencies: Sequence[str] = (),
        *,
        reason_code: str = PR089_MISSING_ATOMIC_DEPENDENCIES,
        canonical_startup: CanonicalPaperVerticalStartup | None = None,
    ) -> None:
        self.missing_dependencies = tuple(missing_dependencies)
        self.invalid_dependencies = tuple(invalid_dependencies)
        self.reason_code = reason_code
        self.canonical_startup = canonical_startup

    async def __call__(self, context: PaperShadowStageContext) -> Mapping[str, Any]:
        details: dict[str, Any] = {
            "schema_version": PR102_COMPOSITION_SCHEMA,
            "previous_schema_version": PR089_COMPOSITION_SCHEMA,
            "stage": context.stage.value,
            "missing_dependencies": list(self.missing_dependencies),
            "invalid_dependencies": list(self.invalid_dependencies),
            "required_dependencies": list(_REQUIRED_ACTIVE_DEPENDENCIES),
            "sender_imported": False,
            "live_mutation_allowed": False,
        }
        if self.canonical_startup is not None:
            details["canonical_paper_vertical"] = self.canonical_startup.to_dict()
        return paper_shadow_stage_blocked(
            self.reason_code,
            details=details,
        )


@dataclass(slots=True)
class PaperShadowRuntime:
    """Runnable PR-102 composition: discovery -> paper/shadow runner."""

    config: RuntimeConfig
    discovery: RuntimeDiscoveryCoordinator
    runner: PaperShadowRunner
    dependency_reasons_on_candidates: tuple[str, ...] = ()
    canonical_startup: CanonicalPaperVerticalStartup | None = None

    async def run_once(self) -> PaperShadowRunSummary:
        report = await self.discovery.run_cycle()
        reasons = list(_paper_shadow_dependency_reasons(report.evidence))
        if report.opportunities:
            reasons.extend(self.dependency_reasons_on_candidates)
        cycle_evidence = report.evidence.to_dict()
        if self.canonical_startup is not None:
            cycle_evidence["canonical_paper_vertical"] = (
                self.canonical_startup.to_dict()
            )
        return await self.runner.run_once(
            report.opportunities,
            upstream_cycle_completed=report.evidence.cycle_succeeded,
            upstream_dependency_reasons=tuple(reasons),
            upstream_cycle_evidence=cycle_evidence,
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
    canonical_startup = build_canonical_paper_vertical_startup(
        config,
        active_dependencies,
    )
    stages = _stage_mapping(active_dependencies, canonical_startup)
    dependency_reasons = _dependency_reasons(active_dependencies, canonical_startup)
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
        canonical_startup=canonical_startup,
    )


def _stage_mapping(
    dependencies: PaperShadowRuntimeDependencies,
    canonical_startup: CanonicalPaperVerticalStartup,
) -> Mapping[PaperShadowStageName, PaperShadowStage]:
    if dependencies.complete and dependencies.atomic_stage_suite is not None:
        return dependencies.atomic_stage_suite.stage_handlers()

    missing = dependencies.missing()
    invalid = dependencies.invalid()
    gate = PaperShadowDependencyGate(
        missing,
        invalid,
        reason_code=_dependency_gate_reason(missing, invalid, canonical_startup),
        canonical_startup=canonical_startup,
    )
    return {stage: gate for stage in PAPER_SHADOW_REQUIRED_STAGES}


def _dependency_reasons(
    dependencies: PaperShadowRuntimeDependencies,
    canonical_startup: CanonicalPaperVerticalStartup,
) -> tuple[str, ...]:
    if dependencies.complete:
        return ()
    missing = dependencies.missing()
    invalid = dependencies.invalid()
    return (
        _dependency_gate_reason(missing, invalid, canonical_startup),
        *tuple(f"missing_{name}" for name in missing),
        *tuple(f"invalid_{name}" for name in invalid),
        *canonical_startup.dependency_reasons(),
    )


def _dependency_gate_reason(
    missing: Sequence[str],
    invalid: Sequence[str],
    canonical_startup: CanonicalPaperVerticalStartup | None = None,
) -> str:
    if canonical_startup is not None and canonical_startup.reason_code is not None:
        return canonical_startup.reason_code
    if invalid and not missing:
        return PR102_TYPE_SAFE_DEPENDENCY_REJECTED
    return PR089_MISSING_ATOMIC_DEPENDENCIES


def _paper_shadow_dependency_reasons(evidence: Any) -> tuple[str, ...]:
    reasons: list[str] = []
    if not evidence.cycle_succeeded:
        reasons.append(str(evidence.terminal_reason))
    reasons.extend(str(reason) for reason in getattr(evidence, "degraded_reasons", ()))
    return tuple(dict.fromkeys(reason for reason in reasons if reason))


def _is_sha256_hex(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


__all__ = [
    "ExactFeeCapitalWorkflowDependency",
    "JupiterV2BuildDependency",
    "MEGA_PR_A_SCHEMA",
    "PR089_COMPOSITION_SCHEMA",
    "PR089_MISSING_ATOMIC_DEPENDENCIES",
    "PR102_COMPOSITION_SCHEMA",
    "PR102_TYPE_SAFE_DEPENDENCY_REJECTED",
    "PR_A_CANONICAL_VERTICAL_INVALID",
    "PR_A_CANONICAL_VERTICAL_UNWIRED",
    "PaperShadowDependencyGate",
    "PaperShadowRuntime",
    "PaperShadowRuntimeDependencies",
    "VerifiedMarginfiProviderDependency",
    "build_paper_shadow_runtime",
]
