# Copy-ready agent assignments — whole project

## Lead / coordinator — MASTER-00
Read `CODEX_START_HERE.md` and `MASTER_00_RECONCILIATION.md`. Do source archive ingestion, current-main registry/status reconciliation, pair delta, owner map, PR dependency inventory and interface freeze. No broad application code, no auto-merges.

## Agent A — P0-1 (reuse #593, do not duplicate)
Inspect open #593 patch and current main. Rebase/review that branch against current main, resolve real conflicts and preserve the single Dynamic Universe/source-intake owner. Verify pagination/cadence/partial snapshot/complete snapshot/dedupe/identity and platform constraints with offline tests. No live reads unless a separate bounded, admitted campaign is explicitly part of the task and authorized by the user.

## Agent B — P0-2 Jupiter V2 + 0x comparable quote capture
Update existing GPR-02 quote owner from Jupiter V1 path to current Jupiter Swap API V2. Pin API schema, auth/rate limit/error docs. Match canonical mints and identical exact base-unit input amount; record taker mode, route/leg identity, quote freshness, route source and pool/resource correlation; response replay fixture, timeout/429 negatives. Do not build/sign/send.

## Agent C — P0-3 direct-state venues
Keep Raydium CPMM native owner. In separate PRs implement Raydium CLMM (full tick/bitmap closure) and Meteora DLMM (active bin/bin arrays/dynamic fee/consumed input). Orca remains blocked unless legal license approval is explicit. Add current program/source pins, owner/genesis/finality, Token-2022 decisions, exact integer math and same-state replay. No TVL-as-depth.

## Agents D–G — R-02 CAP-A/B/C/D
Use `docs/roadmap/r02-capacity-recovery-2026-10-08/`. Produce live read-only resource snapshots. Never infer effective flash capacity from admin fee zero or a program account/checkpoint. P0 is protocol-bank-only by default; no margin account creation. All providers remain disabled if proof unavailable.

## Agent H — R03-00
Freeze the common `UnsignedExecutionPlan`/financing-evidence interface using existing canonical models. No transaction sender, signer, private key or account creation. Builder outputs stay inert and unsigned.

## Agents I–L — R03 protocol builders
Jupiter borrow/payback; Kamino flash borrow/repay with exact instruction-index and reserve fee semantics; NAVI PTB version/receipt/object dependencies; P0 only with verified existing account. Offline SDK conformance tests first. No live-capital claim until matching R-02 proof.

## Agent M — R09 Sui / TON / EVM / CEX / oracle
Research and add one source dossier per focused PR. Sui uses current gRPC/GraphQL/Core and checkpoint/object-version binding (no retired JSON-RPC). TON is discovery/async unless an atomic financing primitive is proven. EVM pins chain IDs, deployed bytecode/ABI, quote callback and flash capacity. CEX/oracle/reference data remain signal-only unless independently admitted.

## Agent N — R10 strategy expansion
Use `STRATEGY_CROSSWALK.json` and `STRATEGY_UNIVERSE_ATLAS.md`. Extend existing owners for stablecoin/redemption, LST/LRT/NAV, BTC wrappers, CLOB-vs-AMM, vault/Pendle/maturity, conditional hyperedges, liquidation/solvency, funding/carry, incentive/governance, blockspace, event/migration, CEX/oracle and cross-chain-flow strategies. Implement only the missing evidence adapters/relation generators and deterministic replay. All strategy-evolution packages remain disabled until their own qualification.

## Agent O — R11 platform and reproducibility
Establish Windows/WSL test baseline, remove platform blocker only with cross-platform tests, validate offline vendor/hash verifiers, install/build/package support, CI checks and deterministic replay. No weakening of socket-disabled or security gates.

## Agent P — R12 dependency security
Recheck current lockfiles and pip-audit advisories against supported Python/tool constraints. Upgrade pins through the canonical lock workflow, run tests and audit, and produce a minimal PR. No silent audit exclusions or unlocked dependencies.

## Shared requirement for every agent
Use separate worktree, branch from freshly fetched main, one owner/PR, exact source commit/license/ABI, tests actually run, evidence status, blockers and next dependency. Do not merge. Keep sign/send/live disabled and exclude tokenized equities.
