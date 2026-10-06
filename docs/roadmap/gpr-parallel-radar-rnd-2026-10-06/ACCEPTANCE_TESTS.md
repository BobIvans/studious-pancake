# ACCEPTANCE / TEST CONTRACT

## Base invariants
- no signer/sender/submission import in new campaign composition;
- unresolved canonical asset ids cannot be promoted;
- source correlation groups survive normalization;
- every physical external request has retained attempt + outcome evidence;
- schema drift, 429, timeout, empty response and cancellation are negative evidence;
- replay performs zero network I/O and reproduces graph identity.

## Research graph tests
- deterministic edge/relation identity independent of input ordering;
- exact duplicate relation dedup keeps all provenance;
- same symbol on two chains never aliases;
- same symbol with unresolved canonical id cannot cross into exact graph;
- direct-vs-synthetic relation materializes only if evidence exists for all required legs;
- CandidateScore components are inspectable and cannot be read as profit;
- stale/correlated sources reduce score;
- top-K verification queue obeys deterministic ties and budgets.

## Scheduler tests
- provider token buckets are independent;
- provider cap and stricter campaign cap both apply;
- batching is preferred when source supports it;
- quota denial is evidence and does not silently reroute into a different provider;
- no source can starve exact-verification budget;
- source failure cannot promote a different source's candidate by accident.

## Solana dual quote tests
- 0x and Jupiter quotes normalize without granting exact authority;
- provider fee/price impact/route topology retained;
- OpenOcean carries correlation to Jupiter/Titan;
- Sanctum `Jup` source carries Jupiter correlation;
- ExactIn/ExactOut differences retained;
- amount grid can show non-monotonic route changes.

## Sui tests
- no JSON-RPC transport introduced;
- checkpoint/object version bound to observations;
- Aftermath and Cetus records can coexist without being treated as independent exact truth;
- PTB/offline model cannot authorize execution;
- chain-specific identity prevents Solana/Sui aliasing.

## Campaign smoke
1. bounded Solana radar;
2. bounded 0x/Jupiter preview;
3. one exact QPR-02 verification candidate;
4. replay;
5. bounded Sui shadow radar;
6. replay;
7. report top anomaly families and next decoder priority.
