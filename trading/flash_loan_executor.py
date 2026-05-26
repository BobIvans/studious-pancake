#!/usr/bin/env python3
"""Flash Loan + Jupiter Arbitrage Executor (Native Python Implementation)"""
import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone

from utils.logger import log_info, log_warning
from utils.io import append_jsonl
from config.settings import Settings
from trading.paper_trader import process_entry_signals  # для совместимости


FLM_PROGRAM_ID = "1oanfPPN8r1i4UbugXHDxWMbWVJ5qLSN5qzNFZkz6Fg"
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
FLM_CLI_PATH = Path("flm-jupiter-arb")  # путь к папке с CLI из репозитория moshthepitt


async def get_jupiter_quote(
    input_mint: str,
    output_mint: str,
    amount_lamports: int,
    slippage_bps: int = 150,
) -> Dict[str, Any]:
    """Получаем свежий quote от Jupiter (бесплатно)"""
    # Task 14: force direct routes + restrictIntermediateTokens to prevent ATA drain
    # Task 16: amount is already int, no float → decimal-point risk
    url = (
        f"{JUPITER_QUOTE_API}?inputMint={input_mint}&outputMint={output_mint}"
        f"&amount={amount_lamports}&slippageBps={slippage_bps}"
        f"&onlyDirectRoutes=true&restrictIntermediateTokens=true&maxAccounts=8"
    )
    try:
        # используем curl (уже есть в окружении, надёжно)
        cmd = ["curl", "-s", "-L", url]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
        
        if process.returncode != 0:
            return {"error": "jupiter_network_error"}
        data = json.loads(stdout.decode())
        if "error" in data:
            return {"error": data.get("error")}
        return data
    except Exception as e:
        log_warning("jupiter_quote_exception", error=str(e))
        return {"error": "jupiter_quote_failed"}


async def execute_flash_loan_jupiter_arb(
    signal: Dict[str, Any],
    settings: Settings,
    run_dir: Path,
) -> Dict[str, Any]:
    """Execute flash loan arbitrage using native Python logic with JupiterTxBuilder."""
    token_in = str(signal.get("token_address") or signal.get("input_mint") or "")
    token_out = str(signal.get("output_mint") or "")
    amount = int(signal.get("amount_lamports") or signal.get("size_sol", 0) * 1_000_000_000 or 1_000_000_000)

    if not token_out:
        token_out = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    log_info("flash_loan_arb_started", token_in=token_in, token_out=token_out, amount=amount)

    marginfi_account = getattr(settings, "MARGINFI_ACCOUNT", "")
    if not marginfi_account:
        log_warning("marginfi_account_missing")
        return {"status": "failed", "reason": "marginfi_account_not_set"}

    quote = await get_jupiter_quote(token_in, token_out, amount)
    if "error" in quote:
        log_warning("flash_loan_arb_quote_failed", token=token_in)
        return {"status": "failed", "reason": quote["error"]}

    expected_out = int(quote.get("outAmount", 0))
    estimated_profit = (expected_out - amount) / 1_000_000_000

    try:
        from src.ingest.tx_builder import JupiterTxBuilder
        
        tx_builder = JupiterTxBuilder(
            session=None,
            rpc_url=settings.RPC_URL_1 if hasattr(settings, 'RPC_URL_1') else "https://api.mainnet-beta.solana.com"
        )
        
        wallet_path = settings.SOLANA_WALLET_PATH if hasattr(settings, 'SOLANA_WALLET_PATH') else "~/.config/solana/id.json"
        
        fl_result = await tx_builder.build_marginfi_flashloan_tx(
            wallet_pubkey=str(settings.WALLET_PUBKEY) if hasattr(settings, 'WALLET_PUBKEY') else "",
            borrow_amount_lamports=amount,
            buy_quote_response=quote,
            sell_quote_response={},
            marginfi_account=marginfi_account,
            bank_pubkey=getattr(settings, 'MARGINFI_SOL_BANK', "CCwqExrqLGHtq12X182rFvA4KEDtK13q2E7B3Jp2Cxyj"),
            bank_liquidity_vault=getattr(settings, 'BANK_LIQUIDITY_VAULT', ""),
            bank_liquidity_vault_authority=getattr(settings, 'BANK_LIQUIDITY_VAULT_AUTH', ""),
            use_jito=True,
        )

        if fl_result:
            from src.ingest.jito_executor import JitoExecutor
            jito_executor = JitoExecutor(session=None)
            
            instructions = fl_result.get("instructions", [])
            bundle_result = await jito_executor.send_bundle(instructions)

            if bundle_result.get("success"):
                tx_signature = bundle_result.get("bundle_id", "unknown")
            else:
                tx_signature = None
        else:
            log_warning("flash_loan_arb_failed", reason="tx_build_failed")
            tx_signature = None

    except Exception as e:
        log_warning("flash_loan_exception", error=str(e))
        tx_signature = None

    trade_record = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "flash_loan_arb_native",
        "token_address": token_in,
        "symbol": signal.get("symbol", "ARB"),
        "side": "BUY",
        "regime": "ARB",
        "arb_score": float(signal.get("arb_score", 0)),
        "tx_signature": tx_signature or "",
        "expected_profit_sol": round(estimated_profit, 6),
        "status": "success" if tx_signature else "failed",
        "contract_version": "native_python_v1",
    }

    append_jsonl(run_dir / "trades.jsonl", trade_record)

    if tx_signature:
        log_info(
            "flash_loan_arb_executed",
            token=token_in,
            arb_score=signal.get("arb_score"),
            profit_est=estimated_profit,
            tx=tx_signature,
        )
    else:
        log_warning("flash_loan_arb_failed", token=token_in, reason="execution_failed")

    return trade_record