"""PR-355 bounded causal intervention and financial digital-twin research."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_native_core import EvidenceNativeError, record, require_int, require_text


def define_market_intervention(payload: Mapping[str, Any]):
    kind = require_text(payload.get("kind"), "kind").upper()
    if kind not in {"POLICY", "CONFIG", "QUEUE", "SLASH", "CAP"}:
        raise EvidenceNativeError("INTERVENTION_KIND_UNSUPPORTED")
    return record(
        "define_market_intervention",
        {
            "intervention_id": require_text(payload.get("intervention_id"), "intervention_id"),
            "kind": kind,
            "effective_at": require_int(payload.get("effective_at"), "effective_at", minimum=0),
            "parameter": require_text(payload.get("parameter"), "parameter"),
            "delta_atoms": require_int(payload.get("delta_atoms", 0), "delta_atoms"),
        },
    )


def declare_causal_assumptions(payload: Mapping[str, Any]):
    confounders = tuple(str(x) for x in payload.get("confounders", ()))
    unobserved = tuple(str(x) for x in payload.get("unobserved_risks", ()))
    identification = require_text(payload.get("identification_strategy"), "identification_strategy")
    return record(
        "declare_causal_assumptions",
        {
            "confounders": confounders,
            "unobserved_risks": unobserved,
            "identification_strategy": identification,
            "causal_claim_supported": not unobserved and bool(payload.get("control_group_available", False)),
        },
    )


def simulate_intervention_twin(payload: Mapping[str, Any]):
    base = require_int(payload.get("base_state_atoms"), "base_state_atoms")
    delta = require_int(payload.get("intervention_delta_atoms"), "intervention_delta_atoms")
    spillovers = sum(require_int(x, "spillover_atoms") for x in payload.get("spillover_atoms", ()))
    ordering = require_text(payload.get("ordering"), "ordering")
    return record(
        "simulate_intervention_twin",
        {
            "base_state_atoms": base,
            "counterfactual_state_atoms": base + delta + spillovers,
            "ordering": ordering,
            "shared_state_mutation_modeled": True,
        },
    )


def compare_observed_and_counterfactual(payload: Mapping[str, Any]):
    observed = require_int(payload.get("observed_atoms"), "observed_atoms")
    alternatives = tuple(require_int(x, "counterfactual_atoms") for x in payload.get("counterfactual_atoms", ()))
    if not alternatives:
        raise EvidenceNativeError("COUNTERFACTUAL_REQUIRED")
    effects = tuple(observed - value for value in alternatives)
    return record(
        "compare_observed_and_counterfactual",
        {"observed_atoms": observed, "effect_atoms": effects, "alternative_count": len(alternatives)},
    )


def estimate_intervention_uncertainty(payload: Mapping[str, Any]):
    effects = tuple(require_int(x, "effect_atoms") for x in payload.get("effect_atoms", ()))
    if not effects:
        raise EvidenceNativeError("INTERVENTION_EFFECTS_REQUIRED")
    return record(
        "estimate_intervention_uncertainty",
        {
            "effect_low_atoms": min(effects),
            "effect_high_atoms": max(effects),
            "ordering_sensitive": min(effects) != max(effects),
        },
    )


def reject_unsupported_causal_claim(payload: Mapping[str, Any]):
    assumptions_ok = bool(payload.get("assumptions_supported", False))
    sensitivity_ok = bool(payload.get("sensitivity_bounded", False))
    conclusion = "CAUSAL_RESEARCH_ONLY" if assumptions_ok and sensitivity_ok else "ASSOCIATION_ONLY"
    return record(
        "reject_unsupported_causal_claim",
        {"conclusion": conclusion, "execution_right": False, "causal_claim_rejected": conclusion == "ASSOCIATION_ONLY"},
    )
