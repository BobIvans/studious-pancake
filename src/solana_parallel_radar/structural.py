"""Sender-free structural references; no fixed peg or exact pool authority."""

import base64
from fractions import Fraction
import struct

import base58

from src.research_economic_graph.registry import SPL_TOKEN_PROGRAM

CLOCK = "SysvarC1ock11111111111111111111111111111111"
SPL_POOL_PROGRAMS = (
    "SPoo1Ku8WFXoNDMHPsrGSTSG1Y47rzgn41SLUNakuHy",
    "SP12tWFxD9oJsVWNavTTBZvMbA6gkAmxtVgxdqvyvhY",
)


def account_bytes(account):
    if account is None or account.get("executable") is not False:
        raise ValueError("NONEXECUTABLE_ACCOUNT_REQUIRED")
    encoded, encoding = account["data"]
    if encoding != "base64" or len(encoded) > 24_000:
        raise ValueError("BOUNDED_BASE64_ACCOUNT_REQUIRED")
    return base64.b64decode(encoded, validate=True)


def sanctum_stake_pool_reference(pool, mint, clock, *, reference, slot):
    p, m, c = account_bytes(pool), account_bytes(mint), account_bytes(clock)
    if (
        pool["owner"] != reference["program_id"]
        or pool["owner"] not in SPL_POOL_PROGRAMS
        or mint["owner"] != SPL_TOKEN_PROGRAM
        or len(p) < 282
        or p[0] != 1
        or len(m) != 82
        or m[45] != 1
        or m[44] != reference["decimals"]
        or base58.b58encode(p[162:194]).decode() != reference["mint"]
        or base58.b58encode(p[226:258]).decode() != SPL_TOKEN_PROGRAM
        or clock["owner"] != "Sysvar1111111111111111111111111111111111111"
        or len(c) != 40
        or type(slot) is not int
        or slot <= 0
    ):
        raise ValueError("SANCTUM_POOL_MINT_PROGRAM_OR_LAYOUT_MISMATCH")
    total, supply, updated = struct.unpack_from("<QQQ", p, 258)
    epoch = struct.unpack_from("<Q", c, 16)[0]
    mint_supply = struct.unpack_from("<Q", m, 36)[0]
    if not total or not supply or supply != mint_supply or updated != epoch:
        raise ValueError("SANCTUM_RATE_STALE_OR_SUPPLY_MISMATCH")
    rate = Fraction(total, supply)
    return {
        "kind": "gpr02_sanctum_stake_pool_reference",
        "mint": reference["mint"],
        "pool_id": reference["pool_id"],
        "slot": slot,
        "epoch": epoch,
        "lamports_per_raw_unit_numerator": rate.numerator,
        "lamports_per_raw_unit_denominator": rate.denominator,
        "reference_kind": "STAKING_EXCHANGE_RATE",
        "fee_adjusted": False,
        "evidence_state": "DISCOVERY_ONLY",
        "exact_graph_allowed": False,
    }


def structural_residual_bps(output_amount, input_amount, numerator, denominator):
    if any(
        type(x) is not int or x <= 0
        for x in (output_amount, input_amount, numerator, denominator)
    ):
        raise ValueError("POSITIVE_INTEGER_STRUCTURAL_UNITS_REQUIRED")
    return (
        (output_amount * denominator - input_amount * numerator)
        * 10_000
        // (input_amount * numerator)
    )


def nav_arithmetic_only(
    *,
    aum_usd_atoms,
    jlp_supply,
    jlp_decimals,
    aum_decimals,
    slot,
    oracle_slot,
    raw_refs,
):
    # Arithmetic helper only. It does not authenticate supplied refs/state.
    if (
        any(type(v) is not int or v <= 0 for v in (aum_usd_atoms, jlp_supply, slot))
        or oracle_slot != slot
        or not raw_refs
        or type(jlp_decimals) is not int
        or not 0 <= jlp_decimals <= 18
        or type(aum_decimals) is not int
        or not 0 <= aum_decimals <= 18
    ):
        raise ValueError("JLP_CURRENT_AUM_SUPPLY_ORACLE_RECEIPTS_REQUIRED")
    nav = Fraction(aum_usd_atoms * 10**jlp_decimals, jlp_supply * 10**aum_decimals)
    return {
        "anchor_type": "NAV",
        "usd_per_jlp_numerator": nav.numerator,
        "usd_per_jlp_denominator": nav.denominator,
        "slot": slot,
        "raw_refs": tuple(sorted(set(raw_refs))),
        "exact_graph_allowed": False,
        "live_nav_qualified": False,
        "receipt_reconstruction_required": True,
    }
