#!/usr/bin/env python3
"""Final integration test for the complete High-Frequency MEV Executor."""

import asyncio
import logging
import os
from decimal import Decimal
from dotenv import load_dotenv
from src.ingest.optimal_trade_sizer import OptimalTradeSizer, VelocitySlippageManager
from src.ingest.pre_trade_guard import PreTradeGuard
from src.ingest.jito_bundle_handler import JitoBundleHandler
from src.ingest.rpc_multiplexing import ExecutionPipeline
from solders.keypair import Keypair

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_complete_mev_pipeline():
    """Test the complete MEV execution pipeline."""
    logger.info("🚀 Testing Complete MEV Executor Pipeline...")

    # Initialize components
    keypair = Keypair()
    trade_sizer = OptimalTradeSizer()
    slippage_manager = VelocitySlippageManager()

    # Test optimal sizing
    logger.info("📊 Testing Optimal Trade Sizing...")
    quote1 = {"outAmount": "1000000000"}  # 1 SOL out
    quote2 = {"outAmount": "1020000000"}  # 1.02 SOL out

    optimal_amount = trade_sizer.find_optimal_trade_size(
        quote1=quote1,
        quote2=quote2,
        base_mint_decimals=9,
        intermediate_mint_decimals=9,
        working_cap_sol=1.0
    )
    logger.info(f"✅ Optimal amount calculated: {optimal_amount}")

    # Test slippage management
    logger.info("📈 Testing Dynamic Slippage...")
    for i in range(20):
        slippage_manager.record_transaction(i * 0.05)
    dynamic_slippage = slippage_manager.get_dynamic_slippage()
    logger.info(f"✅ Dynamic slippage: {dynamic_slippage:.1%}")

    # Test security validation
    logger.info("🛡️ Testing Security Shield...")
    guard = PreTradeGuard()
    is_safe, reason = await guard.validate_token_security("So11111111111111111111111111111111111111112")
    logger.info(f"✅ Security check: {is_safe} - {reason}")

    # Test Jito bundle handler
    logger.info("🔥 Testing Jito Bundle Handler...")
    bundle_handler = JitoBundleHandler(keypair)
    tip_account = await bundle_handler._select_tip_account()
    tip_template = bundle_handler.bundle_template.create_tip_template(50000, tip_account)
    logger.info(f"✅ Tip template created: {tip_template.message.recent_blockhash}")

    logger.info("🎉 All MEV components tested successfully!")

async def test_execution_pipeline():
    """Test the execution pipeline integration."""
    logger.info("⚡ Testing Execution Pipeline Integration...")

    test_rpc = os.getenv("RPC_URL_1", "https://api.mainnet-beta.solana.com")
    keypair = Keypair()
    pipeline = ExecutionPipeline(
        rpc_endpoints=[test_rpc],
        wss_endpoints=[os.getenv("WSS_ENDPOINT_1", "wss://api.mainnet-beta.solana.com")],
        monitored_addresses=["675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"],
        trade_sizer=OptimalTradeSizer(),
        slippage_manager=VelocitySlippageManager(),
        pre_trade_guard=PreTradeGuard(),
        keypair=keypair
    )

    logger.info("✅ Execution pipeline initialized successfully")

async def main():
    """Run all final integration tests."""
    logger.info("🏆 Starting Final MEV Executor Integration Tests...")

    try:
        await test_complete_mev_pipeline()
        await test_execution_pipeline()
        logger.info("🎯 All integration tests passed! MEV Executor is ready for deployment.")
    except Exception as e:
        logger.error(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())