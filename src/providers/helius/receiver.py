"""Aiohttp receiver for the MEGA-PR B3 Helius delivery plane.

The receiver streams the compressed request body into a bounded buffer under one
monotonic deadline, then delegates authorization, decoding and durable enqueue to
``HeliusDeliveryPlane``.  It does no strategy work before acknowledgement.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import AsyncIterable, Callable

from aiohttp import web

from .delivery import DeliveryOutcome, HeliusDeliveryPlane, RejectReason


@dataclass(frozen=True, slots=True)
class ReceiverOutcome:
    http_status: int
    payload: dict[str, object]


async def collect_bounded_body(
    chunks: AsyncIterable[bytes],
    *,
    max_compressed_bytes: int,
    deadline_monotonic_ns: int,
    clock_monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> bytes:
    if (
        isinstance(max_compressed_bytes, bool)
        or not isinstance(max_compressed_bytes, int)
        or max_compressed_bytes <= 0
    ):
        raise ValueError("max_compressed_bytes must be a positive integer")
    buffer = bytearray()
    async for chunk in chunks:
        if clock_monotonic_ns() > deadline_monotonic_ns:
            raise TimeoutError(RejectReason.DELIVERY_DEADLINE_EXCEEDED.value)
        if not isinstance(chunk, bytes):
            raise TypeError("request body chunks must be bytes")
        if len(buffer) + len(chunk) > max_compressed_bytes:
            raise OverflowError(RejectReason.BODY_TOO_LARGE.value)
        buffer.extend(chunk)
    if clock_monotonic_ns() > deadline_monotonic_ns:
        raise TimeoutError(RejectReason.DELIVERY_DEADLINE_EXCEEDED.value)
    return bytes(buffer)


class HeliusReceiverService:
    """Real bounded HTTP receiver with durable-before-ACK semantics."""

    def __init__(
        self,
        plane: HeliusDeliveryPlane,
        *,
        path: str = "/webhook",
        clock_monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError("receiver path must be absolute")
        self.plane = plane
        self.path = path
        self.clock_monotonic_ns = clock_monotonic_ns

    def create_app(self) -> web.Application:
        application = web.Application(
            client_max_size=self.plane.config.limits.max_compressed_bytes
        )
        application.router.add_post(self.path, self.handle)
        return application

    async def handle(self, request: web.Request) -> web.Response:
        started_ns = self.clock_monotonic_ns()
        deadline_ns = (
            started_ns
            + self.plane.config.limits.delivery_deadline_ms * 1_000_000
        )
        try:
            raw_body = await collect_bounded_body(
                request.content.iter_chunked(64 * 1024),
                max_compressed_bytes=(
                    self.plane.config.limits.max_compressed_bytes
                ),
                deadline_monotonic_ns=deadline_ns,
                clock_monotonic_ns=self.clock_monotonic_ns,
            )
        except OverflowError:
            return self._response(
                413,
                reason=RejectReason.BODY_TOO_LARGE.value,
            )
        except TimeoutError:
            return self._response(
                503,
                reason=RejectReason.DELIVERY_DEADLINE_EXCEEDED.value,
            )
        except (TypeError, ValueError):
            return self._response(
                400,
                reason=RejectReason.BAD_ENCODING.value,
            )

        outcome = self.plane.accept_delivery(
            headers=request.headers,
            raw_body=raw_body,
            webhook_id=request.match_info.get("webhook_id"),
            started_monotonic_ns=started_ns,
        )
        return self._delivery_response(outcome)

    @staticmethod
    def _delivery_response(outcome: DeliveryOutcome) -> web.Response:
        payload: dict[str, object] = {
            "schema_version": outcome.schema_version,
            "decision": outcome.decision.value,
            "reason": outcome.reason,
            "delivery_id": outcome.delivery_id,
            "accepted_event_count": outcome.accepted_event_count,
            "duplicate_event_count": outcome.duplicate_event_count,
            "gap_detected": outcome.gap_detected,
            "backfill_required": outcome.backfill_required,
            "duration_ms": outcome.duration_ms,
            "live_enabled": False,
            "sender_reachable": False,
        }
        return web.Response(
            status=outcome.http_status,
            body=json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8"),
            content_type="application/json",
        )

    @staticmethod
    def _response(status: int, *, reason: str) -> web.Response:
        return web.json_response(
            {
                "decision": "REJECTED",
                "reason": reason,
                "live_enabled": False,
                "sender_reachable": False,
            },
            status=status,
        )


__all__ = [
    "HeliusReceiverService",
    "ReceiverOutcome",
    "collect_bounded_body",
]
