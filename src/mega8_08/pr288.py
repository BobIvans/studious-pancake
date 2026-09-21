"""PR-288 / NF-837..840: ERC-4626 immediate buffer parity."""

from __future__ import annotations
from typing import Mapping
from .core import Mega808Error, Result, require_nonnegative, require_positive, result, stable_hash


def register_erc4626_vault(*, vault: str, share_asset: str, underlying_asset: str, decimals: int, deployment_verified: bool) -> Result:
    if not all((vault, share_asset, underlying_asset)) or not deployment_verified:
        raise Mega808Error("VAULT_IDENTITY_UNVERIFIED")
    decimals=require_nonnegative(decimals,"decimals")
    if decimals>30:
        raise Mega808Error("DECIMALS_OUT_OF_RANGE")
    return result("register_erc4626_vault", {"vault": vault, "share_asset": share_asset, "underlying_asset": underlying_asset, "decimals": decimals, "deployment_verified": True})


def read_buffer_capacity(*, total_assets: int, immediately_withdrawable: int, reserved_assets: int=0) -> Result:
    total=require_nonnegative(total_assets,"total_assets")
    immediate=require_nonnegative(immediately_withdrawable,"immediately_withdrawable")
    reserved=require_nonnegative(reserved_assets,"reserved_assets")
    if immediate>total or reserved>immediate:
        raise Mega808Error("BUFFER_STATE_INVALID")
    return result("read_buffer_capacity", {"total_assets": total, "immediate_capacity": immediate-reserved, "reserved_assets": reserved})


def quote_wrap_unwrap_path(*, shares: int, assets_per_share_num: int, assets_per_share_den: int, fee_assets: int, immediate_capacity: int) -> Result:
    shares=require_nonnegative(shares,"shares")
    num=require_positive(assets_per_share_num,"assets_per_share_num")
    den=require_positive(assets_per_share_den,"assets_per_share_den")
    fee=require_nonnegative(fee_assets,"fee_assets")
    capacity=require_nonnegative(immediate_capacity,"immediate_capacity")
    gross=shares*num//den
    net=max(0,gross-fee)
    if net>capacity:
        return result("quote_wrap_unwrap_path", {"shares":shares,"gross_assets":gross,"net_assets":net,"immediate_capacity":capacity}, status="BLOCKED", blockers=("BUFFER_CAPACITY_SHORTFALL",))
    return result("quote_wrap_unwrap_path", {"shares":shares,"gross_assets":gross,"net_assets":net,"immediate_capacity":capacity})


def detect_vault_buffer_parity(*, dex_exit_assets: int, vault_exit_assets: int, total_fees: int) -> Result:
    dex=require_nonnegative(dex_exit_assets,"dex_exit_assets")
    vault=require_nonnegative(vault_exit_assets,"vault_exit_assets")
    fees=require_nonnegative(total_fees,"total_fees")
    edge=vault-dex-fees
    return result("detect_vault_buffer_parity", {"dex_exit_assets":dex,"vault_exit_assets":vault,"fees":fees,"edge":edge,"executable_positive":edge>0})
