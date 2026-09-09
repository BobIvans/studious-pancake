"""Release-profile-scoped production-debt projection for core-v1.

The historical/global production-debt report stays conservative. This module
projects that report onto one immutable release profile so optional expansion
capabilities do not become accidental dependencies of the first release.

It never promotes a release: ``production_ready`` and ``release_claim_allowed``
remain false. MPR-2611 qualification and MPR-2612 promotion remain the owners
of those decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from src.production_debt import ProductionDebtReport, evaluate_production_debt
from src.runtime.core_v1_materializer import CORE_V1_PROFILE_ID

PROFILE_SCHEMA = "core-v1.release-profile.v1"
PROFILE_REPORT_SCHEMA = "core-v1.profile-debt-report.v1"

CORE_CODE_DEBT_IDS = frozenset(
    {
        "runtime.canonical-vertical-wiring",
        "execution.exact-simulation-binding",
        "execution.canonical-transaction-proof",
        "economics.capital-reservations",
        "durability.single-truth-cutover",
    }
)

CORE_EXTERNAL_DEBT_IDS = frozenset(
    {
        "accounts.lifecycle-rent-wsol",
        "data.rpc-rooted-quorum",
        "data.oracle-slot-coherence",
        "external.solana-v0-rpc",
        "external.jupiter-swap-v2",
        "external.marginfi-v2",
        "evidence.real-shadow-soak",
        "evidence.provider-drift-probes",
        "evidence.finalized-economic-proof",
        "deployment.image-provenance",
        "operations.slo-readiness",
        "security.secret-incident-drill",
        "data.lineage-quarantine",
    }
)

ALWAYS_IRRELEVANT_CORE_V1 = frozenset(
    {
        "runtime.product-state",
        "runtime.live-entrypoint",
        "runtime.legacy-ingest-removal",
        "external.kamino-klend",
        "lending.kamino-supported-combinations",
        "external.okx-signed-discovery",
        "external.openocean-whitelist-discovery",
        "external.odos-immutable-transaction",
        "security.signer-isolation",
        "canary.permit-budget-latches",
        "canary.second-human-approval",
    }
)


@dataclass(frozen=True, slots=True)
class CoreV1ReleaseProfile:
    profile_id: str
    release_class: str
    cluster_name: str
    genesis_hash: str
    strategy: str
    lender: str
    router: str
    submission_transport: str
    required_data_producers: tuple[str, ...]
    optional_data_producers: tuple[str, ...]
    live_enabled: bool
    unrestricted_live_allowed: bool
    automatic_scale_up_allowed: bool
    executed_canary_required_for_default_off_review: bool

    @classmethod
    def load(cls, path: str | Path) -> "CoreV1ReleaseProfile":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != PROFILE_SCHEMA:
            raise ValueError("CORE_V1_PROFILE_SCHEMA_MISMATCH")
        cluster = raw.get("cluster")
        if not isinstance(cluster, dict):
            raise ValueError("CORE_V1_PROFILE_CLUSTER_REQUIRED")
        profile = cls(
            profile_id=str(raw.get("profile_id", "")),
            release_class=str(raw.get("release_class", "")),
            cluster_name=str(cluster.get("name", "")),
            genesis_hash=str(cluster.get("genesis_hash", "")),
            strategy=str(raw.get("strategy", "")),
            lender=str(raw.get("lender", "")),
            router=str(raw.get("router", "")),
            submission_transport=str(raw.get("submission_transport", "")),
            required_data_producers=_strings(raw, "required_data_producers"),
            optional_data_producers=_strings(raw, "optional_data_producers"),
            live_enabled=_bool(raw, "live_enabled"),
            unrestricted_live_allowed=_bool(raw, "unrestricted_live_allowed"),
            automatic_scale_up_allowed=_bool(raw, "automatic_scale_up_allowed"),
            executed_canary_required_for_default_off_review=_bool(
                raw, "executed_canary_required_for_default_off_review"
            ),
        )
        profile.validate()
        return profile

    def validate(self) -> None:
        expected = (
            self.profile_id == CORE_V1_PROFILE_ID,
            self.release_class == "production-ready-default-off",
            self.strategy == "circular_arbitrage",
            self.lender == "marginfi",
            self.router == "jupiter",
            self.submission_transport in {"rpc", "rpc+jito"},
            not self.live_enabled,
            not self.unrestricted_live_allowed,
            not self.automatic_scale_up_allowed,
            not self.executed_canary_required_for_default_off_review,
        )
        if not all(expected):
            raise ValueError("CORE_V1_PROFILE_SCOPE_INVALID")
        if not self.cluster_name or not self.genesis_hash:
            raise ValueError("CORE_V1_PROFILE_CLUSTER_IDENTITY_REQUIRED")


@dataclass(frozen=True, slots=True)
class CoreV1CodeFacts:
    code_complete: bool
    installed_entrypoint_wired: bool
    typed_materializer_present: bool
    canonical_planner_simulator_composed: bool
    durable_terminal_owner_reused: bool
    finalized_ledger_consumer_reused: bool
    profile_resource_present: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CoreV1ProfileDebtReport:
    schema_version: str
    profile_id: str
    core_v1_code_complete: bool
    core_v1_installed_path_verified: bool
    core_v1_external_qualification_complete: bool
    paper_qualified: bool
    eligible_for_production_default_off_review: bool
    canary_eligible: bool
    live_capable: bool
    production_ready: bool
    release_claim_allowed: bool
    live_enabled: bool
    automatic_scale_up_allowed: bool
    implementation_blockers: tuple[dict[str, Any], ...]
    external_or_review_blockers: tuple[dict[str, Any], ...]
    ignored_optional_debt_ids: tuple[str, ...]
    global_production_ready: bool
    code_facts: CoreV1CodeFacts

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_facts"] = self.code_facts.to_dict()
        return payload


def evaluate_core_v1_profile_debt(
    *,
    repo_root: str | Path | None = None,
    profile_path: str | Path | None = None,
    global_report: ProductionDebtReport | None = None,
) -> CoreV1ProfileDebtReport:
    root = (
        Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    )
    selected_profile = (
        Path(profile_path)
        if profile_path is not None
        else root / "config" / "release_profiles" / "core-marginfi-jupiter-v1.json"
    )
    profile = CoreV1ReleaseProfile.load(selected_profile)
    report = global_report or evaluate_production_debt(repo_root=root)
    code = inspect_core_v1_code(root)

    irrelevant = set(ALWAYS_IRRELEVANT_CORE_V1)
    if profile.submission_transport == "rpc":
        irrelevant.update(
            {"external.jito-low-latency", "submission.jito-unbundling-protection"}
        )
    if "helius-webhook" not in profile.required_data_producers:
        irrelevant.add("external.helius-webhook-auth")

    implementation: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    ignored: list[str] = []
    for blocker in report.blockers:
        debt_id = str(blocker.get("id", ""))
        if debt_id in irrelevant:
            ignored.append(debt_id)
            continue
        if debt_id in CORE_CODE_DEBT_IDS and code.code_complete:
            continue
        if debt_id in CORE_CODE_DEBT_IDS:
            implementation.append(dict(blocker))
            continue
        if debt_id in CORE_EXTERNAL_DEBT_IDS:
            external.append(dict(blocker))
            continue
        external.append(dict(blocker))

    code_complete = code.code_complete and not implementation
    external_complete = not external
    paper_qualified = code_complete and external_complete
    review_eligible = paper_qualified

    return CoreV1ProfileDebtReport(
        schema_version=PROFILE_REPORT_SCHEMA,
        profile_id=profile.profile_id,
        core_v1_code_complete=code_complete,
        core_v1_installed_path_verified=code.installed_entrypoint_wired,
        core_v1_external_qualification_complete=external_complete,
        paper_qualified=paper_qualified,
        eligible_for_production_default_off_review=review_eligible,
        canary_eligible=False,
        live_capable=False,
        production_ready=False,
        release_claim_allowed=False,
        live_enabled=False,
        automatic_scale_up_allowed=False,
        implementation_blockers=tuple(implementation),
        external_or_review_blockers=tuple(external),
        ignored_optional_debt_ids=tuple(sorted(set(ignored))),
        global_production_ready=report.production_ready,
        code_facts=code,
    )


def inspect_core_v1_code(root: Path) -> CoreV1CodeFacts:
    checks: list[tuple[str, bool]] = []

    entrypoint = _text(root / "src/runtime/runtime_entrypoint.py")
    composition = _text(root / "src/runtime/core_v1_composition.py")
    materializer = _text(root / "src/runtime/core_v1_materializer.py")
    settlement = _text(root / "src/execution/core_v1_finalized_settlement.py")
    profile_present = (
        root / "config/release_profiles/core-marginfi-jupiter-v1.json"
    ).is_file()

    installed = (
        "build_core_v1_composition" in entrypoint
        and "build_installed_durable_paper_service(" not in entrypoint
    )
    typed = (
        "ExactAttemptRuntimeItem" in materializer
        and "CoreV1AttemptMaterializer" in materializer
        and "VerifiedProviderWorkItem" not in materializer
    )
    composed = all(
        token in composition
        for token in (
            "AtomicMarginfiJupiterPlanner",
            "ExactSimulationFinalizer",
            "AtomicPlannerSimulationReconciliationVertical",
            "ExactPaperAttemptOrchestrator",
        )
    )
    durable = all(
        token in composition
        for token in (
            "UnifiedLifecycleAuthority",
            "DurableCapitalCoordinator",
            "DurableCompletedExactAttemptRuntime",
            "VerifiedTerminalInstalledPaperService",
        )
    )
    ledger = (
        "classify_finalized_economics" in settlement
        and "FinalizedEconomicInput" in settlement
        and "CoreV1FinalizedSettlementProducer" in settlement
    )
    forbidden = any(
        token in composition + materializer + settlement
        for token in (
            "src.execution.senders",
            "src.execution.live_control",
            "src.legacy_arb_bot",
            "src.ingest.",
        )
    )

    checks.extend(
        [
            ("CORE_V1_INSTALLED_ENTRYPOINT_UNWIRED", installed),
            ("CORE_V1_TYPED_MATERIALIZER_MISSING", typed),
            ("CORE_V1_PLANNER_SIMULATOR_NOT_COMPOSED", composed),
            ("CORE_V1_DURABLE_OWNER_NOT_REUSED", durable),
            ("CORE_V1_FINALIZED_LEDGER_NOT_REUSED", ledger),
            ("CORE_V1_PROFILE_RESOURCE_MISSING", profile_present),
            ("CORE_V1_FORBIDDEN_RUNTIME_IMPORT", not forbidden),
        ]
    )
    blockers = tuple(name for name, passed in checks if not passed)
    return CoreV1CodeFacts(
        code_complete=not blockers,
        installed_entrypoint_wired=installed,
        typed_materializer_present=typed,
        canonical_planner_simulator_composed=composed,
        durable_terminal_owner_reused=durable,
        finalized_ledger_consumer_reused=ledger,
        profile_resource_present=profile_present,
        blockers=blockers,
    )


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _strings(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{key} must be non-empty strings")
    return tuple(item.strip() for item in value)


def _bool(raw: dict[str, Any], key: str) -> bool:
    value = raw.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


__all__ = [
    "CORE_CODE_DEBT_IDS",
    "CORE_EXTERNAL_DEBT_IDS",
    "CoreV1CodeFacts",
    "CoreV1ProfileDebtReport",
    "CoreV1ReleaseProfile",
    "evaluate_core_v1_profile_debt",
    "inspect_core_v1_code",
]
