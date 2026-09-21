"""PR-280 / WALLET-02: role-separated wallet generations."""

from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_id, stable_hash

_ALLOWED_ROLES = ("canary", "treasury", "research", "settlement")


def allocate_wallet_roles(
    wallet_ids: Sequence[str],
) -> dict[str, str]:
    if len(wallet_ids) != len(_ALLOWED_ROLES):
        raise Mega807Error("EXACTLY_FOUR_ROLE_WALLETS_REQUIRED")
    normalized = [require_id(value, "wallet_id") for value in wallet_ids]
    if len(set(normalized)) != len(normalized):
        raise Mega807Error("WALLET_ROLE_IDENTITY_REUSE")
    return dict(zip(_ALLOWED_ROLES, normalized, strict=True))


def isolate_canary_treasury(roles: Mapping[str, str]) -> bool:
    missing = set(_ALLOWED_ROLES) - set(roles)
    if missing:
        raise Mega807Error("WALLET_ROLE_MISSING")
    if roles["canary"] == roles["treasury"]:
        raise Mega807Error("CANARY_TREASURY_NOT_ISOLATED")
    return True


def rotate_wallet_generation(
    roles: Mapping[str, str],
    *,
    generation: int,
    pending_unknown_roles: Sequence[str] = (),
) -> dict[str, object]:
    isolate_canary_treasury(roles)
    if generation < 1:
        raise Mega807Error("INVALID_WALLET_GENERATION")
    pending = set(pending_unknown_roles)
    if pending & set(roles):
        raise Mega807Error("PENDING_UNKNOWN_BLOCKS_WALLET_ROTATION")
    return {
        "generation": generation + 1,
        "roles": dict(sorted(roles.items())),
        "rotation_sha256": stable_hash(
            "mega8-07-wallet-generation",
            {"generation": generation + 1, "roles": dict(sorted(roles.items()))},
        ),
    }


def audit_wallet_segregation(
    roles: Mapping[str, str], transfers: Sequence[tuple[str, str]]
) -> tuple[str, ...]:
    isolate_canary_treasury(roles)
    reverse = {wallet: role for role, wallet in roles.items()}
    violations: list[str] = []
    for source, destination in transfers:
        if source not in reverse or destination not in reverse:
            violations.append("UNKNOWN_WALLET")
        elif reverse[source] == "research" and reverse[destination] == "treasury":
            violations.append("RESEARCH_TO_TREASURY_REQUIRES_SEPARATE_ADMISSION")
    return tuple(sorted(violations))
