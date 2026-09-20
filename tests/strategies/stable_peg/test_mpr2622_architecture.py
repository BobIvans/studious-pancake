from pathlib import Path


def test_strategy_package_has_no_sender_signer_or_network_imports():
    root = Path("src/strategies/stable_peg")
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
    forbidden = ("sendTransaction", "sendRawTransaction", "sendBundle", "isolated_signer", "aiohttp", "httpx", "requests", "legacy_arb_bot", "src.ingest")
    for token in forbidden:
        assert token not in text
