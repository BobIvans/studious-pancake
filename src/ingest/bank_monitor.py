"""
FIX 268: Модуляризация BankHealthMonitor
Вынесен из arb_bot.py в отдельный модуль для уменьшения размера главного файла.
"""

import asyncio
import logging
import orjson
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger("BankMonitor")


class BankHealthMonitor:
    """Мониторинг здоровья банков (ликвидность vaults) через RPC."""

    def __init__(self, session: aiohttp.ClientSession, rpc_url: str):
        self.session = session
        self.rpc_url = rpc_url

    async def get_vault_liquidity(self, vault_address: str) -> float:
        """Получает текущую ликвидность банковского vault в SOL."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountBalance",
            "params": [vault_address],
        }
        try:
            async with self.session.post(
                self.rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)
            ) as resp:
                if resp.status == 200:
                    data = orjson.loads(await resp.read())
                    if "result" in data and "value" in data["result"]:
                        amount_str = data["result"]["value"].get("amount", "0")
                        decimals = data["result"]["value"].get("decimals", 9)
                        return float(amount_str) / (10 ** decimals)
        except Exception as e:
            logger.warning(f"Failed to query bank vault {vault_address[:8]}...: {e}")
        return 0.0

    async def check_multiple_vaults(self, vault_addresses: Dict[str, str]) -> Dict[str, float]:
        """Проверяет ликвидность нескольких vaults параллельно."""
        results = {}
        tasks = []
        for name, addr in vault_addresses.items():
            tasks.append(self.get_vault_liquidity(addr))
        
        if tasks:
            liquiities = await asyncio.gather(*tasks, return_exceptions=True)
            for i, (name, _) in enumerate(vault_addresses.items()):
                val = liquiities[i]
                results[name] = val if isinstance(val, float) else 0.0
        
        return results
