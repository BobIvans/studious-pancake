"""PR-290 / NF-845..848: PSM/flash-mint cap and immediate basis."""

from __future__ import annotations
from .core import Mega808Error, Result, require_nonnegative, require_positive, result


def register_psm_flashmint_primitive(*, primitive_id: str, input_asset: str, output_asset: str, repayment_same_transaction: bool) -> Result:
    if not primitive_id or not input_asset or not output_asset:
        raise Mega808Error("PRIMITIVE_IDENTITY_REQUIRED")
    if not repayment_same_transaction:
        raise Mega808Error("TEMPORAL_REPAYMENT_UNSUPPORTED")
    return result("register_psm_flashmint_primitive", {"primitive_id":primitive_id,"input_asset":input_asset,"output_asset":output_asset,"repayment_same_transaction":True})


def read_mint_cap_and_fee(*, mint_cap: int, current_minted: int, fee_ppm: int, permissioned: bool, caller_permitted: bool) -> Result:
    cap=require_nonnegative(mint_cap,"mint_cap")
    minted=require_nonnegative(current_minted,"current_minted")
    fee=require_nonnegative(fee_ppm,"fee_ppm")
    if minted>cap or fee>1_000_000:
        raise Mega808Error("MINT_STATE_INVALID")
    if permissioned and not caller_permitted:
        raise Mega808Error("CALLER_NOT_PERMITTED")
    return result("read_mint_cap_and_fee", {"remaining_cap":cap-minted,"fee_ppm":fee,"caller_permitted":caller_permitted or not permissioned})


def quote_stablecoin_mint_redeem(*, amount_in: int, rate_num: int, rate_den: int, fee_ppm: int, remaining_cap: int) -> Result:
    amount=require_nonnegative(amount_in,"amount_in")
    num=require_positive(rate_num,"rate_num")
    den=require_positive(rate_den,"rate_den")
    cap=require_nonnegative(remaining_cap,"remaining_cap")
    if amount>cap:
        raise Mega808Error("MINT_CAP_SHORTFALL")
    gross=amount*num//den
    fee=gross*require_nonnegative(fee_ppm,"fee_ppm")//1_000_000
    return result("quote_stablecoin_mint_redeem", {"amount_in":amount,"gross_out":gross,"fee":fee,"amount_out":max(0,gross-fee)})


def detect_psm_basis(*, conversion_out: int, dex_repurchase_cost: int, execution_cost: int) -> Result:
    out=require_nonnegative(conversion_out,"conversion_out")
    repurchase=require_nonnegative(dex_repurchase_cost,"dex_repurchase_cost")
    cost=require_nonnegative(execution_cost,"execution_cost")
    edge=out-repurchase-cost
    return result("detect_psm_basis", {"conversion_out":out,"dex_repurchase_cost":repurchase,"execution_cost":cost,"edge":edge,"executable_positive":edge>0})
