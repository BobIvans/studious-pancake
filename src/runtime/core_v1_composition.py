"""Canonical installed composition for the first MarginFi + Jupiter core profile.

This module owns dependency construction only.  It deliberately reuses the
accepted lifecycle, capital, planner, simulator, reconciliation, paper-terminal
and replay owners.  It never imports a sender or signer and never enables live.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from src.config.runtime import RuntimeConfig
from src.durability.unified_authority_pr02 import UnifiedLifecycleAuthority
from src.economics.capital import CapitalPolicy, PolicyProfile
from src.economics.durable_reservations import DurableCapitalCoordinator
from src.execution.exact_simulation import (
    ExactSimulationFinalizer,
    ExactSimulationPolicy,
)
from src.execution.models import RpcClient
from src.lending.financing import FinancingEvidence, FinancingPort
from src.lending.financing_planner_adapter import FinancingPlannerProviderAdapter
from src.paper_shadow.atomic_vertical import (
    AtomicPlannerSimulationReconciliationVertical,
    FinancingRepaymentDecoder,
)
from src.paper_shadow.durable_service_a3 import (
    A3ExactAttemptBatch,
    A3ProviderEvidenceState,
)
from src.paper_shadow.exact_attempt_pr152 import ExactPaperAttemptOrchestrator
from src.paper_shadow.mpr2602_completion import DurableCompletedExactAttemptRuntime
from src.paper_shadow.mpr2602_verified_a3 import (
    VerifiedTerminalInstalledPaperService,
    build_verified_terminal_paper_service,
)
from src.providers.marginfi import MarginfiFlashLoanProvider, load_marginfi_contract_pin
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerPolicy,
    VerifiedMarginfiProviderPort,
)
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CoreV1AttemptMaterializer,
    CoreV1DraftSource,
    CoreV1MaterializedBatchSource,
    CoreV1ReleaseProfile,
)

CORE_V1_COMPOSITION_SCHEMA = "core-v1.installed-composition.v1"
CORE_V1_OWNER_ID = "core-v1-installed-marginfi-jupiter"
CORE_V1_LENDER_ADAPTER_REQUIRED = "CORE_V1_LENDER_ADAPTER_REQUIRED"
CORE_V1_FINANCING_DECODER_REQUIRED = "CORE_V1_FINANCING_DECODER_REQUIRED"


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CoreV1Dependencies:
    """Externally qualified dependencies needed for an admitted paper cycle.

    ``marginfi_provider`` remains the compatibility field for the historical
    profile. ``financing_port``/``financing_evidence`` are the AGG-01
    lender-neutral seam consumed by later lender adapters.
    """

    release_id: str
    policy_bundle_hash: str
    draft_source: CoreV1DraftSource
    rpc: RpcClient
    marginfi_provider: VerifiedMarginfiProviderPort | None
    planner_policy: AtomicPlannerPolicy
    simulation_policy: ExactSimulationPolicy | None = None
    financing_port: FinancingPort | None = None
    financing_evidence: FinancingEvidence | None = None
    financing_repayment_decoder: FinancingRepaymentDecoder | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.release_id, str) or not self.release_id.strip():
            raise ValueError("CORE_V1_RELEASE_ID_REQUIRED")
        if (
            not isinstance(self.policy_bundle_hash, str)
            or len(self.policy_bundle_hash) != 64
        ):
            raise ValueError("CORE_V1_POLICY_BUNDLE_HASH_REQUIRED")
        try:
            int(self.policy_bundle_hash, 16)
        except ValueError as exc:
            raise ValueError("CORE_V1_POLICY_BUNDLE_HASH_REQUIRED") from exc
        if self.marginfi_provider is not None and (
            getattr(self.marginfi_provider, "execution_conformance_verified", False)
            is not True
        ):
            raise ValueError("CORE_V1_MARGINFI_EXECUTION_CONFORMANCE_REQUIRED")
        if self.financing_port is not None:
            if (
                getattr(self.financing_port, "execution_conformance_verified", False)
                is not True
            ):
                raise ValueError("CORE_V1_FINANCING_EXECUTION_CONFORMANCE_REQUIRED")
            if self.financing_evidence is None:
                raise ValueError("CORE_V1_FINANCING_EVIDENCE_REQUIRED")
            if self.financing_port.lender_id != self.financing_evidence.lender_id:
                raise ValueError("CORE_V1_FINANCING_LENDER_MISMATCH")
            if (
                self.financing_port.deployment_generation
                != self.financing_evidence.deployment_generation
            ):
                raise ValueError("CORE_V1_FINANCING_GENERATION_MISMATCH")
        if self.financing_evidence is not None and self.financing_port is None:
            raise ValueError("CORE_V1_FINANCING_PORT_REQUIRED")
        if self.financing_repayment_decoder is not None:
            if self.financing_evidence is None:
                raise ValueError("CORE_V1_FINANCING_EVIDENCE_REQUIRED")
            decoder = self.financing_repayment_decoder
            if (
                decoder.lender_id != self.financing_evidence.lender_id
                or decoder.program_id != self.financing_evidence.program_id
                or decoder.deployment_generation
                != self.financing_evidence.deployment_generation
            ):
                raise ValueError("CORE_V1_FINANCING_DECODER_IDENTITY_MISMATCH")
        if not callable(getattr(self.rpc, "call", None)):
            raise ValueError("CORE_V1_GOVERNED_RPC_REQUIRED")


class _BlockedRpcClient:
    """Non-network RPC port used only while real external evidence is absent."""

    async def call(self, _method: str, _params: list[Any]) -> Any:
        raise RuntimeError(CORE_V1_BLOCKED_EXTERNAL)


class _BlockedBatchSource:
    """Explicit BLOCKED_EXTERNAL source used when qualified dependencies are absent."""

    def __init__(self, profile: CoreV1ReleaseProfile, reason: str) -> None:
        self.profile = profile
        self.reason = reason

    def __call__(self) -> A3ExactAttemptBatch:
        evidence_hash = _hash_json(
            {
                "schema": CORE_V1_COMPOSITION_SCHEMA,
                "profile_id": self.profile.profile_id,
                "profile_generation": self.profile.profile_generation,
                "lender": self.profile.lender,
                "reason": self.reason,
            }
        )
        return A3ExactAttemptBatch(
            A3ProviderEvidenceState(evidence_hash, False, (self.reason,))
        )


@dataclass(slots=True)
class CoreV1Composition:
    """Owns deterministic close order for one installed core-v1 process."""

    profile: CoreV1ReleaseProfile
    authority: UnifiedLifecycleAuthority
    capital: DurableCapitalCoordinator
    service: VerifiedTerminalInstalledPaperService
    planner: AtomicMarginfiJupiterPlanner | None
    simulator: ExactSimulationFinalizer | None
    vertical: AtomicPlannerSimulationReconciliationVertical | None
    orchestrator: ExactPaperAttemptOrchestrator | None
    runtime_cycle: DurableCompletedExactAttemptRuntime | None
    materializer: CoreV1AttemptMaterializer | None
    admitted: bool
    blockers: tuple[str, ...]
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.service.close()
        finally:
            self.authority.close()

    def __enter__(self) -> "CoreV1Composition":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


async def _blocked_runtime_cycle(_cycle_id: str, _items: tuple[object, ...]):
    raise RuntimeError(CORE_V1_LENDER_ADAPTER_REQUIRED)


def _is_legacy_marginfi_profile(profile: CoreV1ReleaseProfile) -> bool:
    return (
        profile.profile_id == "core-marginfi-jupiter-v1"
        and profile.lender == "marginfi"
        and profile.profile_generation == 1
    )


def _build_generic_blocked_service(
    config: RuntimeConfig,
    *,
    db_path: str | Path,
    profile: CoreV1ReleaseProfile,
    authority: UnifiedLifecycleAuthority,
    reason: str,
) -> VerifiedTerminalInstalledPaperService:
    return build_verified_terminal_paper_service(
        config,
        db_path=Path(db_path),
        batch_source=_BlockedBatchSource(profile, reason),
        runtime_cycle=_blocked_runtime_cycle,
        authority=authority,
    )


def build_core_v1_composition(
    config: RuntimeConfig,
    *,
    db_path: str | Path,
    profile: CoreV1ReleaseProfile,
    dependencies: CoreV1Dependencies | None = None,
) -> CoreV1Composition:
    """Build exactly one sender-free installed core graph.

    Missing real provider/deployment evidence is represented as BLOCKED_EXTERNAL,
    not as an unconfigured A3 service.  When dependencies are supplied, the
    canonical planner and exact simulator are physically instantiated here.
    """

    config_hash = config.fingerprint()
    release_digest = _hash_json(
        {
            "schema": CORE_V1_COMPOSITION_SCHEMA,
            "profile_id": profile.profile_id,
            "profile_generation": profile.profile_generation,
            "lender": profile.lender,
            "release_id": (
                dependencies.release_id
                if dependencies is not None
                else "blocked-external"
            ),
            "config_hash": config_hash,
        }
    )
    policy_hash = (
        dependencies.policy_bundle_hash
        if dependencies is not None
        else _hash_json(
            {
                "profile_id": profile.profile_id,
                "profile_generation": profile.profile_generation,
                "lender": profile.lender,
                "state": "blocked-external",
            }
        )
    )
    authority = UnifiedLifecycleAuthority(
        Path(db_path),
        release_digest=release_digest,
        policy_bundle_hash=policy_hash,
        owner_id=CORE_V1_OWNER_ID,
        environment="paper",
        cluster_genesis=config.cluster.genesis_hash,
    )
    capital = DurableCapitalCoordinator(
        store=authority.lifecycle,
        policy=CapitalPolicy.from_runtime_config(config, profile=PolicyProfile.PAPER),
        owner_id=CORE_V1_OWNER_ID,
    )

    if dependencies is None:
        if not _is_legacy_marginfi_profile(profile):
        if (
            dependencies.financing_port is None
            or dependencies.financing_evidence is None
        ):
            reason = f"CORE_V1_FINANCING_PORT_REQUIRED:{profile.lender}"
            service = _build_generic_blocked_service(
                config,
                db_path=db_path,
                profile=profile,
                authority=authority,
                reason=reason,
            )
            return CoreV1Composition(
                profile=profile,
                authority=authority,
                capital=capital,
                service=service,
                planner=None,
                simulator=None,
                vertical=None,
                orchestrator=None,
                runtime_cycle=None,
                materializer=None,
                admitted=False,
                blockers=(reason,),
            )
        evidence = dependencies.financing_evidence
        if evidence.lender_id != profile.lender:
            authority.close()
            raise ValueError("CORE_V1_FINANCING_LENDER_MISMATCH")
        if evidence.deployment_generation != profile.profile_generation:
            authority.close()
            raise ValueError("CORE_V1_FINANCING_GENERATION_MISMATCH")
        decoder = dependencies.financing_repayment_decoder
        if decoder is None:
            reason = f"{CORE_V1_FINANCING_DECODER_REQUIRED}:{profile.lender}"
            service = _build_generic_blocked_service(
                config,
                db_path=db_path,
                profile=profile,
                authority=authority,
                reason=reason,
            )
            return CoreV1Composition(
                profile=profile,
                authority=authority,
                capital=capital,
                service=service,
                planner=None,
                simulator=None,
                vertical=None,
                orchestrator=None,
                runtime_cycle=None,
                materializer=None,
                admitted=False,
                blockers=(reason,),
            )
        try:
            materializer = CoreV1AttemptMaterializer(
                config,
                profile,
                release_id=dependencies.release_id,
                policy_bundle_hash=dependencies.policy_bundle_hash,
            )
            batch_source = CoreV1MaterializedBatchSource(
                materializer,
                dependencies.draft_source,
            )
            provider = FinancingPlannerProviderAdapter(
                dependencies.financing_port,
                evidence,
            )
            allowed = tuple(
                dict.fromkeys(
                    (*dependencies.planner_policy.allowed_program_ids, evidence.program_id)
                )
            )
            planner_policy = replace(
                dependencies.planner_policy,
                allowed_program_ids=allowed,
            )
            planner = AtomicMarginfiJupiterPlanner(
                cast(VerifiedMarginfiProviderPort, provider),
                planner_policy,
            )
            simulator = ExactSimulationFinalizer(
                dependencies.rpc,
                policy=dependencies.simulation_policy,
            )
            vertical = AtomicPlannerSimulationReconciliationVertical(
                planner,
                simulator,
                financing_decoder=decoder,
            )
            orchestrator = ExactPaperAttemptOrchestrator(
                coordinator=capital,
                vertical=vertical,
                authority=authority,
            )
            runtime_cycle = DurableCompletedExactAttemptRuntime(
                orchestrator=orchestrator,
                authority=authority,
            )
            service = build_verified_terminal_paper_service(
                config,
                db_path=Path(db_path),
                batch_source=batch_source,
                runtime_cycle=runtime_cycle,
                authority=authority,
            )
        except BaseException:
            authority.close()
            raise
        return CoreV1Composition(
            profile=profile,
            authority=authority,
            capital=capital,
            service=service,
            planner=planner,
            simulator=simulator,
            vertical=vertical,
            orchestrator=orchestrator,
            runtime_cycle=runtime_cycle,
            materializer=materializer,
            admitted=True,
            blockers=(),
        )

    if dependencies.marginfi_provider is None:
        authority.close()
        raise ValueError("CORE_V1_MARGINFI_PROVIDER_REQUIRED")

    try:
        materializer = CoreV1AttemptMaterializer(
            config,
            profile,
            release_id=dependencies.release_id,
            policy_bundle_hash=dependencies.policy_bundle_hash,
        )
        batch_source = CoreV1MaterializedBatchSource(
            materializer,
            dependencies.draft_source,
        )
        planner = AtomicMarginfiJupiterPlanner(
            dependencies.marginfi_provider,
            dependencies.planner_policy,
        )
        simulator = ExactSimulationFinalizer(
            dependencies.rpc,
            policy=dependencies.simulation_policy,
        )
        vertical = AtomicPlannerSimulationReconciliationVertical(planner, simulator)
        orchestrator = ExactPaperAttemptOrchestrator(
            coordinator=capital,
            vertical=vertical,
            authority=authority,
        )
        runtime_cycle = DurableCompletedExactAttemptRuntime(
            orchestrator=orchestrator,
            authority=authority,
        )
        service = build_verified_terminal_paper_service(
            config,
            db_path=Path(db_path),
            batch_source=batch_source,
            runtime_cycle=runtime_cycle,
            authority=authority,
        )
    except BaseException:
        authority.close()
        raise

    return CoreV1Composition(
        profile=profile,
        authority=authority,
        capital=capital,
        service=service,
        planner=planner,
        simulator=simulator,
        vertical=vertical,
        orchestrator=orchestrator,
        runtime_cycle=runtime_cycle,
        materializer=materializer,
        admitted=True,
        blockers=(),
    )


__all__ = [
    "CORE_V1_COMPOSITION_SCHEMA",
    "CORE_V1_FINANCING_DECODER_REQUIRED",
    "CORE_V1_LENDER_ADAPTER_REQUIRED",
    "CORE_V1_OWNER_ID",
    "CoreV1Composition",
    "CoreV1Dependencies",
    "build_core_v1_composition",
]
