"""PR-186 / KEEPER-01 — permission-aware offline keeper qualification."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import (
    EvidenceEnvelope,
    OfflineDecision,
    decision,
    integer,
    require_rows,
    stable_hash,
)


def discover_rebalance_jobs(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: EvidenceEnvelope,
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "jobs")
    if envelope.blockers:
        return ()
    accepted: list[dict[str, Any]] = []
    for row in rows:
        if (
            row.get("authorized") is not True
            or row.get("deployment_verified") is not True
        ):
            continue
        job_id = str(row.get("job_id", "")).strip()
        permission_ref = str(row.get("permission_ref", "")).strip()
        if not job_id or not permission_ref:
            continue
        capacity = integer(row.get("capacity_atomic", 0), "capacity_atomic", minimum=0)
        if capacity <= 0:
            continue
        accepted.append(
            {
                "job_id": job_id,
                "permission_ref": permission_ref,
                "authorization_verified": True,
                "authorization_evidence_sha256": envelope.evidence_sha256,
                "state_generation": envelope.state_generation,
                "deployment_generation": envelope.deployment_generation,
                "capacity_atomic": capacity,
                "reward_atomic": integer(
                    row.get("reward_atomic", 0), "reward_atomic", minimum=0
                ),
            }
        )
    return tuple(sorted(accepted, key=lambda item: item["job_id"]))


def price_keeper_reward_and_cost(
    *,
    reward_atomic: int,
    network_fee_atomic: int,
    tip_atomic: int,
    state_change_cost_atomic: int,
) -> dict[str, int]:
    reward = integer(reward_atomic, "reward_atomic", minimum=0)
    costs = sum(
        integer(value, field, minimum=0)
        for value, field in (
            (network_fee_atomic, "network_fee_atomic"),
            (tip_atomic, "tip_atomic"),
            (state_change_cost_atomic, "state_change_cost_atomic"),
        )
    )
    return {
        "reward_atomic": reward,
        "total_cost_atomic": costs,
        "conservative_net_atomic": reward - costs,
    }


def build_authorized_keeper_plan(
    job: Mapping[str, Any],
    economics: Mapping[str, int],
    *,
    envelope: EvidenceEnvelope,
) -> dict[str, Any]:
    if envelope.blockers:
        raise ValueError("keeper plan requires verified evidence")
    if not str(job.get("job_id", "")).strip():
        raise ValueError("keeper plan requires job identity")
    if not job.get("permission_ref"):
        raise ValueError("keeper plan requires explicit permission")
    if job.get("authorization_verified") is not True:
        raise ValueError("keeper plan requires verified authorization")
    if job.get("authorization_evidence_sha256") != envelope.evidence_sha256:
        raise ValueError("keeper authorization evidence mismatch")
    if job.get("state_generation") != envelope.state_generation:
        raise ValueError("keeper state generation mismatch")
    if job.get("deployment_generation") != envelope.deployment_generation:
        raise ValueError("keeper deployment generation mismatch")
    payload = {
        "job_id": str(job["job_id"]),
        "permission_ref": str(job["permission_ref"]),
        "authorization_verified": True,
        "authorization_evidence_sha256": envelope.evidence_sha256,
        "capacity_atomic": integer(
            job["capacity_atomic"], "capacity_atomic", minimum=1
        ),
        "economics": dict(economics),
        "state_generation": envelope.state_generation,
        "deployment_generation": envelope.deployment_generation,
        "execution_authority": False,
    }
    return payload | {"plan_sha256": stable_hash("mega8-03/keeper-plan/v1", payload)}


def qualify_keeper_operation(
    plan: Mapping[str, Any],
    *,
    envelope: EvidenceEnvelope,
    minimum_net_atomic: int = 0,
) -> OfflineDecision:
    net = integer(
        plan.get("economics", {}).get("conservative_net_atomic"),
        "conservative_net_atomic",
    )
    threshold = integer(minimum_net_atomic, "minimum_net_atomic")
    reasons: list[str] = []
    if not str(plan.get("job_id", "")).strip():
        reasons.append("KEEPER_JOB_ID_MISSING")
    if not plan.get("permission_ref"):
        reasons.append("KEEPER_PERMISSION_MISSING")
    if plan.get("authorization_verified") is not True:
        reasons.append("KEEPER_AUTHORIZATION_NOT_VERIFIED")
    if plan.get("authorization_evidence_sha256") != envelope.evidence_sha256:
        reasons.append("KEEPER_AUTHORIZATION_EVIDENCE_MISMATCH")
    if plan.get("state_generation") != envelope.state_generation:
        reasons.append("KEEPER_STATE_GENERATION_MISMATCH")
    if plan.get("deployment_generation") != envelope.deployment_generation:
        reasons.append("KEEPER_DEPLOYMENT_GENERATION_MISMATCH")
    if plan.get("execution_authority") is not False:
        reasons.append("KEEPER_EXECUTION_AUTHORITY_FORBIDDEN")

    claimed_plan_sha256 = str(plan.get("plan_sha256", ""))
    plan_body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if claimed_plan_sha256 != stable_hash("mega8-03/keeper-plan/v1", plan_body):
        reasons.append("KEEPER_PLAN_INTEGRITY_MISMATCH")
    if net <= threshold:
        reasons.append("KEEPER_NET_BELOW_THRESHOLD")
    return decision("PR-186", envelope=envelope, payload=dict(plan), reasons=reasons)


__all__ = [
    "build_authorized_keeper_plan",
    "discover_rebalance_jobs",
    "price_keeper_reward_and_cost",
    "qualify_keeper_operation",
]
