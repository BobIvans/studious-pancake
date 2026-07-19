from __future__ import annotations

import hashlib

from .models import Commitment, LendingProtocol, LendingSnapshot, Pubkey, RawAccount


def account_set_hash(accounts: tuple[RawAccount, ...]) -> str:
    h = hashlib.sha256()
    for account in sorted(accounts, key=lambda x: x.pubkey):
        h.update(account.hash().encode())
    return h.hexdigest()


def build_snapshot(
    protocol: LendingProtocol,
    deployment_id: str,
    read_slot: int,
    commitment: Commitment,
    market_or_group: Pubkey,
    accounts: tuple[RawAccount, ...],
    version: str,
) -> LendingSnapshot:
    if not accounts:
        raise ValueError("snapshot dependency closure is empty")
    if any(account.commitment is not commitment for account in accounts):
        raise ValueError("mixed commitments forbidden")
    if any(account.slot < read_slot for account in accounts):
        raise ValueError("account older than read_slot forbidden")
    return LendingSnapshot(
        protocol,
        deployment_id,
        read_slot,
        commitment,
        market_or_group,
        accounts,
        account_set_hash(accounts),
        version,
    )
