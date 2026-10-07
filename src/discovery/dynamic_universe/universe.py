from dataclasses import asdict, dataclass, replace
from enum import StrEnum

from src.assets.resolution.evidence import Evidence, EvidenceStore, digest, text
from src.assets.resolution.resolver import CandidateAsset, canonical_identifier


class Lifecycle(StrEnum):
    DISCOVERED = "DISCOVERED"
    CHEAP_WATCH = "CHEAP_WATCH"
    COLD = "COLD"
    WARM = "WARM"
    HOT = "HOT"
    EVENT = "EVENT"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class MarketIdentity:
    chain: str
    venue: str
    program_id: str
    market_id: str
    base: str
    quote: str
    fee_tier: str
    correlation_group: str
    underlying_resources: tuple[str, ...]
    evidence: Evidence | None = None

    def __post_init__(self) -> None:
        for value in (
            self.chain,
            self.venue,
            self.program_id,
            self.market_id,
            self.fee_tier,
            self.correlation_group,
        ):
            text(value)
        if self.chain in ("solana", "sui"):
            object.__setattr__(
                self, "base", canonical_identifier(self.chain, self.base)
            )
            object.__setattr__(
                self, "quote", canonical_identifier(self.chain, self.quote)
            )
        elif self.chain != "ton":
            raise ValueError("unsupported market chain")
        if (
            self.base == self.quote
            or not self.underlying_resources
            or len(set(self.underlying_resources)) != len(self.underlying_resources)
        ):
            raise ValueError(
                "distinct assets and explicit unique liquidity resources required"
            )
        for resource in self.underlying_resources:
            text(resource)

    @property
    def identity(self) -> str:
        # Provider is intentionally excluded: two APIs for one pool are aliases.
        return digest(
            {
                "chain": self.chain,
                "program": self.program_id,
                "market": self.market_id,
                "base": self.base,
                "quote": self.quote,
                "fee": self.fee_tier,
            }
        )


@dataclass(frozen=True)
class DiscoveryEnvelope:
    evidence: Evidence
    assets: tuple[CandidateAsset, ...] = ()
    markets: tuple[MarketIdentity, ...] = ()
    complete_snapshot: bool = False
    truncated: bool = False
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if len(self.assets) > 4096 or len(self.markets) > 4096:
            raise ValueError("discovery envelope hard cap exceeded")
        if self.evidence.negative_reason and (
            self.assets or self.markets or self.complete_snapshot
        ):
            raise ValueError("negative envelope cannot assert positive discovery")
        if self.truncated and self.complete_snapshot:
            raise ValueError("truncated snapshot is not complete")


@dataclass(frozen=True)
class UniverseRecord:
    identity: str
    value: CandidateAsset | MarketIdentity
    lifecycle: Lifecycle
    generation: str
    evidence_refs: tuple[str, ...]
    reason: str | None = None


class DynamicUniverse:
    def __init__(
        self, generation: str, store: EvidenceStore, *, max_entities: int = 8192
    ):
        text(generation)
        if type(max_entities) is not int or not 1 <= max_entities <= 65536:
            raise ValueError("invalid entity bound")
        self.generation, self.store, self.max_entities = generation, store, max_entities
        self.records: dict[str, UniverseRecord] = {}
        self.history: list[UniverseRecord] = []
        self.sources: dict[str, set[str]] = {}
        self.negative_evidence: list[str] = []

    def ingest(
        self, envelope: DiscoveryEnvelope, *, now: float, max_age: float = 300
    ) -> None:
        payload = asdict(envelope)
        event = Evidence(
            "universe-ingest",
            "dynamic-universe",
            "universe",
            self.generation,
            now,
            digest(payload),
            digest(envelope.evidence.source),
        )
        ref = self.store.append(event, payload)
        if not envelope.evidence.fresh(
            now=now, max_age=max_age, generation=self.generation
        ):
            self.negative_evidence.append(ref)
            return
        incoming: dict[str, CandidateAsset | MarketIdentity] = {}
        for asset in envelope.assets:
            if asset.evidence != envelope.evidence:
                raise ValueError("asset provenance differs from containing envelope")
            key = digest({"chain": asset.chain, "asset": asset.identifier})
            if key in incoming and incoming[key] != asset:
                raise ValueError(
                    "duplicate identity with conflicting registry metadata"
                )
            incoming[key] = asset
        for market in envelope.markets:
            if market.evidence != envelope.evidence:
                raise ValueError("market provenance differs from containing envelope")
            if market.identity in incoming and incoming[market.identity] != market:
                raise ValueError("conflicting market alias metadata")
            incoming[market.identity] = market
        if len(set(self.records) | set(incoming)) > self.max_entities:
            raise ValueError("universe entity cap exceeded")
        source = envelope.evidence.source
        for key, value in sorted(incoming.items()):
            previous = self.records.get(key)
            state = (
                Lifecycle.DISCOVERED
                if previous is None or previous.lifecycle == Lifecycle.RETIRED
                else previous.lifecycle
            )
            record = UniverseRecord(key, value, state, self.generation, (ref,))
            self.records[key] = record
            self.history.append(record)
        old = self.sources.get(source, set())
        if envelope.complete_snapshot:
            for missing in sorted(old - set(incoming)):
                # One source disappearing cannot retire a market another source sees.
                if any(
                    missing in keys
                    for name, keys in self.sources.items()
                    if name != source
                ):
                    continue
                record = replace(
                    self.records[missing],
                    lifecycle=Lifecycle.RETIRED,
                    evidence_refs=(ref,),
                    reason="absent_from_complete_live_snapshot",
                )
                self.records[missing] = record
                self.history.append(record)
            self.sources[source] = set(incoming)
        else:
            self.sources[source] = old | set(incoming)

    def active_markets(self) -> tuple[MarketIdentity, ...]:
        return tuple(
            r.value
            for _, r in sorted(self.records.items())
            if isinstance(r.value, MarketIdentity) and r.lifecycle != Lifecycle.RETIRED
        )
