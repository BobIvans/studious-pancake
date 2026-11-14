# OWNER_INTERFACE_FREEZE — shared boundary before parallel work

MASTER-00 must confirm/update this contract from current main. Until then, agents may read, test, build offline fixtures and propose interfaces, but must not independently change shared-owner schemas.

| Shared interface | Owner | Required contract |
|---|---|---|
| Asset identity | AssetResolver | chain/genesis + canonical mint/full Move type + token program + decimals + issuer/bridge/representation + evidence generation |
| Market identity | Dynamic Universe/MarketIdentity | chain + venue/factory/program/package + pool/book ID + fee tier/hook/resource + exact token identities |
| Source provenance | QPR/DIN/SourceDossier | operator/correlation group, access/entitlement/quota, version/doc/ABI, source generation, errors, freshness, raw digest |
| State observation | MarketObservationV2 / chain-specific state models | slot/checkpoint/block, finality/root, raw account/object hashes, dependencies and complete/partial semantics |
| Amount quote | existing quote normalizers / exact venue owners | direction, exact integer input/output, fee, rounding, consumed amount, partial fill, state generation, route-resource IDs |
| Capital edge | FlashCapitalGraph | lender/resource ID, canonical asset, exact cap/fee/rounding, repayment mode, freshness, source proof, unknown blockers |
| Unsigned build | existing financing ports/UnsignedExecutionPlan | exact provider/program/ABI, borrow/repay references, absolute order, object/account closure, no signer |
| Route search | UniversalArbitrageGraph/multihop solver | topology shortlist only until exact evaluator binds amount, state and complete costs |
| Sizing | PR118/non-monotonic sizing | exact fresh quote per size; no scaling one sample |
| Simulation | ExactSimulationFinalizer | complete unsigned message/PTB, current state, borrow/repay postconditions and all costs |
| Paper outcomes | existing durable paper/campaign/evidence store | immutable receipt, replay, no-trade/negative outcomes and time-aware metrics |

## Collision rules
- One agent owns each shared file. Never launch two coders editing AssetResolver, market catalog, SourceDossier schemas, quote normalization, FlashCapitalGraph or runtime authority concurrently.
- P0-1/2/3 can implement separate adapters after shared contract freeze, and each must add a compatibility test against existing owners.
- R02 A-D can implement separate protocol readers but all share QPR/DIN quota and evidence generation. A single quota owner must enforce physical RPC attempt counts.
- R03-00 owns the shared unsigned-plan contract; provider builders consume only frozen contract.
- Only the lead integrates relation/market/quote/capital evidence and updates the crosswalk. No new graph/database/registry.
