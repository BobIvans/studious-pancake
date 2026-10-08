# Offline truthfulness / documentation gaps
Date 2026-10-08. This R&D verifies selected official docs and source repository versions. **It does NOT mean every provider's full documentation/IDL/source tree has been read, mirrored, or live-qualified.**

## Found / verified
- Jupiter official docs include flash API signature, zero flash fee claim, borrow/custom/payback ordering and transaction fees on failure. Pinned docs repository SHA; repo already has a source-pinned admin decoder, but not yet deployed live-capital proof.
- Kamino pinned Rust source demonstrates flash instruction account lists and index tracking; no obligation account is specified for those flash primitives, while reserve-level fees **can** apply. Official klend-sdk source SHA and package v13.0.2 recorded.
- Project 0 official docs explicitly show marginfi account PDA creation + direct transaction ordering and zero flash fee.
- NAVI docs specify modular flash API, asset max/fee fields; legacy navi-sdk repo is deprecated. Deployed full package layout not included in this kit.
- DeepBook official SDK documents pool borrow/repay pairs; fee/cap deployment-specific.
- Scallop fee docs 0.1%, new SDK v5.4.1, read-only query. SDK may sign/send if using Client write methods. Do not use those for R-02.
- Morpho Blue contract flash method and no protocol fee; Euler EVault flash and fee-changing hooks; Aave premium variable; Uniswap V2/V3 and DODO/Pancake V3 pool flash; Instadapp is aggregator, not capital.

## Still UNVERIFIED and must be blockers when needed
1. **Actual live bank/reserve/pool capacity** and fees at a named current slot/checkpoint for any of the providers. No real lender RPC request made for this R&D. If Codex lacks RPC, create no positive live-capital receipt.
2. Jupiter exact active deployed liquidity token reserve's full layout and mint-to-resource link beyond existing code. Need pinned SDK/IDL or locally installed sdk plus governed chain reads.
3. Kamino fee/reserve limit decoding at a named live reserve and validated account owner/code state. Pinned source is available via its SHA only if already checked out; our offline summary alone cannot serve as binary IDL for every deployed reserve.
4. NAVI full live package addresses, per-asset detailed fee configuration, decimals and dynamic shared pool state; source repo stub does not prove package.
5. Project 0 wallet-specific preexisting account and real dynamic banks, initial ATA/rent if absent; there is deliberately no wallet private key.
6. DeepBook pool cap/fee/contention at current checkpoint. JS docs use number for amounts; require exact unit conversion.
7. Scallop/Cetus/Suilend/Bucket exact deployed flash ABI and all pool/per-route costs; Suilend UI flow is not a general SDK.
8. EVM user-deployed receiver contract, chain deployments, RPC gas and live capacity. Morpho zero premium and Euler core zero fee do not remove receiver deployment costs.
9. Current supported assets/mints and business logic per chain. No hardcoded static fee/cap/mints are authority.
10. Full documentation redistribution licenses. This bundle contains original summaries plus cited short signatures and source links, **not unlicensed copies of every documentation page**.
11. Maker DSS Flash/Pancake V2/SparkLend latest live deployment and fee; disabled research only. Fluid DEX flash accounting not yet a proven generic flash-capital loan interface.
12. Save/Solend docs explicitly warn prior flash implementation limited; cannot qualify from source symbol alone.

## Environment failure fallback
No internet to documentation: read SOURCE_LEDGER.json + dossiers, use local repo code and installed dependency source **only if verified matching SHA/version**. If the code needs unsupported real ABI fields, submit a narrow blocker report for that provider, do not guess. Other independent providers can be implemented in separate worktrees when their evidence complete.

No external RPC: implement decoder contract tests, mock protocol owner/mint/fee negatives and deterministic replay. Mark `BLOCKED_LIVE_STATE` and exclude live edges. Offline fixture does not count as a positive real protocol snapshot.
