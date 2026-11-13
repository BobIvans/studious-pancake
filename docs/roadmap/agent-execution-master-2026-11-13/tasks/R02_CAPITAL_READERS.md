# Assignment — R-02 Live Capital Readers (R02-CAP-A/B/C/D)

Copy/paste trigger: Continue R-02 only. R-01 is complete (#584); do not redo it. Read the merged #585 blocker receipt and #586 offline SDK pack, current CODEX_START_HERE.md, R02_UNBLOCK_MATRIX.md and R02_ACCEPTANCE.md. Audit current main/code owners, run both offline verifiers, then implement one reader PR at a time for Jupiter Lend, Kamino, NAVI and wallet-optional Project 0. Use governed read-only transports and exact deployed resource state. Never infer capacity from admin flags, an off-chain list, TVL, vault cash or documentation fees. Prove resource identity, owner/package, mint/coin type, decimals, effective cap, fee and rounding, availability, liabilities, freshness and independent provenance at one rooted slot/checkpoint. Emit positive FlashCapitalEdge only when every required field is proven; otherwise preserve typed negative evidence. Use existing QPR/DIN governance, FlashCapitalGraph and resolver; do not add a second graph. No account creation, ATA creation, signing, sending, borrowing or spend. Return exact evidence, offline replay, tests and blockers in a review-only PR.

## CAP-A — Jupiter Lend
- Use docs/roadmap/r02-capacity-recovery-2026-10-08/offline/jupiter_token_reserve_layout.json and its 192-byte/17-field IDL facts.
- Derive the TokenReserve PDA from the reviewed mint and pinned Liquidity program; verify owner/discriminator/length/layout.
- Read reserve, mint, SPL vault, vault token-account owner/mint/token program, applicable flashloan position/limits and any borrower/debt ceiling state at one finalized/rooted context.
- Determine effective available amount from program constraints, utilization, caps and liabilities; raw vault balance is not enough.
- Read fee from authoritative deployed state; admin fee=0 in #585 is not reserve capacity proof.
- Add narrow Jupiter Lend graph allowance only after full evidence and independent quorum.

## CAP-B — Kamino
- Use pinned @kamino-finance/klend-sdk@13.0.2 generated code under the merged offline pack, not the prefix probe as a full decoder.
- Decode complete Reserve and LendingMarket, LastUpdate, reserve status/config, mint, supply/fee vault, token program, totalAvailableAmount, flash fee flashLoanFeeSf / 2^60, caps, oracle/health eligibility and rounding using exact official SDK math.
- Read supply vault balances and dependencies at coherent slot; validate program and market identities.
- Prove flash borrow/repay semantics separately from standard obligation borrow; do not create an Obligation.

## CAP-C — NAVI
- Use @naviprotocol/lending@2.0.12 pinned source.
- getAllFlashLoanAssets is off-chain API discovery, never an on-chain capacity proof.
- Resolve exact current package/config/pool/shared objects, coinType and decimals through governed Sui gRPC/GraphQL at a recorded checkpoint. Sui legacy JSON-RPC is not an allowed fallback.
- Read object versions/digests, fee/capacity and all PTB-required dependencies. Record the verified v1/v2 package version; do not assume from an old SDK sample.

## CAP-D — Project 0 / P0
- Begin with wallet-free bank enumeration and live bank tag/vault/status/limits.
- If an existing public authority/account is later explicitly provided, read it and verify authority/group/index/bank bindings; never derive absence from another wallet.
- Never call account initialization or account-creation methods. Without an existing account, report the bank-level capability separately from user eligibility.

## Reader exit contract
Per provider: source/version pin; chain genesis + slot/checkpoint; program/package/resource IDs; raw account/object hashes; decoded state; canonical asset identity; exact fee rational/rounding; effective borrow capacity; constraints/negative evidence; independent-source proof; replayable receipt; zero signer/sender imports. Status must distinguish PARTIAL_DECODED, LIVE_READ_PROVEN and BLOCKED_LIVE_STATE. A code PR must not claim all four readers ready if only one passed.
