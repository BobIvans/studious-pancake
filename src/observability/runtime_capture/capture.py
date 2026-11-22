"""Runtime event capture for supported paper/shadow routes (OCA-W10).

Wires REAL EventEnvelope producers through the canonical
``AuthoritativeObservabilityStore`` — the first production producer callsites
on this main (OCA-W0 trace recorded zero). Non-negotiables:

- critical decisions/rejections/gaps are NEVER sampled (no sampling at all in
  this module; any future heartbeat sampling needs a separate policy owner);
- capture failures surface as explicit DEGRADED receipts — never silent loss;
- provenance is real: runtime identity, producer version and config checksum
  are recorded on every event (no test-runtime defaults from this path).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..events import EventEnvelope, EventType, Outcome, make_event
from ..reasons import ReasonCode
from ..authoritative_store_pr195 import AuthoritativeObservabilityStore

PRODUCER_CODE_VERSION = "runtime-capture@v1"
SCHEMA = "studious.observability.runtime-capture.v1"


class CaptureReceipt(dict):
    """Explicit receipt for one capture attempt (never a silent drop)."""


class RuntimeCaptureAdapter:
    """Stage-event producer for one runtime route, bound to one store."""

    def __init__(
        self,
        store: AuthoritativeObservabilityStore,
        *,
        runtime_id: str,
        config_checksum: str,
        route: str,
    ) -> None:
        self._store = store
        self._runtime_id = runtime_id
        self._config_checksum = config_checksum
        self._route = route

    @property
    def route(self) -> str:
        return self._route

    def capture_stage(
        self,
        *,
        logical_opportunity_id: str,
        sequence_no: int,
        event_type: EventType,
        outcome: Outcome = Outcome.observed,
        stage: str | None = None,
        reason_code: str | None = None,
        provider_id: str | None = None,
        venue_id: str | None = None,
        critical: bool = False,
        attributes: dict[str, Any] | None = None,
    ) -> CaptureReceipt:
        """Produce and store one stage event with real provenance.

        A store failure yields a DEGRADED receipt carrying the durable intent
        hash for replay — the event is never silently dropped.
        """
        envelope: EventEnvelope | None = None
        degraded_reason = None
        intent = {
            "logical_opportunity_id": logical_opportunity_id,
            "sequence_no": sequence_no,
            "event_type": event_type.value,
            "outcome": outcome.value,
            "stage": stage,
            "reason_code": reason_code,
            "route": self._route,
        }
        idempotency_key = hashlib.sha256(
            json.dumps(intent, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]
        try:
            # String inputs are coerced to the canonical enum types so callers
            # can pass plain stage-config values without losing validation.
            if isinstance(reason_code, str):
                reason_code = ReasonCode(reason_code)
            envelope = make_event(
                event_type=event_type,
                logical_opportunity_id=logical_opportunity_id,
                plan_hash=self._config_checksum,
                sequence_no=sequence_no,
                stage=stage or event_type.value,
                outcome=outcome,
                reason_code=reason_code,
                provider_id=provider_id,
                venue_id=venue_id,
                attributes={**(attributes or {}), "route": self._route},
                critical=critical,
                runtime_id=self._runtime_id,
                producer_code_version=PRODUCER_CODE_VERSION,
                config_checksum=self._config_checksum,
            )
            stored = self._store.append(envelope)
        except Exception as exc:  # noqa: BLE001 - degraded, never silent
            envelope = None
            degraded_reason = f"{type(exc).__name__}: {exc}"
        if envelope is None or not stored:
            return CaptureReceipt(
                {
                    "schema": SCHEMA,
                    "status": "DEGRADED",
                    "idempotency_key": idempotency_key,
                    "degraded_reason": degraded_reason or "STORE_REJECTED_EVENT",
                    "replayable": True,
                }
            )
        return CaptureReceipt(
            {
                "schema": SCHEMA,
                "status": "CAPTURED",
                "event_id": envelope.event_id,
                "idempotency_key": idempotency_key,
                "runtime_id": self._runtime_id,
                "producer_code_version": PRODUCER_CODE_VERSION,
                "config_checksum": self._config_checksum,
                "critical": critical,
            }
        )


def default_vertical_adapter(
    db_path: str | Path,
    *,
    environment: str = "paper",
    cluster_genesis: str = "fixture-genesis",
    release_id: str = "runtime-capture-vertical",
    runtime_id: str = "paper-vertical-1",
    config_checksum: str = "vertical-config-v1",
) -> RuntimeCaptureAdapter:
    """Capture adapter bound to the supported offline/paper vertical.

    Identity is bootstrapped once (startup-only migration, canonical PR-195
    pattern) before the adapter binds to the store.
    """
    identity = {
        "environment": environment,
        "cluster_genesis": cluster_genesis,
        "release_id": release_id,
    }
    if not Path(db_path).exists():
        with AuthoritativeObservabilityStore(
            str(db_path),
            migration_mode=True,
            migration_owner="runtime-capture-bootstrap",
            environment=environment,
            cluster_genesis=cluster_genesis,
            release_id=release_id,
        ):
            pass
    store = AuthoritativeObservabilityStore(
        str(db_path),
        environment=environment,
        cluster_genesis=cluster_genesis,
        release_id=release_id,
    )
    return RuntimeCaptureAdapter(
        store,
        runtime_id=runtime_id,
        config_checksum=config_checksum,
        route="paper-shadow:solana:atomic-vertical",
    )
