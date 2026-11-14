# W6-12 — Observed participant strategy intelligence and evidence graph

**Class:** RESEARCH_ONLY / INTEL.  
**Purpose:** extend Market Ecology with a disciplined method to learn from successful public on-chain trading behaviour, protocol interactions and market episodes. Discover reusable strategy archetypes and measurable decision rules; do not identify people or blindly copy wallet trades.

## 0. Gap and scope

W6-01/02 cover participant archetype IR and population calibration; W6-05/06 cover benign competition, survival and bounded PSRO/self-play. The prior parallel research asked for a knowledge graph of successful public on-chain traders and behaviour. The missing end-to-end chain is:

public protocol activity -> pseudonymous participant episodes -> strategy hypothesis/archetype -> net outcome attribution -> counterfactual replay -> held-out evaluation -> advisory strategy contract.

W6-12 closes this gap by extending existing owners. It is not a wallet tracker for identifying real people, an execution strategy, or permission to use private orderflow.

## 1. Data and privacy boundary

Use only public chain data, documented protocol/indexer outputs and expressly authorized datasets. Keep wallet/account identifiers as pseudonymous public-chain technical keys for reproducibility; do not attempt real-world identity resolution, deanonymization, doxxing, social graph inference, or linking to personal accounts. Do not process leaked/private orderflow, private group chats, compromised keys or non-consented personal data.

Every source must record official endpoint/schema/SDK revision, retrieval timestamp, license/data rights and quota; canonical chain/account/program/protocol identity and source independence/correlation; raw receipt hash, slot/checkpoint, finality/fork/reorg status; data completeness/censoring; and auditable retention/redaction policy. Unknown rights, history or transaction semantics remain BLOCKED/RESEARCH_ONLY.

## 2. Participant episode model — reuse existing evidence owners

Reuse:
- `src/market_data_evolution/contracts.py` (MarketEpisode and replay/provenance contracts);
- existing `src/agg02/` raw journal / DatasetReplayReader;
- `src/market/observations.py`, `src/market/streams.py` and correction/retraction/watermark semantics;
- `src/intelligence/episode_builder.py` and existing decision dataset/ranker;
- `src/mechanism_discovery/` claims, research quality, causal twin and benchmark owners;
- `src/research/correlation_ledger/` for residual/lead-lag context only.

Do not build a second raw market database, feature store, event journal, wallet graph or strategy registry.

Episodes preserve pseudonymous actor/account key and scope; ordered transactions/instructions/events with slot/checkpoint/signature/event hash and finality; positions, collateral, inventory, LP rights, borrow/repay and fees; before/after market states and exact pool/book identities; external transfers separately from trading PnL; fees/gas/priority/rebates/funding/borrow/rent; failed/reverted transactions and residual inventory; and explicit missing-history/censoring/source-confidence fields.

Never call gross token balance change “profit” without accounting for transfers, inventory, liabilities, fees and unrealized positions.

## 3. Strategy archetype discovery

Candidate archetypes, only where public protocol semantics permit observation:
- direct/fragmented/multi-hop arbitrage;
- LST/NAV/issuer-redemption basis;
- liquidation/repay/unwind and collateral migration;
- LP entry/exit/fee collection/range shift;
- market making / inventory management / hedge;
- lending-rate refinance or multi-period carry;
- launch/migration/curve graduation;
- orderbook liquidity provision, RFQ/intent participation and auction bidding;
- bridge/chain rebalancing and basis inventory.

Each is a versioned hypothesis with state preconditions, observed action pattern, economic mechanism, settlement class, risk/capital requirement, falsifiable null and typed evidence gates. An archetype is not an executable Opportunity.

## 4. Outcome attribution and selection-bias controls

A “successful participant” cannot be selected only by visible profitable exits or high balance:
- include full observable entry/exit lifecycle and unsold inventory mark-to-market;
- count failed/reverted/unfilled attempts and opportunity costs;
- separate trading cashflows from transfers, airdrops, incentives and treasury distributions;
- include chain/venue fees, funding, borrow costs, rebates and estimated execution costs with provenance;
- track drawdown, tail loss, concentration, holding time, capital lock and correlated protocol/pool exposure;
- use cohort-level baselines and protocol/regime normalization;
- account for survivorship, selection bias, missing transactions, address rotation and censored histories;
- report UNKNOWN when history or liabilities are incomplete.

Never rank strategies by wallet balance or win rate alone. Do not recommend mirroring a pseudonymous account directly.

## 5. Learning and validation

Use chronological train/validation/final-holdout partitions with horizon-matched embargo. Group splits by actor, pool, protocol, operator/correlation group and event cluster. Retain failed/no-trade/negative episodes. Compare learned archetypes to deterministic baselines and counterfactual nulls. Report confidence intervals, effective independent episode counts, calibration, false positives/negatives, drawdown, tail risk, capacity, fee sensitivity, data gaps and regime drift. Apply multiple-testing correction across searched strategies/participants/features.

Distinguish OBSERVED_PATTERN, HYPOTHESIS, REPLAY_SUPPORTED, HELDOUT_SUPPORTED and BLOCKED. No model output can issue identity, exact quote, capacity or execution permission. Agent-generated strategies are independently evaluated against source-bound local data and SX-01 StrategyContractV1. Synthetic behaviour remains labelled synthetic.

## 6. Outputs

1. Versioned ParticipantEpisode/archetype mapping using existing MarketEpisode and decision dataset owners; additive schema only if needed.
2. Machine-readable strategy-archetype knowledge graph manifest referencing canonical asset/market/protocol identities and evidence hashes.
3. Reproducible cohort/strategy report: sample sizes, coverage, costs, risk, uncertainty, counterexamples and held-out results.
4. Per-archetype SX-01 contract proposal with execution class and typed blockers.
5. Source-rights audit and no-private-data/no-deanonymization tests.

## 7. Acceptance and safety

- Same source corpus replays to identical episode IDs, graph hashes and statistics.
- Missing/incomplete history never becomes zero activity or zero PnL.
- Transfers, fees, inventory, liabilities and residual assets are separately accounted.
- Train/test splits prevent actor/pool/protocol/time leakage; negative and censored episodes are retained.
- Independent local replay reproduces promoted research claims.
- No real-world identity claims, targeting, private orderflow or automated copy-trading.
- No signer, sender, submission, borrowing, wallet/account creation, spending or production promotion. Output is research-only.
