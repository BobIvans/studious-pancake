"""Validated semantic route graphs for provider-normalized quotes.

The graph is a decision object, not a display projection.  Every edge carries
exact assets, amounts, allocation, venue identity and source provenance.  The
canonical hash intentionally excludes delivery metadata and provider request
IDs so semantically identical routes receive the same identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
from typing import Iterable

from .dimensions import BasisPoints, U64_MAX, exact_positive_int


class RouteGraphError(ValueError):
    """A provider route is structurally ambiguous or violates conservation."""


class RouteEdgeKind(StrEnum):
    SWAP = "swap"
    WRAP_NATIVE = "wrap_native"
    UNWRAP_NATIVE = "unwrap_native"


@dataclass(frozen=True, slots=True)
class RouteEdge:
    stage: int
    branch: int
    kind: RouteEdgeKind
    provider: str
    venue: str
    pool_key: str
    program_id: str | None
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    allocation_bps: BasisPoints
    source_path: str
    writable_accounts: tuple[str, ...] = ()
    oracle_accounts: tuple[str, ...] = ()
    lookup_tables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.stage) is not int or self.stage < 0:
            raise RouteGraphError("route stage must be a non-negative integer")
        if type(self.branch) is not int or self.branch < 0:
            raise RouteGraphError("route branch must be a non-negative integer")
        for name in (
            "provider",
            "venue",
            "pool_key",
            "input_mint",
            "output_mint",
            "source_path",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise RouteGraphError(f"{name} must be non-empty text")
        exact_positive_int(self.input_amount, "route_edge.input_amount")
        exact_positive_int(self.output_amount, "route_edge.output_amount")
        if self.input_mint == self.output_mint and self.kind is RouteEdgeKind.SWAP:
            raise RouteGraphError("swap edge cannot have identical input/output mint")
        for collection_name in (
            "writable_accounts",
            "oracle_accounts",
            "lookup_tables",
        ):
            collection = tuple(getattr(self, collection_name))
            if len(collection) != len(set(collection)):
                raise RouteGraphError(f"duplicate {collection_name}")
            if any(not isinstance(item, str) or not item for item in collection):
                raise RouteGraphError(f"invalid {collection_name}")
            object.__setattr__(self, collection_name, collection)

    def semantic_row(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "branch": self.branch,
            "kind": self.kind.value,
            "provider": self.provider,
            "venue": self.venue,
            "pool_key": self.pool_key,
            "program_id": self.program_id,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "input_amount": str(self.input_amount),
            "output_amount": str(self.output_amount),
            "allocation_bps": self.allocation_bps.value,
            "writable_accounts": sorted(self.writable_accounts),
            "oracle_accounts": sorted(self.oracle_accounts),
            "lookup_tables": sorted(self.lookup_tables),
        }


@dataclass(frozen=True, slots=True)
class OpportunityResourceFootprint:
    pools: tuple[str, ...]
    programs: tuple[str, ...]
    writable_accounts: tuple[str, ...]
    oracles: tuple[str, ...]
    lookup_tables: tuple[str, ...]
    mints: tuple[str, ...]

    @classmethod
    def from_edges(cls, edges: Iterable[RouteEdge]) -> "OpportunityResourceFootprint":
        rows = tuple(edges)
        return cls(
            pools=tuple(sorted({edge.pool_key for edge in rows})),
            programs=tuple(
                sorted({edge.program_id for edge in rows if edge.program_id})
            ),
            writable_accounts=tuple(
                sorted({item for edge in rows for item in edge.writable_accounts})
            ),
            oracles=tuple(
                sorted({item for edge in rows for item in edge.oracle_accounts})
            ),
            lookup_tables=tuple(
                sorted({item for edge in rows for item in edge.lookup_tables})
            ),
            mints=tuple(
                sorted(
                    {
                        mint
                        for edge in rows
                        for mint in (edge.input_mint, edge.output_mint)
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class RouteGraph:
    provider: str
    input_mint: str
    output_mint: str
    input_amount: int
    expected_output: int
    guaranteed_output: int | None
    edges: tuple[RouteEdge, ...]
    asset_generation: str = "unbound"
    normalization_version: str = "canonical-quote-v2"
    _semantic_hash: str = field(init=False, repr=False)
    _resource_footprint: OpportunityResourceFootprint = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.provider or not self.input_mint or not self.output_mint:
            raise RouteGraphError("route graph identity fields are required")
        if self.input_mint == self.output_mint:
            raise RouteGraphError("route graph cannot be a self-swap")
        exact_positive_int(self.input_amount, "route_graph.input_amount")
        exact_positive_int(self.expected_output, "route_graph.expected_output")
        if self.guaranteed_output is not None:
            exact_positive_int(self.guaranteed_output, "route_graph.guaranteed_output")
            if self.guaranteed_output > self.expected_output:
                raise RouteGraphError("guaranteed output cannot exceed expected output")
        raw_edges = tuple(self.edges)
        if not raw_edges:
            raise RouteGraphError("route graph requires at least one edge")
        ordered = sorted(
            raw_edges,
            key=lambda edge: (
                edge.stage,
                edge.input_mint,
                edge.output_mint,
                edge.pool_key,
                edge.input_amount,
                edge.output_amount,
                edge.venue,
            ),
        )
        branch_by_stage: dict[int, int] = {}
        edges_list: list[RouteEdge] = []
        for edge in ordered:
            branch = branch_by_stage.get(edge.stage, 0)
            branch_by_stage[edge.stage] = branch + 1
            edges_list.append(replace(edge, branch=branch))
        edges = tuple(edges_list)
        object.__setattr__(self, "edges", edges)
        self._validate_order_and_conservation()
        object.__setattr__(
            self,
            "_resource_footprint",
            OpportunityResourceFootprint.from_edges(edges),
        )
        payload = {
            "provider": self.provider,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "input_amount": str(self.input_amount),
            "expected_output": str(self.expected_output),
            "guaranteed_output": (
                None if self.guaranteed_output is None else str(self.guaranteed_output)
            ),
            "asset_generation": self.asset_generation,
            "normalization_version": self.normalization_version,
            "edges": [edge.semantic_row() for edge in edges],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        object.__setattr__(
            self, "_semantic_hash", hashlib.sha256(canonical.encode()).hexdigest()
        )

    def _validate_order_and_conservation(self) -> None:
        identities = [
            (
                edge.stage,
                edge.pool_key,
                edge.input_mint,
                edge.output_mint,
                edge.input_amount,
                edge.output_amount,
            )
            for edge in self.edges
        ]
        if len(identities) != len(set(identities)):
            raise RouteGraphError("duplicate semantic route edge")

        by_stage: dict[int, list[RouteEdge]] = {}
        for edge in self.edges:
            by_stage.setdefault(edge.stage, []).append(edge)
        for stage, edges in by_stage.items():
            total = sum(edge.allocation_bps.value for edge in edges)
            if total != 10_000:
                raise RouteGraphError(
                    f"route allocation for stage {stage} must sum to 10000 bps"
                )

        balances: dict[str, int] = {self.input_mint: self.input_amount}
        for stage in sorted(by_stage):
            stage_edges = by_stage[stage]
            required: dict[str, int] = {}
            produced: dict[str, int] = {}
            for edge in stage_edges:
                required[edge.input_mint] = (
                    required.get(edge.input_mint, 0) + edge.input_amount
                )
                produced[edge.output_mint] = (
                    produced.get(edge.output_mint, 0) + edge.output_amount
                )
            for mint, amount in required.items():
                available = balances.get(mint, 0)
                if amount > available:
                    raise RouteGraphError(
                        f"stage {stage} consumes {amount} {mint}, "
                        f"only {available} available"
                    )
                balances[mint] = available - amount
            for mint, amount in produced.items():
                result = balances.get(mint, 0) + amount
                if result > U64_MAX:
                    raise RouteGraphError("route balance overflows u64")
                balances[mint] = result

        terminal = balances.get(self.output_mint, 0)
        if terminal != self.expected_output:
            raise RouteGraphError(
                "route graph terminal output must equal declared expected output"
            )
        residual = {
            mint: amount
            for mint, amount in balances.items()
            if mint != self.output_mint and amount != 0
        }
        if residual:
            raise RouteGraphError("route graph leaves unconsumed non-terminal balances")
        if self.guaranteed_output is not None and terminal < self.guaranteed_output:
            raise RouteGraphError(
                "route graph does not conserve the declared guaranteed output"
            )

    @property
    def semantic_hash(self) -> str:
        return self._semantic_hash

    @property
    def resource_footprint(self) -> OpportunityResourceFootprint:
        return self._resource_footprint

    @property
    def route_labels(self) -> tuple[str, ...]:
        return tuple(edge.venue for edge in self.edges)


__all__ = [
    "OpportunityResourceFootprint",
    "RouteEdge",
    "RouteEdgeKind",
    "RouteGraph",
    "RouteGraphError",
]
