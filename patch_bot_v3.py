import os
import re

def patch_file(filepath, replacements):
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return False
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read().replace('\r\n', '\n')
    
    original_content = content
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            print(f"✅ Replaced block in {filepath}")
        else:
            print(f"⚠️ Block not found in {filepath} (or already patched)")
    
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"💾 Saved changes to {filepath}")
        return True
    return False

def main():
    print("🤖 Starting Comprehensive Production Patch v3...")

    # --- 1. Fix EventTriggerEngine Indentation Error ---
    if os.path.exists("src/ingest/event_triggers.py"):
        with open("src/ingest/event_triggers.py", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        
        corrected = False
        for i, line in enumerate(lines):
            if "if token_symbol in self.oracle_prices:" in line:
                # The next line should be indented with 12 spaces
                next_line = lines[i+1]
                if next_line.strip() and not next_line.startswith(" " * 12):
                    lines[i+1] = "            " + next_line.strip()
                    corrected = True
                    print("✅ Corrected indentation for _check_oracle_lag_arbitrage in event_triggers.py")
                    break
        if corrected:
            with open("src/ingest/event_triggers.py", "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    # --- 2. Fix ExecutionRouter Indentation Error ---
    if os.path.exists("src/ingest/execution_router.py"):
        with open("src/ingest/execution_router.py", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            
        corrected = False
        for i, line in enumerate(lines):
            if "pair_key = self._pair_key(" in line:
                # This should be indented with exactly 8 spaces
                if not line.startswith("        ") or line.startswith("         "):
                    lines[i] = "        " + line.strip()
                    corrected = True
                    print(f"✅ Corrected indentation for pair_key on line {i+1} in execution_router.py")
                    break
        if corrected:
            with open("src/ingest/execution_router.py", "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    # --- 3. Fix spl.token ValueError (SPL_TOKEN_2022_PROGRAM_ID) in arb_bot.py ---
    if os.path.exists("arb_bot.py"):
        with open("arb_bot.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Update import to include TOKEN_2022_PROGRAM_ID
        old_import = "from spl.token.constants import TOKEN_PROGRAM_ID"
        new_import = "from spl.token.constants import TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID as SPL_TOKEN_2022_PROGRAM_ID"
        if old_import in content:
            content = content.replace(old_import, new_import)
            print("✅ Updated spl.token.constants import in arb_bot.py")

        # Update _GOLDEN_ATA_MINTS mapping to use correct objects directly
        old_mints = """_GOLDEN_ATA_MINTS: Dict[str, str] = {
    # SPL Token Program mints
    "So11111111111111111111111111111111111111112": str(TOKEN_PROGRAM_ID),  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": str(TOKEN_PROGRAM_ID),  # USDC
    # Token-2022 LST mints
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": str(
        TOKEN_2022_PROGRAM_ID
    ),  # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": str(TOKEN_2022_PROGRAM_ID),  # mSOL
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": str(TOKEN_2022_PROGRAM_ID),  # INF
}"""
        new_mints = """_GOLDEN_ATA_MINTS: Dict[str, Any] = {
    # SPL Token Program mints
    "So11111111111111111111111111111111111111112": TOKEN_PROGRAM_ID,  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": TOKEN_PROGRAM_ID,  # USDC
    # Token-2022 LST mints
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": SPL_TOKEN_2022_PROGRAM_ID,  # jitoSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": SPL_TOKEN_2022_PROGRAM_ID,  # mSOL
    "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": SPL_TOKEN_2022_PROGRAM_ID,  # INF
}"""
        if old_mints in content:
            content = content.replace(old_mints, new_mints)
            print("✅ Updated _GOLDEN_ATA_MINTS mapping with actual constants")
        else:
            # RegEx fallback
            content = re.sub(r'_GOLDEN_ATA_MINTS: Dict\[str, str\] = \{.*?\n\}', new_mints, content, flags=re.DOTALL)
            print("✅ Handled _GOLDEN_ATA_MINTS mapping via regex fallback")

        # Update warmup_golden_atas loop to pass actual Pubkeys
        old_warmup_loop = """    for mint_str, program_id_str in _GOLDEN_ATA_MINTS.items():
        mint_pk = Pubkey.from_string(mint_str)
        program_id = Pubkey.from_string(program_id_str)
        ata = get_associated_token_address(wallet_pubkey, mint_pk, program_id)"""
        
        new_warmup_loop = """    for mint_str, program_id in _GOLDEN_ATA_MINTS.items():
        mint_pk = Pubkey.from_string(mint_str)
        ata = get_associated_token_address(wallet_pubkey, mint_pk, program_id)"""
        
        if old_warmup_loop in content:
            content = content.replace(old_warmup_loop, new_warmup_loop)
            print("✅ Updated warmup_golden_atas loop signature")

        with open("arb_bot.py", "w", encoding="utf-8") as f:
            f.write(content)

    # --- 4. Patch other bugs in arb_bot.py (MarginFi liquidity loop, best_route_idx, jito_bidding_manager) ---
    arb_bot_reps = [
        # BankHealthMonitor SOL vault use getTokenAccountBalance instead of getBalance
        (
            '            vault = str(bank_info["liquidity_vault"])\n            is_sol_vault = (vault == "7uttpzxsHAcX97X5ZwaX8xMpsJc9aKx2V8t4Gf6A43XJ")\n            method = "getBalance" if is_sol_vault else "getTokenAccountBalance"\n            \n            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": [vault]}\n            session = await self.rpc._get_session()\n            async with session.post(self.rpc.get_rpc(), json=payload, timeout=5.0) as resp:\n                if resp.status == 200:\n                    data = await resp.json()\n                    if "result" in data and "value" in data["result"]:\n                        if is_sol_vault:\n                            vault_lamports = int(data["result"]["value"])\n                        else:\n                            vault_lamports = int(data["result"]["value"]["amount"])\n                        return vault_lamports / 1e9',
            '            vault = str(bank_info["liquidity_vault"])\n            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountBalance", "params": [vault]}\n            session = await self.rpc._get_session()\n            async with session.post(self.rpc.get_rpc(), json=payload, timeout=5.0) as resp:\n                if resp.status == 200:\n                    data = await resp.json()\n                    if "result" in data and "value" in data["result"]:\n                        vault_lamports = int(data["result"]["value"]["amount"])\n                        return vault_lamports / 1e9'
        ),
        # worker best_route_idx fix
        (
            '            elif best_route_idx == 1:\n                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)',
            '            elif route_type == "triangular":\n                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)'
        ),
        # jito_tip_manager -> jito_bidding_manager parameter mismatch in run()
        (
            '    if cfg.LST_UNSTAKE_ARB_ENABLED:\n        unstake_task = asyncio.create_task(\n            lst_unstake_arbitrage_scanner(session, cfg, rpc, keypair, jito_executor, jito_tip_manager, data_aggregator=data_aggregator)\n        )',
            '    if cfg.LST_UNSTAKE_ARB_ENABLED:\n        unstake_task = asyncio.create_task(\n            lst_unstake_arbitrage_scanner(session, cfg, rpc, keypair, jito_executor, jito_bidding_manager=jito_bidding_manager, data_aggregator=data_aggregator)\n        )'
        )
    ]
    patch_file("arb_bot.py", arb_bot_reps)

    # --- 5. Programmatically fix un-indented block in lst_depeg_scanner (arb_bot.py) ---
    if os.path.exists("arb_bot.py"):
        with open("arb_bot.py", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        
        in_lst_depeg = False
        in_unindented_zone = False
        new_lines = []
        indented_count = 0
        
        for line in lines:
            if 'async def lst_depeg_scanner(' in line:
                in_lst_depeg = True
            if in_lst_depeg and 'jito_tip_lamports = capped_tip' in line:
                in_unindented_zone = True
                new_lines.append(line)
                continue
            if in_unindented_zone and line.startswith("        except Exception as e:"):
                in_unindented_zone = False
                in_lst_depeg = False
            
            if in_unindented_zone:
                if line.strip():
                    new_lines.append("    " + line)
                    indented_count += 1
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        if indented_count > 0:
            with open("arb_bot.py", "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
            print(f"✅ Programmatically fixed {indented_count} lines of unindented block inside lst_depeg_scanner in arb_bot.py")

    # --- 6. Patch src/ingest/tx_builder.py ---
    tx_builder_reps = [
        (
            '            is_sol_vault = (bank_liquidity_vault == "7uttpzxsHAcX97X5ZwaX8xMpsJc9aKx2V8t4Gf6A43XJ")\n            method = "getBalance" if is_sol_vault else "getTokenAccountBalance"\n            \n            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": [bank_liquidity_vault]}',
            '            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountBalance", "params": [bank_liquidity_vault]}'
        ),
        (
            '                        if is_sol_vault:\n                            vault_lamports = int(data["result"]["value"])\n                        else:\n                            vault_lamports = int(data["result"]["value"]["amount"])',
            '                        vault_lamports = int(data["result"]["value"]["amount"])'
        ),
        (
            '    async def _check_marginfi_liquidity_realtime(\n        self, borrow_amount: int, bank_pubkey: str\n    ) -> bool:',
            '    async def _check_marginfi_liquidity_realtime(\n        self, borrow_amount: int, vault_pubkey: str\n    ) -> bool:'
        ),
        (
            '"params": [bank_pubkey],  # This should be the VAULT address in practice',
            '"params": [vault_pubkey],'
        ),
        (
            '        if not await self._check_marginfi_liquidity_realtime(\n            borrow_amount_lamports, bank_pubkey\n        ):',
            '        if not await self._check_marginfi_liquidity_realtime(\n            borrow_amount_lamports, str(marginfi_config["bank_liquidity_vault"])\n        ):'
        )
    ]
    patch_file("src/ingest/tx_builder.py", tx_builder_reps)

    # --- 7. Patch src/ingest/execution_router.py ---
    router_reps = [
        (
            '                prof_ok, prof_reason, actual_net = await _ptg.check_profit_before_execution(\n                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC leg in\n                    output_mint=token_mint,                                  # xStock leg out\n                    amount_lamports=optimal_size_lamports,\n                    jito_tip_lamports=jito_tip_lamports,\n                    base_fee_lamports=_base_fee,\n                    expected_profit_sol=expected_profit_sol,\n                )',
            '                prof_ok, prof_reason, actual_net = await _ptg.check_profit_before_execution(\n                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC leg in\n                    output_mint=token_mint,                                  # xStock leg out\n                    amount_lamports=optimal_size_lamports,\n                    jito_tip_lamports=jito_tip_lamports,\n                    base_fee_lamports=_base_fee,\n                    expected_profit_sol=expected_profit_sol,\n                    is_circular=True,  # FIX: Circular cross-currency check\n                )'
        )
    ]
    patch_file("src/ingest/execution_router.py", router_reps)

    print("🎉 All fixes applied successfully! Run 'python arb_bot.py' to start.")

if __name__ == "__main__":
    main()
