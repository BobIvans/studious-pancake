# MEV Bot Knowledge Base

## System Overview
High-frequency MEV arbitrage bot on Solana utilizing MarginFi flash loans and Jito bundles.

## Operational Constraints
- **Current Working Capital:** 0.015 SOL (Survival Phase)
- **Minimum Reserve (Gas/Rent):** 0.003 - 0.005 SOL (Configured via `MIN_RESERVE_SOL` in `.env`)
- **Maneuver Budget:** 0.010 - 0.012 SOL (Dynamic, available for Jito tips and ATA rent)

## Critical Formats
- **MarginFi Account:** Base58 Solana Pubkey (32-44 alphanumeric characters).
- **Transaction Flow:** 
  1. ComputeBudget 
  2. MarginFi Borrow 
  3. Swap Leg 1 
  4. Swap Leg 2 (or more) 
  5. MarginFi Repay 
  6. Jito Tip (Final instruction for capital protection)

## Helius Webhook Integration
| Webhook ID | Events Monitored | Purpose |
|------------|----------------|---------|
| `d0f65273-6427-48fc-b3cf-b70af928b0fc` | ADD_LIQUIDITY | Liquidity Sniping (High Priority) |
| `27b50030-0a6c-4c2a-89f4-a7bd8c9ba618` | CREATE_POOL | Liquidity Sniping (High Priority) |
| `19de5b19-33d0-4c4c-9ad8-6f5194264a6b` | SWAP, TRANSFER | General Arbitrage Signals |

## Core Logic Modules

### Dynamic Sizing 1.0
- **Goal:** Maximize profit while protecting the 0.015 SOL balance.
- **Mechanism:** Calculates `amount_in` based on `virtual_balance`.
- **ATA Rent Deduction:** Automatically subtracts **0.00204 SOL** from expected profit for each new ATA required (checked via `ATA_CACHE`).
- **Safety Cap:** `FLASH_LOAN_SIZE_SOL` serves only as an absolute upper limit.

### Smart Retry
- **Trigger:** Simulation failure (pre-flight check).
- **Slippage Error:** Maintanly reduces `borrow_amount` by 50% and retries (1 attempt).
- **Account/Rent Error:** Rebuilds route with `onlyDirectRoutes=True` and `restrictIntermediateTokens=True` to minimize rent costs.

### Double Check (Simulation Failure)
- If simulation fails due to liquidity or slippage, the bot re-calculates the optimal size (reducing by 50%) and performs one final retry before abandoning the opportunity.

### High-Priority Webhook Routing
- **Trigger:** Webhook ID matches `SNIPER_IDS` (Liquidity Sniping).
- **Mechanism:** Assigns a score of **100.0** (max priority) to the opportunity.
- **Goal:** Minimize latency for market-entry signals (new liquidity/pools).

## HFT Hardening (0.015 SOL Survival)

### Token-2022 Rent Trap Protection
- **Standard Rent:** 0.00204 SOL.
- **Token-2022 Rent:** 0.0035 SOL (e.g., xStocks/RWA).
- **Logic:** Precisely budgets for the higher rent; aborts trade if `Profit - Rent - Gas <= 0`.

### Stale Quote Guard
- **TTL:** 1.5 seconds.
- **Mechanism:** Aborts execution if the Jupiter quote is older than 1.5s to prevent slippage reverts.

### Safe Dust Sweeper
- **Priority Fee:** Reduced to **20,000 micro-lamports** (0.000002 SOL).
- **Fail Tracker:** Blacklists any ATA address after **2 consecutive failures** to prevent repeated gas burn.
- **Safety:** Skips Token-2022 accounts with hidden extension balances.

### Jito Tip Floor Guard
- **Logic:** Aborts micro-trades (Profit < 0.0005 SOL) if the required Jito tip floor exceeds 40% of the profit.

## HFT Micro-Mechanics (Final Hardening)

### ExactOut Repayment Guard
- **Problem:** AMM rounding can leave 1-2 lamports debt, causing MarginFi reverts.
- **Solution:** Final swap leg (e.g., LST -> SOL) is strictly requested as `ExactOut` with `amount = borrow_amount`.
- **Result:** 100% repayment guarantee; profit is collected as residual token or SOL difference.

### Jito-Native Blockhash
- **Mechanism:** Races blockhashes from Jito-specific RPCs and prioritizes them.
- **Goal:** Eliminates `BlockhashNotFound` errors at the Jito Block Engine level.

### Smart Pivot Trigger
- **Mechanism:** Monitors for `BankCapacityExceeded` or `BankUtilizationLimit` errors.
- **Adaptive Fallback:** Automatically switches flash loan asset (e.g., SOL -> USDC) using `FlashPivotEngine` to bypass protocol limits.

## Hybrid Mode (Testing & Validation)

### Webhook-Driven Paper Trading
- **Variable:** `PAPER_TRADING_ONLY=true`.
- **Mechanism:** Bot processes real-time Helius webhooks, builds full transactions, and runs RPC simulation.
- **Interception:** Execution is blocked just before Jito submission; results are logged to `paper_trading.db`.
- **Purpose:** Full end-to-end strategy validation on live data without capital risk.

## Health Monitoring
- **Endpoint:** `GET /health` returns `{"status": "alive"}`.
- **Port:** Configured via `WEBHOOK_PORT` (default 3000).
