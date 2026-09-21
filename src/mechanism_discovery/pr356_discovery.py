"""PR-356 typed scientific discovery and negative-knowledge primitives."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .pr356_contracts import (
    HypothesisProgram,
    NegativeKnowledgeCard,
    PR356ContractError,
    canonical_hash,
)


def define_hypothesis_program(payload: Mapping[str, Any]) -> HypothesisProgram:
    return HypothesisProgram(
        hypothesis_id=str(payload["hypothesis_id"]),
        mechanism_motif_id=str(payload["mechanism_motif_id"]),
        observed_variables=tuple(str(x) for x in payload["observed_variables"]),
        latent_variables=tuple(str(x) for x in payload.get("latent_variables", ())),
        target=str(payload["target"]),
        lag=int(payload.get("lag", 0)),
        horizon=int(payload["horizon"]),
        regime=str(payload["regime"]),
        null_hypothesis=str(payload["null_hypothesis"]),
        reject_condition=str(payload["reject_condition"]),
        counterexample_class=str(payload["counterexample_class"]),
        data_requirements=tuple(str(x) for x in payload.get("data_requirements", ())),
        cost_budget={str(k): int(v) for k, v in dict(payload.get("cost_budget", {})).items()},
        holdout_id=str(payload["holdout_id"]),
    )


def canonicalize_hypothesis_identity(program: HypothesisProgram) -> str:
    semantic = {
        "motif": program.mechanism_motif_id,
        "observed": tuple(sorted(program.observed_variables)),
        "latent": tuple(sorted(program.latent_variables)),
        "target": program.target,
        "lag": program.lag,
        "horizon": program.horizon,
        "regime": program.regime,
        "null": program.null_hypothesis,
        "reject": program.reject_condition,
        "counterexample": program.counterexample_class,
    }
    return canonical_hash(semantic)


def detect_trivial_reparameterization(
    candidate: HypothesisProgram, prior: HypothesisProgram
) -> Mapping[str, Any]:
    duplicate = canonicalize_hypothesis_identity(candidate) == canonicalize_hypothesis_identity(prior)
    return {"duplicate": duplicate, "reason": "SEMANTIC_IDENTITY_MATCH" if duplicate else "NOVEL_DELTA_PRESENT"}


def detect_prior_rejection_overlap(
    candidate: HypothesisProgram, negatives: Sequence[NegativeKnowledgeCard]
) -> Mapping[str, Any]:
    motif = candidate.mechanism_motif_id
    matches = tuple(card.negative_id for card in negatives if card.mechanism_motif == motif)
    return {"overlap": bool(matches), "negative_ids": matches}


def publish_novelty_receipt(
    candidate: HypothesisProgram,
    priors: Sequence[HypothesisProgram],
    negatives: Sequence[NegativeKnowledgeCard],
) -> Mapping[str, Any]:
    identity = canonicalize_hypothesis_identity(candidate)
    duplicates = tuple(
        prior.hypothesis_id for prior in priors if canonicalize_hypothesis_identity(prior) == identity
    )
    negative_overlap = detect_prior_rejection_overlap(candidate, negatives)
    verdict = "DUPLICATE" if duplicates else ("COUNTEREXAMPLE_REVIEW_REQUIRED" if negative_overlap["overlap"] else "NOVEL")
    payload = {
        "hypothesis_id": candidate.hypothesis_id,
        "semantic_identity": identity,
        "duplicates": duplicates,
        "negative_overlap": negative_overlap["negative_ids"],
        "verdict": verdict,
    }
    return {**payload, "receipt_hash": canonical_hash(payload)}


def declare_symbolic_units(units: Mapping[str, str]) -> Mapping[str, str]:
    if not units:
        raise PR356ContractError("SYMBOLIC_UNITS_REQUIRED")
    normalized = {}
    for variable, unit in units.items():
        if not variable or not unit:
            raise PR356ContractError("SYMBOLIC_UNIT_INVALID")
        normalized[str(variable)] = str(unit)
    return normalized


def reject_dimensionally_invalid_expression(
    *, left_unit: str, right_unit: str
) -> Mapping[str, Any]:
    compatible = bool(left_unit) and left_unit == right_unit
    return {"dimensionally_valid": compatible, "rejected": not compatible}


def validate_symbolic_law_out_of_sample(
    *, train_error_atoms: int, holdout_error_atoms: int, baseline_holdout_error_atoms: int
) -> Mapping[str, Any]:
    if min(train_error_atoms, holdout_error_atoms, baseline_holdout_error_atoms) < 0:
        raise PR356ContractError("SYMBOLIC_ERROR_NEGATIVE")
    return {
        "train_error_atoms": train_error_atoms,
        "holdout_error_atoms": holdout_error_atoms,
        "baseline_holdout_error_atoms": baseline_holdout_error_atoms,
        "oos_improves": holdout_error_atoms < baseline_holdout_error_atoms,
        "overfit_warning": holdout_error_atoms > train_error_atoms * 2,
    }


def downgrade_to_predictive_association(
    *, claim_id: str, identifiability_ok: bool, refuters_passed: bool
) -> Mapping[str, Any]:
    causal = identifiability_ok and refuters_passed
    return {
        "claim_id": claim_id,
        "claim_kind": "CAUSAL" if causal else "PREDICTIVE_ASSOCIATION",
        "causal_authority": causal,
        "downgraded": not causal,
    }


def define_strategy_program_grammar(allowed_operations: Sequence[str]) -> Mapping[str, Any]:
    operations = tuple(sorted({str(item).upper() for item in allowed_operations}))
    forbidden = {"SIGN", "SUBMIT", "SEND", "FUND", "REMOTE_MUTATE"}
    if forbidden.intersection(operations):
        raise PR356ContractError("STRATEGY_GRAMMAR_EFFECT_FORBIDDEN")
    return {"allowed_operations": operations, "execution_right": False}


def prove_program_prefix_feasibility(
    steps: Sequence[Mapping[str, int]], *, initial_balance_atoms: int
) -> Mapping[str, Any]:
    balance = int(initial_balance_atoms)
    trace = [balance]
    for step in steps:
        balance += int(step.get("delta_atoms", 0))
        trace.append(balance)
        if balance < 0:
            return {"proved": False, "reason": "NEGATIVE_PREFIX_BALANCE", "trace": tuple(trace)}
    return {"proved": True, "trace": tuple(trace)}


def prove_program_obligation_closure(
    temporary_obligations: Mapping[str, int], settled_obligations: Mapping[str, int]
) -> Mapping[str, Any]:
    remaining = {
        key: int(amount) - int(settled_obligations.get(key, 0))
        for key, amount in temporary_obligations.items()
    }
    open_items = {key: value for key, value in remaining.items() if value != 0}
    return {"proved": not open_items, "remaining": open_items}


def publish_strategy_synthesis_verdict(
    *, prefix_proved: bool, obligations_closed: bool, duplicate: bool, blocked: bool
) -> Mapping[str, Any]:
    if blocked:
        verdict = "BLOCKED"
    elif duplicate:
        verdict = "DUPLICATE"
    elif not prefix_proved or not obligations_closed:
        verdict = "INVALID"
    else:
        verdict = "NEW_RESEARCH_HYPOTHESIS"
    return {"verdict": verdict, "execution_right": False}


def canonicalize_negative_result(payload: Mapping[str, Any]) -> NegativeKnowledgeCard:
    return NegativeKnowledgeCard(
        negative_id=str(payload["negative_id"]),
        canonical_claim=str(payload["canonical_claim"]),
        mechanism_motif=str(payload["mechanism_motif"]),
        failed_assumptions=tuple(str(x) for x in payload.get("failed_assumptions", ())),
        minimal_counterexample=dict(payload.get("minimal_counterexample", {})),
        valid_from=int(payload["valid_from"]),
        valid_until=None if payload.get("valid_until") is None else int(payload["valid_until"]),
        retest_trigger=str(payload["retest_trigger"]),
        rediscovery_count=int(payload.get("rediscovery_count", 0)),
    )


def extract_minimal_counterexample(card: NegativeKnowledgeCard) -> Mapping[str, Any]:
    return dict(card.minimal_counterexample)


def retrieve_counterexample_for_new_hypothesis(
    program: HypothesisProgram, cards: Sequence[NegativeKnowledgeCard]
) -> tuple[NegativeKnowledgeCard, ...]:
    return tuple(card for card in cards if card.mechanism_motif == program.mechanism_motif_id)


def publish_negative_knowledge_card(card: NegativeKnowledgeCard) -> Mapping[str, Any]:
    payload = asdict(card)
    return {**payload, "card_hash": canonical_hash(payload), "execution_right": False}
