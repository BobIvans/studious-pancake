"""PR-294 / NF-861..864: solver-network cross-chain settlement."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, require_positive, result, stable_hash


def register_solver_network(*, network_id: str, escrow_contract: str, settlement_domain: str, identity_verified: bool) -> Result:
    if not identity_verified or not all((network_id,escrow_contract,settlement_domain)):
        raise Mega808Error("SOLVER_NETWORK_UNVERIFIED")
    return result("register_solver_network", {"network_id":network_id,"escrow_contract":escrow_contract,"settlement_domain":settlement_domain,"identity_verified":True})


def model_intent_settlement_guarantee(*, expiry: int, challenge_period: int, refund_right_verified: bool, partial_fill_allowed: bool) -> Result:
    expiry=require_nonnegative(expiry,"expiry")
    challenge=require_nonnegative(challenge_period,"challenge_period")
    blockers=() if refund_right_verified else ("REFUND_RIGHT_UNVERIFIED",)
    return result("model_intent_settlement_guarantee", {"expiry":expiry,"challenge_period":challenge,"refund_right_verified":refund_right_verified,"partial_fill_allowed":partial_fill_allowed,"atomic":False}, status="OK" if not blockers else "INCOMPLETE", blockers=blockers)


def score_crosschain_solver_risk(*, dependency_failures_ppm: Mapping[str,int], max_total_risk_ppm: int) -> Result:
    cap=require_nonnegative(max_total_risk_ppm,"max_total_risk_ppm")
    risks={k:require_nonnegative(v,f"risk_{k}") for k,v in dependency_failures_ppm.items()}
    total=min(1_000_000,sum(risks.values()))
    return result("score_crosschain_solver_risk", {"dependency_risks_ppm":risks,"total_upper_bound_ppm":total,"within_policy":total<=cap}, status="OK" if total<=cap else "BLOCKED", blockers=() if total<=cap else ("CROSSCHAIN_RISK_LIMIT",))


def reconcile_solver_settlement(*, source_debit: int, destination_credit: int|None, fees: int, finality_proven: bool) -> Result:
    debit=require_nonnegative(source_debit,"source_debit")
    fee=require_nonnegative(fees,"fees")
    if destination_credit is None or not finality_proven:
        return result("reconcile_solver_settlement", {"source_debit":debit,"destination_credit":destination_credit,"fees":fee,"settled":False}, status="UNKNOWN", blockers=("FINAL_OUTCOME_UNKNOWN",))
    credit=require_nonnegative(destination_credit,"destination_credit")
    return result("reconcile_solver_settlement", {"source_debit":debit,"destination_credit":credit,"fees":fee,"net":credit-debit-fee,"settled":True})
