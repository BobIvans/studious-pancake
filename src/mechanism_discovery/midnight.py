"""RND-03 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_midnight_market = make_research_function("ingest_midnight_market", "RND-03")
reconstruct_credit_debt_book = make_research_function("reconstruct_credit_debt_book", "RND-03")
price_midnight_zero_coupon_curve = make_research_function("price_midnight_zero_coupon_curve", "RND-03")
model_settlement_liquidity = make_research_function("model_settlement_liquidity", "RND-03")
detect_cross_maturity_kink = make_research_function("detect_cross_maturity_kink", "RND-03")
detect_fixed_float_basis = make_research_function("detect_fixed_float_basis", "RND-03")
model_post_maturity_and_liquidation = make_research_function("model_post_maturity_and_liquidation", "RND-03")
qualify_midnight_family = make_research_function("qualify_midnight_family", "RND-03")

__all__ = [
    "ingest_midnight_market",
    "reconstruct_credit_debt_book",
    "price_midnight_zero_coupon_curve",
    "model_settlement_liquidity",
    "detect_cross_maturity_kink",
    "detect_fixed_float_basis",
    "model_post_maturity_and_liquidation",
    "qualify_midnight_family"
]
