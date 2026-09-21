"""PR-355 exploit-aware mechanism admission using incident evidence."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import stable_hash
from .evidence_native_core import EvidenceNativeError, record, require_int, require_text


def ingest_protocol_incident(payload: Mapping[str, Any]):
    timeline = tuple(
        {
            "at": require_int(row.get("at"), "incident_at", minimum=0),
            "state": require_text(row.get("state"), "incident_state"),
        }
        for row in payload.get("timeline", ())
    )
    if not timeline:
        raise EvidenceNativeError("INCIDENT_TIMELINE_REQUIRED")
    return record(
        "ingest_protocol_incident",
        {
            "incident_id": require_text(payload.get("incident_id"), "incident_id"),
            "deployment_id": require_text(payload.get("deployment_id"), "deployment_id"),
            "root_cause_hypothesis": require_text(payload.get("root_cause_hypothesis"), "root_cause_hypothesis"),
            "timeline": timeline,
            "affected_state_hash": stable_hash("pr355:incident-state", payload.get("affected_state", {})),
        },
    )


def derive_incident_invariant_tests(payload: Mapping[str, Any]):
    mechanics = tuple(str(x) for x in payload.get("mechanics", ()))
    if not mechanics:
        raise EvidenceNativeError("INCIDENT_MECHANICS_REQUIRED")
    tests = tuple(
        {
            "invariant_id": stable_hash("pr355:incident-invariant", {"mechanic": mechanic})[:16],
            "mechanic": mechanic,
            "test_kinds": ("PROPERTY", "FUZZ", "DIFFERENTIAL"),
        }
        for mechanic in mechanics
    )
    return record("derive_incident_invariant_tests", {"tests": tests, "test_count": len(tests)})


def build_adversarial_mechanism_states(payload: Mapping[str, Any]):
    base = payload.get("base_state")
    mutations = tuple(payload.get("mutations", ()))
    if not isinstance(base, Mapping) or not mutations:
        raise EvidenceNativeError("ADVERSARIAL_STATE_INPUT_REQUIRED")
    states = []
    for index, mutation in enumerate(mutations):
        if not isinstance(mutation, Mapping):
            raise EvidenceNativeError("ADVERSARIAL_MUTATION_OBJECT_REQUIRED")
        state = dict(base)
        state.update(mutation)
        states.append({"scenario": index, "state_hash": stable_hash("pr355:adversarial-state", state)})
    return record("build_adversarial_mechanism_states", {"states": tuple(states)})


def quarantine_vulnerable_deployment(payload: Mapping[str, Any]):
    vulnerable = bool(payload.get("known_vulnerable", False))
    fixed = bool(payload.get("fix_attested", False))
    quarantine = vulnerable and not fixed
    return record(
        "quarantine_vulnerable_deployment",
        {
            "deployment_id": require_text(payload.get("deployment_id"), "deployment_id"),
            "quarantined": quarantine,
            "production_adapter_allowed": False if quarantine else bool(payload.get("independently_qualified", False)),
        },
    )


def detect_semantic_security_drift(payload: Mapping[str, Any]):
    previous = require_text(payload.get("previous_semantic_hash"), "previous_semantic_hash")
    current = require_text(payload.get("current_semantic_hash"), "current_semantic_hash")
    config_previous = require_text(payload.get("previous_config_hash"), "previous_config_hash")
    config_current = require_text(payload.get("current_config_hash"), "current_config_hash")
    drift = previous != current or config_previous != config_current
    return record(
        "detect_semantic_security_drift",
        {"drift": drift, "invalidate_prior_safety_evidence": drift},
    )


def gate_mechanism_admission_on_security(payload: Mapping[str, Any]):
    incident_coverage = bool(payload.get("incident_coverage_complete", False))
    invariant_coverage = bool(payload.get("invariant_tests_passed", False))
    deployment_fixed = bool(payload.get("deployment_fixed_or_not_affected", False))
    admitted = incident_coverage and invariant_coverage and deployment_fixed
    return record(
        "gate_mechanism_admission_on_security",
        {"research_admitted": admitted, "execution_admitted": False, "security_blocked": not admitted},
    )
