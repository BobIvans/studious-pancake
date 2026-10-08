# R-01 reconciliation gate -> R-02 live flash-capital readers (R&D)
Date: 2026-10-08 | Base audited: main 103c13795f1d2ac1fa88cf02bba1e9bb2e2477cf

**Status: specification only, no implementation or live lender observations.** This package was prepared after inspecting repository files and the official protocol documentation. The specific SHA and GitHub compares are point-in-time observations, not permissions for live execution.

## Most important finding
PR #579 (RCN-00) already restored stacked QPR-01/02/03, GPR-01/02/03 and UXE documentation into main. PRs #580 DIN-00, #581 DIN-02, #582 DIN-01 are also merged into main. Do **not** re-merge the old large integration branches. R-01 is now a verification/one-commit-disposition gate, not a second wholesale integration.

**No-margin-account-first policy:** First qualify Jupiter Lend, Kamino and NAVI; allow Project 0 only where a previously initialized marginfi/P0 account is present or an explicit later rent budget has been approved. Even zero protocol flashloan fees do not imply gas-free, ATA-free or account-creation-free transactions.

## Reading order
1. MASTER_CONTEXT.md — verified owners and important code gap.
2. R01_BRANCH_RECONCILIATION.md — mandatory before R-02 edits.
3. PROVIDER_SELECTION.md + PROVIDER_CATALOG.json — select account-light lenders.
4. R02_ARCHITECTURE.md — exact read-only adapters, schema, evidence, integration boundaries.
5. R02_TESTS_AND_EXIT_GATES.md — offline, live-read and no-signing acceptance criteria.
6. CODEX_START_HERE.md — executable Codex assignment and PR division.
7. CAPITAL_SNAPSHOT_EXAMPLE.json — **synthetic NEGATIVE example only**, not live evidence.

## Principle
Research graph remains broad; real capital hubs are separately qualified. Borrow-capacity observation is not transaction authority. R-02 has **no signing, no sending, no account creation, no borrowing**; R-03/R-05 later cover protocol builders and full exact simulation.


## 2026-10-08 offline-first source audit update
This directory now includes `offline/`: four locally readable protocol/architecture dossiers plus source ledger, verified upstream Git commit/version pins, 27-option provider selector and dependency-free offline checker. It does **not** mirror every upstream web page or certify the current chain state. Codex must be able to complete its design work and deterministic negative tests with zero documentation web access, and must report missing on-chain/SDK evidence honestly.
