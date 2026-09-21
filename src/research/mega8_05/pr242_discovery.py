"""PR-242 / DISCOVERY-02: unknown deployment quarantine and evidence promotion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text


def discover_unknown_deployment(observation: Mapping[str, Any]) -> ResearchArtifact:
    payload = {
        "chain": nonempty_text(observation.get("chain"), "chain"),
        "deployment_id": nonempty_text(
            observation.get("deployment_id"), "deployment_id"
        ),
        "binary_identity": str(observation.get("binary_identity", "UNKNOWN")),
        "schema_identity": str(observation.get("schema_identity", "UNKNOWN")),
        "known": bool(observation.get("known", False)),
    }
    disposition = Disposition.PASS if not payload["known"] else Disposition.REJECT
    return artifact(
        "unknown-deployment",
        payload,
        disposition=disposition,
        reason="requires-quarantine" if not payload["known"] else "already-known",
    )


def quarantine_unknown_market(
    deployment: ResearchArtifact,
    market_id: str,
) -> ResearchArtifact:
    return artifact(
        "market-quarantine",
        {
            "deployment": deployment.identity,
            "market_id": nonempty_text(market_id, "market_id"),
            "strategy_admission": False,
            "execution_admission": False,
        },
        disposition=Disposition.BLOCKED,
        reason="unknown-market-quarantined",
    )


def collect_promotion_evidence(
    *,
    binary_verified: bool,
    schema_verified: bool,
    owner_verified: bool,
    upgrade_authority_verified: bool,
    liquidity_verified: bool,
    liquid_exit_verified: bool,
) -> ResearchArtifact:
    checks = {
        "binary_verified": bool(binary_verified),
        "schema_verified": bool(schema_verified),
        "owner_verified": bool(owner_verified),
        "upgrade_authority_verified": bool(upgrade_authority_verified),
        "liquidity_verified": bool(liquidity_verified),
        "liquid_exit_verified": bool(liquid_exit_verified),
    }
    passed = all(checks.values())
    return artifact(
        "promotion-evidence",
        checks,
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason=(
            "promotion-evidence-complete" if passed else "promotion-evidence-missing"
        ),
    )


def promote_discovered_capability(
    quarantine: ResearchArtifact,
    evidence: ResearchArtifact,
    *,
    authority_receipt: str | None,
) -> ResearchArtifact:
    authority = (authority_receipt or "").strip()
    passed = (
        quarantine.kind == "market-quarantine"
        and evidence.disposition is Disposition.PASS
        and bool(authority)
    )
    return artifact(
        "capability-promotion-candidate",
        {
            "quarantine": quarantine.identity,
            "evidence": evidence.identity,
            "authority_receipt": authority or "MISSING",
            "promotion_applied_by_this_module": False,
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason=(
            "ready-for-existing-authority" if passed else "promotion-authority-missing"
        ),
    )


__all__ = [
    "collect_promotion_evidence",
    "discover_unknown_deployment",
    "promote_discovered_capability",
    "quarantine_unknown_market",
]
