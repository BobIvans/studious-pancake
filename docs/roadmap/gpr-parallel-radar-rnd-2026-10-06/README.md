# GPR V2.1 — Evidence-Classified Multi-layer Economic Topology

Qualification continuation for PR #571.

## Core flow

```text
cheap/indexed/router observations
          ↓
AssetIdentity / Representation registry
          ↓
ResearchRelation
  heat + execution_class + evidence_state
          ↓
ResearchEconomicGraph
          ↓
CandidateScore / VerificationQueue
          ↓
chain-specific exact verification
          ↓
existing exact graph / sizing owners
```

## V2.1 changes

- registry expanded to 91 research identities;
- USDG and PYUSD corrected to Token-2022;
- Solana xBTC_OKX added;
- Sui generic Wormhole wUSDC split from Solana-origin USDCsol representation;
- Sui XAUM/XAU reference experiment added;
- 9 DeepBook pool identifiers materialized;
- 14 first-campaign families materialized;
- priority, topology and proof are now separate axes:
  - heat
  - execution_class
  - evidence_state

## First campaign principle

Do not poll all 330 symbolic relations equally.

Start with `FIRST_CAMPAIGN_FAMILIES_V2_1.json`; use the broader universe as a dynamic cheap research pool and promote from observed evidence.

## Safety

Registry identity, a known pool ID, HOT heat, or a router quote never grants execution authority.

No signer, sender, submission or live capital is introduced by this package.
