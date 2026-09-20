"""Point-in-time market membership and survivorship contracts for SUPER-01.

This module extends the existing AGG-02 market/data authority. It is offline and
effect-free: lifecycle evidence may influence research-universe membership, but
never grants signing, submission, or live-trading authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Iterable, Sequence

from .contracts import Agg02Error, canonical_hash

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarketLifecycleState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MIGRATED = "migrated"
    CLOSED = "closed"
    UNKNOWN = "unknown"


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg02Error(f"SUPER01_INVALID_{label.upper()}")
    return value


def _nonnegative_int(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise Agg02Error(f"SUPER01_INVALID_{label.upper()}")
    return value


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise Agg02Error(f"SUPER01_INVALID_{label.upper()}")
    return value


def _sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Agg02Error(f"SUPER01_INVALID_{label.upper()}")
    return value


@dataclass(frozen=True, slots=True)
class MarketLifecycleFact:
    event_id: str
    market_id: str
    state: MarketLifecycleState
    effective_at_ms: int
    observed_at_ms: int
    source_evidence_sha256: str
    revision: int
    related_market_id: str | None = None
    supersedes_event_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        _text(self.market_id, "market_id")
        _nonnegative_int(self.effective_at_ms, "effective_at_ms")
        _nonnegative_int(self.observed_at_ms, "observed_at_ms")
        _sha256(self.source_evidence_sha256, "source_evidence_sha256")
        _positive_int(self.revision, "revision")
        if self.related_market_id is not None:
            _text(self.related_market_id, "related_market_id")
            if self.related_market_id == self.market_id:
                raise Agg02Error("SUPER01_SELF_RELATED_MARKET")
        if self.supersedes_event_id is not None:
            _text(self.supersedes_event_id, "supersedes_event_id")
            if self.supersedes_event_id == self.event_id:
                raise Agg02Error("SUPER01_SELF_SUPERSESSION")
        if (
            self.state is MarketLifecycleState.MIGRATED
            and self.related_market_id is None
        ):
            raise Agg02Error("SUPER01_MIGRATION_TARGET_REQUIRED")

    @property
    def fact_hash(self) -> str:
        return canonical_hash(
            {
                "event_id": self.event_id,
                "market_id": self.market_id,
                "state": self.state.value,
                "effective_at_ms": self.effective_at_ms,
                "observed_at_ms": self.observed_at_ms,
                "source_evidence_sha256": self.source_evidence_sha256,
                "revision": self.revision,
                "related_market_id": self.related_market_id,
                "supersedes_event_id": self.supersedes_event_id,
            }
        )


def record_market_lifecycle_evidence(
    *,
    event_id: str,
    market_id: str,
    state: MarketLifecycleState,
    effective_at_ms: int,
    observed_at_ms: int,
    source_evidence_sha256: str,
    revision: int,
    related_market_id: str | None = None,
    supersedes_event_id: str | None = None,
) -> MarketLifecycleFact:
    return MarketLifecycleFact(
        event_id=event_id,
        market_id=market_id,
        state=state,
        effective_at_ms=effective_at_ms,
        observed_at_ms=observed_at_ms,
        source_evidence_sha256=source_evidence_sha256,
        revision=revision,
        related_market_id=related_market_id,
        supersedes_event_id=supersedes_event_id,
    )


@dataclass(frozen=True, slots=True)
class MarketMembershipInterval:
    market_id: str
    state: MarketLifecycleState
    valid_from_ms: int
    valid_to_ms: int | None
    known_from_ms: int
    source_event_id: str
    source_fact_hash: str
    revision: int
    related_market_id: str | None = None

    def contains(self, instant_ms: int) -> bool:
        if instant_ms < self.valid_from_ms:
            return False
        return self.valid_to_ms is None or instant_ms < self.valid_to_ms


def _facts_digest(facts: Sequence[MarketLifecycleFact]) -> str:
    return canonical_hash(tuple((fact.event_id, fact.fact_hash) for fact in facts))


def _selected_facts(
    facts: Iterable[MarketLifecycleFact],
    *,
    dataset_revision: int,
    knowledge_cutoff_ms: int | None,
) -> tuple[MarketLifecycleFact, ...]:
    _positive_int(dataset_revision, "dataset_revision")
    if knowledge_cutoff_ms is not None:
        _nonnegative_int(knowledge_cutoff_ms, "knowledge_cutoff_ms")
    eligible = [
        fact
        for fact in facts
        if fact.revision <= dataset_revision
        and (
            knowledge_cutoff_ms is None
            or fact.observed_at_ms <= knowledge_cutoff_ms
        )
    ]
    by_id: dict[str, MarketLifecycleFact] = {}
    for fact in eligible:
        previous = by_id.get(fact.event_id)
        if previous is not None and previous != fact:
            raise Agg02Error("SUPER01_EVENT_IDENTITY_CONFLICT")
        by_id[fact.event_id] = fact

    for fact in by_id.values():
        if fact.supersedes_event_id is None:
            continue
        superseded = by_id.get(fact.supersedes_event_id)
        if superseded is None:
            raise Agg02Error("SUPER01_UNRESOLVED_REVISION_LINK")
        if fact.revision <= superseded.revision:
            raise Agg02Error("SUPER01_SUPERSESSION_REVISION_NOT_INCREASING")
        if (
            superseded.market_id != fact.market_id
            or superseded.effective_at_ms != fact.effective_at_ms
        ):
            raise Agg02Error("SUPER01_REVISION_IDENTITY_CHANGE_UNSUPPORTED")

    by_transition: dict[tuple[str, int], MarketLifecycleFact] = {}
    for fact in sorted(
        by_id.values(),
        key=lambda item: (
            item.market_id,
            item.effective_at_ms,
            item.revision,
            item.observed_at_ms,
            item.event_id,
        ),
    ):
        key = (fact.market_id, fact.effective_at_ms)
        previous = by_transition.get(key)
        if previous is None or fact.revision > previous.revision:
            by_transition[key] = fact
            continue
        if fact.revision == previous.revision and fact.fact_hash != previous.fact_hash:
            raise Agg02Error("SUPER01_UNRESOLVED_LIFECYCLE_CONFLICT")
    return tuple(
        sorted(
            by_transition.values(),
            key=lambda item: (
                item.market_id,
                item.effective_at_ms,
                item.observed_at_ms,
                item.event_id,
            ),
        )
    )


def materialize_market_membership(
    facts: Iterable[MarketLifecycleFact],
    *,
    dataset_revision: int,
    knowledge_cutoff_ms: int | None = None,
) -> tuple[MarketMembershipInterval, ...]:
    selected = _selected_facts(
        facts,
        dataset_revision=dataset_revision,
        knowledge_cutoff_ms=knowledge_cutoff_ms,
    )
    grouped: dict[str, list[MarketLifecycleFact]] = {}
    for fact in selected:
        grouped.setdefault(fact.market_id, []).append(fact)

    intervals: list[MarketMembershipInterval] = []
    for market_id in sorted(grouped):
        transitions = sorted(
            grouped[market_id],
            key=lambda item: (
                item.effective_at_ms,
                item.observed_at_ms,
                item.event_id,
            ),
        )
        for index, fact in enumerate(transitions):
            next_effective = (
                transitions[index + 1].effective_at_ms
                if index + 1 < len(transitions)
                else None
            )
            if next_effective is not None and next_effective <= fact.effective_at_ms:
                raise Agg02Error("SUPER01_INVALID_INTERVAL")
            intervals.append(
                MarketMembershipInterval(
                    market_id=market_id,
                    state=fact.state,
                    valid_from_ms=fact.effective_at_ms,
                    valid_to_ms=next_effective,
                    known_from_ms=fact.observed_at_ms,
                    source_event_id=fact.event_id,
                    source_fact_hash=fact.fact_hash,
                    revision=fact.revision,
                    related_market_id=fact.related_market_id,
                )
            )
    return tuple(intervals)


@dataclass(frozen=True, slots=True)
class UniverseDecision:
    market_id: str
    disposition: str
    reason: str

    def __post_init__(self) -> None:
        _text(self.market_id, "market_id")
        if self.disposition not in {"included", "excluded", "unknown"}:
            raise Agg02Error("SUPER01_INVALID_UNIVERSE_DISPOSITION")
        _text(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class UniverseManifest:
    experiment_time_ms: int
    knowledge_cutoff_ms: int
    dataset_revision: int
    eligibility_policy: str
    decisions: tuple[UniverseDecision, ...]
    facts_digest: str
    manifest_hash: str

    @property
    def included_market_ids(self) -> tuple[str, ...]:
        return tuple(
            item.market_id for item in self.decisions if item.disposition == "included"
        )

    @property
    def excluded_market_ids(self) -> tuple[str, ...]:
        return tuple(
            item.market_id for item in self.decisions if item.disposition == "excluded"
        )

    @property
    def unknown_market_ids(self) -> tuple[str, ...]:
        return tuple(
            item.market_id for item in self.decisions if item.disposition == "unknown"
        )


def select_universe_as_known(
    facts: Iterable[MarketLifecycleFact],
    *,
    experiment_time_ms: int,
    knowledge_cutoff_ms: int,
    dataset_revision: int,
    eligibility_policy: str = "active-only",
) -> UniverseManifest:
    _nonnegative_int(experiment_time_ms, "experiment_time_ms")
    _nonnegative_int(knowledge_cutoff_ms, "knowledge_cutoff_ms")
    _positive_int(dataset_revision, "dataset_revision")
    _text(eligibility_policy, "eligibility_policy")
    if eligibility_policy != "active-only":
        raise Agg02Error("SUPER01_UNKNOWN_COVERAGE_POLICY")
    if knowledge_cutoff_ms > experiment_time_ms:
        raise Agg02Error("SUPER01_FUTURE_KNOWLEDGE")

    all_facts = tuple(facts)
    selected = _selected_facts(
        all_facts,
        dataset_revision=dataset_revision,
        knowledge_cutoff_ms=knowledge_cutoff_ms,
    )
    market_ids = tuple(sorted({fact.market_id for fact in selected}))
    intervals = materialize_market_membership(
        selected,
        dataset_revision=dataset_revision,
        knowledge_cutoff_ms=knowledge_cutoff_ms,
    )
    decisions: list[UniverseDecision] = []
    for market_id in market_ids:
        matching = [
            interval
            for interval in intervals
            if interval.market_id == market_id
            and interval.known_from_ms <= knowledge_cutoff_ms
            and interval.contains(experiment_time_ms)
        ]
        if not matching:
            decisions.append(
                UniverseDecision(market_id, "unknown", "no-known-interval")
            )
            continue
        interval = matching[-1]
        if interval.state is MarketLifecycleState.ACTIVE:
            decisions.append(UniverseDecision(market_id, "included", "active"))
        elif interval.state is MarketLifecycleState.UNKNOWN:
            decisions.append(UniverseDecision(market_id, "unknown", "explicit-unknown"))
        else:
            decisions.append(
                UniverseDecision(market_id, "excluded", f"state:{interval.state.value}")
            )

    ordered = tuple(sorted(decisions, key=lambda item: item.market_id))
    digest = _facts_digest(selected)
    payload = {
        "experiment_time_ms": experiment_time_ms,
        "knowledge_cutoff_ms": knowledge_cutoff_ms,
        "dataset_revision": dataset_revision,
        "eligibility_policy": eligibility_policy,
        "decisions": tuple(
            (item.market_id, item.disposition, item.reason) for item in ordered
        ),
        "facts_digest": digest,
    }
    return UniverseManifest(
        experiment_time_ms=experiment_time_ms,
        knowledge_cutoff_ms=knowledge_cutoff_ms,
        dataset_revision=dataset_revision,
        eligibility_policy=eligibility_policy,
        decisions=ordered,
        facts_digest=digest,
        manifest_hash=canonical_hash(payload),
    )


@dataclass(frozen=True, slots=True)
class SurvivorshipAudit:
    manifest_hash: str
    denominator: int
    later_closed: tuple[str, ...]
    later_migrated: tuple[str, ...]
    unknown_at_cutoff: tuple[str, ...]
    excluded_at_cutoff: tuple[str, ...]
    audit_hash: str


def audit_universe_survivorship(
    manifest: UniverseManifest,
    facts: Iterable[MarketLifecycleFact],
    *,
    result_market_ids: Iterable[str],
) -> SurvivorshipAudit:
    result_ids = tuple(sorted(set(result_market_ids)))
    included = tuple(sorted(manifest.included_market_ids))
    if result_ids != included:
        raise Agg02Error("SUPER01_DENOMINATOR_MISMATCH")
    fact_tuple = tuple(facts)
    selected_at_cutoff = _selected_facts(
        fact_tuple,
        dataset_revision=manifest.dataset_revision,
        knowledge_cutoff_ms=manifest.knowledge_cutoff_ms,
    )
    if _facts_digest(selected_at_cutoff) != manifest.facts_digest:
        raise Agg02Error("SUPER01_MANIFEST_FACTS_MISMATCH")

    included_set = set(included)
    latest_revision = max(
        (fact.revision for fact in fact_tuple),
        default=manifest.dataset_revision,
    )
    resolved_all = _selected_facts(
        fact_tuple,
        dataset_revision=max(manifest.dataset_revision, latest_revision),
        knowledge_cutoff_ms=None,
    )
    later_closed = tuple(
        sorted(
            {
                fact.market_id
                for fact in resolved_all
                if fact.market_id in included_set
                and fact.effective_at_ms > manifest.experiment_time_ms
                and fact.state is MarketLifecycleState.CLOSED
            }
        )
    )
    later_migrated = tuple(
        sorted(
            {
                fact.market_id
                for fact in resolved_all
                if fact.market_id in included_set
                and fact.effective_at_ms > manifest.experiment_time_ms
                and fact.state is MarketLifecycleState.MIGRATED
            }
        )
    )
    unknown = tuple(sorted(manifest.unknown_market_ids))
    excluded = tuple(sorted(manifest.excluded_market_ids))
    payload = {
        "manifest_hash": manifest.manifest_hash,
        "denominator": len(included),
        "later_closed": later_closed,
        "later_migrated": later_migrated,
        "unknown_at_cutoff": unknown,
        "excluded_at_cutoff": excluded,
    }
    return SurvivorshipAudit(
        manifest_hash=manifest.manifest_hash,
        denominator=len(included),
        later_closed=later_closed,
        later_migrated=later_migrated,
        unknown_at_cutoff=unknown,
        excluded_at_cutoff=excluded,
        audit_hash=canonical_hash(payload),
    )


__all__ = [
    "MarketLifecycleFact",
    "MarketLifecycleState",
    "MarketMembershipInterval",
    "SurvivorshipAudit",
    "UniverseDecision",
    "UniverseManifest",
    "audit_universe_survivorship",
    "materialize_market_membership",
    "record_market_lifecycle_evidence",
    "select_universe_as_known",
]
