# MPR-041 — Canonical Economic Semantics and Conserved Route Graphs

This change is the installed-runtime cutover for the compressed MPR-041 scope
(former PR-048 + PR-041 + PR-043).  It preserves the original residual finding
IDs `R048-*`, `R041-*`, and `R043-*` as the review traceability namespace.

## Installed authority

The routing boundary now has one semantic chain:

1. `src.routing.dimensions` owns exact bps/percent, time/slot/count wrappers and
   provider-specific exact decimal serialization.
2. `CanonicalQuoteV2` is the only installed quote class.  The historical
   `NormalizedQuote` name is an alias to the same class, not a second model.
3. `RouteGraph` and `RouteEdge` own hop topology, allocation and integer amount
   conservation, stable semantic hashing and resource footprints.
4. Provider adapters construct the graph while normalizing.  The discovery
   classifier refuses executable admission without a graph, a proven minimum,
   bounded freshness and proven response echo for executable providers.

## Safety properties

- Binary-float percent serialization is absent from the active provider clients.
- Request bools, self-swaps, invalid dimensions and scientific notation fail
  closed.
- Missing quote expiry is stale; reviewed provider-contract TTL is explicit in
  provenance rather than an anonymous adapter literal.
- Jupiter request echo validates mints, input amount, swap mode and slippage.
- Full Jupiter hop identity is retained when returned (`ammKey`, program, mints,
  amounts and allocation bps).
- Route stages must each conserve 10,000 allocation bps and cannot consume more
  value than prior stages produced.
- Semantic route hashes are deterministic across equivalent provider ordering.
- Fee and price-impact values have typed exact representations while original
  provider text remains diagnostic provenance.

## Compatibility boundary

Historical fixture/report fields (`price_impact_pct`, `provider_fee`,
`platform_fee`, `route_provenance`) remain read-only compatibility inputs on the
same V2 object.  Active network clients, executable admission and route identity
use typed fee components and `RouteGraph`.  There is no V1-to-V2 active adapter.

## Verification

`tests/routing/test_mpr041_canonical_semantics.py` covers exact conversion,
self-swap rejection, split/merge conservation, allocation failures, stable
route hashes, provider echo mismatches, missing-expiry fail-closed behavior,
no-float static checks and optimized-Python validation.
