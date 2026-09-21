"""PR-271 / PERF-01: isolated Rust accelerator protocol and parity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .core import Mega807Error, require_id, require_positive, stable_hash


@dataclass(frozen=True, slots=True)
class RustSidecarProtocol:
    protocol_id: str
    version: str
    max_batch: int
    network_access: bool = False
    signer_access: bool = False

    def __post_init__(self) -> None:
        require_id(self.protocol_id, "protocol_id")
        require_id(self.version, "version")
        require_positive(self.max_batch, "max_batch")
        if self.network_access or self.signer_access:
            raise Mega807Error("SIDECAR_AUTHORITY_FORBIDDEN")


def define_rust_sidecar_protocol(
    *, protocol_id: str, version: str, max_batch: int
) -> RustSidecarProtocol:
    return RustSidecarProtocol(protocol_id, version, max_batch)


def batch_quote_in_rust(
    protocol: RustSidecarProtocol,
    amounts: Sequence[int],
    *,
    numerator: int,
    denominator: int,
) -> tuple[int, ...]:
    if len(amounts) > protocol.max_batch:
        raise Mega807Error("SIDECAR_BATCH_LIMIT")
    require_positive(numerator, "numerator")
    require_positive(denominator, "denominator")
    return tuple(
        require_positive(v, "amount") * numerator // denominator for v in amounts
    )


def search_routes_in_rust(
    protocol: RustSidecarProtocol,
    adjacency: Mapping[str, Sequence[str]],
    *,
    start: str,
    target: str,
    max_hops: int = 5,
) -> tuple[tuple[str, ...], ...]:
    require_id(start, "start")
    require_id(target, "target")
    if not 1 <= max_hops <= 5:
        raise Mega807Error("INVALID_HOP_LIMIT")
    routes: set[tuple[str, ...]] = set()

    def walk(node: str, path: tuple[str, ...]) -> None:
        if len(path) - 1 > max_hops:
            return
        if node == target:
            routes.add(path)
            return
        for nxt in sorted(set(adjacency.get(node, ()))):
            if nxt in path:
                continue
            walk(nxt, path + (nxt,))

    walk(start, (start,))
    if len(routes) > protocol.max_batch:
        raise Mega807Error("SIDECAR_ROUTE_LIMIT")
    return tuple(sorted(routes))


def verify_sidecar_parity(
    reference: Sequence[int],
    accelerated: Sequence[int],
    *,
    protocol: RustSidecarProtocol,
) -> str:
    if tuple(reference) != tuple(accelerated):
        raise Mega807Error("SIDECAR_PARITY_MISMATCH")
    return stable_hash(
        "mega8-07-rust-parity",
        {
            "protocol": protocol.protocol_id,
            "version": protocol.version,
            "outputs": list(accelerated),
        },
    )
