# FlashLoan Arbitrage Bot

Автоматический arbitrage бот для Solana с использованием MarginFi flash loans и Jupiter DEX агрегации. Бот выполняет высокопроизводительные arbitrage сделки в реальном времени.

## Reproducible offline baseline

The supported runtime for CI, Docker, and local verification is Python 3.13. A clean checkout can be validated without Solana mainnet, external APIs, private keys, Jito, or live transaction submission.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
make verify
```

`make verify` runs dependency validation, syntax compilation, import smoke tests, and offline pytest with sockets disabled. It intentionally does not run paper trading, live simulation, or live trading readiness checks. Use `make test-live` only when deliberately running tests marked `live` with real external services.

Safe verification defaults are:

```bash
PAPER_TRADING_ONLY=true
LIVE_TRADING_ENABLED=false
JITO_ENABLED=false
KAMINO_LIQUIDATION_ENABLED=false
```

## Основные возможности

- 🚀 **MarginFi Flash Loans** - Бесплатные flash loans для arbitrage
- ⚡ **Jupiter DEX Aggregation** - Лучшие цены через все DEX
- 📦 **Jito Bundle Execution** - Высокоскоростное выполнение транзакций
- 🛡️ **Risk Management** - Защита от убытков и rate limiting

## Системные требования

### MacOS (M1/M2/M3 чипы)
- **Python 3.13+** с исправлениями для aiohttp дескрипторов
- **Синхронизация времени**: Обязательно включите автоматическую синхронизацию времени для предотвращения slot drift:
  ```
  Системные настройки → Дата и время → Выключить/включить "Выставлять время автоматически"
  ```
  Это предотвратит ошибки Jito BlockhashNotFound из-за дрейфа системных часов.

## Быстрый старт

1. **Настройка:**
    ```bash
    ./setup_flashloan.sh
    ```

2. **Заполните .env:**
    ```bash
    MARGINFI_ACCOUNT=ваш_marginfi_аккаунт
    HELIUS_API_KEY=ваш_helius_api_key
    ```

3. **Настройка Helius Webhook (для LST arbitrage):**
    ```bash
    python setup_helius_webhook.py
    ```

4. **Запуск:**
     ```bash
     python arb_bot.py
     ```

 4. **Симуляция сделок (тестирование):**
    ```bash
    make paper
    ```

 5. **Запуск тестов:**
    ```bash
    make verify
    ```

## Архитектура

### Компоненты:
- **Matrix Scanner** - Бесконечный цикл поиска circular arbitrage routes
- **MarginFi Integration** - Flash loan provider
- **Jupiter DEX** - Swap execution
- **Jito Bundles** - High-speed execution
- **Transaction Prebuilder** - Оптимизация Compute Units и Priority Fees
- **Helius Webhook Handler** - Real-time LST arbitrage detection
- **Data Aggregator** - Comprehensive event logging and analytics

## Helius Webhook Integration

Бот поддерживает real-time webhook от Helius для обнаружения LST arbitrage возможностей через Sanctum Router.

### Настройка Webhook:

#### Вариант 1: Автоматическая настройка (Рекомендуется)
```bash
# Установите ваш Helius API key в .env
echo "HELIUS_API_KEY=your_helius_api_key_here" >> .env

# Опционально установите ваш webhook URL
echo "WEBHOOK_URL=https://your-domain.com/webhook" >> .env

# Запустите скрипт настройки
python setup_helius_webhook.py
```

Скрипт автоматически:
- Создаст webhook через Helius API
- Сохранит webhook ID в `helius_webhook_id.txt`
- Сохранит конфигурацию в `helius_webhook_config.json`

#### Вариант 2: Ручная настройка через Dashboard
1. **Создайте webhook в Helius Dashboard:**
   ```json
   {
     "webhookURL": "https://your-domain.com/webhook",
     "webhookType": "enhanced",
     "transactionTypes": ["SWAP", "TRANSFER"],
     "accountAddresses": [
       "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",  // Sanctum Router
       "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  // JitoSOL
       "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  // mSOL
       "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  // bSOL
       "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"   // Sanctum Infinity (INF)
     ],
     "txnStatus": "all"
   }
   ```

2. **Настройте .env:**
   ```bash
   HELIUS_WEBHOOK_ENABLED=true
   WEBHOOK_PORT=3000
   ```

3. **Webhook Endpoint:**
   - URL: `http://your-server:3000/webhook`
   - Method: POST
   - Бот автоматически обрабатывает входящие события

### Что отслеживает webhook:
- SWAP транзакции через Sanctum Router
- TRANSFER токенов между LST и SOL
- Балансовые изменения в аккаунтах
- Price impact сигналы от крупных транзакций

### Управление webhook:
```bash
# Проверить статус всех webhook
python manage_webhooks.py

# Создать/проверить webhook
python setup_helius_webhook.py

# Протестировать конфигурацию
python test_webhook_config.py
```

### Аналитика webhook данных:
```python
# Получить статистику webhook событий
stats = await data_aggregator.get_webhook_opportunity_stats()

# Получить LST arbitrage возможности
opportunities = await data_aggregator.get_lst_arbitrage_opportunities()
```

### Webhook IDs и управление:
- **Webhook IDs**: <YOUR_HELIUS_WEBHOOK_ID_1>, <YOUR_HELIUS_WEBHOOK_ID_2>
- **Management IDs**: <YOUR_HELIUS_MANAGEMENT_ID_1>, <YOUR_HELIUS_MANAGEMENT_ID_2>
- **Мониторятся адреса**: JitoSOL, mSOL, bSOL, INF, Sanctum Router

## Безопасность

- **Rate Limiting** - Ограничение по стратегиям и токенам
- **Profit Thresholds** - Минимальные требования к прибыли
- **Token Blacklist** - Исключение подозрительных токенов
- **Simulation Mode** - Тестирование перед реальным выполнением
- **Paper Trading** - Полная симуляция сделок без риска
- **Max Drawdown** - Защита от больших потерь

## Симуляция и тестирование

### Режимы симуляции:

1. **Встроенная симуляция** - `arb_bot.py` по умолчанию симулирует транзакции перед выполнением
2. **Paper Trading** - Полная симуляция arbitrage без реальных транзакций:
   ```bash
   make paper
   ```
3. **Тестирование компонентов**:
   ```bash
   make verify
   ```

### Переменные окружения для симуляции:
- `SIMULATE_BEFORE_EXECUTE=true` - Симуляция перед выполнением (по умолчанию)
- `PAPER_STARTING_BALANCE_SOL=1.0` - Начальный баланс для paper trading
- `PAPER_MAX_ARBITRAGES=5` - Максимум одновременных arbitrage

## Разработка

### Структура проекта:
```
├── arb_bot.py                     # Основной бот
├── paper_trader.py                 # Симуляция сделок
├── test_runner.py                  # Тестовый runner
├── setup_helius_webhook.py         # Автоматическая настройка webhook
├── manage_webhooks.py              # Управление webhook через API
├── helius-sanctum-lst-webhook.json # Шаблон конфигурации webhook
├── test_webhook_config.py          # Тест конфигурации webhook
├── src/
│   ├── ingest/
│   │   ├── tx_builder.py           # Jupiter интеграция
│   │   ├── jito_bundle_client.py   # Jito execution
│   │   ├── data_aggregator.py      # Логирование и аналитика
│   │   ├── helius_webhook_handler.py # Обработчик webhook
│   │   ├── leader_tracker.py       # Отслеживание лидеров слотов
│   │   ├── execution_router.py     # Гибридное выполнение
│   │   └── webhook_config.py       # Конфигурация webhook IDs
├── trading/                        # Система paper trading
│   ├── position_book.py            # Управление позициями
│   ├── flash_loan_executor.py      # Executor flash loans
│   └── trade_logger_v2.py          # Логирование сделок
├── programs/                       # Anchor контракты
├── docs/                           # Документация
└── scripts/                        # Скрипты настройки
```

## Лицензия

MIT License
