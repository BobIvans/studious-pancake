"""Deterministic readiness evidence for PR-040 and future PR-042 exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .common import ReadinessState, SCHEMA_VERSION, canonical_hash, json_safe


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    schema_version: str
    state: ReadinessState
    ready: bool
    reasons: tuple[str, ...]
    components: tuple[tuple[str, object], ...]
    evidence_hash: str

    @classmethod
    def build(
        cls,
        state: ReadinessState,
        reasons: Iterable[str],
        components: Mapping[str, object],
    ) -> "ReadinessReport":
        reason_tuple = tuple(sorted(set(reasons)))
        component_tuple = tuple(sorted(components.items(), key=lambda item: item[0]))
        evidence = canonical_hash(
            {
                "schema": SCHEMA_VERSION,
                "state": state.value,
                "reasons": reason_tuple,
                "components": json_safe(dict(component_tuple)),
            }
        )
        return cls(
            SCHEMA_VERSION,
            state,
            state is ReadinessState.READY,
            reason_tuple,
            component_tuple,
            evidence,
        )
