from src.decision.contracts import ALLOWED_PRE_QUOTE_FEATURES


def test_no_float_money_or_legacy_score_schema():
    joined = " ".join(ALLOWED_PRE_QUOTE_FEATURES)
    for token in [
        "float",
        "UI amount",
        "virtual balance",
        "0.015",
        "0.02",
        "legacy_score",
    ]:
        assert token not in joined
