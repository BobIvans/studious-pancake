"""PR-177 / SOLANA-CONFIG-01: verified program/config change events."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import EvidenceBinding, Mega802Error, offline_result, stable_hash


@dataclass(frozen=True, slots=True)
class ProgramChange:
    program_id: str
    old_generation: str
    new_generation: str
    change_kind: str
    evidence: EvidenceBinding


def collect_program_upgrade_events(
    events: Sequence[ProgramChange], *, now: int
) -> tuple[ProgramChange, ...]:
    for event in events:
        event.evidence.assert_usable(now=now)
        if event.old_generation == event.new_generation:
            raise Mega802Error("NO_PROGRAM_GENERATION_CHANGE")
    return tuple(
        sorted(events, key=lambda item: (item.program_id, item.new_generation))
    )


def collect_protocol_config_changes(
    events: Sequence[ProgramChange], *, now: int
) -> tuple[ProgramChange, ...]:
    return tuple(
        event
        for event in collect_program_upgrade_events(events, now=now)
        if event.change_kind in {"config", "fee", "authority", "binary"}
    )


def classify_upgrade_impact(event: ProgramChange) -> str:
    if event.change_kind in {"binary", "authority"}:
        return "REQUALIFY_ALL_CAPABILITIES"
    if event.change_kind in {"fee", "config"}:
        return "REQUALIFY_AFFECTED_CAPABILITIES"
    return "RESEARCH_REVIEW"


def trigger_protocol_requalification(event: ProgramChange, *, now: int) -> str:
    result = offline_result(
        "trigger_protocol_requalification",
        event.evidence,
        {"event": stable_hash(event), "impact": classify_upgrade_impact(event)},
        now=now,
        reason="REQUALIFICATION_REQUIRED",
    )
    return result.payload_sha256
