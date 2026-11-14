"""SX-10 permitted-backrun auction replay and cost ledger (RESEARCH_ONLY).

Deterministic, offline replay of protocol-permitted backrun opportunities
over an ordered transaction stream. This module is RESEARCH ONLY and its
exclusions are part of its contract:

- it never builds, signs, sends or submits transactions; it imports no
  sender, no bundle/relay/submission module and no Jito client of any
  kind, and performs no network or file I/O;
- it models only public / protocol-permitted orderflow. Any input that
  declares a sandwich, frontrun or user-targeting pattern is refused
  with ``PolicyViolation``; a backrun attempt without the explicit
  ``protocol_permitted_backrun=True`` flag is likewise refused;
- a permitted-backrun candidate is valid only when (a) flow
  authorization is proven (public/protocol-permitted; otherwise the
  typed blocker ``flow_authorization_unproven`` is recorded and no
  candidate is produced), (b) ``protocol_permitted_backrun=True`` is
  explicit, and (c) the candidate reads a resource written by an
  earlier transaction in the same slot with state-before/state-after
  versions consistent (otherwise it is excluded, as
  ``state_dependency_stale`` when the observation is stale);
- inclusion probability comes only from supplied empirical calibration
  observations. Absent or insufficient observations yield the typed
  blocker ``inclusion_probability_uncalibrated`` and expected-value
  claims are refused in code;
- unknown cost fields stay ``None`` and are never treated as zero
  ("unknown is not zero"); realized settlement outcomes are recorded
  with typed reasons.

Family: MEV-BACKRUN (RESEARCH_ONLY) per
docs/strategy-expansion/2026-11-14/STRATEGY_ACCEPTANCE_MATRIX.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence

from .core import (
    EvolutionError,
    TypedBlocker,
    require_nonnegative,
    require_ppm,
    require_text,
    stable_hash,
)

EXECUTION_CLASS = "RESEARCH_ONLY"
SUBMISSION_ENABLED = False

MIN_CALIBRATION_OBSERVATIONS = 30
PROBABILITY_SCALE_PPM = 1_000_000


class PolicyViolation(EvolutionError):
    """Input models prohibited MEV or an unpermitted backrun claim."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code)
        self.detail = require_text(detail, "detail")


class FlowAuthorization(StrEnum):
    PUBLIC_ORDERFLOW = "public_orderflow"
    PROTOCOL_PERMITTED = "protocol_permitted"
    UNKNOWN = "unknown"


AUTHORIZED_FLOW: tuple[FlowAuthorization, ...] = (
    FlowAuthorization.PUBLIC_ORDERFLOW,
    FlowAuthorization.PROTOCOL_PERMITTED,
)


class SettlementOutcome(StrEnum):
    INCLUDED = "included"
    INCLUDED_REVERTED = "included_reverted"
    NOT_INCLUDED = "not_included"


@dataclass(frozen=True)
class CostLedger:
    """Exact cost ledger; ``None`` means unknown and is never treated as 0."""

    priority_fee_tip_atoms: int | None = None
    compute_budget_units: int | None = None
    revert_cost_atoms: int | None = None

    def __post_init__(self) -> None:
        if self.priority_fee_tip_atoms is not None:
            require_nonnegative(self.priority_fee_tip_atoms, "priority_fee_tip_atoms")
        if self.compute_budget_units is not None:
            require_nonnegative(self.compute_budget_units, "compute_budget_units")
        if self.revert_cost_atoms is not None:
            require_nonnegative(self.revert_cost_atoms, "revert_cost_atoms")

    @classmethod
    def unknown(cls) -> CostLedger:
        return cls()


@dataclass(frozen=True)
class SettlementRecord:
    """Realized settlement outcome with a typed reason."""

    outcome: SettlementOutcome
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, SettlementOutcome):
            raise EvolutionError("SETTLEMENT_OUTCOME_UNTYPED")
        require_text(self.reason_code, "reason_code")


@dataclass(frozen=True)
class InclusionCalibration:
    """Empirical inclusion calibration from observed attempt/inclusion counts."""

    attempts_observed: int
    inclusions_observed: int

    def __post_init__(self) -> None:
        require_nonnegative(self.attempts_observed, "attempts_observed")
        require_nonnegative(self.inclusions_observed, "inclusions_observed")
        if self.inclusions_observed > self.attempts_observed:
            raise EvolutionError("CALIBRATION_COUNTS_INVALID")

    @property
    def is_calibrated(self) -> bool:
        return self.attempts_observed >= MIN_CALIBRATION_OBSERVATIONS

    @property
    def probability_ppm(self) -> int:
        if self.attempts_observed == 0:
            raise EvolutionError("CALIBRATION_EMPTY")
        if not self.is_calibrated:
            raise EvolutionError("INCLUSION_PROBABILITY_UNCALIBRATED")
        return (
            self.inclusions_observed * PROBABILITY_SCALE_PPM
        ) // self.attempts_observed


@dataclass(frozen=True)
class TxEvent:
    """One transaction of the ordered stream with resource reads/writes."""

    tx_id: str
    slot: int
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    flow_authorization: FlowAuthorization = FlowAuthorization.UNKNOWN
    protocol_permitted_backrun: bool = False
    backrun_attempt: bool = False
    prohibited_patterns: tuple[str, ...] = ()
    observed_versions: tuple[tuple[str, int], ...] = ()
    cost: CostLedger | None = None

    def __post_init__(self) -> None:
        require_text(self.tx_id, "tx_id")
        require_nonnegative(self.slot, "slot")
        if not isinstance(self.flow_authorization, FlowAuthorization):
            raise EvolutionError("FLOW_AUTHORIZATION_UNTYPED")
        if not isinstance(self.protocol_permitted_backrun, bool):
            raise EvolutionError("TX_FLAG_NOT_BOOLEAN")
        if not isinstance(self.backrun_attempt, bool):
            raise EvolutionError("TX_FLAG_NOT_BOOLEAN")
        for resource in self.reads:
            require_text(resource, "read_resource")
        for resource in self.writes:
            require_text(resource, "write_resource")
        for pattern in self.prohibited_patterns:
            require_text(pattern, "prohibited_pattern")
        seen: set[str] = set()
        for resource, version in self.observed_versions:
            resource_text = require_text(resource, "observed_resource")
            require_nonnegative(version, "observed_version")
            if resource_text in seen:
                raise EvolutionError("OBSERVED_VERSION_DUPLICATE")
            seen.add(resource_text)
        if self.cost is not None and not isinstance(self.cost, CostLedger):
            raise EvolutionError("COST_LEDGER_UNTYPED")


@dataclass(frozen=True)
class BackrunDependency:
    """Same-slot state dependency: candidate reads a resource an earlier tx wrote."""

    resource: str
    writer_tx_id: str
    writer_index: int
    version_before: int
    version_after: int

    def __post_init__(self) -> None:
        require_text(self.resource, "resource")
        require_text(self.writer_tx_id, "writer_tx_id")
        require_nonnegative(self.writer_index, "writer_index")
        require_nonnegative(self.version_before, "version_before")
        require_nonnegative(self.version_after, "version_after")
        if self.version_after <= self.version_before:
            raise EvolutionError("DEPENDENCY_VERSION_NOT_ADVANCED")


@dataclass(frozen=True)
class CandidateExclusion:
    """Deterministic per-event exclusion with a typed reason."""

    stream_index: int
    tx_id: str
    code: str
    detail: str

    def __post_init__(self) -> None:
        require_nonnegative(self.stream_index, "stream_index")
        require_text(self.tx_id, "tx_id")
        require_text(self.code, "code")
        require_text(self.detail, "detail")


@dataclass(frozen=True)
class BackrunCandidate:
    """Permitted-backrun candidate emitted by a deterministic replay."""

    tx_id: str
    slot: int
    stream_index: int
    dependencies: tuple[BackrunDependency, ...]
    cost: CostLedger
    inclusion_probability_ppm: int | None
    calibration_attempts_observed: int | None
    settlement: SettlementRecord | None
    blockers: tuple[TypedBlocker, ...]

    def __post_init__(self) -> None:
        require_text(self.tx_id, "tx_id")
        require_nonnegative(self.slot, "slot")
        require_nonnegative(self.stream_index, "stream_index")
        for dependency in self.dependencies:
            if not isinstance(dependency, BackrunDependency):
                raise EvolutionError("DEPENDENCY_UNTYPED")
        if not isinstance(self.cost, CostLedger):
            raise EvolutionError("COST_LEDGER_UNTYPED")
        if self.inclusion_probability_ppm is not None:
            require_ppm(self.inclusion_probability_ppm, "inclusion_probability_ppm")
        if self.calibration_attempts_observed is not None:
            require_nonnegative(
                self.calibration_attempts_observed, "calibration_attempts_observed"
            )
        if self.settlement is not None and not isinstance(
            self.settlement, SettlementRecord
        ):
            raise EvolutionError("SETTLEMENT_RECORD_UNTYPED")
        for blocker in self.blockers:
            if not isinstance(blocker, TypedBlocker):
                raise EvolutionError("BLOCKER_UNTYPED")


@dataclass(frozen=True)
class AuctionReplayReport:
    """Deterministic replay report: candidates, exclusions, blockers, evidence."""

    event_count: int
    slot_count: int
    candidates: tuple[BackrunCandidate, ...]
    exclusions: tuple[CandidateExclusion, ...]
    blockers: tuple[TypedBlocker, ...]
    final_resource_versions: tuple[tuple[str, int], ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        require_nonnegative(self.event_count, "event_count")
        require_nonnegative(self.slot_count, "slot_count")
        for candidate in self.candidates:
            if not isinstance(candidate, BackrunCandidate):
                raise EvolutionError("CANDIDATE_UNTYPED")
        for exclusion in self.exclusions:
            if not isinstance(exclusion, CandidateExclusion):
                raise EvolutionError("EXCLUSION_UNTYPED")
        for blocker in self.blockers:
            if not isinstance(blocker, TypedBlocker):
                raise EvolutionError("BLOCKER_UNTYPED")
        seen: set[str] = set()
        resources: list[str] = []
        for resource, version in self.final_resource_versions:
            require_text(resource, "resource")
            require_nonnegative(version, "resource_version")
            if resource in seen:
                raise EvolutionError("RESOURCE_VERSION_DUPLICATE")
            seen.add(resource)
            resources.append(resource)
        if resources != sorted(resources):
            raise EvolutionError("RESOURCE_VERSIONS_UNSORTED")
        if len(self.evidence_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.evidence_hash
        ):
            raise EvolutionError("EVIDENCE_DIGEST_INVALID")


def assert_permitted_backrun_policy(event: TxEvent) -> None:
    """Refuse prohibited MEV patterns and unpermitted backrun attempts.

    No sandwich, frontrun or user-targeting pattern may ever enter the
    replay, and a backrun attempt without the explicit
    ``protocol_permitted_backrun=True`` flag is a policy violation.
    """
    if event.prohibited_patterns:
        raise PolicyViolation(
            "PROHIBITED_MEV_PATTERN",
            f"tx={event.tx_id} prohibited_patterns={','.join(event.prohibited_patterns)}",
        )
    if event.backrun_attempt and event.protocol_permitted_backrun is not True:
        raise PolicyViolation(
            "BACKRUN_NOT_PROTOCOL_PERMITTED",
            f"tx={event.tx_id} backrun_attempt without explicit protocol_permitted_backrun=True",
        )


def _ordered_unique(resources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for resource in resources:
        if resource not in seen:
            seen.add(resource)
            ordered.append(resource)
    return tuple(ordered)


def _validate_stream(events: tuple[TxEvent, ...]) -> None:
    seen_ids: set[str] = set()
    previous_slot: int | None = None
    for event in events:
        if event.tx_id in seen_ids:
            raise EvolutionError("TX_ID_DUPLICATE")
        seen_ids.add(event.tx_id)
        if previous_slot is not None and event.slot < previous_slot:
            raise EvolutionError("STREAM_SLOT_ORDER_INVALID")
        previous_slot = event.slot
        assert_permitted_backrun_policy(event)


def _validate_settlements(
    events: tuple[TxEvent, ...],
    settlements: Mapping[str, SettlementRecord] | None,
) -> dict[str, SettlementRecord]:
    if settlements is None:
        return {}
    known_ids = {event.tx_id for event in events}
    validated: dict[str, SettlementRecord] = {}
    for tx_id, record in settlements.items():
        if tx_id not in known_ids:
            raise EvolutionError("SETTLEMENT_TX_UNKNOWN")
        if not isinstance(record, SettlementRecord):
            raise EvolutionError("SETTLEMENT_RECORD_UNTYPED")
        validated[tx_id] = record
    return validated


def _calibration_blocker(calibration: InclusionCalibration | None) -> TypedBlocker:
    if calibration is None:
        detail = (
            "no calibration observations supplied; "
            f"minimum required is {MIN_CALIBRATION_OBSERVATIONS}"
        )
    else:
        detail = (
            f"attempts_observed={calibration.attempts_observed} "
            f"inclusions_observed={calibration.inclusions_observed} "
            f"below minimum required {MIN_CALIBRATION_OBSERVATIONS}"
        )
    return TypedBlocker("inclusion_probability_uncalibrated", detail)


def replay_permitted_backrun_auction(
    events: Sequence[TxEvent],
    *,
    calibration: InclusionCalibration | None = None,
    settlements: Mapping[str, SettlementRecord] | None = None,
) -> AuctionReplayReport:
    """Deterministically replay the ordered stream into permitted candidates.

    Ordinary flow events are context only. Events marked as permitted
    backruns are evaluated in stream order against exact resource state
    versions: authorization must be proven, a same-slot earlier writer
    must exist for at least one read, and any declared observed state
    version that contradicts the replayed post-write state excludes the
    candidate as ``state_dependency_stale``.
    """
    event_list = tuple(events)
    _validate_stream(event_list)
    settlement_map = _validate_settlements(event_list, settlements)

    blockers: list[TypedBlocker] = []
    candidates: list[BackrunCandidate] = []
    exclusions: list[CandidateExclusion] = []
    versions: dict[str, int] = {}
    slot_writer: dict[tuple[int, str], tuple[str, int, int, int]] = {}

    for index, event in enumerate(event_list):
        if event.protocol_permitted_backrun:
            if event.flow_authorization not in AUTHORIZED_FLOW:
                detail = (
                    f"tx={event.tx_id} "
                    f"flow_authorization={event.flow_authorization.value}"
                )
                blockers.append(TypedBlocker("flow_authorization_unproven", detail))
                exclusions.append(
                    CandidateExclusion(
                        stream_index=index,
                        tx_id=event.tx_id,
                        code="flow_authorization_unproven",
                        detail=detail,
                    )
                )
            else:
                dependencies: list[BackrunDependency] = []
                for resource in _ordered_unique(event.reads):
                    writer_entry = slot_writer.get((event.slot, resource))
                    if writer_entry is not None:
                        writer_tx_id, writer_index, before, after = writer_entry
                        dependencies.append(
                            BackrunDependency(
                                resource=resource,
                                writer_tx_id=writer_tx_id,
                                writer_index=writer_index,
                                version_before=before,
                                version_after=after,
                            )
                        )
                declared = dict(event.observed_versions)
                stale_detail: str | None = None
                for dependency in dependencies:
                    if (
                        dependency.resource in declared
                        and declared[dependency.resource] != dependency.version_after
                    ):
                        stale_detail = (
                            f"tx={event.tx_id} resource={dependency.resource} "
                            f"expected_version={dependency.version_after} "
                            f"observed_version={declared[dependency.resource]}"
                        )
                        break
                if not dependencies:
                    exclusions.append(
                        CandidateExclusion(
                            stream_index=index,
                            tx_id=event.tx_id,
                            code="dependency_absent",
                            detail=(
                                f"tx={event.tx_id} reads={','.join(event.reads) or '<none>'} "
                                "have no same-slot earlier writer"
                            ),
                        )
                    )
                elif stale_detail is not None:
                    exclusions.append(
                        CandidateExclusion(
                            stream_index=index,
                            tx_id=event.tx_id,
                            code="state_dependency_stale",
                            detail=stale_detail,
                        )
                    )
                else:
                    candidate_blockers: list[TypedBlocker] = []
                    probability_ppm: int | None = None
                    attempts_observed: int | None = None
                    if calibration is None or not calibration.is_calibrated:
                        candidate_blockers.append(_calibration_blocker(calibration))
                    else:
                        probability_ppm = calibration.probability_ppm
                        attempts_observed = calibration.attempts_observed
                    cost = (
                        event.cost if event.cost is not None else CostLedger.unknown()
                    )
                    candidates.append(
                        BackrunCandidate(
                            tx_id=event.tx_id,
                            slot=event.slot,
                            stream_index=index,
                            dependencies=tuple(dependencies),
                            cost=cost,
                            inclusion_probability_ppm=probability_ppm,
                            calibration_attempts_observed=attempts_observed,
                            settlement=settlement_map.get(event.tx_id),
                            blockers=tuple(candidate_blockers),
                        )
                    )
        for resource in event.writes:
            version_before = versions.get(resource, 0)
            version_after = version_before + 1
            versions[resource] = version_after
            slot_writer[(event.slot, resource)] = (
                event.tx_id,
                index,
                version_before,
                version_after,
            )

    payload = {
        "event_count": len(event_list),
        "slot_count": len({event.slot for event in event_list}),
        "candidates": [
            {
                "tx_id": candidate.tx_id,
                "slot": candidate.slot,
                "stream_index": candidate.stream_index,
                "dependencies": [
                    {
                        "resource": dependency.resource,
                        "writer_tx_id": dependency.writer_tx_id,
                        "writer_index": dependency.writer_index,
                        "version_before": dependency.version_before,
                        "version_after": dependency.version_after,
                    }
                    for dependency in candidate.dependencies
                ],
                "cost": {
                    "priority_fee_tip_atoms": candidate.cost.priority_fee_tip_atoms,
                    "compute_budget_units": candidate.cost.compute_budget_units,
                    "revert_cost_atoms": candidate.cost.revert_cost_atoms,
                },
                "inclusion_probability_ppm": candidate.inclusion_probability_ppm,
                "calibration_attempts_observed": candidate.calibration_attempts_observed,
                "settlement": (
                    None
                    if candidate.settlement is None
                    else {
                        "outcome": candidate.settlement.outcome.value,
                        "reason_code": candidate.settlement.reason_code,
                    }
                ),
                "blockers": [
                    {"code": blocker.code, "detail": blocker.detail}
                    for blocker in candidate.blockers
                ],
            }
            for candidate in candidates
        ],
        "exclusions": [
            {
                "stream_index": exclusion.stream_index,
                "tx_id": exclusion.tx_id,
                "code": exclusion.code,
                "detail": exclusion.detail,
            }
            for exclusion in exclusions
        ],
        "blockers": [
            {"code": blocker.code, "detail": blocker.detail} for blocker in blockers
        ],
        "final_resource_versions": sorted(versions.items()),
    }
    return AuctionReplayReport(
        event_count=len(event_list),
        slot_count=len({event.slot for event in event_list}),
        candidates=tuple(candidates),
        exclusions=tuple(exclusions),
        blockers=tuple(blockers),
        final_resource_versions=tuple(sorted(versions.items())),
        evidence_hash=stable_hash("sx10:backrun-auction-replay", payload),
    )


def realized_settlement_cost_atoms(
    ledger: CostLedger,
    record: SettlementRecord,
    *,
    compute_cost_atoms: int | None,
) -> int:
    """Exact realized cost atoms for a realized settlement outcome.

    Unknown ledger fields are never treated as zero: a proven priority
    fee/tip and compute cost are required for any included outcome, and a
    proven revert cost is additionally required when the transaction
    included but reverted. ``not_included`` realizes no fees under this
    research model.
    """
    if compute_cost_atoms is None:
        raise EvolutionError("COMPUTE_COST_UNKNOWN")
    compute = require_nonnegative(compute_cost_atoms, "compute_cost_atoms")
    if record.outcome is SettlementOutcome.NOT_INCLUDED:
        return 0
    if ledger.priority_fee_tip_atoms is None:
        raise EvolutionError("PRIORITY_FEE_UNKNOWN")
    if record.outcome is SettlementOutcome.INCLUDED:
        return ledger.priority_fee_tip_atoms + compute
    if ledger.revert_cost_atoms is None:
        raise EvolutionError("REVERT_COST_UNKNOWN")
    return ledger.priority_fee_tip_atoms + compute + ledger.revert_cost_atoms


def expected_value_atoms(
    candidate: BackrunCandidate,
    *,
    gross_value_atoms: int,
    compute_cost_atoms: int | None,
) -> int:
    """Exact integer expected value from calibrated probability and proven costs.

    Refuses expected-value claims in code when the candidate's inclusion
    probability is uncalibrated or when any required cost field is unknown
    (``None`` is never treated as zero). Integer arithmetic only; the
    result is floored to whole atoms.
    """
    gross = require_nonnegative(gross_value_atoms, "gross_value_atoms")
    if candidate.inclusion_probability_ppm is None:
        raise EvolutionError("INCLUSION_PROBABILITY_UNCALIBRATED")
    if candidate.cost.priority_fee_tip_atoms is None:
        raise EvolutionError("PRIORITY_FEE_UNKNOWN")
    if candidate.cost.revert_cost_atoms is None:
        raise EvolutionError("REVERT_COST_UNKNOWN")
    if compute_cost_atoms is None:
        raise EvolutionError("COMPUTE_COST_UNKNOWN")
    compute = require_nonnegative(compute_cost_atoms, "compute_cost_atoms")
    net_if_included = gross - candidate.cost.priority_fee_tip_atoms - compute
    probability = candidate.inclusion_probability_ppm
    complement = PROBABILITY_SCALE_PPM - probability
    revert_cost = candidate.cost.revert_cost_atoms
    return (
        net_if_included * probability - revert_cost * complement
    ) // PROBABILITY_SCALE_PPM
