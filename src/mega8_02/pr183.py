"""PR-183 / LST-03: stake-account exchange and instant-exit routes."""
from __future__ import annotations
from dataclasses import dataclass
from .core import EvidenceBinding, Mega802Error, rational_quote, stable_hash


@dataclass(frozen=True, slots=True)
class StakeAccountQuote:
    stake_account: str
    input_lamports: int
    output_lamports: int
    exit_capacity: int
    evidence: EvidenceBinding


def quote_stake_account_exchange(
    quote: StakeAccountQuote, *, amount: int, now: int
) -> int:
    quote.evidence.assert_usable(now=now)
    if amount > quote.input_lamports or amount > quote.exit_capacity:
        raise Mega802Error("STAKE_ACCOUNT_CAPACITY_EXCEEDED")
    return rational_quote(amount, quote.output_lamports, quote.input_lamports)


def build_stake_account_route(
    quote: StakeAccountQuote, *, amount: int, now: int
) -> str:
    output = quote_stake_account_exchange(quote, amount=amount, now=now)
    return stable_hash(
        {"stake_account": quote.stake_account, "amount": amount, "output": output,
         "evidence": quote.evidence.identity}
    )


def verify_instant_exit_capacity(
    quote: StakeAccountQuote, *, amount: int
) -> bool:
    if amount > quote.exit_capacity:
        raise Mega802Error("INSTANT_EXIT_CAPACITY_UNAVAILABLE")
    return True


def simulate_stake_account_cycle(
    quote: StakeAccountQuote, *, amount: int, dex_guaranteed_out: int, now: int
) -> int:
    acquired = quote_stake_account_exchange(quote, amount=amount, now=now)
    net = dex_guaranteed_out - acquired
    if net <= 0:
        raise Mega802Error("NO_STAKE_ACCOUNT_CYCLE")
    return net
