"""Typed configuration loader for PR-010 feasibility policies."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
import os
from typing import Mapping

from src.domain.money import Lamports, LAMPORTS_PER_SOL, MonetaryUnitError, TokenAmount, USDC_MINT
from src.domain.feasibility import FeasibilityPolicy, WalletReservePolicy


def parse_sol_lamports(value: str) -> Lamports:
    if value is None or value == "":
        raise MonetaryUnitError("explicit SOL amount is required")
    return Lamports(int((Decimal(value) * Decimal(LAMPORTS_PER_SOL)).to_integral_value(rounding=ROUND_FLOOR)))


@dataclass(frozen=True)
class FeasibilityConfig:
    wallet_policy: WalletReservePolicy
    policy: FeasibilityPolicy
    max_principal: TokenAmount
    max_sizing_evaluations: int
    token_2022_policy: str = "exact_snapshot_required"
    live_readiness: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "FeasibilityConfig":
        required = ["PROTECTED_RESERVE_SOL", "MIN_NET_PROFIT_USDC_UNITS", "MIN_NET_PROFIT_BPS", "PRIORITY_FEE_CAP_LAMPORTS", "TIP_CAP_LAMPORTS", "MAX_PRINCIPAL_USDC_UNITS"]
        missing = [k for k in required if not env.get(k)]
        live = env.get("LIVE_TRADING_ENABLED", "false").lower() == "true"
        if live and missing:
            raise MonetaryUnitError(f"live config missing explicit values: {missing}")
        protected = parse_sol_lamports(env.get("PROTECTED_RESERVE_SOL", "0"))
        failure_cap = Lamports(int(env.get("FAILED_ATTEMPT_CAP_LAMPORTS", "0")))
        wallet_policy = WalletReservePolicy(protected, int(env.get("MAX_ADDITIONAL_FAILURE_ATTEMPTS", "0")), failure_cap, env.get("FEASIBILITY_CONFIG_VERSION", "env"))
        min_abs = TokenAmount(USDC_MINT, int(env.get("MIN_NET_PROFIT_USDC_UNITS", "0")), 6)
        safety = TokenAmount(USDC_MINT, int(env.get("PROFIT_SAFETY_BUFFER_USDC_UNITS", "0")), 6)
        policy = FeasibilityPolicy(
            min_abs,
            int(env.get("MIN_NET_PROFIT_BPS", "0")),
            safety,
            max_quote_age=timedelta(milliseconds=int(env.get("MAX_QUOTE_AGE_MS", "1500"))),
            max_conversion_age=timedelta(milliseconds=int(env.get("MAX_CONVERSION_AGE_MS", "5000"))),
            max_wallet_age=timedelta(milliseconds=int(env.get("MAX_WALLET_SNAPSHOT_AGE_MS", "2000"))),
            max_account_age=timedelta(milliseconds=int(env.get("MAX_ACCOUNT_SNAPSHOT_AGE_MS", "2000"))),
            max_price_impact_bps=int(env.get("MAX_PRICE_IMPACT_BPS", "10000")),
            tip_absolute_cap=Lamports(int(env.get("TIP_CAP_LAMPORTS", "0"))),
            priority_fee_absolute_cap=Lamports(int(env.get("PRIORITY_FEE_CAP_LAMPORTS", "0"))),
            live_readiness=False,
            config_version=env.get("FEASIBILITY_CONFIG_VERSION", "env"),
        )
        return cls(wallet_policy, policy, TokenAmount(USDC_MINT, int(env.get("MAX_PRINCIPAL_USDC_UNITS", "0")), 6), int(env.get("MAX_SIZING_EVALUATIONS", "16")), live_readiness=False)
