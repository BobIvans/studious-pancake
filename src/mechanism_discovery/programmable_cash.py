"""PR-355 programmable cash and synthetic-dollar research specialization."""

from __future__ import annotations

from typing import Any, Mapping

from .evidence_native_core import EvidenceNativeError, record, require_int, require_ppm, require_text


def register_programmable_cash_asset(payload: Mapping[str, Any]):
    return record(
        "register_programmable_cash_asset",
        {
            "asset_id": require_text(payload.get("asset_id"), "asset_id"),
            "base_money_id": require_text(payload.get("base_money_id"), "base_money_id"),
            "wrapper_or_extension": require_text(payload.get("wrapper_or_extension"), "wrapper_or_extension"),
            "index_id": require_text(payload.get("index_id"), "index_id"),
            "issuer": require_text(payload.get("issuer"), "issuer"),
            "rights_id": require_text(payload.get("rights_id"), "rights_id"),
        },
    )


def model_earning_and_claim_modes(payload: Mapping[str, Any]):
    mode = require_text(payload.get("mode"), "mode").upper()
    if mode not in {"REBASING", "NON_REBASING", "EXPLICIT_CLAIM", "NON_EARNING"}:
        raise EvidenceNativeError("EARNING_MODE_UNKNOWN")
    principal = require_int(payload.get("principal_atoms"), "principal_atoms", minimum=0)
    index_ppm = require_ppm(payload.get("index_ppm", 1_000_000), "index_ppm")
    claim_atoms = principal * max(0, index_ppm - 1_000_000) // 1_000_000
    return record(
        "model_earning_and_claim_modes",
        {"mode": mode, "principal_atoms": principal, "index_ppm": index_ppm, "claim_atoms": claim_atoms},
    )


def read_mint_redeem_capacity(payload: Mapping[str, Any]):
    if payload.get("permissions_known") is not True:
        raise EvidenceNativeError("MINT_REDEEM_PERMISSIONS_UNKNOWN")
    mint = require_int(payload.get("mint_capacity_atoms"), "mint_capacity_atoms", minimum=0)
    redeem = require_int(payload.get("redeem_capacity_atoms"), "redeem_capacity_atoms", minimum=0)
    swap = require_int(payload.get("swap_facility_capacity_atoms", 0), "swap_facility_capacity_atoms", minimum=0)
    return record(
        "read_mint_redeem_capacity",
        {"mint_capacity_atoms": mint, "redeem_capacity_atoms": redeem, "swap_facility_capacity_atoms": swap},
    )


def detect_extension_parity_residual(payload: Mapping[str, Any]):
    secondary = require_int(payload.get("secondary_value_atoms"), "secondary_value_atoms")
    redeem = require_int(payload.get("redeem_value_atoms"), "redeem_value_atoms")
    costs = require_int(payload.get("conversion_cost_atoms", 0), "conversion_cost_atoms", minimum=0)
    capacity = require_int(payload.get("capacity_atoms"), "capacity_atoms", minimum=0)
    return record(
        "detect_extension_parity_residual",
        {
            "residual_atoms": redeem - secondary - costs,
            "capacity_atoms": capacity,
            "realizable": capacity > 0 and redeem - secondary - costs > 0,
        },
    )


def decompose_synthetic_dollar_backing(payload: Mapping[str, Any]):
    backing = require_int(payload.get("backing_atoms"), "backing_atoms", minimum=0)
    hedge = require_int(payload.get("hedge_value_atoms"), "hedge_value_atoms")
    reserves = require_int(payload.get("stable_reserve_atoms"), "stable_reserve_atoms", minimum=0)
    liabilities = require_int(payload.get("liability_atoms"), "liability_atoms", minimum=1)
    coverage_ppm = (backing + hedge + reserves) * 1_000_000 // liabilities
    return record(
        "decompose_synthetic_dollar_backing",
        {
            "backing_atoms": backing,
            "hedge_value_atoms": hedge,
            "stable_reserve_atoms": reserves,
            "liability_atoms": liabilities,
            "coverage_ppm": coverage_ppm,
            "custody_identity": require_text(payload.get("custody_identity"), "custody_identity"),
        },
    )


def qualify_redemption_eligibility(payload: Mapping[str, Any]):
    holder = bool(payload.get("holder_eligible", False))
    minter = bool(payload.get("mint_user_eligible", False))
    jurisdiction = bool(payload.get("jurisdiction_eligible", False))
    direct = bool(payload.get("direct_redemption_available", False))
    eligible = holder and minter and jurisdiction and direct
    return record(
        "qualify_redemption_eligibility",
        {
            "holder_eligible": holder,
            "mint_user_eligible": minter,
            "jurisdiction_eligible": jurisdiction,
            "direct_redemption_available": direct,
            "eligible": eligible,
        },
    )
