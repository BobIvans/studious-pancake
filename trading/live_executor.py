"""Live trade executor for real Solana transactions via Jito bundles."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from solders.keypair import Keypair

from src.ingest.jito_bundle_client import JitoBundleClient
from src.ingest.jito_priority_context import JitoPriorityContextAdapter
from trading.fill_model import simulate_entry_fill
from trading.position_book import (
    apply_partial_exit,
    ensure_state,
    get_open_position_by_id,
    get_open_position_by_token,
    mark_to_market,
    next_trade_id,
    open_position,
)
from trading.trade_logger_v2 import log_signal, log_trade
from utils.clock import utc_now_iso
from utils.wallet_family_contract_fields import copy_wallet_family_contract_fields

logger = logging.getLogger(__name__)


def _market_index(market_states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in market_states:
        token = str(m.get("token_address") or "")
        if token:
            out[token] = m
    return out


def _sizing_fields(ctx: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "recommended_position_pct",
        "base_position_pct",
        "effective_position_pct",
        "sizing_multiplier",
        "sizing_origin",
        "sizing_reason_codes",
        "sizing_confidence",
        "sizing_warning",
        "evidence_quality_score",
        "evidence_conflict_flag",
        "partial_evidence_flag",
        "evidence_coverage_ratio",
        "evidence_available",
        "evidence_scores",
    )
    return {field: ctx.get(field) for field in fields if field in ctx}


class LiveTrader:
    """Real trade executor using Jito bundles."""

    def __init__(
        self,
        payer_keypair: Keypair,
        jito_client: Optional[JitoBundleClient] = None,
        jito_adapter: Optional[JitoPriorityContextAdapter] = None,
    ):
        self.payer_keypair = payer_keypair
        self.jito_client = jito_client or JitoBundleClient()
        self.jito_adapter = jito_adapter or JitoPriorityContextAdapter()

    async def execute_entry(
        self,
        signal: dict[str, Any],
        market_states: list[dict[str, Any]],
        state: dict[str, Any],
        settings: Any,
        token_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a real entry trade via Jito bundles.

        Args:
            signal: Entry signal from decide_entry
            market_states: Current market state data
            state: Portfolio state
            settings: Application settings
            token_context: Additional token context for Jito priority

        Returns:
            Updated portfolio state
        """
        ensure_state(state, settings)
        markets = _market_index(market_states)
        paths = state["paths"]

        # Log the entry signal
        log_signal(
            {
                "ts": utc_now_iso(),
                "event": "live_entry_signal",
                "token_address": signal.get("token_address"),
                "symbol": signal.get("symbol"),
                "decision": signal.get("entry_decision"),
                "confidence": signal.get("regime_confidence"),
                "recommended_position_pct": signal.get("recommended_position_pct"),
                "max_slippage_bps": signal.get("max_slippage_bps"),
                "execution_route": signal.get("execution_route"),
                "reason": signal.get("entry_reason"),
                **copy_wallet_family_contract_fields(signal),
                "contract_version": settings.LIVE_CONTRACT_VERSION,
            },
            paths,
        )

        decision = signal.get("entry_decision")
        if decision == "IGNORE":
            return state

        # Check for duplicate positions
        duplicate = get_open_position_by_token(state, str(signal.get("token_address") or ""))
        portfolio = state["portfolio"]
        max_positions_reached = int(portfolio.get("open_positions") or 0) >= int(settings.LIVE_MAX_CONCURRENT_POSITIONS)

        free_capital = float(portfolio.get("free_capital_sol") or 0.0)
        min_required_capital = 0.02  # Minimum usable balance

        if duplicate or max_positions_reached or free_capital <= min_required_capital:
            log_signal(
                {
                    "ts": utc_now_iso(),
                    "event": "live_signal_rejected",
                    "token_address": signal.get("token_address"),
                    "decision": decision,
                    "reason": "duplicate_or_capital_limit_or_dust",
                    **copy_wallet_family_contract_fields(signal),
                    "contract_version": settings.LIVE_CONTRACT_VERSION,
                },
                paths,
            )
            return state

        market = markets.get(signal.get("token_address"), {})

        # Simulate fill to estimate position size (paper trading logic)
        fill = simulate_entry_fill(signal, market, portfolio, settings)
        trade_id = next_trade_id(state)

        if fill["tx_failed"]:
            log_trade(
                {
                    "ts": utc_now_iso(),
                    "event": "live_fill_failed",
                    "trade_id": trade_id,
                    "position_id": None,
                    "token_address": signal.get("token_address"),
                    "symbol": signal.get("symbol"),
                    "side": "BUY",
                    "tx_failed": True,
                    "failure_reason": fill.get("failure_reason"),
                    **copy_wallet_family_contract_fields(signal),
                    "contract_version": settings.LIVE_CONTRACT_VERSION,
                },
                paths,
            )
            return state

        # Build Jito priority context
        ctx_for_jito = token_context or signal
        jito_context = self.jito_adapter.build_jito_context(ctx_for_jito)

        # Build actual swap instructions
        # NOTE: This is a placeholder - you need to implement actual swap instruction building
        # based on your specific DEX integration (Raydium, Jupiter, etc.)
        swap_instructions = await self._build_swap_instructions(
            signal, market, fill, settings
        )

        if not swap_instructions:
            logger.error(f"Failed to build swap instructions for {signal.get('token_address')}")
            log_trade(
                {
                    "ts": utc_now_iso(),
                    "event": "live_fill_failed",
                    "trade_id": trade_id,
                    "position_id": None,
                    "token_address": signal.get("token_address"),
                    "symbol": signal.get("symbol"),
                    "side": "BUY",
                    "tx_failed": True,
                    "failure_reason": "swap_instruction_build_failed",
                    **copy_wallet_family_contract_fields(signal),
                    "contract_version": settings.LIVE_CONTRACT_VERSION,
                },
                paths,
            )
            return state

        execution_route = signal.get("execution_route", "rpc")

        if execution_route == "jito":
            # Execute via Jito bundle
            bundle_result = await self.jito_client.build_and_send_bundle(
                swap_instructions=swap_instructions,
                payer_keypair=self.payer_keypair,
            )

            if not bundle_result.get("success"):
                logger.error(f"Jito bundle failed: {bundle_result.get('error')}")
                log_trade(
                    {
                        "ts": utc_now_iso(),
                        "event": "live_fill_failed",
                        "trade_id": trade_id,
                        "position_id": None,
                        "token_address": signal.get("token_address"),
                        "symbol": signal.get("symbol"),
                        "side": "BUY",
                        "tx_failed": True,
                        "failure_reason": f"jito_bundle_failed: {bundle_result.get('error')}",
                        "bundle_id": bundle_result.get("bundle_id"),
                        **copy_wallet_family_contract_fields(signal),
                        "contract_version": settings.LIVE_CONTRACT_VERSION,
                    },
                    paths,
                )
                return state

            # Wait for bundle confirmation
            confirmation = await self.jito_client.wait_for_bundle_confirmation(
                bundle_result["bundle_id"],
                max_wait_time=30.0,  # Shorter timeout for live trading
            )

            if confirmation["status"] not in ["confirmed", "finalized"]:
                logger.warning(f"Bundle not confirmed: {confirmation}")
                # For live trading, we might still want to track the position
                # even if confirmation is pending, as the trade might still land

            fill["bundle_id"] = bundle_result["bundle_id"]
            fill["bundle_status"] = confirmation["status"]
            fill["execution_route"] = "jito"

        else:
            # Execute via regular RPC (fallback)
            logger.warning("RPC execution not implemented - falling back to simulation")
            fill["execution_route"] = "rpc_simulated"
            # TODO: Implement direct RPC execution as fallback

        # Create position in state
        requested_effective_position_pct = float(signal.get("effective_position_pct") or signal.get("recommended_position_pct") or 0.0)
        actual_effective_position_pct = round(requested_effective_position_pct * float(fill.get("fill_ratio") or 0.0), 4)

        signal_for_position = {
            **signal,
            "requested_effective_position_pct": requested_effective_position_pct,
            "effective_position_pct": actual_effective_position_pct,
        }

        pos = open_position(fill, signal_for_position, state)

        log_trade(
            {
                "ts": utc_now_iso(),
                "event": "live_buy",
                "trade_id": trade_id,
                "position_id": pos["position_id"],
                "token_address": pos["token_address"],
                "symbol": pos.get("symbol"),
                "side": "BUY",
                **fill,
                **_sizing_fields(pos),
                "requested_effective_position_pct": requested_effective_position_pct,
                "regime": signal.get("entry_decision"),
                "reason": "live_entry_signal_executed",
                **copy_wallet_family_contract_fields(signal, fallback=pos),
                "contract_version": settings.LIVE_CONTRACT_VERSION,
            },
            paths,
        )

        return state

    async def _build_swap_instructions(
        self,
        signal: dict[str, Any],
        market: dict[str, Any],
        fill: dict[str, Any],
        settings: Any,
    ) -> list[Any]:
        """Build actual swap instructions using Jupiter API.

        Args:
            signal: Trading signal with entry/exit details
            market: Market state information
            fill: Fill details with amount and price
            settings: Trading settings

        Returns:
            List of instructions for the swap
        """
        try:
            # Import JupiterTxBuilder for real instruction building
            from src.ingest.tx_builder import JupiterTxBuilder
            import aiohttp

            # Extract trade details from signal/fill
            token_in = signal.get("token_in", signal.get("base_token"))
            token_out = signal.get("token_out", signal.get("target_token"))
            amount_in = fill.get("amount", fill.get("quantity", 0))

            if not token_in or not token_out or amount_in <= 0:
                logger.error(f"Invalid trade parameters: token_in={token_in}, token_out={token_out}, amount={amount_in}")
                return []

            # Convert amount to lamports if needed
            if token_in == "SOL":
                amount_lamports = int(amount_in * 1e9)
            else:
                # For other tokens, assume amount is already in correct decimals
                # This should be improved with proper decimal handling
                amount_lamports = int(amount_in * 1e6)  # Assume USDC-like decimals

            # Get slippage from signal or use default
            slippage_bps = signal.get("max_slippage_bps", 50)  # 0.5% default

            # Create Jupiter quote request
            async with aiohttp.ClientSession() as session:
                tx_builder = JupiterTxBuilder(session=session)

                # Get Jupiter quote
                params = {
                    "inputMint": token_in if token_in.startswith("So1") or len(token_in) > 10 else market.get("tokens", {}).get(token_in, token_in),
                    "outputMint": token_out if token_out.startswith("So1") or len(token_out) > 10 else market.get("tokens", {}).get(token_out, token_out),
                    "amount": str(amount_lamports),
                    "slippageBps": slippage_bps,
                    "onlyDirectRoutes": "true",         # Task 14: force direct routes for micro-balance safety
                    "restrictIntermediateTokens": "true",  # Task 14: unconditionally block intermediate tokens
                    "maxAccounts": "28",
                }

                # Get quote from Jupiter API
                quote_url = "https://quote-api.jup.ag/v6/quote"
                async with session.get(quote_url, params=params, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    if resp.status != 200:
                        logger.error(f"Jupiter quote failed: {resp.status}")
                        return []

                    quote_data = await resp.json()

                # Get swap instructions from Jupiter
                wallet_pubkey = str(self.payer_keypair.pubkey())  # Fixed: use self.payer_keypair
                swap_ixs, address_lookup_tables = await tx_builder.get_swap_instructions(
                    quote_data, wallet_pubkey, use_custom_cu=True
                )

                if not swap_ixs:
                    logger.error("Failed to get swap instructions from Jupiter")
                    return []

                logger.info(f"Built {len(swap_ixs)} swap instructions for {token_in} -> {token_out}")
                return swap_ixs

        except Exception as e:
            logger.error(f"Error building swap instructions: {e}")
            return []

    async def execute_exit(
        self,
        exit_signal: dict[str, Any],
        market_states: list[dict[str, Any]],
        state: dict[str, Any],
        settings: Any,
        token_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a real exit trade via Jito bundles."""
        # Similar to execute_entry but for selling positions
        # Implementation would mirror execute_entry but for exit trades
        logger.warning("Live exit execution not implemented")
        return state


async def process_live_entry_signals(
    entry_signals: list[dict[str, Any]],
    market_states: list[dict[str, Any]],
    state: dict[str, Any],
    settings: Any,
    live_trader: LiveTrader,
    token_contexts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Process multiple live entry signals."""
    token_ctx_map = {}
    if token_contexts:
        for ctx in token_contexts:
            token_addr = ctx.get("token_address")
            if token_addr:
                token_ctx_map[token_addr] = ctx

    for signal in entry_signals:
        token_addr = signal.get("token_address")
        token_ctx = token_ctx_map.get(token_addr)
        state = await live_trader.execute_entry(signal, market_states, state, settings, token_ctx)

    return state


def run_live_mark_to_market(
    state: dict[str, Any],
    market_states: list[dict[str, Any]],
    settings: Any
) -> dict[str, Any]:
    """Update live positions with current market prices."""
    ensure_state(state, settings)
    markets = _market_index(market_states)

    for pos in state.get("positions", []):
        if not pos.get("is_open"):
            continue
        mark_to_market(pos, markets.get(pos["token_address"], {}), state)

    return state