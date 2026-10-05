# RPC Quorum + Native Capture

## Current gap
Generic rooted RPC quorum exists, but native CPMM collector still owns a hardcoded public URL.

## Refactor
Replace URL ownership with interface:

```text
RootedSnapshotProvider.collect(request) -> RootedSnapshotBundle
```

Bundle contains:
- cluster genesis hash;
- commitment/finality;
- exact context slot/root;
- raw account bytes;
- request fingerprints;
- response hashes;
- provider/operator/correlation-group identities;
- acquisition/availability times;
- disagreements/failures.

## Modes
- `CAPTURE_SINGLE_SOURCE`: useful for problem discovery, always `BLOCKED_SINGLE_SOURCE`.
- `QUALIFY_QUORUM`: requires >=2 independent provider/operator groups.
- `REPLAY_ONLY`: zero network.

## Public RPC
Current Solana docs explicitly say public endpoints are not for production. Keep public endpoint only as smoke/fallback and never count it as a production-grade quorum plan.

## Independence
Different URLs from same Helius account/operator = one source. Different labels from same backend = one source. `correlation_group` alone cannot override provider/operator identity.
