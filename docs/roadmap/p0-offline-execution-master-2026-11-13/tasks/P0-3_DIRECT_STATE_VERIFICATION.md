# Codex task — P0-3: Exact direct-state verification for Raydium, Orca and Meteora

**Priority:** P0  
**Mode:** offline account-layout/quote implementation and fixtures first; bounded RPC reads are separate read-only qualification.  
**Technical baseline:** `docs/integrations/offline/solana-p0/DIRECT_STATE_RAYDIUM_ORCA_METEORA.md` and `SOLANA_RPC_STATE.md`.

## Assignment

Extend the existing direct-state verification pathway so it can independently verify supported Raydium CPMM/CLMM, Orca Whirlpools and Meteora DLMM pools and determine amount-specific reachable liquidity. Reuse existing canonical state/quote owners.

## Required sequence

1. Audit the current native Raydium CPMM decoder and its fixture coverage; keep it as canonical CPMM owner.
2. Add or complete Raydium CLMM state/account reader using pinned mainnet program ID, program source version, pool state, tick bitmap and initialized tick arrays.
3. Evaluate Orca only after license review. The current Orca source repository uses a custom license for code from 2025-02-27 onward. Until an authorized use path is documented, mark direct-state implementation `BLOCKED_LICENSE_REVIEW`; do not vendor code or SDK.
4. Add Meteora DLMM reader against pinned SDK/doc contract and supported pool/account versions: LbPair, bin arrays, bitmap extension, oracle/fee data and vaults.
5. For every pool prove owner/program ID, discriminator/version, account lengths, mint/vault bindings, token programs, decimals and Token-2022 extensions.
6. Read dependent accounts with slot coherence: pools, vaults, ticks, bin arrays, bitmaps and any oracle/fee config necessary for math. Reject stale or missing dependency accounts.
7. Implement exact-in math in integer/fixed-point arithmetic. CLMM must traverse initialized ticks; DLMM must traverse reachable bins and apply dynamic fee logic. CPMM must apply the current fee model/status flags. Total vault balances are not equivalent to depth at the active price.
8. Persist raw account hashes, provider/context slot, decoder version, all dependent account refs, state snapshot receipt and the exact amount-specific quote.
9. Differential test against upstream SDK/reference vectors only where license permits. Otherwise compare against independent, reviewed fixtures from public chain data and explicitly document the assurance gap.

## Mandatory negative fixtures

Wrong owner/program; wrong genesis; unknown discriminator; bad account length; wrong mint/vault; unsupported token program; Token-2022 extension mismatch; stale slot; inconsistent multi-account snapshot; pool paused; missing tick/bin array; bitmap says unavailable; zero/insufficient active liquidity; dynamic fee/rounding boundaries; amount that crosses multiple ticks/bins.

## Acceptance

- Every claimed supported venue/version has an offline decoder fixture and exact-in differential test.
- The decoder rejects unknown program versions and never returns a quote from incomplete tick/bin data.
- Amount-specific output changes appropriately across tick/bin boundaries and applies fees/transfer costs.
- A live read-only capture uses governed bounded RPC and produces replayable state evidence; no send/simulation requiring a signer.
- Indexed APIs cannot set `RPC_EXACT` or `EXECUTABLE`.
- Orca remains clearly blocked unless license permission is confirmed.
- No signer, sender, transaction submission, borrowing or production promotion is added.

## Deliverables

One reviewable PR (split by venue if necessary), decoder version matrix, account schema facts, fixture/provenance manifest, P0-3 report, focused replay and verifier commands, known unsupported account versions.
