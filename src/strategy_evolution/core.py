"""Immutable sender-free kernel for PR-353 strategy-evolution research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from src.strategy.domain import Opportunity


class EvolutionError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EvolutionState(StrEnum):
    DISABLED = "DISABLED"
    RECORDED_OFFLINE = "RECORDED_OFFLINE"
    SHADOW_CANDIDATE = "SHADOW_CANDIDATE"
    VERIFIED_SHADOW = "VERIFIED_SHADOW"
    REJECTED_WITH_EVIDENCE = "REJECTED_WITH_EVIDENCE"


FINALITIES = {"ROOTED", "FINALIZED"}
SECRET_FIELDS = {
    "private_key",
    "secret_key",
    "auth_header",
    "authorization",
    "signed_transaction",
    "raw_signed_transaction",
}


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvolutionError(f"{field.upper()}_REQUIRED")
    return value.strip()


def require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvolutionError(f"{field.upper()}_INTEGER_REQUIRED")
    return value


def require_nonnegative(value: object, field: str) -> int:
    parsed = require_int(value, field)
    if parsed < 0:
        raise EvolutionError(f"{field.upper()}_NEGATIVE")
    return parsed


def require_positive(value: object, field: str) -> int:
    parsed = require_int(value, field)
    if parsed <= 0:
        raise EvolutionError(f"{field.upper()}_POSITIVE_REQUIRED")
    return parsed


def require_ppm(value: object, field: str) -> int:
    parsed = require_nonnegative(value, field)
    if parsed > 1_000_000:
        raise EvolutionError(f"{field.upper()}_PPM_OUT_OF_RANGE")
    return parsed


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise EvolutionError("UNSUPPORTED_RESEARCH_VALUE")


def stable_hash(domain: str, value: Any) -> str:
    payload = {"domain": require_text(domain, "domain"), "value": _canonical(value)}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reject_secret_material(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in SECRET_FIELDS and item not in (None, "", False):
                raise EvolutionError("SECRET_DETECTED")
            reject_secret_material(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_secret_material(item)


@dataclass(frozen=True, slots=True)
class EvolutionEvidenceRef:
    source_id: str
    digest: str
    observed_at: int
    finality: str

    def __post_init__(self) -> None:
        require_text(self.source_id, "source_id")
        if len(self.digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.digest
        ):
            raise EvolutionError("EVIDENCE_DIGEST_INVALID")
        require_nonnegative(self.observed_at, "observed_at")
        if self.finality not in FINALITIES:
            raise EvolutionError("UNFINALIZED_EVIDENCE")


@dataclass(frozen=True, slots=True)
class EventClock:
    chain_domain: str
    mode: str
    event_time: int
    observed_time: int

    def __post_init__(self) -> None:
        require_text(self.chain_domain, "chain_domain")
        if self.mode not in {"BLOCK", "SLOT", "TIMESTAMP", "EPOCH"}:
            raise EvolutionError("AMBIGUOUS_CLOCK")
        if require_nonnegative(
            self.observed_time, "observed_time"
        ) < require_nonnegative(self.event_time, "event_time"):
            raise EvolutionError("CLOCK_UNTRUSTED")


@dataclass(frozen=True, slots=True)
class ValueBand:
    low_atoms: int
    high_atoms: int
    unit: str

    def __post_init__(self) -> None:
        low = require_int(self.low_atoms, "low_atoms")
        high = require_int(self.high_atoms, "high_atoms")
        require_text(self.unit, "unit")
        if high < low:
            raise EvolutionError("BAND_INVERTED")


@dataclass(frozen=True, slots=True)
class LifecycleState:
    state: str
    sequence: int
    terminal: bool = False

    def __post_init__(self) -> None:
        require_text(self.state, "state")
        require_nonnegative(self.sequence, "sequence")


@dataclass(frozen=True, slots=True)
class TypedBlocker:
    code: str
    detail: str
    retryable: bool = False

    def __post_init__(self) -> None:
        require_text(self.code, "code")
        require_text(self.detail, "detail")


@dataclass(frozen=True, slots=True)
class CoverageCell:
    domain: str
    shape: str
    horizon: str
    state: str
    tradability: str
    evidence_quality: str
    status: str


@dataclass(frozen=True, slots=True)
class CorrelationHypothesis:
    hypothesis_id: str
    source_ids: tuple[str, ...]
    lag_min: int
    lag_max: int
    preregistered: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.hypothesis_id, "hypothesis_id")
        if not self.preregistered:
            raise EvolutionError("HYPOTHESIS_NOT_PREREGISTERED")
        if self.lag_max < self.lag_min:
            raise EvolutionError("LAG_UNSTABLE")
        if not self.source_ids:
            raise EvolutionError("SOURCE_REQUIRED")


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    schema_version: str
    strategy_id: str
    candidate_type: str
    chain_domain: str
    detected_at: int
    event_time: int
    finality: str
    expires_at: int
    input_atoms: int
    output_atoms: int
    cost_band: ValueBand
    value_band: ValueBand
    capacity_band: ValueBand
    scenario_ids: tuple[str, ...]
    evidence_refs: tuple[EvolutionEvidenceRef, ...]
    config_digest: str
    code_sha: str
    blockers: tuple[TypedBlocker, ...]
    state: EvolutionState
    candidate_id: str = ""

    def __post_init__(self) -> None:
        detected = require_nonnegative(self.detected_at, "detected_at")
        event = require_nonnegative(self.event_time, "event_time")
        expires = require_nonnegative(self.expires_at, "expires_at")
        if detected < event or expires <= detected:
            raise EvolutionError("CANDIDATE_CLOCK_INVALID")
        if self.finality not in FINALITIES:
            raise EvolutionError("UNFINALIZED_EVIDENCE")
        require_nonnegative(self.input_atoms, "input_atoms")
        require_nonnegative(self.output_atoms, "output_atoms")
        if self.value_band.low_atoms - self.cost_band.high_atoms <= 0:
            raise EvolutionError("NONPOSITIVE_WORST_CASE")
        if not self.scenario_ids or not self.evidence_refs:
            raise EvolutionError("MISSING_LINEAGE")
        if len(self.config_digest) != 64 or len(self.code_sha) != 40:
            raise EvolutionError("LINEAGE_DIGEST_INVALID")
        if self.state not in {
            EvolutionState.SHADOW_CANDIDATE,
            EvolutionState.VERIFIED_SHADOW,
            EvolutionState.REJECTED_WITH_EVIDENCE,
        }:
            raise EvolutionError("INVALID_CANDIDATE_STATE")
        payload = {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "candidate_type": self.candidate_type,
            "chain_domain": self.chain_domain,
            "detected_at": detected,
            "event_time": event,
            "finality": self.finality,
            "expires_at": expires,
            "input_atoms": self.input_atoms,
            "output_atoms": self.output_atoms,
            "cost_band": asdict(self.cost_band),
            "value_band": asdict(self.value_band),
            "capacity_band": asdict(self.capacity_band),
            "scenario_ids": self.scenario_ids,
            "evidence_refs": tuple(asdict(ref) for ref in self.evidence_refs),
            "config_digest": self.config_digest,
            "code_sha": self.code_sha,
            "blockers": tuple(asdict(item) for item in self.blockers),
            "state": self.state.value,
        }
        digest = stable_hash("pr353:research-candidate", payload)
        if self.candidate_id and self.candidate_id != digest:
            raise EvolutionError("CANDIDATE_ID_MISMATCH")
        object.__setattr__(self, "candidate_id", digest)


@dataclass(frozen=True, slots=True)
class QualificationArtifact:
    strategy_id: str
    candidate_id: str
    state: EvolutionState
    replay_count: int
    evidence_digest: str
    metrics: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    contract: str
    payload: Mapping[str, Any]
    evidence_hash: str
    state: EvolutionState = EvolutionState.RECORDED_OFFLINE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "payload", MappingProxyType(dict(_canonical(self.payload)))
        )


def result(contract: str, payload: Mapping[str, Any]) -> EvolutionResult:
    reject_secret_material(payload)
    normalized = _canonical(payload)
    return EvolutionResult(
        contract=contract,
        payload=normalized,
        evidence_hash=stable_hash(f"pr353:{contract}", normalized),
    )


def contract(
    name: str,
    payload: Mapping[str, Any],
    *,
    required: Sequence[str] = (),
    integer_fields: Sequence[str] = (),
    finality: bool = False,
    positive_edge: bool = False,
) -> EvolutionResult:
    data = dict(payload)
    reject_secret_material(data)
    for field in required:
        if field not in data or data[field] is None:
            raise EvolutionError(f"{field.upper()}_MISSING")
    for field in integer_fields:
        if field in data:
            require_int(data[field], field)
    if finality and data.get("finality") not in FINALITIES:
        raise EvolutionError("UNFINALIZED_EVIDENCE")
    if "event_time" in data and "observed_time" in data:
        if int(data["observed_time"]) < int(data["event_time"]):
            raise EvolutionError("CLOCK_UNTRUSTED")
    if positive_edge:
        value_low = require_int(data.get("value_low_atoms"), "value_low_atoms")
        cost_high = require_nonnegative(data.get("cost_high_atoms"), "cost_high_atoms")
        worst = value_low - cost_high
        if worst <= 0:
            raise EvolutionError("NEGATIVE_EDGE")
        data["worst_case_net_atoms"] = worst
    return result(name, data)


def evidence_ref(
    source_id: str,
    payload: Mapping[str, Any],
    *,
    observed_at: int,
    finality: str,
) -> EvolutionEvidenceRef:
    return EvolutionEvidenceRef(
        source_id,
        stable_hash(f"pr353:evidence:{source_id}", payload),
        observed_at,
        finality,
    )


def build_candidate(
    strategy_id: str,
    candidate_type: str,
    payload: Mapping[str, Any],
) -> ResearchCandidate:
    data = dict(payload)
    refs = tuple(data.get("evidence_refs", ()))
    if any(not isinstance(ref, EvolutionEvidenceRef) for ref in refs):
        raise EvolutionError("MISSING_LINEAGE")
    return ResearchCandidate(
        schema_version=str(data.get("schema_version", "pr353.strategy-evolution.v1")),
        strategy_id=strategy_id,
        candidate_type=candidate_type,
        chain_domain=require_text(data.get("chain_domain"), "chain_domain"),
        detected_at=require_nonnegative(data.get("detected_at"), "detected_at"),
        event_time=require_nonnegative(data.get("event_time"), "event_time"),
        finality=require_text(data.get("finality"), "finality"),
        expires_at=require_nonnegative(data.get("expires_at"), "expires_at"),
        input_atoms=require_nonnegative(data.get("input_atoms"), "input_atoms"),
        output_atoms=require_nonnegative(data.get("output_atoms"), "output_atoms"),
        cost_band=ValueBand(
            require_nonnegative(data.get("cost_low_atoms"), "cost_low_atoms"),
            require_nonnegative(data.get("cost_high_atoms"), "cost_high_atoms"),
            str(data.get("unit", "atoms")),
        ),
        value_band=ValueBand(
            require_int(data.get("value_low_atoms"), "value_low_atoms"),
            require_int(data.get("value_high_atoms"), "value_high_atoms"),
            str(data.get("unit", "atoms")),
        ),
        capacity_band=ValueBand(
            require_nonnegative(data.get("capacity_low_atoms"), "capacity_low_atoms"),
            require_nonnegative(data.get("capacity_high_atoms"), "capacity_high_atoms"),
            str(data.get("unit", "atoms")),
        ),
        scenario_ids=tuple(str(item) for item in data.get("scenario_ids", ())),
        evidence_refs=refs,
        config_digest=require_text(data.get("config_digest"), "config_digest"),
        code_sha=require_text(data.get("code_sha"), "code_sha"),
        blockers=(),
        state=EvolutionState.SHADOW_CANDIDATE,
    )


def qualify_candidate(
    candidate: ResearchCandidate,
    *,
    replay_count: int,
    minimum_replays: int,
    policy_passed: bool,
    drift: bool = False,
    tail_risk_bounded: bool = True,
    false_positive_ppm: int = 0,
) -> QualificationArtifact:
    count = require_positive(replay_count, "replay_count")
    if count < require_positive(minimum_replays, "minimum_replays"):
        raise EvolutionError("INSUFFICIENT_REPLAY")
    if drift:
        raise EvolutionError("DRIFT")
    if not tail_risk_bounded:
        raise EvolutionError("TAIL_LOSS_EXCEEDS_LIMIT")
    if not policy_passed:
        raise EvolutionError("POLICY_REJECTED")
    fp = require_ppm(false_positive_ppm, "false_positive_ppm")
    digest = stable_hash(
        "pr353:qualification",
        {"candidate_id": candidate.candidate_id, "count": count, "fp_ppm": fp},
    )
    return QualificationArtifact(
        candidate.strategy_id,
        candidate.candidate_id,
        EvolutionState.VERIFIED_SHADOW,
        count,
        digest,
        MappingProxyType({"false_positive_ppm": fp}),
    )


def assert_transition(
    current: str, target: str, allowed: Mapping[str, Sequence[str]]
) -> None:
    if target not in tuple(allowed.get(current, ())):
        raise EvolutionError("ILLEGAL_TRANSITION")


def shadow_opportunity_adapter(
    candidate: ResearchCandidate,
    *,
    detection_slot: int,
    input_mint: str,
    output_mint: str,
) -> Opportunity:
    if candidate.state is not EvolutionState.VERIFIED_SHADOW:
        raise EvolutionError("CANDIDATE_NOT_VERIFIED_SHADOW")
    return Opportunity(
        strategy_name=candidate.strategy_id,
        opportunity_type=f"research:{candidate.candidate_type}",
        detected_at=float(candidate.detected_at),
        detection_slot=require_nonnegative(detection_slot, "detection_slot"),
        input_mint=input_mint,
        output_mint=output_mint,
        proposed_amount_base_units=max(1, candidate.input_atoms),
        expected_gross_profit=(
            candidate.value_band.low_atoms - candidate.cost_band.high_atoms
        ),
        expires_at=float(candidate.expires_at),
        metadata={
            "pr353_candidate_id": candidate.candidate_id,
            "research_only": True,
            "live_authority": False,
        },
    )
