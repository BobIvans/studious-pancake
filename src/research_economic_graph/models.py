"""GPR-01 research contracts. Classification never grants execution authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from src.qualification_campaign.identity import digest


class Heat(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    EVENT = "EVENT"


class ExecutionClass(StrEnum):
    LOCAL_ATOMIC = "LOCAL_ATOMIC"
    LOCAL_SIGNAL = "LOCAL_SIGNAL"
    CROSS_CHAIN_SIGNAL = "CROSS_CHAIN_SIGNAL"
    REBALANCE_ONLY = "REBALANCE_ONLY"


class EvidenceState(StrEnum):
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    IDENTIFIER_VERIFIED = "IDENTIFIER_VERIFIED"
    RPC_VERIFIED = "RPC_VERIFIED"
    EXECUTABLE = "EXECUTABLE"


class IdentityState(StrEnum):
    RND_VERIFIED_CURRENT = "RND_VERIFIED_CURRENT"
    RND_VERIFIED_SPECIFIC_REPRESENTATION = "RND_VERIFIED_SPECIFIC_REPRESENTATION"
    REVALIDATE_CURRENT = "REVALIDATE_CURRENT"
    REVALIDATE_ISSUER_STATUS = "REVALIDATE_ISSUER_STATUS"
    UNRESOLVED = "UNRESOLVED"


class AnchorType(StrEnum):
    USD_REDEMPTION = "USD_REDEMPTION"
    STAKING_EXCHANGE_RATE = "STAKING_EXCHANGE_RATE"
    NAV = "NAV"
    SAME_UNDERLYING = "SAME_UNDERLYING"
    BRIDGE_PARITY = "BRIDGE_PARITY"
    ORACLE_REFERENCE = "ORACLE_REFERENCE"
    DIRECT_VS_SYNTHETIC = "DIRECT_VS_SYNTHETIC"


def integer(value: int, label: str, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError(f"invalid {label}")


@dataclass(frozen=True)
class AssetIdentity:
    asset_id: str
    asset_key: str
    chain: str
    canonical_identifier: str | None
    token_program_or_move_type: str | None
    decimals: int | None
    economic_asset: str
    representation_kind: str
    origin_chain: str | None
    bridge: str | None
    issuer: str | None
    standard: str
    verification_state: IdentityState
    verification_sources: tuple[str, ...]
    identity_generation: str
    legacy_aliases: tuple[str, ...] = ()
    note: str = ""
    runtime_enabled: bool = False
    exact_graph_allowed: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, "verification_state", IdentityState(self.verification_state)
        )
        if self.asset_id != f"{self.chain}:{self.asset_key}":
            raise ValueError("chain-qualified representation identity required")
        if not all(
            (self.asset_key, self.chain, self.economic_asset, self.representation_kind)
        ):
            raise ValueError("complete representation required")
        if self.runtime_enabled is not False or self.exact_graph_allowed is not False:
            raise ValueError("registry cannot grant runtime/exact authority")
        if self.decimals is not None:
            integer(self.decimals, "decimals")
            if self.decimals > 255:
                raise ValueError("decimals outside byte range")
        if (
            self.canonical_identifier is None
            and self.verification_state != IdentityState.UNRESOLVED
        ):
            raise ValueError("missing identifier must remain unresolved")
        for name in ("verification_sources", "legacy_aliases"):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))

    @property
    def identifier_verified(self) -> bool:
        return self.canonical_identifier is not None and self.verification_state in (
            IdentityState.RND_VERIFIED_CURRENT,
            IdentityState.RND_VERIFIED_SPECIFIC_REPRESENTATION,
        )

    @property
    def representation(self) -> dict:
        return {
            name: getattr(self, name)
            for name in (
                "asset_id",
                "chain",
                "canonical_identifier",
                "token_program_or_move_type",
                "standard",
                "economic_asset",
                "representation_kind",
                "origin_chain",
                "bridge",
                "issuer",
            )
        }


# A representation is the full identity, never a ticker/economic-asset alias.
Representation = AssetIdentity


@dataclass(frozen=True)
class ResearchEvidence:
    raw_evidence_id: str
    source_id: str
    source_generation: str
    provider_id: str
    provider_generation: str
    provider: str
    operator: str
    correlation_group: str
    request_hash: str
    response_hash: str | None
    retained_payload_hash: str | None
    observed_at_ns: int
    available_at_ns: int
    quality: str
    source_time: str | int | float | None = None
    slot: int | None = None
    checkpoint: int | None = None

    def __post_init__(self):
        integer(self.observed_at_ns, "observation time", 1)
        integer(self.available_at_ns, "availability time", self.observed_at_ns)
        for value in (self.slot, self.checkpoint):
            if value is not None:
                integer(value, "chain context")
        if not all(
            (
                self.raw_evidence_id,
                self.source_id,
                self.source_generation,
                self.provider_id,
                self.provider_generation,
                self.provider,
                self.operator,
                self.correlation_group,
                self.request_hash,
                self.quality,
            )
        ):
            raise ValueError("complete QPR provenance required")
        digest(asdict(self))  # Reject non-finite source times.


@dataclass(frozen=True)
class SyntheticPath:
    representations: tuple[str, ...]
    expression: str

    def __post_init__(self):
        object.__setattr__(self, "representations", tuple(self.representations))
        if len(self.representations) < 2 or not self.expression:
            raise ValueError("synthetic path needs exact representation references")


@dataclass(frozen=True)
class ResearchRelation:
    relation_id: str
    relation_class: str
    representations: tuple[str, ...]
    heat: Heat
    execution_class: ExecutionClass
    evidence_state: EvidenceState
    anchor_types: tuple[AnchorType, ...] = ()
    direct_venues: tuple[str, ...] = ()
    known_pool_or_book_ids: tuple[str, ...] = ()
    synthetic_paths: tuple[SyntheticPath, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    evidence: tuple[ResearchEvidence, ...] = ()
    observed_at_ns: int | None = None
    staleness_ttl_ns: int = 60_000_000_000
    quality: str = "research-identifier-only"
    reference: str | None = None
    frictions: tuple[str, ...] = ()

    def __post_init__(self):
        for name, kind in (
            ("heat", Heat),
            ("execution_class", ExecutionClass),
            ("evidence_state", EvidenceState),
        ):
            object.__setattr__(self, name, kind(getattr(self, name)))
        if not self.relation_id or not self.relation_class or not self.representations:
            raise ValueError("complete research relation required")
        for name in (
            "representations",
            "direct_venues",
            "known_pool_or_book_ids",
            "provenance_refs",
            "frictions",
        ):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))
        object.__setattr__(
            self,
            "anchor_types",
            tuple(sorted({AnchorType(a) for a in self.anchor_types})),
        )
        for name in ("synthetic_paths", "evidence"):
            values = {digest(asdict(v)): v for v in getattr(self, name)}
            object.__setattr__(self, name, tuple(values[k] for k in sorted(values)))
        integer(self.staleness_ttl_ns, "staleness TTL", 1)
        if self.observed_at_ns is not None:
            integer(self.observed_at_ns, "relation observation time", 1)
        chains = {ref.split(":", 1)[0] for ref in self.representations}
        if len(chains) > 1 and self.execution_class not in (
            ExecutionClass.CROSS_CHAIN_SIGNAL,
            ExecutionClass.REBALANCE_ONLY,
        ):
            raise ValueError("cross-chain relations must stay non-atomic")
        if self.relation_class in (
            "NATIVE_BURN_MINT",
            "LOCK_MINT_BRIDGE",
            "INVENTORY_REBALANCE",
            "BRIDGE",
            "CCTP",
            "WORMHOLE",
            "TRANSPORT_REBALANCE",
            "LOCK_MINT_BRIDGE_TEMPLATE",
            "USDT0_LEGACY_MESH",
        ) and self.execution_class not in (
            ExecutionClass.CROSS_CHAIN_SIGNAL,
            ExecutionClass.REBALANCE_ONLY,
        ):
            raise ValueError("transport relations must stay research/rebalance-only")
        if AnchorType.USD_REDEMPTION in self.anchor_types and (
            self.relation_class in ("NAV_MARKET_BASIS", "ORACLE_MARKET_BASIS")
        ):
            raise ValueError("NAV/gold reference cannot become a fixed USD peg")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> ResearchRelation:
        values = dict(raw)
        values["synthetic_paths"] = tuple(
            SyntheticPath(**p) for p in values.get("synthetic_paths", ())
        )
        values["evidence"] = tuple(
            ResearchEvidence(**p) for p in values.get("evidence", ())
        )
        return cls(**values)
