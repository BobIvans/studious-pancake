# Strategy blocks and currency routes — prioritization

## Working vertical
`asset identity → physical market identity → rooted state → quote → topology → exact sequential route → overlap dedup → amount grid → all-in net → capital/builder/simulation gates → paper evidence`.

A strategy is not a registry label or a price comparison. Separate:
- asset identity (chain/genesis, mint, token program, decimals, representation);
- market identity (program, physical pool/book, fee tier/hooks, vault/tick/bin resources);
- state (slot/checkpoint/version, reserves/depth, freshness, generation);
- quote (amount/direction, exact in/out, fee, rounding, guaranteed/min output, expiry);
- route (ordered legs, same starting/ending asset, chain atomicity, resource overlap);
- funding (lender capacity, premium and repayment);
- unsigned builder + atomic simulation;
- paper evidence and later confirmed execution.

## Route examples (conceptual; resolve canonical mint IDs)
| Route | Shape | Priority |
|---|---|---|
| SOL → USDC → SOL | 2 legs across two distinct physical pools | P0, existing detector |
| SOL → USDC → USDT → SOL | 3-leg triangle | P0, exact CPMM cycle binding |
| SOL → mSOL → USDC → USDT → SOL | 4-leg cycle | P0, bounded exact CPMM |
| USDC → USDT → EURC → USDC | stable triangle | P0 only if each leg is locally exact-supported |
| SOL → mSOL → SOL via stake/unstake | rights/conversion edge | P1 research, instant exit proof required |
| wrapper/bridge paths | representation / cross-chain | P2; bridge is signal, not local atomic leg |
| Orderbook ↔ AMM | depth, sequence and fill model | P2; subscriptions unqualified |
| liquidation + unwind | lender + oracle + collateral route | P2; many extra gates |

Symbols are labels only. A closed route must start/end at the identical canonical mint. Bridges, delayed claims, queues, cooldowns and maturity are not local atomic legs.

## ROI order
1. Close two-leg + 3/4-pool CPMM exact evaluation, amount propagation, resource dedup, PR118 sizing, all-in economics and deterministic replay.
2. Add exact venue breadth to the same path: Raydium CLMM (ticks/bitmap), Meteora DLMM (directional bin arrays/fees), then book venues after proven subscriptions.
3. Add split-flow after single-route resource capacity is proven.
4. Only then investigate LST/issuer, liquidations and async or cross-chain economic routes.

Flashloan is a funding primitive, not the strategy. First measure market edge; then independently gate lender capacity, builder, simulation and paper.

## Net economics
At each amount, quote every leg sequentially. Conceptually:
`net_A = final_A - principal_A - lender_premium_A - swap_fees_A - transfer_fees_A - converted_network_costs_A - setup_costs_A - safety_buffer_A`.
Keep each fee in its source denomination until an explicit conservative conversion is available. Unknown is not zero. Quote output is not an execution fill; simulation pass is not realized profit.

## Success metrics
Report separate exact qualification, economic survival, capital eligibility, builder eligibility, simulation pass and paper completion rates. For later live execution, require landed/finalized transaction, reconciled token deltas and realized fees. Preserve rejected/no-trade observations.
