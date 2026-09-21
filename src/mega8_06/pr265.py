"""PR-265 / NETWORK-03: offline TPU/QUIC adapter qualification."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_text, stable_hash


def build_tpu_quic_payload(
    signed_wire_hex: str, *, permit_message_sha256: str
) -> dict[str, str]:
    signed_wire_hex = require_text(signed_wire_hex, "signed_wire_hex")
    permit_message_sha256 = require_text(
        permit_message_sha256, "permit_message_sha256"
    )
    try:
        wire = bytes.fromhex(signed_wire_hex)
    except ValueError as exc:
        raise Mega806Error("INVALID_WIRE_HEX") from exc
    if not wire:
        raise Mega806Error("EMPTY_SIGNED_WIRE")
    return {
        "wire_sha256": stable_hash({"wire_hex": signed_wire_hex}),
        "permit_message_sha256": permit_message_sha256,
        "transport": "TPU_QUIC_HANDOFF_ONLY",
    }


def probe_tpu_endpoint(observation: Mapping[str, object]) -> dict[str, object]:
    endpoint_id = require_text(observation.get("endpoint_id"), "endpoint_id")
    return {
        "endpoint_id": endpoint_id,
        "latency_us": require_nonnegative_int(
            observation.get("latency_us"), "latency_us"
        ),
        "reachable": observation.get("reachable") is True,
        "generation": require_text(observation.get("generation"), "generation"),
    }


def simulate_direct_send_policy(
    attempts: Sequence[Mapping[str, object]], *, max_retries: int
) -> dict[str, object]:
    max_retries = require_nonnegative_int(max_retries, "max_retries")
    ambiguous = any(row.get("ambiguous") is True for row in attempts)
    if ambiguous:
        return {
            "allowed_retries": 0,
            "freeze": True,
            "reason": "AMBIGUOUS_OUTCOME",
        }
    return {
        "allowed_retries": min(max_retries, max(0, len(attempts))),
        "freeze": False,
        "reason": "OFFLINE_POLICY_ONLY",
    }


def qualify_direct_send_adapter(
    *,
    wire_parity: bool,
    bounded_retry_proven: bool,
    independent_finality: bool,
) -> bool:
    if not (wire_parity and bounded_retry_proven and independent_finality):
        raise Mega806Error("DIRECT_SEND_UNQUALIFIED")
    return True
