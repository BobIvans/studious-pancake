"""MEGA8-02 shared offline contracts.

The package is deliberately sender-free. It accepts already-observed, immutable
state/evidence and produces deterministic research/shadow artifacts only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from fractions import Fraction
import hashlib
import json
from typing import Iterable, Mapping, Sequence


class Mega802Error(ValueError):
    """Fail-closed MEGA8-02 contract violation."""


class Disposition(StrEnum):
    IMPLEMENTED_OFFLINE = "implemented-offline"
    RESEARCH_ONLY = "research-only"
    REJECTED = "rejected"


def stable_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Mega802Error(f"{field} is required")
    return value


def require_nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Mega802Error(f"{field} must be a non-negative integer")
    return value


def require_positive_int(value: object, field: str) -> int:
    value = require_nonnegative_int(value, field)
    if value == 0:
        raise Mega802Error(f"{field} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    generation: str
    state_sha256: str
    schema_version: str
    observed_at: int
    expires_at: int
    verified: bool = True
    live_enabled: bool = False

    def __post_init__(self) -> None:
        require_text(self.generation, "generation")
        require_text(self.schema_version, "schema_version")
        if (
            not isinstance(self.state_sha256, str)
            or len(self.state_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in self.state_sha256)
        ):
            raise Mega802Error("state_sha256 must be lowercase sha256")
        require_nonnegative_int(self.observed_at, "observed_at")
        require_positive_int(self.expires_at, "expires_at")
        if self.expires_at <= self.observed_at:
            raise Mega802Error("expires_at must be after observed_at")
        if not isinstance(self.verified, bool):
            raise Mega802Error("verified must be bool")
        if self.live_enabled:
            raise Mega802Error("MEGA8-02 cannot grant live authority")

    def assert_usable(self, *, now: int) -> None:
        require_nonnegative_int(now, "now")
        if not self.verified:
            raise Mega802Error("unverified evidence")
        if now >= self.expires_at:
            raise Mega802Error("stale evidence")

    @property
    def identity(self) -> str:
        return stable_hash(asdict(self))


@dataclass(frozen=True, slots=True)
class Primitive:
    primitive_id: str
    kind: str
    asset_id: str
    unit: str
    rights: tuple[str, ...]
    underlying: tuple[str, ...] = ()
    maturity: int | None = None

    def __post_init__(self) -> None:
        for field in ("primitive_id", "kind", "asset_id", "unit"):
            require_text(getattr(self, field), field)
        rights = tuple(sorted(set(self.rights)))
        if not rights:
            raise Mega802Error("primitive rights are required")
        if any(not item.strip() for item in rights):
            raise Mega802Error("primitive rights contain blank values")
        object.__setattr__(self, "rights", rights)
        underlying = tuple(self.underlying)
        if len(underlying) != len(set(underlying)):
            raise Mega802Error("duplicate underlying assets")
        object.__setattr__(self, "underlying", underlying)
        if self.maturity is not None:
            require_nonnegative_int(self.maturity, "maturity")


@dataclass(frozen=True, slots=True)
class Hyperedge:
    edge_id: str
    inputs: tuple[tuple[str, int], ...]
    outputs: tuple[tuple[str, int], ...]
    obligations: tuple[tuple[str, int], ...]
    writable_resources: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.edge_id, "edge_id")
        if not self.inputs or not self.outputs:
            raise Mega802Error("hyperedge requires inputs and outputs")
        for collection in (self.inputs, self.outputs, self.obligations):
            for asset, amount in collection:
                require_text(asset, "asset")
                require_positive_int(amount, "amount")
        if len(self.writable_resources) != len(set(self.writable_resources)):
            raise Mega802Error("duplicate writable resource")


@dataclass(frozen=True, slots=True)
class RouteVariant:
    route_id: str
    legs: tuple[str, ...]
    input_amount: int
    guaranteed_output: int
    state_generation: str
    writable_resources: tuple[str, ...] = ()
    financing_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.route_id, "route_id")
        if not self.legs or any(not item.strip() for item in self.legs):
            raise Mega802Error("route legs are required")
        require_positive_int(self.input_amount, "input_amount")
        require_nonnegative_int(self.guaranteed_output, "guaranteed_output")
        require_text(self.state_generation, "state_generation")
        if len(self.writable_resources) != len(set(self.writable_resources)):
            raise Mega802Error("duplicate writable resource")
        if len(self.financing_resources) != len(set(self.financing_resources)):
            raise Mega802Error("duplicate financing resource")

    @property
    def economic_identity(self) -> str:
        return stable_hash(
            {
                "legs": self.legs,
                "input_amount": self.input_amount,
                "guaranteed_output": self.guaranteed_output,
                "state_generation": self.state_generation,
            }
        )

    @property
    def resource_identity(self) -> str:
        return stable_hash(
            {
                "economic": self.economic_identity,
                "writable": sorted(self.writable_resources),
                "financing": sorted(self.financing_resources),
            }
        )


@dataclass(frozen=True, slots=True)
class ResourceEnvelope:
    compute_units: int
    account_metas: int
    message_bytes: int
    contention_ppm: int = 0

    def __post_init__(self) -> None:
        for field in (
            "compute_units",
            "account_metas",
            "message_bytes",
            "contention_ppm",
        ):
            require_nonnegative_int(getattr(self, field), field)
        if self.contention_ppm > 1_000_000:
            raise Mega802Error("contention_ppm exceeds 1e6")


@dataclass(frozen=True, slots=True)
class ObjectiveVector:
    candidate_id: str
    conservative_net: int
    duration_us: int
    resource_cost: int
    uncertainty: int
    contention_ppm: int

    def __post_init__(self) -> None:
        require_text(self.candidate_id, "candidate_id")
        if isinstance(self.conservative_net, bool) or not isinstance(
            self.conservative_net, int
        ):
            raise Mega802Error("conservative_net must be integer")
        for field in ("duration_us", "resource_cost", "uncertainty", "contention_ppm"):
            require_nonnegative_int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class CapacityQuote:
    source_id: str
    asset_id: str
    capacity: int
    fee: int
    generation: str
    atomic: bool = True

    def __post_init__(self) -> None:
        for field in ("source_id", "asset_id", "generation"):
            require_text(getattr(self, field), field)
        require_nonnegative_int(self.capacity, "capacity")
        require_nonnegative_int(self.fee, "fee")
        if not isinstance(self.atomic, bool):
            raise Mega802Error("atomic must be bool")


@dataclass(frozen=True, slots=True)
class ContractResult:
    operation: str
    evidence_id: str
    payload_sha256: str
    disposition: Disposition
    reason: str
    live_enabled: bool = False

    def __post_init__(self) -> None:
        require_text(self.operation, "operation")
        require_text(self.evidence_id, "evidence_id")
        require_text(self.payload_sha256, "payload_sha256")
        require_text(self.reason, "reason")
        if self.live_enabled:
            raise Mega802Error("contract result cannot enable live effects")


def offline_result(
    operation: str,
    evidence: EvidenceBinding,
    payload: object,
    *,
    now: int,
    reason: str = "OFFLINE_CONTRACT_SATISFIED",
    disposition: Disposition = Disposition.IMPLEMENTED_OFFLINE,
) -> ContractResult:
    evidence.assert_usable(now=now)
    return ContractResult(
        operation=operation,
        evidence_id=evidence.identity,
        payload_sha256=stable_hash(payload),
        disposition=disposition,
        reason=reason,
    )


def compile_hyperedge_core(
    *,
    edge_id: str,
    inputs: Mapping[str, int],
    outputs: Mapping[str, int],
    obligations: Mapping[str, int] | None = None,
    writable_resources: Sequence[str] = (),
) -> Hyperedge:
    def rows(values: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted(
                (key, require_positive_int(value, key))
                for key, value in values.items()
            )
        )

    return Hyperedge(
        edge_id=edge_id,
        inputs=rows(inputs),
        outputs=rows(outputs),
        obligations=rows(obligations or {}),
        writable_resources=tuple(sorted(writable_resources)),
    )


def apply_hyperedge_core(
    state: Mapping[str, int], edge: Hyperedge
) -> dict[str, int]:
    result = {key: require_nonnegative_int(value, key) for key, value in state.items()}
    for asset, amount in edge.inputs:
        available = result.get(asset, 0)
        if available < amount:
            raise Mega802Error(f"insufficient {asset}")
        result[asset] = available - amount
    for asset, amount in edge.outputs:
        result[asset] = result.get(asset, 0) + amount
    for asset, amount in edge.obligations:
        available = result.get(asset, 0)
        if available < amount:
            raise Mega802Error(f"unsatisfied obligation for {asset}")
        result[asset] = available - amount
    return result


def canonicalize_routes_core(
    routes: Iterable[RouteVariant],
) -> tuple[RouteVariant, ...]:
    by_resource: dict[str, RouteVariant] = {}
    for route in routes:
        previous = by_resource.get(route.resource_identity)
        if previous is None or route.route_id < previous.route_id:
            by_resource[route.resource_identity] = route
    return tuple(sorted(by_resource.values(), key=lambda item: item.resource_identity))


def pareto_frontier_core(
    rows: Iterable[ObjectiveVector],
) -> tuple[ObjectiveVector, ...]:
    items = tuple(rows)
    frontier: list[ObjectiveVector] = []
    for candidate in items:
        dominated = False
        for other in items:
            if other.candidate_id == candidate.candidate_id:
                continue
            not_worse = (
                other.conservative_net >= candidate.conservative_net
                and other.duration_us <= candidate.duration_us
                and other.resource_cost <= candidate.resource_cost
                and other.uncertainty <= candidate.uncertainty
                and other.contention_ppm <= candidate.contention_ppm
            )
            strictly_better = (
                other.conservative_net > candidate.conservative_net
                or other.duration_us < candidate.duration_us
                or other.resource_cost < candidate.resource_cost
                or other.uncertainty < candidate.uncertainty
                or other.contention_ppm < candidate.contention_ppm
            )
            if not_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return tuple(sorted(frontier, key=lambda item: item.candidate_id))


def allocate_capacity_core(
    quotes: Sequence[CapacityQuote],
    *,
    amount: int,
    max_total_fee: int | None = None,
) -> tuple[tuple[str, int], ...]:
    remaining = require_positive_int(amount, "amount")
    if max_total_fee is not None:
        require_nonnegative_int(max_total_fee, "max_total_fee")
    generations = {quote.generation for quote in quotes}
    assets = {quote.asset_id for quote in quotes}
    if len(generations) != 1 or len(assets) != 1:
        raise Mega802Error("capacity quotes must share asset and generation")
    selected: list[tuple[str, int]] = []
    fee_total = 0
    for quote in sorted(quotes, key=lambda item: (item.fee, item.source_id)):
        if not quote.atomic or quote.capacity <= 0 or remaining <= 0:
            continue
        take = min(remaining, quote.capacity)
        if max_total_fee is not None and fee_total + quote.fee > max_total_fee:
            continue
        selected.append((quote.source_id, take))
        fee_total += quote.fee
        remaining -= take
    if remaining:
        raise Mega802Error("insufficient qualified capacity")
    return tuple(selected)


def empirical_interval(
    samples: Sequence[int], *, margin_ppm: int = 100_000
) -> tuple[int, int]:
    if not samples:
        raise Mega802Error("samples are required")
    values = [require_nonnegative_int(value, "sample") for value in samples]
    margin_ppm = require_nonnegative_int(margin_ppm, "margin_ppm")
    if margin_ppm > 1_000_000:
        raise Mega802Error("margin_ppm exceeds 1e6")
    center = sorted(values)[len(values) // 2]
    margin = max(1, center * margin_ppm // 1_000_000)
    return max(0, center - margin), center + margin


def rational_quote(amount: int, numerator: int, denominator: int, fee: int = 0) -> int:
    amount = require_positive_int(amount, "amount")
    numerator = require_positive_int(numerator, "numerator")
    denominator = require_positive_int(denominator, "denominator")
    fee = require_nonnegative_int(fee, "fee")
    gross = (Fraction(amount) * numerator // denominator)
    if gross < fee:
        raise Mega802Error("fee exceeds gross output")
    return int(gross - fee)
