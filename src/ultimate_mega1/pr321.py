"""PR-321 / NF-986..990: cross-venue transfer rail capability graph."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, stable_hash


def normalize_transfer_rail_identity(
    *,
    venue: str,
    network_code: str,
    canonical_chain_id: str,
    asset_contract: str,
    native: bool,
) -> ContractResult:
    if not venue or not network_code or not canonical_chain_id or not asset_contract:
        raise UltimateMegaError("NETWORK_ALIAS_AMBIGUOUS")
    return record(
        "normalize_transfer_rail_identity",
        {"venue": venue, "network_code": network_code, "chain_id": canonical_chain_id, "asset_contract": asset_contract, "native": native, "rail_id": stable_hash("transfer-rail-id", (venue, canonical_chain_id, asset_contract, native))},
    )


def record_transfer_rail_capability(
    *,
    rail_id: str,
    deposit_enabled: bool | None,
    withdrawal_enabled: bool | None,
    min_amount: int | None,
    fee: int | None,
    memo_required: bool | None,
    observed_at: int,
    valid_until: int,
) -> ContractResult:
    observed = require_nonnegative(observed_at, "observed_at")
    valid = require_nonnegative(valid_until, "valid_until")
    if valid <= observed:
        raise UltimateMegaError("STATUS_STALE")
    unknown = any(v is None for v in (deposit_enabled, withdrawal_enabled, min_amount, fee, memo_required))
    payload = {
        "rail_id": rail_id,
        "deposit_enabled": deposit_enabled,
        "withdrawal_enabled": withdrawal_enabled,
        "min_amount": None if min_amount is None else require_nonnegative(min_amount, "min_amount"),
        "fee": None if fee is None else require_nonnegative(fee, "fee"),
        "memo_required": memo_required,
        "observed_at": observed,
        "valid_until": valid,
    }
    return record(
        "record_transfer_rail_capability",
        payload,
        status="INCOMPLETE" if unknown else "OK",
        blockers=("TERMS_MISSING",) if unknown else (),
    )


def estimate_transfer_latency_envelope(
    history_seconds: Sequence[int],
    *,
    published_min_seconds: int | None = None,
    published_max_seconds: int | None = None,
) -> ContractResult:
    samples = tuple(sorted(require_nonnegative(v, "history_seconds") for v in history_seconds))
    if samples:
        low, high = samples[0], samples[-1]
        source = "OWN_HISTORY"
    elif published_min_seconds is not None and published_max_seconds is not None:
        low = require_nonnegative(published_min_seconds, "published_min_seconds")
        high = require_nonnegative(published_max_seconds, "published_max_seconds")
        if high < low:
            raise UltimateMegaError("NO_OBSERVABLE_HISTORY")
        source = "PUBLISHED_CONSTRAINT"
    else:
        raise UltimateMegaError("NO_OBSERVABLE_HISTORY")
    return record("estimate_transfer_latency_envelope", {"min_seconds": low, "max_seconds": high, "source": source, "exact_latency_claim": False})


def validate_prefunded_crossvenue_plan(
    *,
    source_inventory: int,
    destination_inventory: int,
    source_required: int,
    destination_required: int,
    withdrawal_enabled: bool,
) -> ContractResult:
    if not withdrawal_enabled:
        raise UltimateMegaError("WITHDRAWAL_PAUSED")
    source = require_nonnegative(source_inventory, "source_inventory")
    dest = require_nonnegative(destination_inventory, "destination_inventory")
    src_req = require_nonnegative(source_required, "source_required")
    dst_req = require_nonnegative(destination_required, "destination_required")
    if source < src_req or dest < dst_req:
        raise UltimateMegaError("UNFUNDED_DESTINATION")
    return record(
        "validate_prefunded_crossvenue_plan",
        {"source_buffer": source - src_req, "destination_buffer": dest - dst_req, "pending_transfer_counts_as_inventory": False},
    )


def reconcile_transfer_identity_chain(
    *,
    debited_amount: int,
    fee: int,
    chain_tx_amount: int,
    custodial_credit: int | None,
    chain_final: bool,
) -> ContractResult:
    debit = require_nonnegative(debited_amount, "debited_amount")
    fee_value = require_nonnegative(fee, "fee")
    tx = require_nonnegative(chain_tx_amount, "chain_tx_amount")
    if custodial_credit is None:
        return record(
            "reconcile_transfer_identity_chain",
            {"debited": debit, "fee": fee_value, "chain_tx_amount": tx, "custodial_credit": None, "chain_final": chain_final},
            status="UNKNOWN",
            blockers=("CUSTODIAL_CREDIT_UNKNOWN",),
        )
    credit = require_nonnegative(custodial_credit, "custodial_credit")
    return record(
        "reconcile_transfer_identity_chain",
        {"debited": debit, "fee": fee_value, "chain_tx_amount": tx, "custodial_credit": credit, "chain_final": chain_final, "reconciled": debit - fee_value == tx and credit <= tx},
    )
