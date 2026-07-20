"""Bounded polling, webhook replay protection and detector backpressure."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
from typing import Protocol

from .common import (
    DataConsistencyPolicy,
    DataPlaneError,
    DataPlaneReason,
    SCHEMA_VERSION,
    canonical_hash,
    non_empty,
    non_negative_int,
)


@dataclass(frozen=True, slots=True)
class PollPermit:
    key: str
    issued_monotonic_ms: int
    generation: int


class PollingFallbackController:
    def __init__(self, policy: DataConsistencyPolicy) -> None:
        self.policy = policy
        self.last_started: dict[str, int] = {}
        self.active: dict[str, PollPermit] = {}
        self.generation = 0

    def acquire(self, key: str, *, now_monotonic_ms: int) -> PollPermit:
        non_empty(key, "key")
        non_negative_int(now_monotonic_ms, "now_monotonic_ms")
        if key in self.active or len(self.active) >= self.policy.polling_max_inflight:
            raise DataPlaneError(
                DataPlaneReason.POLL_CAPACITY_EXHAUSTED,
                "polling fallback reached its inflight ceiling",
            )
        previous = self.last_started.get(key)
        if (
            previous is not None
            and now_monotonic_ms - previous < self.policy.polling_min_interval_ms
        ):
            raise DataPlaneError(
                DataPlaneReason.POLL_COOLDOWN,
                "polling fallback cadence is bounded",
            )
        self.generation += 1
        permit = PollPermit(key, now_monotonic_ms, self.generation)
        self.active[key] = permit
        self.last_started[key] = now_monotonic_ms
        return permit

    def release(self, permit: PollPermit) -> bool:
        if self.active.get(permit.key) != permit:
            return False
        del self.active[permit.key]
        return True


class WebhookSignatureVerifier(Protocol):
    def __call__(self, raw_body: bytes, signature: str) -> bool: ...


class HmacSha256Verifier:
    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < 16:
            raise ValueError("HMAC secret must contain at least 16 bytes")
        self.secret = secret

    def __call__(self, raw_body: bytes, signature: str) -> bool:
        expected = hmac.new(self.secret, raw_body, hashlib.sha256).hexdigest()
        return isinstance(signature, str) and hmac.compare_digest(
            expected, signature.lower()
        )


@dataclass(frozen=True, slots=True)
class WebhookAdmission:
    accepted: bool
    reason: DataPlaneReason
    delivery_id: str
    body_hash: str
    evidence_hash: str


class AuthenticatedWebhookGuard:
    def __init__(
        self, policy: DataConsistencyPolicy, verifier: WebhookSignatureVerifier
    ) -> None:
        self.policy = policy
        self.verifier = verifier
        self.seen: OrderedDict[str, int] = OrderedDict()

    def admit(
        self,
        *,
        delivery_id: str,
        sent_wall_ms: int,
        raw_body: bytes,
        signature: str,
        now_wall_ms: int,
    ) -> WebhookAdmission:
        non_empty(delivery_id, "delivery_id")
        non_negative_int(sent_wall_ms, "sent_wall_ms")
        non_negative_int(now_wall_ms, "now_wall_ms")
        if not isinstance(raw_body, bytes):
            raise TypeError("raw_body must be bytes")
        self._prune(now_wall_ms)
        body_hash = hashlib.sha256(raw_body).hexdigest()
        if len(raw_body) > self.policy.webhook_max_body_bytes:
            return self._result(
                False, DataPlaneReason.WEBHOOK_BODY_TOO_LARGE, delivery_id, body_hash
            )
        age = now_wall_ms - sent_wall_ms
        if (
            age > self.policy.webhook_max_age_ms
            or age < -self.policy.max_future_clock_skew_ms
        ):
            return self._result(
                False,
                DataPlaneReason.WEBHOOK_TIMESTAMP_INVALID,
                delivery_id,
                body_hash,
            )
        if delivery_id in self.seen:
            return self._result(
                False, DataPlaneReason.WEBHOOK_REPLAY, delivery_id, body_hash
            )
        if not self.verifier(raw_body, signature):
            return self._result(
                False, DataPlaneReason.WEBHOOK_AUTH_FAILED, delivery_id, body_hash
            )
        self.seen[delivery_id] = now_wall_ms
        while len(self.seen) > self.policy.webhook_max_seen_deliveries:
            self.seen.popitem(last=False)
        return self._result(True, DataPlaneReason.OK, delivery_id, body_hash)

    def _prune(self, now_wall_ms: int) -> None:
        cutoff = now_wall_ms - self.policy.webhook_nonce_ttl_ms
        while self.seen and next(iter(self.seen.values())) < cutoff:
            self.seen.popitem(last=False)

    @staticmethod
    def _result(
        accepted: bool,
        reason: DataPlaneReason,
        delivery_id: str,
        body_hash: str,
    ) -> WebhookAdmission:
        evidence = canonical_hash(
            {
                "schema": SCHEMA_VERSION,
                "accepted": accepted,
                "reason": reason.value,
                "delivery_id_hash": hashlib.sha256(delivery_id.encode()).hexdigest(),
                "body_hash": body_hash,
            }
        )
        return WebhookAdmission(accepted, reason, delivery_id, body_hash, evidence)


@dataclass(frozen=True, slots=True)
class DetectorPermit:
    candidate_id: str
    generation: int


class DetectorBackpressureGate:
    def __init__(self, policy: DataConsistencyPolicy) -> None:
        self.limit = policy.detector_max_inflight
        self.active: dict[str, DetectorPermit] = {}
        self.generation = 0

    def acquire(self, candidate_id: str) -> DetectorPermit:
        non_empty(candidate_id, "candidate_id")
        if candidate_id in self.active:
            return self.active[candidate_id]
        if len(self.active) >= self.limit:
            raise DataPlaneError(
                DataPlaneReason.BACKPRESSURE,
                "detector admission reached its inflight ceiling",
            )
        self.generation += 1
        permit = DetectorPermit(candidate_id, self.generation)
        self.active[candidate_id] = permit
        return permit

    def release(self, permit: DetectorPermit) -> bool:
        if self.active.get(permit.candidate_id) != permit:
            return False
        del self.active[permit.candidate_id]
        return True
