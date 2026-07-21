"""PR-103 unified immutable runtime truth and readiness graph.

This module is intentionally sender-free. It derives a single machine-readable
truth object from product mode, provider admission, credential/conformance
signals and paper-stage wiring so status/readiness surfaces cannot disagree with
execution admission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


PR103_RUNTIME_TRUTH_SCHEMA = "pr103.runtime-truth.v1"


class RuntimeTruthError(ValueError):
    """Raised when runtime truth inputs describe an impossible state."""


class ProductMode(StrEnum):
    OFFLINE = "offline"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE_DISABLED = "live-disabled"


class RuntimeState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class ProviderRole(StrEnum):
    DISABLED = "disabled"
    DISCOVERY_ONLY = "discovery-only"
    QUOTE_ONLY = "quote-only"
    IMMUTABLE_TRANSACTION = "immutable-transaction"
    EXECUTABLE = "executable"


class CredentialState(StrEnum):
    NOT_REQUIRED = "not-required"
    AVAILABLE = "available"
    MISSING = "missing"
    INVALID = "invalid"


class ConformanceState(StrEnum):
    VERIFIED = "verified"
    SKIPPED = "skipped"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class StageState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    BLOCKED = "blocked"


class ReadinessSurface(StrEnum):
    HEALTH = "health"
    READY = "ready"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class CredentialTruth:
    provider: str
    required: bool
    state: CredentialState
    reason: str = ""

    def __post_init__(self) -> None:
        _require_name(self.provider, field="credential.provider")
        if self.required and self.state == CredentialState.NOT_REQUIRED:
            raise RuntimeTruthError(
                f"credential {self.provider!r} is required but marked not-required"
            )
        if not self.required and self.state in {
            CredentialState.MISSING,
            CredentialState.INVALID,
        }:
            raise RuntimeTruthError(
                f"credential {self.provider!r} cannot be missing/invalid when not required"
            )

    @property
    def ready(self) -> bool:
        return self.state in {CredentialState.NOT_REQUIRED, CredentialState.AVAILABLE}

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "required": self.required,
            "state": self.state.value,
            "ready": self.ready,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ConformanceTruth:
    provider: str
    credentialed_api: ConformanceState
    execution_composition: ConformanceState
    promotion_evidence: ConformanceState
    human_reviewed: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        _require_name(self.provider, field="conformance.provider")

    @property
    def execution_verified(self) -> bool:
        return (
            self.credentialed_api == ConformanceState.VERIFIED
            and self.execution_composition == ConformanceState.VERIFIED
            and self.promotion_evidence == ConformanceState.VERIFIED
            and self.human_reviewed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "credentialed_api": self.credentialed_api.value,
            "execution_composition": self.execution_composition.value,
            "promotion_evidence": self.promotion_evidence.value,
            "human_reviewed": self.human_reviewed,
            "execution_verified": self.execution_verified,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ProviderTruth:
    name: str
    contract_execution_allowed: bool
    requested_role: ProviderRole
    credential: CredentialTruth
    conformance: ConformanceTruth
    local_schema_active: bool = True
    drift_free: bool = True
    request_ready: bool = False
    startup_ready: bool = False
    external_pin: str = ""
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_name(self.name, field="provider.name")
        if self.credential.provider != self.name:
            raise RuntimeTruthError("credential provider must match provider name")
        if self.conformance.provider != self.name:
            raise RuntimeTruthError("conformance provider must match provider name")
        if self.startup_ready and not self.request_ready:
            raise RuntimeTruthError(
                f"{self.name}: startup_ready cannot be true while request_ready is false"
            )
        if self.startup_ready and not self.credential.ready:
            raise RuntimeTruthError(
                f"{self.name}: missing/invalid credential cannot report startup ready"
            )
        if (
            self.requested_role == ProviderRole.EXECUTABLE
            and not self.contract_execution_allowed
        ):
            raise RuntimeTruthError(
                f"{self.name}: execution_allowed=false cannot request EXECUTABLE"
            )

    @property
    def admitted_role(self) -> ProviderRole:
        if not self.local_schema_active:
            return ProviderRole.DISABLED
        if not self.drift_free:
            return ProviderRole.DISABLED
        if not self.credential.ready:
            return ProviderRole.DISABLED
        if self.requested_role == ProviderRole.EXECUTABLE:
            if not self.contract_execution_allowed:
                return ProviderRole.DISABLED
            if not self.conformance.execution_verified:
                return ProviderRole.DISABLED
        return self.requested_role

    @property
    def executable(self) -> bool:
        return self.admitted_role == ProviderRole.EXECUTABLE

    @property
    def readiness_reasons(self) -> tuple[str, ...]:
        reasons = list(self.reasons)
        if not self.local_schema_active:
            reasons.append(f"{self.name}:local-schema-inactive")
        if not self.drift_free:
            reasons.append(f"{self.name}:local-drift-detected")
        if not self.credential.ready:
            reasons.append(f"{self.name}:credential-{self.credential.state.value}")
        if self.requested_role == ProviderRole.EXECUTABLE:
            if not self.contract_execution_allowed:
                reasons.append(f"{self.name}:contract-execution-denied")
            if not self.conformance.execution_verified:
                reasons.append(f"{self.name}:execution-conformance-unverified")
        if self.startup_ready != self.request_ready:
            reasons.append(f"{self.name}:startup-request-readiness-mismatch")
        return _dedupe(reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "contract_execution_allowed": self.contract_execution_allowed,
            "requested_role": self.requested_role.value,
            "admitted_role": self.admitted_role.value,
            "credential": self.credential.to_dict(),
            "conformance": self.conformance.to_dict(),
            "local_schema_active": self.local_schema_active,
            "drift_free": self.drift_free,
            "request_ready": self.request_ready,
            "startup_ready": self.startup_ready,
            "external_pin": self.external_pin,
            "readiness_reasons": list(self.readiness_reasons),
        }


@dataclass(frozen=True, slots=True)
class StageTruth:
    name: str
    state: StageState
    reason: str = ""

    def __post_init__(self) -> None:
        _require_name(self.name, field="stage.name")

    @property
    def ready(self) -> bool:
        return self.state == StageState.PRESENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "ready": self.ready,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RuntimeTruth:
    product_mode: ProductMode
    providers: Mapping[str, ProviderTruth]
    active_detector: str
    stages: Mapping[str, StageTruth]
    external_pins: Mapping[str, str] = field(default_factory=dict)
    trace_id: str = "pr103-runtime-truth"
    schema_version: str = PR103_RUNTIME_TRUTH_SCHEMA
    live_allowed: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != PR103_RUNTIME_TRUTH_SCHEMA:
            raise RuntimeTruthError("unsupported runtime truth schema")
        if self.live_allowed:
            raise RuntimeTruthError("PR-103 truth cannot enable live execution")
        _require_name(self.active_detector, field="runtime.active_detector")
        provider_map = _freeze_mapping(self.providers)
        stage_map = _freeze_mapping(self.stages)
        pin_map = _freeze_mapping(self.external_pins)
        object.__setattr__(self, "providers", provider_map)
        object.__setattr__(self, "stages", stage_map)
        object.__setattr__(self, "external_pins", pin_map)
        for name, provider in self.providers.items():
            if name != provider.name:
                raise RuntimeTruthError("provider mapping key must match provider name")
        for name, stage in self.stages.items():
            if name != stage.name:
                raise RuntimeTruthError("stage mapping key must match stage name")
        _assert_no_impossible_states(self)

    @property
    def active_providers(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, provider in self.providers.items()
            if provider.admitted_role != ProviderRole.DISABLED
        )

    @property
    def admitted_roles(self) -> Mapping[str, ProviderRole]:
        return MappingProxyType(
            {name: provider.admitted_role for name, provider in self.providers.items()}
        )

    @property
    def active_stages(self) -> tuple[str, ...]:
        return tuple(name for name, stage in self.stages.items() if stage.ready)

    @property
    def paper_ready(self) -> bool:
        required = _paper_required_stage_names()
        return all(self.stages.get(name, _absent_stage(name)).ready for name in required)

    @property
    def readiness_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for provider in self.providers.values():
            reasons.extend(provider.readiness_reasons)
        for stage in self.stages.values():
            if not stage.ready:
                reasons.append(f"stage:{stage.name}:{stage.state.value}")
                if stage.reason:
                    reasons.append(f"stage:{stage.name}:{stage.reason}")
        if not self.active_providers:
            reasons.append("no-active-providers")
        if self.product_mode in {ProductMode.PAPER, ProductMode.SHADOW} and not self.paper_ready:
            reasons.append("paper-stages-incomplete")
        return _dedupe(reasons)

    @property
    def state(self) -> RuntimeState:
        if self.product_mode == ProductMode.OFFLINE:
            return RuntimeState.READY
        if self.readiness_reasons:
            if not self.active_providers or not self.paper_ready:
                return RuntimeState.BLOCKED
            return RuntimeState.DEGRADED
        return RuntimeState.READY

    def surface(self, surface: ReadinessSurface) -> dict[str, Any]:
        payload = self.to_dict()
        if surface == ReadinessSurface.HEALTH:
            payload["ok"] = self.state != RuntimeState.BLOCKED
        elif surface == ReadinessSurface.READY:
            payload["ready"] = self.state == RuntimeState.READY
        elif surface == ReadinessSurface.STATUS:
            payload["status"] = self.state.value
        return payload

    def health_payload(self) -> dict[str, Any]:
        return self.surface(ReadinessSurface.HEALTH)

    def ready_payload(self) -> dict[str, Any]:
        return self.surface(ReadinessSurface.READY)

    def status_payload(self) -> dict[str, Any]:
        return self.surface(ReadinessSurface.STATUS)

    def metrics(self) -> dict[str, int]:
        return {
            "runtime_truth_providers": len(self.providers),
            "runtime_truth_active_providers": len(self.active_providers),
            "runtime_truth_stages": len(self.stages),
            "runtime_truth_active_stages": len(self.active_stages),
            "runtime_truth_blocking_reasons": len(self.readiness_reasons),
            "runtime_truth_live_allowed": int(self.live_allowed),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "product_mode": self.product_mode.value,
            "state": self.state.value,
            "live_allowed": self.live_allowed,
            "active_detector": self.active_detector,
            "active_providers": list(self.active_providers),
            "admitted_roles": {
                name: role.value for name, role in self.admitted_roles.items()
            },
            "providers": {
                name: provider.to_dict() for name, provider in self.providers.items()
            },
            "active_stages": list(self.active_stages),
            "paper_ready": self.paper_ready,
            "stages": {name: stage.to_dict() for name, stage in self.stages.items()},
            "external_pins": dict(self.external_pins),
            "readiness_reasons": list(self.readiness_reasons),
            "metrics": self.metrics(),
        }


@dataclass(frozen=True, slots=True)
class RuntimeTruthInputs:
    product_mode: ProductMode
    providers: Sequence[ProviderTruth]
    active_detector: str
    stages: Sequence[StageTruth]
    external_pins: Mapping[str, str] = field(default_factory=dict)
    trace_id: str = "pr103-runtime-truth"


def build_runtime_truth(inputs: RuntimeTruthInputs) -> RuntimeTruth:
    return RuntimeTruth(
        product_mode=inputs.product_mode,
        providers={provider.name: provider for provider in inputs.providers},
        active_detector=inputs.active_detector,
        stages={stage.name: stage for stage in inputs.stages},
        external_pins=inputs.external_pins,
        trace_id=inputs.trace_id,
    )


def assert_runtime_truth_safe(truth: RuntimeTruth) -> None:
    _assert_no_impossible_states(truth)


def _assert_no_impossible_states(truth: RuntimeTruth) -> None:
    for provider in truth.providers.values():
        if (
            provider.contract_execution_allowed is False
            and provider.admitted_role == ProviderRole.EXECUTABLE
        ):
            raise RuntimeTruthError(
                f"{provider.name}: execution_allowed=false + EXECUTABLE is impossible"
            )
        if not provider.credential.ready and provider.startup_ready:
            raise RuntimeTruthError(f"{provider.name}: missing key + startup ready")
    if truth.product_mode in {ProductMode.PAPER, ProductMode.SHADOW}:
        for name in _paper_required_stage_names():
            if truth.stages.get(name, _absent_stage(name)).state != StageState.PRESENT:
                if truth.paper_ready:
                    raise RuntimeTruthError("stage absent + paper-ready=true is impossible")


def _paper_required_stage_names() -> tuple[str, ...]:
    return (
        "capital_sizing",
        "planner",
        "compiler",
        "final_simulation",
        "reconciliation",
    )


def _absent_stage(name: str) -> StageTruth:
    return StageTruth(name=name, state=StageState.ABSENT, reason="not-declared")


def _freeze_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _require_name(value: str, *, field: str) -> None:
    if not value or not value.strip():
        raise RuntimeTruthError(f"{field} must be non-empty")


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "PR103_RUNTIME_TRUTH_SCHEMA",
    "ConformanceState",
    "ConformanceTruth",
    "CredentialState",
    "CredentialTruth",
    "ProductMode",
    "ProviderRole",
    "ProviderTruth",
    "ReadinessSurface",
    "RuntimeState",
    "RuntimeTruth",
    "RuntimeTruthError",
    "RuntimeTruthInputs",
    "StageState",
    "StageTruth",
    "assert_runtime_truth_safe",
    "build_runtime_truth",
]
