"""PR-355 RWA eligibility, custody and NAV lifecycle specialization."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_native_core import AccessAndCustodySpec, EvidenceNativeError, record, require_int, require_text


def register_rwa_instrument_rights(payload: Mapping[str, Any]):
    return record(
        "register_rwa_instrument_rights",
        {
            "instrument_id": require_text(payload.get("instrument_id"), "instrument_id"),
            "issuer": require_text(payload.get("issuer"), "issuer"),
            "fund": require_text(payload.get("fund"), "fund"),
            "underlying": require_text(payload.get("underlying"), "underlying"),
            "settlement_asset": require_text(payload.get("settlement_asset"), "settlement_asset"),
            "transfer_rule": require_text(payload.get("transfer_rule"), "transfer_rule"),
            "eligibility_rule": require_text(payload.get("eligibility_rule"), "eligibility_rule"),
        },
    )


def ingest_nav_revision_history(rows: Sequence[Mapping[str, Any]]):
    normalized = []
    previous_available = -1
    previous_revision = -1
    for row in rows:
        event_time = require_int(row.get("event_time"), "event_time", minimum=0)
        published_at = require_int(row.get("published_at"), "published_at", minimum=0)
        available_at = require_int(row.get("available_at"), "available_at", minimum=0)
        revision = require_int(row.get("revision"), "revision", minimum=0)
        if not event_time <= published_at <= available_at:
            raise EvidenceNativeError("NAV_CLOCK_ORDER_INVALID")
        if available_at < previous_available or revision <= previous_revision:
            raise EvidenceNativeError("NAV_REVISION_NOT_MONOTONIC")
        normalized.append(
            {
                "event_time": event_time,
                "published_at": published_at,
                "available_at": available_at,
                "revision": revision,
                "nav_atoms": require_int(row.get("nav_atoms"), "nav_atoms", minimum=0),
            }
        )
        previous_available = available_at
        previous_revision = revision
    return record("ingest_nav_revision_history", {"rows": tuple(normalized), "revision_count": len(normalized)})


def model_rwa_subscription_redemption(payload: Mapping[str, Any]):
    subscription = require_int(payload.get("subscription_capacity_atoms"), "subscription_capacity_atoms", minimum=0)
    redemption = require_int(payload.get("redemption_capacity_atoms"), "redemption_capacity_atoms", minimum=0)
    requested = require_int(payload.get("requested_atoms"), "requested_atoms", minimum=0)
    async_mode = bool(payload.get("asynchronous", False))
    return record(
        "model_rwa_subscription_redemption",
        {
            "asynchronous": async_mode,
            "subscription_capacity_atoms": subscription,
            "redemption_capacity_atoms": redemption,
            "admissible_atoms": min(requested, redemption),
            "immediate_cashflow": not async_mode,
        },
    )


def model_custody_receipt_state(payload: Mapping[str, Any]) -> AccessAndCustodySpec:
    return AccessAndCustodySpec(
        access_id=require_text(payload.get("access_id"), "access_id"),
        issuer=require_text(payload.get("issuer"), "issuer"),
        fund=require_text(payload.get("fund"), "fund"),
        custodian=require_text(payload.get("custodian"), "custodian"),
        rights=tuple(str(x) for x in payload.get("rights", ())),
        jurisdictions=tuple(str(x) for x in payload.get("jurisdictions", ())),
        allowlist_required=bool(payload.get("allowlist_required", False)),
        transfer_restricted=bool(payload.get("transfer_restricted", False)),
        nav_atoms=require_int(payload.get("nav_atoms"), "nav_atoms", minimum=0),
        nav_published_at=require_int(payload.get("nav_published_at"), "nav_published_at", minimum=0),
        nav_available_at=require_int(payload.get("nav_available_at"), "nav_available_at", minimum=0),
        nav_revision=require_int(payload.get("nav_revision", 0), "nav_revision", minimum=0),
        subscription_open=require_int(payload.get("subscription_open"), "subscription_open", minimum=0),
        redemption_open=require_int(payload.get("redemption_open"), "redemption_open", minimum=0),
        redemption_capacity_atoms=require_int(payload.get("redemption_capacity_atoms"), "redemption_capacity_atoms", minimum=0),
        custody_receipt_state=require_text(payload.get("custody_receipt_state"), "custody_receipt_state"),
        synchronized=bool(payload.get("synchronized", False)),
    )


def detect_rwa_nav_basis(payload: Mapping[str, Any]):
    nav = require_int(payload.get("nav_atoms"), "nav_atoms", minimum=0)
    secondary = require_int(payload.get("secondary_value_atoms"), "secondary_value_atoms")
    lending = require_int(payload.get("lending_value_atoms"), "lending_value_atoms")
    session_open = bool(payload.get("session_open", False))
    redeemable = bool(payload.get("redeemable", False))
    return record(
        "detect_rwa_nav_basis",
        {
            "secondary_basis_atoms": secondary - nav,
            "lending_basis_atoms": lending - nav,
            "session_open": session_open,
            "redeemable": redeemable,
            "realizable_now": session_open and redeemable,
        },
    )


def qualify_rwa_access_path(payload: Mapping[str, Any]):
    unknown = tuple(
        field
        for field in ("jurisdiction_known", "allowlist_known", "session_known", "custody_known")
        if payload.get(field) is not True
    )
    if unknown:
        return record("qualify_rwa_access_path", {"qualified": False, "unknown_fields": unknown})
    eligible = all(
        bool(payload.get(field, False))
        for field in ("jurisdiction_allowed", "allowlisted", "session_open", "custody_synchronized")
    )
    return record("qualify_rwa_access_path", {"qualified": eligible, "unknown_fields": ()})
