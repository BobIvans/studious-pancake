"""Fail-closed runtime admission for MPR-CLOSE-03 provider/protocol evidence.

This module is dependency-light by design.  It translates provider conformance
state into a single admission decision used by the runtime data plane.  It does
not send transactions, load signers, or resolve secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class ProviderRole(str, Enum):
    EXECUTION_COMPOSABLE = "execution_composable"
    DISCOVERY_ONLY = "discovery_only"
    PROTOCOL_LENDING = "protocol_lending"


class ConformanceState(str, Enum):
    CONFORMANCE_READY = "conformance_ready"
    FIXTURE_ONLY_BLOCKED = "fixture_only_blocked"
    DISABLED_FAIL_CLOSED = "disabled_fail_closed"
    DISCOVERY_ONLY = "discovery_only"


@dataclass(frozen=True, slots=True)
class ProviderConformance:
    provider: str
    role: ProviderRole
    state: ConformanceState
    evidence_digest: str | None = None
    reviewed: bool = False
    raw_instruction_composable: bool = False
    rooted_slot_coherent: bool = False


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    admitted: bool
    reason: str
    provider: str


EXECUTION_PROVIDER_ALLOWLIST = frozenset({"jupiter_v2_build"})
DISCOVERY_ONLY_PROVIDERS = frozenset({"okx", "openocean", "odos"})
LENDING_PROTOCOLS = frozenset({"marginfi_v2", "kamino_klend"})


def _valid_sha256(value: str | None) -> bool:
    if value is None or len(value) != 64:
        return False
    return all(ch in "0123456789abcdef" for ch in value.lower())


def admit_provider(candidate: ProviderConformance) -> AdmissionDecision:
    """Return one deterministic, fail-closed data-plane admission decision."""

    name = candidate.provider.strip().lower()
    if not name:
        return AdmissionDecision(False, "provider_name_missing", name)

    if name in DISCOVERY_ONLY_PROVIDERS:
        if candidate.role is not ProviderRole.DISCOVERY_ONLY:
            return AdmissionDecision(False, "discovery_provider_role_escalation", name)
        if candidate.raw_instruction_composable:
            return AdmissionDecision(False, "discovery_provider_execution_claim", name)
        return AdmissionDecision(True, "discovery_only_admitted", name)

    if name == "jupiter_v2_build":
        if candidate.role is not ProviderRole.EXECUTION_COMPOSABLE:
            return AdmissionDecision(False, "jupiter_execution_role_required", name)
        if candidate.state is not ConformanceState.CONFORMANCE_READY:
            return AdmissionDecision(False, "jupiter_conformance_not_ready", name)
        if not candidate.raw_instruction_composable:
            return AdmissionDecision(False, "jupiter_raw_instruction_proof_missing", name)
        if not candidate.reviewed or not _valid_sha256(candidate.evidence_digest):
            return AdmissionDecision(False, "jupiter_reviewed_evidence_missing", name)
        return AdmissionDecision(True, "execution_composable_admitted", name)

    if name in LENDING_PROTOCOLS:
        if candidate.role is not ProviderRole.PROTOCOL_LENDING:
            return AdmissionDecision(False, "lending_protocol_role_required", name)
        if candidate.state is not ConformanceState.CONFORMANCE_READY:
            return AdmissionDecision(False, "lending_protocol_blocked", name)
        if not candidate.rooted_slot_coherent:
            return AdmissionDecision(False, "rooted_slot_coherence_missing", name)
        if not candidate.reviewed or not _valid_sha256(candidate.evidence_digest):
            return AdmissionDecision(False, "reviewed_protocol_evidence_missing", name)
        return AdmissionDecision(True, "lending_protocol_admitted", name)

    return AdmissionDecision(False, "provider_not_allowlisted", name)


def evaluate_registry(
    registry: Iterable[ProviderConformance],
) -> Mapping[str, AdmissionDecision]:
    """Evaluate a registry and reject duplicate provider identities."""

    decisions: dict[str, AdmissionDecision] = {}
    for candidate in registry:
        key = candidate.provider.strip().lower()
        if key in decisions:
            decisions[key] = AdmissionDecision(False, "duplicate_provider_identity", key)
            continue
        decisions[key] = admit_provider(candidate)
    return decisions
