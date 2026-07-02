import asyncio
import os
import json
import logging
import base64
from typing import List
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash
import aiohttp
from spl.token.instructions import close_account, CloseAccountParams
from src.ingest.tx_builder import validate_cb_ordering

COMPUTE_BUDGET_PROG_ID = Pubkey.from_string("ComputeBudget111111111111111111111111111111")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EmergencyRecover")

async def get_all_token_accounts(session: aiohttp.ClientSession, rpc_url: str, owner: Pubkey):
    """Fetch all token accounts for the owner."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            str(owner),
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }
    async with session.post(rpc_url, json=payload) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("result", {}).get("value", [])
    return []


async def unwrap_wsol_accounts(session, rpc_url, keypair, wsol_accounts):
    """Real wSOL unwrap + close logic."""
    from spl.token.instructions import close_account, CloseAccountParams
    TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

    for account_info in wsol_accounts:
        acc_pubkey = account_info["pubkey"]
        balance = account_info["balance"]

        logger.info(f"Unwrapping wSOL account {str(acc_pubkey)[:8]}... with {balance} wSOL")

        close_ix = close_account(CloseAccountParams(
            account=acc_pubkey,
            dest=keypair.pubkey(),
            owner=keypair.pubkey(),
            program_id=TOKEN_PROGRAM_ID,
            signers=[],
        ))

        blockhash_payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}]
        }

        try:
            async with session.post(rpc_url, json=blockhash_payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    blockhash = Hash.from_string(data["result"]["value"]["blockhash"])
                    
                    if not validate_cb_ordering([close_ix], "emergency_recover.unwrap_wsol"):
                        logger.critical("CRITICAL: ComputeBudget ordering violation in emergency_recover. Skipping TX.")
                        return

                    msg = MessageV0.try_compile(
                        payer=keypair.pubkey(),
                        instructions=[close_ix],
                        address_lookup_table_accounts=[],
                        recent_blockhash=blockhash
                    )
                    tx = VersionedTransaction(msg, [keypair])
                    send_payload = {
                        "jsonrpc": "2.0", "id": 1,
                        "method": "sendTransaction",
                        "params": [base64.b64encode(bytes(tx)).decode(), {"encoding": "base64", "skipPreflight": True}]
                    }
                    async with session.post(rpc_url, json=send_payload) as send_resp:
                        if send_resp.status == 200:
                            logger.info(f"✅ wSOL account {str(acc_pubkey)[:8]} closed and unwrapped successfully")
                        else:
                            logger.error(f"Failed to send wSOL close tx: {await send_resp.text()}")
        except Exception as e:
            logger.error(f"Error during wSOL unwrap: {e}")

async def recover_rent():
    """Main recovery loop."""
    from dotenv import load_dotenv
    load_dotenv()
    
    rpc_url = os.getenv("RPC_URL_1")
    wallet_path = os.getenv("WALLET_PATH", "wallet.json")
    
    # Try primary wallet path first
    keypair = None
    if os.path.exists(wallet_path):
        with open(wallet_path, 'r') as f:
            raw = f.read().strip()
            if raw and raw != "[]":
                keypair = Keypair.from_bytes(bytes(json.loads(raw)))

    # Fallback: empty wallet.json → try WALLET_PATH env var
    if keypair is None:
        alt_path = os.getenv("WALLET_PATH", "/Users/ivansbobrovs/.config/solana/new_id.json")
        logger.warning(f"wallet.json is empty or missing; falling back to {alt_path}")
        if os.path.exists(alt_path):
            with open(alt_path, 'r') as f:
                keypair = Keypair.from_bytes(bytes(json.load(f)))

    if keypair is None:
        logger.error("No valid wallet keypair found. Check wallet.json or WALLET_PATH.")
        return
    
    logger.info(f"Starting recovery for wallet: {keypair.pubkey()}")

    async with aiohttp.ClientSession() as session:
        accounts = await get_all_token_accounts(session, rpc_url, keypair.pubkey())
        logger.info(f"Found {len(accounts)} token accounts.")

        empty_accounts = []
        wsol_accounts_to_unwrap = []
        WSOL_MINT = "So11111111111111111111111111111111111111112"

        for acc in accounts:
            pubkey = acc.get("pubkey")
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            mint = info.get("mint")
            balance = info.get("tokenAmount", {}).get("uiAmount", 0)

            # Fix 5: wSOL (So11111111111111111111111111111111111111112) must be unwrapped BEFORE close_account
            # If wSOL balance > 0, unwrap (close_account with unwrap) instead of just close_account
            # This recovers the full wSOL amount + rent to native SOL
            if mint == WSOL_MINT and balance > 0:
                wsol_accounts_to_unwrap.append({"pubkey": Pubkey.from_string(pubkey), "balance": balance})
            elif mint == WSOL_MINT and balance == 0:
                # Empty wSOL account - just close it
                empty_accounts.append(Pubkey.from_string(pubkey))
            elif balance == 0:
                empty_accounts.append(Pubkey.from_string(pubkey))

        # Fix point 1 + 7: call real unwrap logic
        if wsol_accounts_to_unwrap:
            await unwrap_wsol_accounts(session, rpc_url, keypair, wsol_accounts_to_unwrap)

        if not empty_accounts and not wsol_accounts_to_unwrap:
            logger.info("No empty accounts found. Nothing to recover.")
            return

        if empty_accounts:
            logger.info(f"Identified {len(empty_accounts)} empty accounts to close.")

        # 3. Create close instructions (batch in groups of 10)
        from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
        batch_size = 10
        for i in range(0, len(empty_accounts), batch_size):
            batch = empty_accounts[i:i + batch_size]
            instructions = []
            # Add priority fee instructions to ensure the rescue tx lands during congestion
            # Phase 8.1: Priority Fee for Emergency Recovery
            instructions.append(set_compute_unit_limit(100_000))
            instructions.append(set_compute_unit_price(1_000_000))  # 1M micro-lamports (1 lamport/CU) to guarantee instant rescue
            for acc_pubkey in batch:
                ix = close_account(CloseAccountParams(
                    program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                    account=acc_pubkey,
                    dest=keypair.pubkey(),
                    owner=keypair.pubkey(),
                    signers=[],
                ))
                instructions.append(ix)

            # 4. Get recent blockhash
            async with session.post(rpc_url, json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}) as resp:
                bh_data = await resp.json()
                recent_blockhash = Hash.from_string(bh_data["result"]["value"]["blockhash"])

            # 5. Build and send transaction
            # ── FIX 2: Compute Budget Strict Ordering check ────────────────
            if not validate_cb_ordering(instructions, "emergency_recover.recover_rent"):
                logger.critical("CRITICAL: ComputeBudget ordering violation in emergency_recover. Skipping TX.")
                return
            # ─────────────────────────────────────────────────────────────────
            msg = MessageV0.try_compile(
                payer=keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash
            )
            tx = VersionedTransaction(msg, [keypair])
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [base64.b64encode(bytes(tx)).decode('ascii'), {"encoding": "base64", "skipPreflight": False}]
            }
            
            async with session.post(rpc_url, json=payload) as resp:
                data = await resp.json()
                if "result" in data:
                    logger.info(f"✅ Batch {i//batch_size + 1} sent: {data['result']}")
                    logger.info(f"💰 Recovered {len(batch) * 0.002:.4f} SOL")
                else:
                    logger.error(f"❌ Failed to send batch {i//batch_size + 1}: {data.get('error')}")

if __name__ == "__main__":
    asyncio.run(recover_rent())
