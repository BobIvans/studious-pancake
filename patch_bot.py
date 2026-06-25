import os

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

# 1. Patch src/ingest/tx_builder.py
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

# 2. Patch src/ingest/execution_router.py
router_reps = [
    (
        '                prof_ok, prof_reason, actual_net = await _ptg.check_profit_before_execution(\n                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC leg in\n                    output_mint=token_mint,                                  # xStock leg out\n                    amount_lamports=optimal_size_lamports,\n                    jito_tip_lamports=jito_tip_lamports,\n                    base_fee_lamports=_base_fee,\n                    expected_profit_lamports=int(expected_profit_sol * 1e9),\n                )',
        '                prof_ok, prof_reason, actual_net = await _ptg.check_profit_before_execution(\n                    input_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",   # USDC leg in\n                    output_mint=token_mint,                                  # xStock leg out\n                    amount_lamports=optimal_size_lamports,\n                    jito_tip_lamports=jito_tip_lamports,\n                    base_fee_lamports=_base_fee,\n                    expected_profit_lamports=int(expected_profit_sol * 1e9),\n                    is_circular=True,  # FIX: Circular cross-currency check\n                )'
    )
]
patch_file("src/ingest/execution_router.py", router_reps)

# 3. Patch arb_bot.py basics
arb_bot_reps = [
    (
        '            vault = str(bank_info["liquidity_vault"])\n            is_sol_vault = (vault == "7uttpzxsHAcX97X5ZwaX8xMpsJc9aKx2V8t4Gf6A43XJ")\n            method = "getBalance" if is_sol_vault else "getTokenAccountBalance"\n            \n            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": [vault]}\n            session = await self.rpc._get_session()\n            async with session.post(self.rpc.get_rpc(), json=payload, timeout=5.0) as resp:\n                if resp.status == 200:\n                    data = await resp.json()\n                    if "result" in data and "value" in data["result"]:\n                        if is_sol_vault:\n                            vault_lamports = int(data["result"]["value"])\n                        else:\n                            vault_lamports = int(data["result"]["value"]["amount"])\n                        return vault_lamports / 1e9',
        '            vault = str(bank_info["liquidity_vault"])\n            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountBalance", "params": [vault]}\n            session = await self.rpc._get_session()\n            async with session.post(self.rpc.get_rpc(), json=payload, timeout=5.0) as resp:\n                if resp.status == 200:\n                    data = await resp.json()\n                    if "result" in data and "value" in data["result"]:\n                        vault_lamports = int(data["result"]["value"]["amount"])\n                        return vault_lamports / 1e9'
    ),
    (
        '            elif best_route_idx == 1:\n                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)',
        '            elif route_type == "triangular":\n                # Triangular route re-fetch: use restrictIntermediateTokens=false (2 calls instead of 3)'
    ),
    (
        '    if cfg.LST_UNSTAKE_ARB_ENABLED:\n        unstake_task = asyncio.create_task(\n            lst_unstake_arbitrage_scanner(session, cfg, rpc, keypair, jito_executor, jito_tip_manager, data_aggregator=data_aggregator)\n        )',
        '    if cfg.LST_UNSTAKE_ARB_ENABLED:\n        unstake_task = asyncio.create_task(\n            lst_unstake_arbitrage_scanner(session, cfg, rpc, keypair, jito_executor, jito_bidding_manager=jito_bidding_manager, data_aggregator=data_aggregator)\n        )'
    )
]
patch_file("arb_bot.py", arb_bot_reps)

# 4. Programmatic Indentation of Steps 4-7 inside lst_depeg_scanner (arb_bot.py)
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
                # Add 4 spaces of indentation
                new_lines.append("    " + line)
                indented_count += 1
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if indented_count > 0:
        with open("arb_bot.py", "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        print(f"✅ Indented {indented_count} lines inside lst_depeg_scanner in arb_bot.py")
