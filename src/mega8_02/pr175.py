"""PR-175 / TXVAR-01: exact unsigned transaction variant portfolio."""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from typing import Sequence
from .core import Mega802Error, ResourceEnvelope, stable_hash


@dataclass(frozen=True, slots=True)
class TransactionVariant:
    variant_id: str
    route_id: str
    lender_id: str
    format_id: str
    send_path: str
    message_sha256: str
    envelope: ResourceEnvelope
    expected_net: int


def generate_transaction_variants(
    *, route_ids: Sequence[str], lender_ids: Sequence[str],
    format_ids: Sequence[str], send_paths: Sequence[str],
) -> tuple[tuple[str, str, str, str], ...]:
    if not route_ids or not lender_ids or not format_ids or not send_paths:
        raise Mega802Error("TX_VARIANT_DIMENSION_EMPTY")
    return tuple(product(
        sorted(route_ids), sorted(lender_ids), sorted(format_ids), sorted(send_paths)
    ))


def bind_variant_resources(
    raw: tuple[str, str, str, str], *, message_sha256: str,
    envelope: ResourceEnvelope, expected_net: int,
) -> TransactionVariant:
    route, lender, fmt, send = raw
    return TransactionVariant(
        variant_id=stable_hash(
            {"route": route, "lender": lender, "format": fmt, "send": send,
             "message": message_sha256, "resources": envelope}
        ),
        route_id=route, lender_id=lender, format_id=fmt, send_path=send,
        message_sha256=message_sha256, envelope=envelope, expected_net=expected_net,
    )


def prune_dominated_variants(
    variants: Sequence[TransactionVariant],
) -> tuple[TransactionVariant, ...]:
    kept: list[TransactionVariant] = []
    for candidate in variants:
        dominated = any(
            other.variant_id != candidate.variant_id
            and other.expected_net >= candidate.expected_net
            and other.envelope.compute_units <= candidate.envelope.compute_units
            and other.envelope.message_bytes <= candidate.envelope.message_bytes
            and (
                other.expected_net > candidate.expected_net
                or other.envelope.compute_units < candidate.envelope.compute_units
                or other.envelope.message_bytes < candidate.envelope.message_bytes
            )
            for other in variants
        )
        if not dominated:
            kept.append(candidate)
    return tuple(sorted(kept, key=lambda item: item.variant_id))


def schedule_variant_simulations(
    variants: Sequence[TransactionVariant], *, max_count: int
) -> tuple[str, ...]:
    if max_count <= 0:
        raise Mega802Error("INVALID_SIMULATION_BUDGET")
    ranked = sorted(
        prune_dominated_variants(variants),
        key=lambda item: (
            -item.expected_net,
            item.envelope.compute_units,
            item.variant_id,
        ),
    )
    return tuple(item.variant_id for item in ranked[:max_count])
