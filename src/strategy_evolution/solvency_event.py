"""EVO-05 insolvency, insurance, ADL, recapitalization and claims."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def normalize_solvency_state(payload: Mapping[str, Any]):
    if payload.get("version_verified") is False:
        raise EvolutionError("VERSION_UNKNOWN")
    if payload.get("accounting_gap"):
        raise EvolutionError("ACCOUNTING_GAP")
    if payload.get("oracle_disputed"):
        raise EvolutionError("ORACLE_DISPUTED")
    assets = int(payload.get("assets_atoms", 0))
    liabilities = int(payload.get("liabilities_atoms", 0))
    insurance = int(payload.get("insurance_atoms", 0))
    return result(
        "normalize_solvency_state",
        {**dict(payload), "deficit_atoms": max(0, liabilities - assets - insurance)},
    )


def estimate_insurance_fund_runway(payload: Mapping[str, Any]):
    if payload.get("inflow_verified") is False:
        raise EvolutionError("INFLOW_UNVERIFIED")
    if payload.get("liability_unknown"):
        raise EvolutionError("LIABILITY_UNKNOWN")
    losses = tuple(int(value) for value in payload.get("loss_scenarios_atoms", ()))
    if not losses:
        raise EvolutionError("DEFICIT_UNBOUNDED")
    insurance = int(payload.get("insurance_atoms", 0))
    remaining = tuple(max(0, insurance - loss) for loss in losses)
    return result(
        "estimate_insurance_fund_runway",
        {
            **dict(payload),
            "remaining_low_atoms": min(remaining),
            "remaining_high_atoms": max(remaining),
        },
    )


def model_auto_deleveraging_priority(payload: Mapping[str, Any]):
    if not payload.get("rules_verified"):
        raise EvolutionError("RULES_UNKNOWN")
    if payload.get("account_state_stale"):
        raise EvolutionError("ACCOUNT_STATE_STALE")
    exposures = dict(payload.get("exposure_scores", {}))
    ranking = tuple(
        sorted(
            ((str(account), int(score)) for account, score in exposures.items()),
            key=lambda row: (-row[1], row[0]),
        )
    )
    reported = payload.get("reported_priority")
    if reported is not None and tuple(tuple(row) for row in reported) != ranking:
        raise EvolutionError("RANK_MISMATCH")
    return result(
        "model_auto_deleveraging_priority",
        {**dict(payload), "priority": ranking},
    )


def detect_bad_debt_recapitalization_event(payload: Mapping[str, Any]):
    if int(payload.get("deficit_atoms", 0)) <= 0:
        raise EvolutionError("DEFICIT_UNCONFIRMED")
    if payload.get("event_reorged"):
        raise EvolutionError("EVENT_REORGED")
    if not payload.get("remedy_active"):
        raise EvolutionError("REMEDY_NOT_ACTIVE")
    return result("detect_bad_debt_recapitalization_event", payload)


def price_backstop_auction(payload: Mapping[str, Any]):
    if not payload.get("auction_rules_verified"):
        raise EvolutionError("AUCTION_RULE_UNKNOWN")
    if not payload.get("hedge_present"):
        raise EvolutionError("HEDGE_MISSING")
    if payload.get("settlement_risk_unbounded"):
        raise EvolutionError("SETTLEMENT_RISK")
    return contract(
        "price_backstop_auction",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def price_cover_claim_right(payload: Mapping[str, Any]):
    if not payload.get("transferable"):
        raise EvolutionError("COVER_NOT_TRANSFERABLE")
    if not payload.get("incident_verified"):
        raise EvolutionError("INCIDENT_UNVERIFIED")
    if not payload.get("terms_verified"):
        raise EvolutionError("TERMS_AMBIGUOUS")
    return contract(
        "price_cover_claim_right",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def build_solvency_event_candidate(payload: Mapping[str, Any]):
    if int(payload.get("value_low_atoms", 0)) <= int(payload.get("cost_high_atoms", 0)):
        raise EvolutionError("NEGATIVE_EDGE")
    if payload.get("waterfall_ambiguous"):
        raise EvolutionError("WATERFALL_AMBIGUOUS")
    if payload.get("seniority_mismatch"):
        raise EvolutionError("SENIORITY_MISMATCH")
    return build_candidate(
        "EVO-05", str(payload.get("candidate_type", "SOLVENCY_EVENT")), payload
    )


def qualify_solvency_event(
    candidate,
    *,
    replay_count: int,
    policy_passed: bool,
    tail_risk_bounded: bool,
    waterfall_replay_passed: bool = True,
):
    if not waterfall_replay_passed:
        raise EvolutionError("WATERFALL_REPLAY_FAIL")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
        tail_risk_bounded=tail_risk_bounded,
    )
