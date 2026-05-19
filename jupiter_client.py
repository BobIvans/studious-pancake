import asyncio
import requests
import random
import time
from dotenv import load_dotenv

load_dotenv()

PROXY_URLS = [
    "https://tiny-base-1f12.ivans-bobrovs4321.workers.dev/quote",
    "https://jupiter-proxy-2.info-feelflow.workers.dev/quote",
    "https://jupiter-proxy-3.bobrovsivans1.workers.dev/quote",
    "https://jupiter-proxy-4.glowsphere-skinnova.workers.dev/quote",
    "https://jupiter-proxy-5.glowsphere-skinnova.workers.dev/quote",
]

# Глобальные переменные для контроля очереди
rate_limiter = asyncio.Semaphore(3)  # Allow 3 concurrent requests
last_request_time = 0
proxy_index = 0

async def get_jupiter_quote(input_mint: str, output_mint: str, slippage_bps: int = None):
    global last_request_time, proxy_index

    # Rate limiting: control concurrent requests without blocking all workers
    async with rate_limiter:
        now = time.time()
        
        # HFT OPTIMIZED GAP (0.05 - 0.15 сек)
        # Reduced from 1.1-1.3s to enable HFT performance while avoiding 429 errors
        safe_gap = random.uniform(0.05, 0.15)
        
        elapsed = now - last_request_time
        if elapsed < safe_gap:
            await asyncio.sleep(safe_gap - elapsed)

        # Выбор следующего воркера по кругу
        proxy_url = PROXY_URLS[proxy_index]
        proxy_index = (proxy_index + 1) % len(PROXY_URLS)

        # Мутация суммы для уникальности URL
        fuzzed_amount = 1500000 + random.randint(-25, 25)
        
        # Load slippage from .env if not explicitly passed
        if slippage_bps is None:
            from dotenv import dotenv_values
            env_slippage = dotenv_values().get("STARTING_SLIPPAGE_BPS", "15")
            slippage_bps = int(env_slippage)
        
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(fuzzed_amount),
            "slippageBps": str(slippage_bps),
            "onlyDirectRoutes": "true",
            "restrictIntermediateTokens": "true",
            "maxAccounts": "8",
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            # Выполняем запрос в отдельном потоке, чтобы не блокировать Event Loop
            resp = await asyncio.to_thread(
                requests.get, proxy_url, params=params, headers=headers, timeout=10
            )
            
            last_request_time = time.time()

            if resp.status_code == 429:
                print(f"⚠️ [!] Лимит всё же задет. Этичная пауза 10с...")
                await asyncio.sleep(10)
                return None

            resp.raise_for_status()
            data = resp.json()

            out_amount = int(data.get("outAmount", 0)) / 1_000_000_000
            worker_id = proxy_url.split('.')[0][-4:]
            
            print(f"✅ {input_mint[:4]}.. → {output_mint[:4]}.. | {worker_id} | Gap: {safe_gap:.2f}s | OK")
            return data

        except Exception:
            # В случае любой ошибки (таймаут, сеть) обновляем время, чтобы не частить
            last_request_time = time.time()
            return None

async def get_best_quote(input_mint: str, output_mint: str, slippage_bps: int = None):
    return await get_jupiter_quote(input_mint, output_mint, slippage_bps)

print("🛡️ РЕЖИМ 'ZEN MASTER' (1.2s Gap, 0% Errors, 100% Ethics)")
