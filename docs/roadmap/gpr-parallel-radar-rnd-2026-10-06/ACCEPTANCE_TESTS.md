# ACCEPTANCE / TEST CONTRACT — GPR V2

## Base invariants
- no signer/sender/submission import in new campaign composition;
- every external physical request retains attempt + outcome evidence;
- schema drift, 429, timeout, empty response and cancellation are negative evidence;
- replay performs zero network I/O and reproduces graph identity;
- source/provider/operator/correlation identity survives normalization.

## Asset/representation registry tests
- registry digest is deterministic;
- chain + canonical id uniquely identifies a representation;
- same ticker on two chains never aliases;
- native and bridged/wrapped representations never alias;
- all registry rows default to runtime_enabled=false and exact_graph_allowed=false;
- RND_VERIFIED_CURRENT may enter research graph but not exact graph directly;
- REVALIDATE_CURRENT cannot enter exact verification without a fresh identity receipt;
- REVALIDATE_ISSUER_STATUS cannot produce a stronger issuer-equivalence claim until refreshed;
- UNRESOLVED cannot produce canonical network requests;
- Token-2022 identity does not imply Token-2022 semantic qualification.

Regression identities:
- Solana old Sollet BTC must not alias WBTC_WORMHOLE;
- Solana cbBTC / WBTC_WORMHOLE / tBTC remain separate;
- Sui USDC_NATIVE / USDC_WORMHOLE remain separate;
- Sui USDT_SUI_BRIDGE / USDT_WORMHOLE remain separate;
- Sui XBTC / WBTC_WORMHOLE / WBTC_SUI_BRIDGE / ZWBTC remain separate;
- SOL@Solana / WSOL_WORMHOLE@Sui remain separate representations of one economic underlying.

## Research graph tests
- deterministic relation identity independent of input ordering;
- duplicate relation dedup retains all provenance;
- direct-vs-synthetic relation materializes only when all legs have evidence;
- representation/economic-equivalence relation never implies free convertibility;
- CandidateScore components are inspectable and cannot be read as profit;
- stale/correlated sources reduce score;
- top-K VerificationQueue obeys deterministic tie-breaking and request budgets.

## Exact-promotion tests
- QPR-03 indexed discovery never directly enters UniversalArbitrageGraph;
- Solana exact promotion still requires QPR-02/direct state + MarketObservationV2;
- REVALIDATE/UNRESOLVED identities fail closed;
- cross-chain relations fail closed when sent to atomic graph ingest;
- bridge relation cannot masquerade as a swap pool edge.

## Solana quote-preview tests
- 0x and Jupiter normalize without granting exact authority;
- provider fee/price impact/route topology retained;
- OpenOcean carries underlying-router correlation;
- Sanctum Jup-backed path carries Jupiter correlation;
- ExactIn/ExactOut differences retained;
- amount grid may show non-monotonic route/topology switches;
- structural LST/LRT and JLP-NAV observations remain research evidence until exact qualification.

## Sui tests
- no new legacy JSON-RPC transport introduced;
- checkpoint/object version bound to observations;
- Aftermath/Cetus/DeepBook observations do not count as independent exact truth by name alone;
- PTB/offline model cannot authorize execution;
- native/bridge representations remain distinct;
- Sui exact-state promotion requires governed gRPC/GraphQL object/checkpoint evidence.

## Cross-chain tests
- load six interchain research edge types;
- all interchain edges have RESEARCH_ONLY_NON_ATOMIC atomicity;
- USDC CCTP / SOL Wormhole relations never enter local atomic solver;
- cross-chain basis score includes expected rebalance/latency/capital penalties when available;
- prefunded inventory simulation is absent from GPR-01 and remains a later PR.

## Campaign smoke after GPR-01
1. load Asset Registry V2;
2. replay QPR-03 source evidence into ResearchEconomicGraph;
3. rank Solana candidates;
4. load Sui representation relations in shadow mode;
5. load 12 interchain watch relations as research-only;
6. attempt forbidden exact/cross-chain promotions and prove fail-closed;
7. replay and compare deterministic identities/scores;
8. stop and report split for GPR-02/GPR-03.
