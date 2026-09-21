"""PR-299 / NF-881..884: evidence-bound strategy proposal governance."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def submit_strategy_proposal(*, strategy_id: str, evidence_hashes: Sequence[str], max_loss: int, requested_stage: str="SHADOW") -> Result:
    if not strategy_id or not evidence_hashes:
        raise Mega808Error("PROPOSAL_EVIDENCE_REQUIRED")
    if requested_stage not in {"RESEARCH","SHADOW"}:
        raise Mega808Error("LIVE_PROMOTION_NOT_AUTHORIZED")
    return result("submit_strategy_proposal", {"strategy_id":strategy_id,"evidence_hashes":tuple(dict.fromkeys(evidence_hashes)),"max_loss":require_nonnegative(max_loss,"max_loss"),"requested_stage":requested_stage,"submission":False})


def review_strategy_evidence(*, proposal: Mapping[str,object], coverage_complete: bool, economics_verified: bool, risk_verified: bool) -> Result:
    blockers=tuple(code for ok,code in ((coverage_complete,"COVERAGE_INCOMPLETE"),(economics_verified,"ECONOMICS_UNVERIFIED"),(risk_verified,"RISK_UNVERIFIED")) if not ok)
    return result("review_strategy_evidence", {"proposal_hash":stable_hash("strategy-proposal",dict(proposal)),"review_passed":not blockers}, status="OK" if not blockers else "BLOCKED", blockers=blockers)


def approve_shadow_promotion(*, strategy_id: str, review_passed: bool, scope_hash: str, expiry: int, now: int) -> Result:
    if not review_passed:
        raise Mega808Error("REVIEW_REQUIRED")
    expiry=require_nonnegative(expiry,"expiry"); now=require_nonnegative(now,"now")
    if expiry<=now:
        raise Mega808Error("PROMOTION_EXPIRED")
    return result("approve_shadow_promotion", {"strategy_id":strategy_id,"scope_hash":scope_hash,"expiry":expiry,"stage":"SHADOW","live_enabled":False})


def revoke_strategy_promotion(*, strategy_id: str, reason: str, pending_plan_ids: Sequence[str]) -> Result:
    if not strategy_id or not reason:
        raise Mega808Error("REVOCATION_REASON_REQUIRED")
    return result("revoke_strategy_promotion", {"strategy_id":strategy_id,"reason":reason,"pending_plan_ids":tuple(pending_plan_ids),"admission_allowed":False,"live_enabled":False})
