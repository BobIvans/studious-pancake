"""PR-254 / SCAM-01: dynamic asset-admission revocation research."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, probability


def monitor_authority_mutations(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> ResearchArtifact:
    keys = (
        "mint_authority",
        "freeze_authority",
        "upgrade_authority",
        "delegate",
        "token_program",
    )
    changes = {
        key: {"previous": previous.get(key), "current": current.get(key)}
        for key in keys
        if previous.get(key) != current.get(key)
    }
    return artifact(
        "authority-mutations",
        {"changes": changes, "old_evidence_expires": bool(changes)},
    )


def detect_liquidity_withdrawal_risk(
    *,
    previous_executable_liquidity: int | None,
    current_executable_liquidity: int | None,
    warning_fraction: float = 0.5,
) -> ResearchArtifact:
    if previous_executable_liquidity is None or current_executable_liquidity is None:
        return artifact(
            "liquidity-withdrawal-risk",
            {"risk": "unknown", "data_gap": True},
            disposition=Disposition.UNKNOWN,
            reason="liquidity-data-gap",
        )
    if previous_executable_liquidity < 0 or current_executable_liquidity < 0:
        raise ValueError("liquidity cannot be negative")
    if previous_executable_liquidity == 0:
        fraction = 0.0
    else:
        fraction = 1.0 - (current_executable_liquidity / previous_executable_liquidity)
    risky = fraction >= probability(warning_fraction, "warning_fraction")
    return artifact(
        "liquidity-withdrawal-risk",
        {"withdrawal_fraction": fraction, "risk": "high" if risky else "normal"},
    )


def score_honeypot_or_rug_behavior(
    *,
    buy_success_rate: float | None,
    exit_success_rate: float | None,
    authority_mutation: bool,
) -> ResearchArtifact:
    if buy_success_rate is None or exit_success_rate is None:
        return artifact(
            "asset-behavior-risk",
            {"score": None, "data_gap": True, "rug_label": False},
            disposition=Disposition.UNKNOWN,
            reason="behavior-data-gap",
        )
    buy_rate = probability(buy_success_rate, "buy_success_rate")
    exit_rate = probability(exit_success_rate, "exit_success_rate")
    asymmetry = max(0.0, buy_rate - exit_rate)
    score = min(1.0, asymmetry * 0.8 + (0.2 if authority_mutation else 0.0))
    return artifact(
        "asset-behavior-risk",
        {
            "score": score,
            "exit_asymmetry": asymmetry,
            "authority_mutation": bool(authority_mutation),
            "rug_label": score >= 0.8,
        },
    )


def enforce_dynamic_asset_quarantine(
    authority: ResearchArtifact,
    liquidity: ResearchArtifact,
    behavior: ResearchArtifact,
    *,
    unknown_extension: bool,
) -> ResearchArtifact:
    high_risk = (
        bool(authority.payload.get("changes"))
        or liquidity.disposition is Disposition.UNKNOWN
        or liquidity.payload.get("risk") == "high"
        or behavior.disposition is Disposition.UNKNOWN
        or float(behavior.payload.get("score") or 0.0) >= 0.8
        or bool(unknown_extension)
    )
    return artifact(
        "dynamic-asset-quarantine",
        {
            "authority": authority.identity,
            "liquidity": liquidity.identity,
            "behavior": behavior.identity,
            "unknown_extension": bool(unknown_extension),
            "admitted": not high_risk,
            "live_promotion": False,
        },
        disposition=Disposition.BLOCKED if high_risk else Disposition.PASS,
        reason="quarantined-fail-closed" if high_risk else "research-admission-ok",
    )


__all__ = [
    "detect_liquidity_withdrawal_risk",
    "enforce_dynamic_asset_quarantine",
    "monitor_authority_mutations",
    "score_honeypot_or_rug_behavior",
]
