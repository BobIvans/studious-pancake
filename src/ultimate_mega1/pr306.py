"""PR-306 / NF-911..915: raw token units, UI scale and epoch fee semantics."""

from __future__ import annotations

from typing import Mapping

from .core import ContractResult, UltimateMegaError, ppm_fee_ceil, record, require_int, require_nonnegative, require_positive


def capture_token_amount_basis(
    *,
    mint: str,
    raw_supply: int,
    decimals: int,
    display_multiplier_num: int = 1,
    display_multiplier_den: int = 1,
    current_epoch: int,
    extensions: tuple[str, ...] = (),
) -> ContractResult:
    raw_supply = require_nonnegative(raw_supply, "raw_supply")
    decimals = require_nonnegative(decimals, "decimals")
    if decimals > 30:
        raise UltimateMegaError("DECIMALS_OUT_OF_RANGE")
    num = require_positive(display_multiplier_num, "display_multiplier_num")
    den = require_positive(display_multiplier_den, "display_multiplier_den")
    epoch = require_nonnegative(current_epoch, "current_epoch")
    unknown = tuple(sorted(x for x in extensions if x.startswith("unknown:")))
    return record(
        "capture_token_amount_basis",
        {
            "mint": mint,
            "raw_supply": raw_supply,
            "decimals": decimals,
            "display_multiplier": (num, den),
            "current_epoch": epoch,
            "extensions": tuple(sorted(extensions)),
            "unknown_extensions": unknown,
        },
        status="INCOMPLETE" if unknown else "OK",
        blockers=("UNKNOWN_EXTENSION_COMBINATION",) if unknown else (),
    )


def normalize_quote_amount_basis(
    amount: int,
    *,
    basis: str,
    multiplier_num: int = 1,
    multiplier_den: int = 1,
) -> ContractResult:
    amount = require_nonnegative(amount, "amount")
    num = require_positive(multiplier_num, "multiplier_num")
    den = require_positive(multiplier_den, "multiplier_den")
    if basis == "raw":
        raw = amount
    elif basis == "display_scaled":
        product = amount * den
        if product % num:
            raise UltimateMegaError("ROUNDING_OUT_OF_BOUNDS")
        raw = product // num
    else:
        raise UltimateMegaError("AMBIGUOUS_DISPLAY_UNITS")
    return record(
        "normalize_quote_amount_basis",
        {"input_amount": amount, "basis": basis, "raw_amount": raw},
    )


def segment_epoch_fee_boundaries(
    *,
    quote_epoch: int,
    build_epoch: int,
    quote_fee_ppm: int,
    build_fee_ppm: int,
    raw_amount: int,
) -> ContractResult:
    quote_epoch = require_nonnegative(quote_epoch, "quote_epoch")
    build_epoch = require_nonnegative(build_epoch, "build_epoch")
    raw_amount = require_nonnegative(raw_amount, "raw_amount")
    quote_fee = ppm_fee_ceil(raw_amount, quote_fee_ppm)
    build_fee = ppm_fee_ceil(raw_amount, build_fee_ppm)
    segments = (
        {"epoch": quote_epoch, "fee": quote_fee},
        {"epoch": build_epoch, "fee": build_fee},
    ) if quote_epoch != build_epoch or quote_fee != build_fee else (
        {"epoch": quote_epoch, "fee": quote_fee},
    )
    return record(
        "segment_epoch_fee_boundaries",
        {"segments": segments, "refresh_required": len(segments) > 1},
    )


def reject_cosmetic_price_anomaly(
    *,
    raw_value_before: int,
    raw_value_after: int,
    ui_value_before: int,
    ui_value_after: int,
) -> ContractResult:
    raw_before = require_nonnegative(raw_value_before, "raw_value_before")
    raw_after = require_nonnegative(raw_value_after, "raw_value_after")
    ui_before = require_nonnegative(ui_value_before, "ui_value_before")
    ui_after = require_nonnegative(ui_value_after, "ui_value_after")
    cosmetic = raw_before == raw_after and ui_before != ui_after
    return record(
        "reject_cosmetic_price_anomaly",
        {
            "classification": "COSMETIC" if cosmetic else "ECONOMIC_OR_UNCHANGED",
            "profitable_candidate": False if cosmetic else None,
            "raw_delta": raw_after - raw_before,
            "ui_delta": ui_after - ui_before,
        },
    )


def reconcile_display_adjusted_fills(
    raw_deltas: Mapping[str, int],
    *,
    display_multiplier_num: int = 1,
    display_multiplier_den: int = 1,
) -> ContractResult:
    num = require_positive(display_multiplier_num, "display_multiplier_num")
    den = require_positive(display_multiplier_den, "display_multiplier_den")
    normalized = {
        str(asset): require_int(delta, f"delta_{asset}")
        for asset, delta in raw_deltas.items()
    }
    raw_pnl = sum(normalized.values())
    return record(
        "reconcile_display_adjusted_fills",
        {
            "raw_deltas": normalized,
            "raw_pnl": raw_pnl,
            "display_pnl_fraction": (raw_pnl * num, den),
            "ledger_basis": "raw",
        },
    )
