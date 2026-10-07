from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Protocol

from src.assets.resolution.evidence import Evidence, EvidenceStore, digest, text
from src.assets.resolution.resolver import AssetIdentity, canonical_identifier
from src.economics.non_monotonic_sizing import (
    PR118AssetAmount,
    PR118CostLedgerEntry,
    PR118FlashRepaymentTerms,
    PR118TypedCostLedger,
    build_pr118_amount_grid,
)


@dataclass(frozen=True)
class FlashCapitalEdge:
    chain: str
    provider: str
    asset_id: str
    canonical_identifier: str
    resource_id: str
    max_amount_live: int
    fee_numerator: int
    fee_denominator: int
    protocol_rounding: int
    atomicity_class: str
    constraints: tuple[str, ...]
    evidence: Evidence
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        canonical_identifier(self.chain, self.canonical_identifier)
        for value in (self.provider, self.asset_id, self.resource_id):
            text(value)
        for number in (
            self.max_amount_live,
            self.fee_numerator,
            self.fee_denominator,
            self.protocol_rounding,
        ):
            if type(number) is not int or number < 0:
                raise ValueError("integer financing units required")
        if (
            self.fee_denominator <= 0
            or self.fee_numerator >= self.fee_denominator
            or not self.evidence_refs
            or self.evidence.slot_or_checkpoint is None
            or self.evidence.negative_reason
        ):
            raise ValueError("current observed fee/capacity provenance required")
        if self.atomicity_class != "LOCAL_ATOMIC_CANDIDATE":
            raise ValueError(
                "unsupported capital atomicity; candidate is not authorization"
            )
        if self.provider not in {
            "project0",
            "marginfi",
            "kamino",
            "navi",
            "deepbook",
            "scallop",
        }:
            raise ValueError("unqualified capital provider")
        if (
            self.provider in {"project0", "marginfi", "kamino"}
            and self.chain != "solana"
            or self.provider in {"navi", "deepbook", "scallop"}
            and self.chain != "sui"
        ):
            raise ValueError("capital provider/chain mismatch")

    @property
    def identity(self) -> str:
        return digest(asdict(self))

    def fee(self, amount: int) -> int:
        if type(amount) is not int or not 0 < amount <= self.max_amount_live:
            raise ValueError("amount exceeds observed flash capacity")
        return (
            amount * self.fee_numerator + self.fee_denominator - 1
        ) // self.fee_denominator


class FlashCapitalProvider(Protocol):
    def discover_assets(self) -> tuple[FlashCapitalEdge, ...]: ...
    def refresh(self, asset_id: str, amount_hint: int) -> FlashCapitalEdge: ...


class LiveCapitalProvider:
    """Inject a read-only protocol SDK/chain reader, not a borrowing client.

    The normalized reader contract is explicit, integer atom capacity + rational
    fee, and positive bank/reserve/pool evidence. Unknown SDK schema fails closed.
    No provider-wide asset-list fallback or assumed fee is permitted.
    """

    def __init__(
        self,
        provider: str,
        chain: str,
        reader: Callable[[], tuple[dict, Evidence]],
        assets: tuple[AssetIdentity, ...],
    ):
        self.provider, self.chain, self.reader = provider, chain, reader
        self.assets = {a.canonical_identifier: a for a in assets if a.chain == chain}
        self.negative_evidence: list[str] = []

    def discover_assets(self) -> tuple[FlashCapitalEdge, ...]:
        payload, evidence = self.reader()
        if evidence.negative_reason:
            self.negative_evidence.append(evidence.negative_reason)
            return ()
        if (
            payload.get("schema") != "dynamic-universe.capital.v1"
            or payload.get("provider") != self.provider
            or type(payload.get("assets")) is not list
            or len(payload["assets"]) > 4096
        ):
            self.negative_evidence.append("capital_schema_drift")
            return ()
        result = []
        try:
            for row in payload["assets"]:
                # Disabled flash borrowing is evidence, never zero-fee support.
                if row["flash_enabled"] is not True:
                    continue
                identifier = canonical_identifier(
                    self.chain, row["canonical_identifier"]
                )
                asset = self.assets.get(identifier)
                if asset is None or asset.resolver_generation != evidence.generation:
                    self.negative_evidence.append("unverified_lender_asset")
                    continue
                result.append(
                    FlashCapitalEdge(
                        self.chain,
                        self.provider,
                        asset.asset_id,
                        identifier,
                        row["resource_id"],
                        row["max_amount_atoms"],
                        row["fee_numerator"],
                        row["fee_denominator"],
                        row["protocol_rounding_atoms"],
                        "LOCAL_ATOMIC_CANDIDATE",
                        tuple(row["constraints"]),
                        evidence,
                        (digest(asdict(evidence)),),
                    )
                )
        except (KeyError, TypeError, ValueError):
            self.negative_evidence.append("capital_row_schema_drift")
            return ()
        keys = {(e.asset_id, e.resource_id) for e in result}
        if len(keys) != len(result):
            self.negative_evidence.append("duplicate_lender_resource")
            return ()
        return tuple(sorted(result, key=lambda e: e.identity))

    def refresh(self, asset_id: str, amount_hint: int) -> FlashCapitalEdge:
        if type(amount_hint) is not int or amount_hint <= 0:
            raise ValueError("positive atom amount hint required")
        choices = tuple(
            e
            for e in self.discover_assets()
            if e.asset_id == asset_id and e.max_amount_live >= amount_hint
        )
        if not choices:
            raise ValueError("no live lender capacity for this asset/size")
        return min(choices, key=lambda e: (e.fee(amount_hint), e.identity))


class Project0CapitalProvider(LiveCapitalProvider):
    def __init__(self, reader, assets):
        super().__init__("project0", "solana", reader, assets)


class KaminoCapitalProvider(LiveCapitalProvider):
    def __init__(self, reader, assets):
        super().__init__("kamino", "solana", reader, assets)


class NaviCapitalProvider(LiveCapitalProvider):
    def __init__(self, reader, assets):
        super().__init__("navi", "sui", reader, assets)


class DeepBookCapitalProvider(LiveCapitalProvider):
    def __init__(self, reader, assets):
        super().__init__("deepbook", "sui", reader, assets)


class ScallopCapitalProvider(LiveCapitalProvider):
    def __init__(self, reader, assets):
        super().__init__("scallop", "sui", reader, assets)


def navi_sdk_snapshot(rows: list[dict], *, decimals_by_type: dict[str, int]) -> dict:
    """Adapt getAllFlashLoanAssets() values using declared units, never float math.

    SDK max values in coin units require independently verified decimals.
    The SDK bridge must supply its current pool/contract resource identifier.
    """
    if len(rows) > 4096:
        raise ValueError("NAVI result cap exceeded")
    result = []
    for r in rows:
        if not isinstance(r["max"], str) or not isinstance(r["flashloanFee"], str):
            raise ValueError("NAVI exact decimal strings required")
        coin = canonical_identifier("sui", r["coinType"])
        capacity = Decimal(r["max"]) * 10 ** decimals_by_type[coin]
        rate = Fraction(Decimal(r["flashloanFee"]))
        if (
            not capacity.is_finite()
            or capacity != capacity.to_integral_value()
            or capacity < 0
            or not 0 <= rate < 1
        ):
            raise ValueError("invalid NAVI units/fee")
        result.append(
            {
                "canonical_identifier": coin,
                "resource_id": r["resource_id"],
                "flash_enabled": r["flash_enabled"],
                "max_amount_atoms": int(capacity),
                "fee_numerator": rate.numerator,
                "fee_denominator": rate.denominator,
                "protocol_rounding_atoms": r["protocol_rounding_atoms"],
                "constraints": r["constraints"],
            }
        )
    return {
        "schema": "dynamic-universe.capital.v1",
        "provider": "navi",
        "assets": result,
    }


class FlashCapitalGraph:
    def __init__(self, generation: str, store: EvidenceStore):
        self.generation, self.store = generation, store
        self.edges: dict[tuple[str, str, str], FlashCapitalEdge] = {}
        self.history: list[str] = []
        self.invalidated: set[tuple[str, str, str]] = set()

    def observe(
        self, edge: FlashCapitalEdge, *, now: float, max_age: float = 30
    ) -> None:
        if not edge.evidence.fresh(
            now=now, max_age=max_age, generation=self.generation
        ):
            raise ValueError("stale capital evidence")
        key = (edge.provider, edge.asset_id, edge.resource_id)
        old = self.edges.get(key)
        position = edge.evidence.slot_or_checkpoint
        old_position = None if old is None else old.evidence.slot_or_checkpoint
        if position is None or old is not None and old_position is None:
            raise ValueError("capital chain position missing")
        if (
            old
            and key in self.invalidated
            and old_position is not None
            and position <= old_position
        ):
            raise ValueError("capital disagreement requires a newer verified state")
        if old_position is not None and position < old_position:
            raise ValueError("capital generation moved backwards")
        if (
            old
            and edge.evidence.slot_or_checkpoint == old.evidence.slot_or_checkpoint
            and (
                edge.max_amount_live,
                edge.fee_numerator,
                edge.fee_denominator,
                edge.constraints,
            )
            != (
                old.max_amount_live,
                old.fee_numerator,
                old.fee_denominator,
                old.constraints,
            )
        ):
            self.invalidated.add(key)
            raise ValueError("capital provider disagreement at same state")
        payload = asdict(edge)
        ref = self.store.append(
            Evidence(
                "flash-capital",
                edge.provider,
                edge.resource_id,
                self.generation,
                now,
                digest(payload),
                digest(key),
                edge.evidence.slot_or_checkpoint,
            ),
            payload,
        )
        self.edges[key] = edge
        self.invalidated.discard(key)
        self.history.append(ref)

    def paper_ledger(
        self,
        edge: FlashCapitalEdge,
        *,
        asset: AssetIdentity,
        principal: int,
        guaranteed_output: int,
        costs: tuple[PR118CostLedgerEntry, ...],
        resources: frozenset[str],
        now: float,
        max_age: float = 30,
    ) -> PR118TypedCostLedger:
        key = (edge.provider, edge.asset_id, edge.resource_id)
        if (
            self.edges.get(key) != edge
            or key in self.invalidated
            or not edge.evidence.fresh(
                now=now, max_age=max_age, generation=self.generation
            )
        ):
            raise ValueError(
                "capital quote changed, disagreed or expired; resize route"
            )
        if (
            asset.asset_id,
            asset.chain,
            asset.canonical_identifier,
            asset.resolver_generation,
        ) != (edge.asset_id, edge.chain, edge.canonical_identifier, self.generation):
            raise ValueError("capital/asset identity mismatch")
        if edge.constraints and not set(edge.constraints) <= resources:
            raise ValueError("route violates provider pool/atomicity constraints")
        # PR118 owns exact economics. Symbol is not used as its internal asset key.
        ledger_asset = "ASSET:" + asset.asset_id[:58].upper()
        terms = PR118FlashRepaymentTerms(
            ledger_asset, principal, edge.fee(principal), edge.protocol_rounding
        )
        return PR118TypedCostLedger(
            PR118AssetAmount(ledger_asset, guaranteed_output),
            terms,
            costs,
            edge.identity,
        )

    def size_grid(
        self, edge: FlashCapitalEdge, *, lower: int, upper: int, max_points: int = 16
    ) -> tuple[int, ...]:
        return build_pr118_amount_grid(
            lower_lamports=lower,
            upper_lamports=min(upper, edge.max_amount_live),
            max_points=max_points,
        )
