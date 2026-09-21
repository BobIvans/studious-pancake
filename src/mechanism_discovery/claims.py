"""PR-355 Financial Claims / Cashflow IR specialization."""

from __future__ import annotations

from typing import Any, Mapping

from .evidence_native_core import (
    CashflowSpec,
    ClaimRightSpec,
    EvidenceNativeError,
    record,
    require_int,
    require_ppm,
    require_text,
)


def define_cashflow_stream(payload: Mapping[str, Any]) -> CashflowSpec:
    return CashflowSpec(
        cashflow_id=require_text(payload.get("cashflow_id"), "cashflow_id"),
        instrument_id=require_text(payload.get("instrument_id"), "instrument_id"),
        payer_role=require_text(payload.get("payer_role"), "payer_role"),
        receiver_role=require_text(payload.get("receiver_role"), "receiver_role"),
        payment_asset=require_text(payload.get("payment_asset"), "payment_asset"),
        payment_unit=require_text(payload.get("payment_unit"), "payment_unit"),
        fixed_or_floating=require_text(payload.get("fixed_or_floating"), "fixed_or_floating"),
        index_id=require_text(payload.get("index_id"), "index_id"),
        observation_schedule=tuple(payload.get("observation_schedule", ())),
        settlement_schedule=tuple(payload.get("settlement_schedule", ())),
        maturity=require_int(payload.get("maturity"), "maturity", minimum=0),
        margin_atoms=require_int(payload.get("margin_atoms", 0), "margin_atoms", minimum=0),
        collateral_asset=require_text(payload.get("collateral_asset"), "collateral_asset"),
        eligibility=tuple(str(x) for x in payload.get("eligibility", ())),
        transferable=bool(payload.get("transferable", False)),
        event_time=require_int(payload.get("event_time"), "event_time", minimum=0),
        published_at=require_int(payload.get("published_at"), "published_at", minimum=0),
        received_at=require_int(payload.get("received_at"), "received_at", minimum=0),
        available_at=require_int(payload.get("available_at"), "available_at", minimum=0),
        revision=require_int(payload.get("revision", 0), "revision", minimum=0),
        provenance=require_text(payload.get("provenance"), "provenance"),
    )


def define_claim_right(payload: Mapping[str, Any]) -> ClaimRightSpec:
    return ClaimRightSpec(
        right_id=require_text(payload.get("right_id"), "right_id"),
        holder_role=require_text(payload.get("holder_role"), "holder_role"),
        beneficiary_role=require_text(payload.get("beneficiary_role"), "beneficiary_role"),
        issuer=require_text(payload.get("issuer"), "issuer"),
        counterparty=require_text(payload.get("counterparty"), "counterparty"),
        underlying_claim=require_text(payload.get("underlying_claim"), "underlying_claim"),
        redemption_rule=require_text(payload.get("redemption_rule"), "redemption_rule"),
        transferable=bool(payload.get("transferable", False)),
        expiry=require_int(payload.get("expiry"), "expiry", minimum=0),
        maturity=require_int(payload.get("maturity"), "maturity", minimum=0),
        settlement_asset=require_text(payload.get("settlement_asset"), "settlement_asset"),
        jurisdiction=require_text(payload.get("jurisdiction"), "jurisdiction"),
        allowlist_required=bool(payload.get("allowlist_required", False)),
        custody_required=bool(payload.get("custody_required", False)),
        capacity_atoms=require_int(payload.get("capacity_atoms", 0), "capacity_atoms", minimum=0),
        version=require_text(payload.get("version"), "version"),
    )


def normalize_rate_instrument(payload: Mapping[str, Any]):
    convention = require_text(payload.get("convention"), "convention").upper()
    if convention not in {"FIXED", "FLOATING", "FUNDING", "APR"}:
        raise EvidenceNativeError("RATE_CONVENTION_UNSUPPORTED")
    rate_ppm = require_ppm(payload.get("rate_ppm"), "rate_ppm")
    periods = require_int(payload.get("periods_per_year", 1), "periods_per_year", minimum=1)
    return record(
        "normalize_rate_instrument",
        {
            "convention": convention,
            "rate_ppm": rate_ppm,
            "periods_per_year": periods,
            "annualized_simple_ppm": rate_ppm * periods,
            "index_id": require_text(payload.get("index_id"), "index_id"),
            "settlement_asset": require_text(payload.get("settlement_asset"), "settlement_asset"),
        },
    )


def compile_fixed_floating_payoff(payload: Mapping[str, Any]):
    notional = require_int(payload.get("notional_atoms"), "notional_atoms", minimum=0)
    fixed_ppm = require_ppm(payload.get("fixed_rate_ppm"), "fixed_rate_ppm")
    floating_ppm = require_ppm(payload.get("floating_rate_ppm"), "floating_rate_ppm")
    day_num = require_int(payload.get("day_count_num", 1), "day_count_num", minimum=0)
    day_den = require_int(payload.get("day_count_den", 1), "day_count_den", minimum=1)
    delta_num = notional * (floating_ppm - fixed_ppm) * day_num
    payoff_atoms = delta_num // (1_000_000 * day_den)
    return record(
        "compile_fixed_floating_payoff",
        {
            "notional_atoms": notional,
            "fixed_rate_ppm": fixed_ppm,
            "floating_rate_ppm": floating_ppm,
            "day_count_num": day_num,
            "day_count_den": day_den,
            "payoff_atoms": payoff_atoms,
            "rounding": "FLOOR_TOWARD_NEGATIVE_INFINITY",
        },
    )


def price_cashflow_after_costs(payload: Mapping[str, Any]):
    gross_low = require_int(payload.get("gross_low_atoms"), "gross_low_atoms")
    gross_high = require_int(payload.get("gross_high_atoms"), "gross_high_atoms")
    if gross_high < gross_low:
        raise EvidenceNativeError("GROSS_BAND_INVERTED")
    costs = sum(
        require_int(payload.get(name, 0), name, minimum=0)
        for name in ("fees_atoms", "margin_cost_atoms", "borrow_cost_atoms", "uncertainty_atoms")
    )
    return record(
        "price_cashflow_after_costs",
        {
            "gross_low_atoms": gross_low,
            "gross_high_atoms": gross_high,
            "total_cost_atoms": costs,
            "net_low_atoms": gross_low - costs,
            "net_high_atoms": gross_high - costs,
        },
    )


def qualify_cashflow_identity(payload: Mapping[str, Any]):
    fields = ("maturity", "settlement_asset", "index_id", "collateral_asset", "eligibility_id")
    mismatches = tuple(
        field
        for field in fields
        if payload.get(f"left_{field}") != payload.get(f"right_{field}")
    )
    return record(
        "qualify_cashflow_identity",
        {
            "compatible": not mismatches,
            "mismatches": mismatches,
            "execution_right": False,
        },
    )
