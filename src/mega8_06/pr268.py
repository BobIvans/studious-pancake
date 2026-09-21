"""PR-268 / ORDERFLOW-02: opt-in user-protective backrun policy."""

from __future__ import annotations
from typing import Mapping
from .core import Mega806Error, require_nonnegative_int, require_text, stable_hash


def register_opt_in_orderflow_policy(
    *,
    intent_id: str,
    user_id: str,
    expires_at: int,
    min_user_output: int,
    consent_revision: str,
) -> dict[str, object]:
    return {
        "intent_id": require_text(intent_id, "intent_id"),
        "user_id": require_text(user_id, "user_id"),
        "expires_at": require_nonnegative_int(expires_at, "expires_at"),
        "min_user_output": require_nonnegative_int(min_user_output, "min_user_output"),
        "consent_revision": require_text(consent_revision, "consent_revision"),
        "harmful_frontrun_allowed": False,
    }


def compute_user_surplus_floor(
    quoted_output: int, *, min_user_output: int, protected_surplus: int = 0
) -> int:
    quoted_output = require_nonnegative_int(quoted_output, "quoted_output")
    min_user_output = require_nonnegative_int(min_user_output, "min_user_output")
    protected_surplus = require_nonnegative_int(protected_surplus, "protected_surplus")
    return max(min_user_output, quoted_output + protected_surplus)


def verify_orderflow_consent(
    policy: Mapping[str, object],
    *,
    now: int,
    consent_revision: str,
    revoked: bool = False,
) -> bool:
    now = require_nonnegative_int(now, "now")
    if revoked:
        raise Mega806Error("CONSENT_REVOKED")
    if now >= require_nonnegative_int(policy.get("expires_at"), "expires_at"):
        raise Mega806Error("CONSENT_EXPIRED")
    if require_text(policy.get("consent_revision"), "consent_revision") != require_text(
        consent_revision, "consent_revision"
    ):
        raise Mega806Error("CONSENT_REVISION_MISMATCH")
    return True


def build_protective_backrun_plan(
    policy: Mapping[str, object],
    *,
    user_output: int,
    candidate_profit: int,
) -> dict[str, object]:
    floor = require_nonnegative_int(policy.get("min_user_output"), "min_user_output")
    user_output = require_nonnegative_int(user_output, "user_output")
    candidate_profit = require_nonnegative_int(candidate_profit, "candidate_profit")
    if user_output < floor:
        raise Mega806Error("USER_SURPLUS_FLOOR_VIOLATED")
    payload = {
        "intent_id": require_text(policy.get("intent_id"), "intent_id"),
        "user_output": user_output,
        "candidate_profit": candidate_profit,
        "pre_user_execution": False,
        "submission_authority": False,
    }
    return {**payload, "plan_sha256": stable_hash(payload)}
