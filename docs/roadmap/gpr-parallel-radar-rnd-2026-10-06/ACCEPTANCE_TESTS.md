# ACCEPTANCE / TEST CONTRACT — GPR V2.1

## Base evidence invariants
- no signer/sender/submission in campaign composition;
- every physical read retains attempt + outcome evidence;
- negative responses remain evidence;
- replay uses zero network I/O;
- provider/operator/correlation identity survives normalization.

## Registry tests
- 91 rows load deterministically;
- chain + canonical id identifies a representation;
- all rows default runtime_enabled=false and exact_graph_allowed=false;
- USDG standard == Token-2022;
- PYUSD standard == Token-2022;
- xBTC_OKX is distinct from cbBTC/WBTC_WORMHOLE/tBTC;
- Sui USDC_NATIVE, WUSDC_ETH_ORIGIN and USDC_SOL_PORTAL_ON_SUI are distinct;
- USDT_SUI_BRIDGE and USDT_WORMHOLE are distinct;
- XBTC/WBTC_WORMHOLE/WBTC_SUI_BRIDGE/ZWBTC are distinct;
- XAUM has its separate tokenized-gold identity and decimals=9;
- REVALIDATE/UNRESOLVED fail closed.

## Relation-classification tests
For every first-campaign relation:
- heat ∈ HOT/WARM/COLD/EVENT;
- execution_class ∈ LOCAL_ATOMIC/LOCAL_SIGNAL/CROSS_CHAIN_SIGNAL/REBALANCE_ONLY;
- evidence_state ∈ DISCOVERY_ONLY/IDENTIFIER_VERIFIED/RPC_VERIFIED/EXECUTABLE;
- heat cannot auto-upgrade evidence_state;
- LOCAL_ATOMIC cannot auto-upgrade to EXECUTABLE;
- CROSS_CHAIN_SIGNAL and REBALANCE_ONLY cannot enter atomic graph.

## Anchor tests
Support:
- USD_REDEMPTION
- STAKING_EXCHANGE_RATE
- NAV
- SAME_UNDERLYING
- BRIDGE_PARITY
- ORACLE_REFERENCE

JLP must not be treated as fixed $1 peg.
XAUM must not be treated as XAU spot without tokenization/redemption/liquidity frictions.

## HARD_BOUND tests
Before exact use require receipt with:
- canonical identifier;
- owner/program or Move type;
- decimals;
- token extensions/standard when applicable;
- representation/origin/bridge where material;
- exact venue/pool/book identity when requested;
- slot/checkpoint;
- campaign/repository generation.

Known registry identity alone must fail exact promotion.

## DeepBook seed tests
- all 9 pool IDs parse deterministically;
- each remains IDENTIFIER_VERIFIED/read-only until checkpoint/object/depth/fee verification;
- WUSDC/native-USDC, wUSDT/USDC, sbUSDT/USDC, suiUSDe/USDC, SUI/suiUSDe, SUI/USDSUI, USDSUI/USDC, XBTC/USDC and ZWBTC/USDC are represented separately.

## Synthetic/direct tests
- PYUSD/USDG starts as synthetic through USDC;
- absence of a direct current market does not create a fake direct edge;
- discovery may later add a direct relation without mutating the synthetic identity.

## Exact-promotion tests
- QPR-03 discovery never directly enters UniversalArbitrageGraph;
- Solana exact promotion still requires QPR-02/direct state + MarketObservationV2;
- Sui exact promotion requires governed checkpoint/object evidence;
- bridge/CCTP/Wormhole transport cannot masquerade as an atomic swap edge.

## Campaign seed tests
- load 14 first-campaign families;
- broader universe remains inactive/cheap until scheduler promotion;
- F01/F02 are HOT but IDENTIFIER_VERIFIED, not EXECUTABLE;
- F14 is HOT + CROSS_CHAIN_SIGNAL and non-atomic;
- replay reproduces identities, classifications and score inputs.

## Stop condition
After GPR-01 tests pass, stop and report readiness for parallel GPR-02 and GPR-03.
