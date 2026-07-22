"""B1 provider/protocol conformance readiness surface.

This module is intentionally side-effect-free by default. It does not promote any
provider to execution and it does not perform network calls unless the caller
explicitly opts in through ``enable_online``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import os
from typing import Any

from src.external_contracts.conformance import (
    ConformanceResult,
    Transport,
    run_read_only_conformance,
)
from src.external_contracts.models import ExternalContract
from src.external_contracts.registry import ExternalContractRegistry

B1_SCHEMA_VERSION = "b1.provider-protocol-readiness.v1"
DEFAULT_B1_PROVIDERS = ("jupiter", "marginfi", "jito")
_REQUIRED_EVIDENCE = {
    "jupiter": (
        "remote_schema_freshness",
        "credentialed_api_conformance",
        "execution_conformance",
        "promotion_evidence",
    ),
    "marginfi": (
        "remote_schema_freshness",
        "deployed_program_attestation",
        "execution_conformance",
        "promotion_evidence",
    ),
    "jito": (
        "remote_schema_freshness",
        "credentialed_api_conformance",
        "execution_conformance",
        "promotion_evidence",
    ),
}


@dataclass(frozen=True, slots=True)
class B1ProviderReadiness:
    provider: str
    contract_id: str | None
    status: str | None
    promotion_state: str | None
    execution_allowed: bool
    local_artifact_integrity: bool
    has_conformance_probe: bool
    conformance_state: str | None
    conformance_verified: bool
    required_env: tuple[str, ...]
    missing_env: tuple[str, ...]
    can_feed_paper_vertical: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class B1ProviderProtocolReport:
    schema_version: str
    online_enabled: bool
    paper_vertical_ready: bool
    providers: tuple[B1ProviderReadiness, ...]
    diagnostic: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "online_enabled": self.online_enabled,
            "paper_vertical_ready": self.paper_vertical_ready,
            "diagnostic": self.diagnostic,
            "providers": [item.to_dict() for item in self.providers],
        }


def _first_contract(
    registry: ExternalContractRegistry, provider: str
) -> ExternalContract | None:
    matches = registry.provider(provider)
    return matches[0] if matches else None


def _required_env(contract: ExternalContract | None) -> tuple[str, ...]:
    if contract is None or contract.conformance_probe is None:
        return ()
    probe = contract.conformance_probe
    if probe.required_env:
        return probe.required_env
    if probe.credential_env:
        return (probe.credential_env,)
    return ()


def _missing_env(
    contract: ExternalContract | None,
    environ: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(name for name in _required_env(contract) if not environ.get(name))


def _missing_evidence(contract: ExternalContract, provider: str) -> tuple[str, ...]:
    evidence = contract.evidence
    names = _REQUIRED_EVIDENCE.get(provider, ())
    return tuple(
        f"evidence-missing:{name}"
        for name in names
        if getattr(evidence, name) is not True
    )


def _conformance_blocker(
    result: ConformanceResult,
    *,
    online_enabled: bool,
) -> str | None:
    if result.verified:
        return None
    if not online_enabled:
        return "credentialed-conformance-not-run"
    return f"credentialed-conformance-not-verified:{result.state}"


def _provider_readiness(
    provider: str,
    contract: ExternalContract | None,
    result: ConformanceResult | None,
    *,
    online_enabled: bool,
    environ: Mapping[str, str],
) -> B1ProviderReadiness:
    if contract is None:
        return B1ProviderReadiness(
            provider=provider,
            contract_id=None,
            status=None,
            promotion_state=None,
            execution_allowed=False,
            local_artifact_integrity=False,
            has_conformance_probe=False,
            conformance_state=None,
            conformance_verified=False,
            required_env=(),
            missing_env=(),
            can_feed_paper_vertical=False,
            blockers=("missing-external-contract",),
        )

    blockers: list[str] = []
    if contract.status.value != "active":
        blockers.append(f"contract-not-active:{contract.status.value}")
    if contract.evidence.local_artifact_integrity is not True:
        blockers.append("evidence-missing:local_artifact_integrity")
    blockers.extend(_missing_evidence(contract, provider))
    if contract.conformance_probe is None:
        blockers.append("missing-conformance-probe")
    missing = _missing_env(contract, environ)
    if missing:
        blockers.append("missing-credential-env:" + ",".join(missing))

    conformance_state = result.state if result is not None else None
    conformance_verified = bool(result and result.verified)
    if result is not None:
        blocker = _conformance_blocker(result, online_enabled=online_enabled)
        if blocker:
            blockers.append(blocker)

    if contract.execution_allowed:
        blockers.append("unexpected-execution-allowed-before-b1-review")

    can_feed = not blockers and conformance_verified and not contract.execution_allowed
    return B1ProviderReadiness(
        provider=provider,
        contract_id=contract.id,
        status=contract.status.value,
        promotion_state=contract.promotion_state.value,
        execution_allowed=contract.execution_allowed,
        local_artifact_integrity=contract.evidence.local_artifact_integrity,
        has_conformance_probe=contract.conformance_probe is not None,
        conformance_state=conformance_state,
        conformance_verified=conformance_verified,
        required_env=_required_env(contract),
        missing_env=missing,
        can_feed_paper_vertical=can_feed,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def evaluate_b1_provider_protocol_readiness(
    registry: ExternalContractRegistry | None = None,
    *,
    providers: Sequence[str] = DEFAULT_B1_PROVIDERS,
    enable_online: bool = False,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> B1ProviderProtocolReport:
    """Evaluate whether the MEGA-PR B1 providers may feed the paper vertical.

    The answer is intentionally stricter than registry integrity. Local pinned
    documentation and review snapshots are not enough: the provider must have the
    required evidence, credentialed conformance, and no execution promotion.
    """

    active_registry = registry or ExternalContractRegistry.load_default()
    active_env = os.environ if environ is None else environ

    reports: list[B1ProviderReadiness] = []
    for provider in tuple(dict.fromkeys(providers)):
        contract = _first_contract(active_registry, provider)
        result = None
        if contract is not None:
            result = run_read_only_conformance(
                contract,
                enable_online=enable_online,
                environ=active_env,
                transport=transport,
            )
        reports.append(
            _provider_readiness(
                provider,
                contract,
                result,
                online_enabled=enable_online,
                environ=active_env,
            )
        )

    ready = bool(reports) and all(item.can_feed_paper_vertical for item in reports)
    return B1ProviderProtocolReport(
        schema_version=B1_SCHEMA_VERSION,
        online_enabled=enable_online,
        paper_vertical_ready=ready,
        providers=tuple(reports),
        diagnostic="ready" if ready else "blocked-provider-protocol-conformance",
    )


def b1_exit_code(
    report: B1ProviderProtocolReport,
    *,
    require_ready: bool = False,
) -> int:
    if require_ready and not report.paper_vertical_ready:
        return 3
    return 0
