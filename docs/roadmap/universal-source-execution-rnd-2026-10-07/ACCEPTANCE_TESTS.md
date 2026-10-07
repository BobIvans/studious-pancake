# Acceptance Contract

## Provider contracts
- same logical quote normalizes deterministically
- provider raw evidence is retained/hashed
- correlation groups survive normalization
- rate-limit denial is negative evidence
- one slow provider cannot block all providers
- Jupiter 1 RPS cannot serialize the whole scheduler

## Solana builders
- 0x instructions build a v0 transaction without provider-held key
- Titan ready tx/instructions are locally verifiable
- OpenOcean marked correlated to Jupiter/Titan
- OKX/Rango transaction data is locally decoded/validated
- expiry/minOut/route hash preserved
- simulation happens before any signing

## Sui builders
- Aftermath route can be added to existing Transaction
- Cetus PTB composition works with sponsored/non-sponsored modes
- 7K/FlowX/provider overlap is correlation-tagged
- Rango unsignedPtbBase64 is decoded locally
- direct DeepBook path remains exact independent state
- no legacy JSON-RPC exact dependency

## Slumlord
- program ID/hash are pinned and reverified before enablement
- current Slumlord balance/capacity read at runtime
- no Slumlord-funded account remains open at tx end
- every funded account is zero before close
- rent recovered >= required repayment
- Repay + CheckRepaid ordering enforced
- persistent output ATA fails SLUMLORD_EPHEMERAL eligibility
- Token-2022 sizing/semantics fail closed until qualified
- network fee remains separately funded
- concurrent Slumlord usage is bounded and contention measured

## Flash capital
- fees/capacity read from live state/config or retained exact evidence
- P0 fee modeled as 0 only under current qualified protocol generation
- NAVI fee is dynamic from API/state, not hardcoded
- Scallop 10 bps modeled
- route solver includes capital cost

## Dynamic universe
- direct markets generate relations only from real evidence
- synthetic relations require both hub legs
- parity links require common economic underlying + representation proof
- 3–5 hop cycles bounded
- broad registry ingest cannot flood expensive verification queue

## Correlation
- uses residuals instead of raw stable/LST prices
- event-time alignment
- stale sources excluded/penalized
- lead/lag result cannot grant exact execution authority

## Safety
- qualification build has sign_enabled=false
- no private key in logs/evidence/provider request
- no sender/live capital added by this R&D package
