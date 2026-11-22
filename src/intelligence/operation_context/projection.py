"""Deterministic OperationEpisode projection over canonical owners (OCA-W2).

Reads the canonical ``ObservabilityStore`` event log (read side only) and
groups events into deterministic, replayable operation episodes. Every join to
other canonical owners (MarketEpisode, provider evidence, runtime lineage) is
recorded with an explicit PRESENT/MISSING/UNKNOWN status — unmatched joins
stay UNKNOWN and are never inferred. Terminal outcomes require authoritative
reconciliation evidence; without it they remain UNKNOWN.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = "studious.operation-context.episode-projection.v1"


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_operation_episodes(store: Any) -> dict[str, Any]:
    """Project one deterministic episode per observed logical opportunity.

    ``store`` is any object exposing the canonical event-log read surface
    (``ObservabilityStore``); the projection never writes.
    """
    rows = list(
        store.db.execute(
            "SELECT * FROM event_log ORDER BY logical_opportunity_id, sequence_no"
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        record = {key: row[key] for key in row.keys()}
        grouped.setdefault(record.get("logical_opportunity_id") or "", []).append(
            record
        )
    episodes: list[dict[str, Any]] = []
    for opportunity_id in sorted(grouped):
        events = grouped[opportunity_id]
        ordered = sorted(
            events,
            key=lambda item: (item.get("sequence_no") or 0, item.get("event_id") or ""),
        )
        stage_timeline = [
            {
                "sequence_no": event.get("sequence_no"),
                "event_type": event.get("event_type"),
                "stage": event.get("stage") or event.get("event_type"),
                "outcome": str(event.get("outcome")),
                "reason_code": (
                    str(event.get("reason_code")) if event.get("reason_code") else None
                ),
                "attempt_id": event.get("attempt_id"),
                "event_id": event.get("event_id"),
                "producer_code_version": event.get("producer_code_version"),
                "config_checksum": event.get("config_checksum"),
            }
            for event in ordered
        ]
        # P2-4: terminal outcomes are authoritative reconciliation events
        # only — simulation success alone is never terminal, and outcome
        # enums do not encode reconciliation.
        terminal = [
            event
            for event in ordered
            if str(event.get("event_type")) == "reconciliation_completed"
        ]
        joins = {
            "market_episode": "UNKNOWN (no episode_id field on EventEnvelope; join key missing)",
            "provider_evidence": "UNKNOWN (provider_id present only on some events; no capture evidence)",
            "runtime_lineage": "MISSING (no production producer callsite on this main; OCA-W10 gate)",
        }
        episodes.append(
            {
                "episode_id": _digest(
                    {
                        "opportunity_id": opportunity_id,
                        "event_ids": [event.get("event_id") for event in ordered],
                    }
                )[:24],
                "logical_opportunity_id": opportunity_id,
                "event_count": len(ordered),
                "stage_timeline": stage_timeline,
                "terminal_outcome": (
                    {
                        "outcome": terminal[-1].get("outcome"),
                        "event_id": terminal[-1].get("event_id"),
                    }
                    if terminal
                    else {
                        "outcome": "UNKNOWN",
                        "reason": "NO_AUTHORITATIVE_RECONCILIATION_EVENT (simulation/paper success is not terminal without reconciliation)",
                    }
                ),
                "joins": joins,
                "producer_provenance": ordered[0].get("producer_code_version")
                or "UNKNOWN",
            }
        )
    episodes.sort(key=lambda item: item["episode_id"])
    return {
        "schema": SCHEMA,
        "episodes": episodes,
        "coverage": {
            "opportunities_observed": len(episodes),
            "joins_present": sum(
                1
                for episode in episodes
                for status in episode["joins"].values()
                if status == "PRESENT"
            ),
            "joins_unknown_or_missing": sum(
                1
                for episode in episodes
                for status in episode["joins"].values()
                if status != "PRESENT"
            ),
        },
        "projection_digest": _digest(episodes),
    }
