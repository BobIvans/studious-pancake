# W6-12 — Observed participant strategy intelligence and evidence graph

**Class:** RESEARCH_ONLY / INTEL.  
**Purpose:** extend Market Ecology with a disciplined, privacy-preserving way to learn from successful public on-chain trading behaviour, protocol interactions and market episodes. The goal is to discover reusable strategy archetypes and measurable decision rules, not to identify real people or blindly copy wallet trades.

## 0. Gap and scope

W6-01/02 already cover participant archetype IR and population calibration; W6-05/06 cover benign competition, survival and bounded PSRO/self-play. The recovered prior-chat research also asked for a knowledge graph of successful traders and all public data that helps the system learn.

The existing assignments do not explicitly close the end-to-end chain:
public protocol activity → pseudonymous participant episodes → strategy hypothesis/archetype → net outcome attribution → counterfactual replay → held-out evaluation → advisory strategy contract.

W6-12 closes that research gap while extending existing owners. It is not a wallet tracker for identifying people, not an execution strategy and not permission to use private order flow.

## 1. Data and privacy boundary

Only public chain data, documented protocol/indexer outputs and expressly authorized datasets may be used. Store wallet/account identifiers as pseudonymous public-chain identifiers needed for reproducibility; do not attempt real-world identity resolution, deanonymization, doxxing, social-graph inference or linking to personal accounts. Do not process leaked/private orderflow, private group chats, compromised keys or non-consented personal data.

Every source must have:
- official endpoint/schema/SDK revision, retrieval timestamp, license/data rights and quota;
- canonical chain/account/program/protocol identity and source independence/correlation;
- raw receipt hash, availability timestamp, slot/checkpoint, finality/fork/reorg status;
- explicit completeness and censoring state (partial history is not “no trade”);
- an auditable retention/redaction policy.

If source rights, full-history coverage, participant attribution or transaction semantics are unknown, status stays BLOCKED or RESEARCH_ONLY.

## 2. Participant episode model — reuse existing evidence owners

Reuse:
- src/market_data_evolution/contracts.py (MarketEpisode, replay/provenance contracts);
- existing src/agg02/ raw journal / DatasetReplayReader;
- src/market/observations.py, src/market/streams.py and correction/retraction/watermark semantics;
- src/intelligence/episode_builder.py and the existing decision dataset/ranker;
- src/mechanism_discovery/ claims, research quality, causal twin and existing benchmark owners;
- src/research/correlation_ledger/ for residual/lead-lag context only.

Do not build a second raw market database, feature store, event journal, wallet graph or strategy registry.

A bounded episode should preserve:
- pseudonymous public actor/account key and scope (protocol/program/market);
- ordered transactions/instructions/events and state transitions with slot/checkpoint, signature/event hash and finality;
- positions, collateral, inventory, LP rights, borrow/repay, fees and realised/mark-to-market deltas when observable;
- market state before/after, exact pool/book identities and correlated underlying resources;
- external cashflows/transfers separately from trading PnL;
- fees, gas/priority, rebates, funding/borrow cost, rent, failed/reverted transactions and residual inventory;
- missing-history/censoring flags, source coverage, confidence and unknown fields.

Never call gross token balance change “profit” without accounting for transfers, inventory, liabilities, fees and unrealised positions.

## 3. Strategy archetype discovery

Candidate archetypes may include (only where public protocol semantics allow observation):
- direct/fragmented/multi-hop arbitrage;
- LST/NAV/issuer-redemption basis;
- liquidation/repay/unwind and collateral migration;
- LP entry/exit/fee collection/range shift;
- market making / inventory management / hedge;
- lending-rate refinance or multi-period carry;
- launch/migration/curve graduation;
- orderbook liquidity provision, RFQ/intent participation and auction bidding;
- bridge/chain rebalancing and basis inventory.

Represent each as a versioned hypothesis: state preconditions, observed action pattern, expected economic mechanism, execution/settlement class, risk/capital requirement, falsifiable null and typed evidence gates. A strategy archetype is not an executable Opportunity.

## 4. Outcome attribution and selection-bias controls

A “successful participant” cannot be selected only by visible profitable exits or high balance:
- include full observable entry/exit lifecycle and unsold inventory mark-to-market;
- count failed/reverted/unfilled attempts and opportunity costs;
- separate trading cashflows from transfers, airdrops, incentives and treasury distributions;
- include chain fees, venue fees, funding, borrow cost, rebates and estimated execution cost with provenance;
- track drawdown, tail loss, concentration, holding time, capital lock and exposure to correlated pools/protocols;
- use cohort-level baselines and protocol/regime normalization;
- account for survivorship, selection, missing transactions, address rotation and censored histories;
- report UNKNOWN when the full history or liability set is unavailable.

Never rank participant strategies by wallet balance, win rate alone or selected successful transactions. No recommendation to mirror a pseudonymous account directly.

## 5. Learning and validation

- Use chronological train/validation/final-holdout partitions with embargo matched to strategy horizon.
- Group splits by actor, pool, protocol, operator/correlation group and event cluster to prevent leakage.
- Retain failed/no-trade/negative episodes.
- Compare learned archetypes to deterministic strategy baselines and counterfactual nulls.
- Use confidence intervals, effective independent episode counts, calibration, false-positive/false-negative rates, drawdown, tail risk, capacity, fee sensitivity, data gaps and regime drift.
- Apply multiple-testing correction across searched strategies/participants/features.
- Distinguish OBSERVED_PATTERN, HYPOTHESIS, REPLAY_SUPPORTED, HELDOUT_SUPPORTED and BLOCKED; no model output can issue identity, exact quote, capacity or execution permission.

Any agent-generated strategy must be independently re-evaluated against source-bound local data and the existing SX-01 StrategyContractV1. Synthetic or simulated behaviour is always labelled synthetic.

## 6. Outputs

1. Versioned ParticipantEpisode/archetype mapping using existing MarketEpisode and decision dataset owners; propose an additive schema only if required.
2. A machine-readable strategy-archetype knowledge graph manifest with nodes/edges referencing canonical asset/market/protocol identities and source evidence hashes.
3. Reproducible cohort/strategy report with sample sizes, data coverage, costs, risk, uncertainty, counterexamples and held-out results.
4. Per-archetype SX-01 contract proposal with execution class and typed blockers.
5. A no-private-data/no-deanonymization test suite and source-rights audit.

## 7. Acceptance and safety

- Replay the same source corpus twice and obtain identical episode IDs, graph hashes and statistics.
- Missing or incomplete history never becomes zero activity or zero PnL.
- Transfer, fee, inventory, liability and residual assets are accounted for separately.
- Train/test splits prevent actor/pool/protocol/time leakage; negative and censored episodes are retained.
- Independent local replay reproduces every promoted research claim.
- No real-world identity claims, targeting, private orderflow or automated copy-trading.
- No signer, sender, transaction submission, borrow, wallet/account creation, spending or production promotion. Output is research-only.
