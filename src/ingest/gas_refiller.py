import asyncio
import logging
import base64
import time
import os
import aiohttp
import orjson
from typing import Optional
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.instructions import get_associated_token_address
from .jupiter_api_client import JupiterClient

logger = logging.getLogger("GasManager")


class StateManager:
    @staticmethod
    async def get_balance(session, rpc_manager, pubkey):
        # Fix 72: Force confirmed commitment (never use processed)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [str(pubkey), {"commitment": "confirmed"}],
        }
        timeout = aiohttp.ClientTimeout(total=3.0)
        headers = {
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            try:
                rpc_url = rpc_manager.get_rpc()
            except Exception as e:
                logger.error(f"No available RPCs: {e}")
                return None

            try:
                async with session.post(
                    rpc_url, json=payload, headers=headers, timeout=timeout
                ) as resp:
                    if resp.status == 200:
                        data = orjson.loads(await resp.read())
                        if "result" in data:
                            return data["result"]["value"] / 1e9
                    else:
                        error_text = await resp.text()
                        logger.warning(
                            f"Ошибка {resp.status} на RPC. Ответ: {error_text}"
                        )
                        if (
                            resp.status == 401
                            or "invalid api key" in error_text.lower()
                        ):
                            rpc_manager.blacklist(rpc_url)
            except Exception as e:
                logger.warning(f"Исключение на RPC: {e}")

        logger.error("Все 3 попытки RPC провалились, возвращаем None")
        return None


# FIX 306: Cooldown guard — prevent USDC drain from rapid refill loops
_LAST_REFILL_TIME = 0.0

async def check_and_refill_gas(session, rpc, keypair):
    """
    🔴 THREAT #1 FIX: Auto-swap USDC → Native SOL when gas runs low.
    P0 #20: Realistic target 0.008 SOL (was 0.020 — exceeding entire 0.015 SOL capital).
    P0 #21: 30s hard cooldown between refill attempts, timer updated only on real attempt.
    """
    global _LAST_REFILL_TIME

    # P0 #40: Paper mode — skip gas refill entirely
    if os.getenv("PAPER_TRADING_ONLY", "false").lower() == "true":
        return

    now = time.time()
    # P0 #21: Hard 30-second cooldown between refill attempts
    if now - _LAST_REFILL_TIME < 30.0:
        return

    try:
        # Check native balance
        native_bal = await StateManager.get_balance(session, rpc, keypair.pubkey())
        import src.ingest.shared_state as _ss
        min_reserve = _ss.MIN_RESERVE_SOL
        # P0 #20: Realistic target — 0.008 SOL (was 0.020)
        target_balance = float(os.getenv("TARGET_GAS_SOL", "0.008"))

        if native_bal is None:
            return
        # Don't refill if balance is above min reserve + small buffer
        if native_bal > (min_reserve + 0.001):
            return

        USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        usdc_ata = get_associated_token_address(
            keypair.pubkey(), Pubkey.from_string(USDC_MINT)
        )
        usdc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [str(usdc_ata)],
        }
        async with session.post(
            rpc.get_rpc(),
            json=usdc_payload,
            headers={"Content-Type": "application/json"},
        ) as usdc_resp:
            usdc_data = await usdc_resp.json()
            if "result" in usdc_data and "value" in usdc_data["result"]:
                usdc_amount = int(usdc_data["result"]["value"]["amount"])

                # Calculate dynamic deficit instead of hardcoded 2 USDC
                deficit_sol = target_balance - native_bal
                from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder
                feeder = get_pyth_core_feeder()
                sol_price = feeder.get_price("So11111111111111111111111111111111111111112") if feeder else None
                if sol_price is None:
                    logger.warning("🚫 SOL price unavailable from Pyth oracle — skipping gas refill (Fail-Closed)")
                    return
                deficit_usdc_lamports = int(
                    deficit_sol * sol_price * 1_000_000
                )  # Dynamic SOL price via Pyth
                # Cap at 50% of available USDC balance to protect trading capital (BL-013)
                max_allowed_usdc = int(usdc_amount * 0.5)
                # FIX 216: Protect USDC capital by applying max_allowed_usdc cap LAST
                swap_amount = max(deficit_usdc_lamports, 500_000)
                swap_amount = min(swap_amount, max_allowed_usdc)
                if swap_amount < 500_000:
                    logger.warning("USDC balance too low for minimum gas swap (requires at least $0.50)")
                    return

                # P0 #21: Update cooldown timer — only on real attempt
                _LAST_REFILL_TIME = time.time()

                if usdc_amount > 500_000:  # At least $0.50 USDC
                    logger.info(
                        f"🔄 GAS REPLENISHMENT: Swapping {swap_amount / 1_000_000:.2f} USDC to Native SOL "
                        f"(deficit={deficit_sol:.4f} SOL, Current: {native_bal:.4f} SOL, USDC: {usdc_amount / 1_000_000:.2f})"
                    )
                    try:
                        async with JupiterClient(session=session) as jup:
                            # Step 1: Get quote for USDC → SOL swap (dynamic amount)
                            quote = await jup.get_quote(
                                input_mint=USDC_MINT,
                                output_mint="So11111111111111111111111111111111111111112",
                                amount=swap_amount,
                                slippage_bps=50,  # Increased slippage for reliability
                                wallet_balance_sol=native_bal,
                            )
                            if "error" in quote:
                                logger.error(
                                    f"❌ Jupiter quote failed for USDC→SOL swap: {quote['error']}"
                                )
                                return

                            # Step 2: Build signed swap transaction
                            swap_tx = await jup.get_swap_transaction(
                                quote,
                                str(keypair.pubkey()),
                                wrap_unwrap_sol=True,
                            )
                            if "error" in swap_tx:
                                logger.error(
                                    f"❌ Jupiter swap tx failed for USDC→SOL swap: {swap_tx['error']}"
                                )
                                return

                            # Step 3: Decode the versioned transaction
                            signed_tx = JupiterClient.decode_swap_transaction(swap_tx)
                            if signed_tx is None:
                                logger.error(
                                    "❌ Failed to decode Jupiter swap transaction"
                                )
                                return

                            # Step 4: Resign with our keypair
                            signed_tx = VersionedTransaction(
                                signed_tx.message,
                                [keypair],
                            )

                            # Step 5: Broadcast via direct RPC
                            tx_b64_swap = base64.b64encode(bytes(signed_tx)).decode(
                                "ascii"
                            )
                            send_response = await session.post(
                                rpc.get_rpc(),
                                json={
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "sendTransaction",
                                    "params": [
                                        tx_b64_swap,
                                        {
                                            "skipPreflight": False,
                                            "maxRetries": 3,
                                        },
                                    ],
                                },
                            )
                            if send_response.status == 200:
                                swap_result = await send_response.json()
                                # FIX 217: Check for internal RPC errors masked as HTTP 200
                                if "error" in swap_result:
                                    logger.error(f"❌ Swap broadcast RPC error: {swap_result['error']}")
                                else:
                                    logger.info(f"✅ GAS REFILL: USDC→SOL swap relayed: {swap_result.get('result', 'OK')}")
                            else:
                                logger.error(
                                    f"❌ Swap broadcast returned "
                                    f"HTTP {send_response.status}: "
                                    f"{await send_response.text()}"
                                )
                    except Exception as jup_err:
                        logger.error(f"❌ USDC→SOL swap failed: {jup_err}")
    except Exception as e:
        logger.debug(f"Gas refill error: {e}")
