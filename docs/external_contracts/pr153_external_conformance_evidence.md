# PR-153 external conformance and program attestation evidence

PR-153 turns read-only provider probes and rooted on-chain program observations
into one immutable review bundle.

## Provider evidence

The runner executes selected contracts through the existing opt-in conformance
transport and records only sanitized evidence:

- contract and provider identity;
- probe state and verification result;
- request method and URL;
- response SHA-256;
- assertion results;
- a bounded error category rather than raw exception text.

Jupiter, Jito and any other provider remain unpromoted when a probe is skipped,
missing credentials, fails transport, violates schema assertions or produces an
invalid response hash.

## Program evidence

MarginFi, Kamino or another on-chain program can supply a rooted attestation with:

- exact registry contract and program IDs;
- cluster and loader owner;
- executable and ProgramData identity;
- reviewed upgrade-authority state;
- deployed and reproducible binary hashes;
- pinned source commit;
- rooted slot and explicit expiry.

A mismatched program ID, cluster, binary hash, stale observation, non-executable
program or unreviewed upgrade authority blocks the evidence package.

## Promotion boundary

A complete bundle may become `review_ready`, but it never edits the registry and
always returns:

```text
registry_mutated = false
automatic_promotion_allowed = false
```

A separate human-reviewed PR must consume the immutable bundle before changing
any provider or program execution role.

## Safety

- Online probes are opt-in.
- No private key or transaction submission.
- No registry mutation.
- No automatic external-contract promotion.
- Raw credential values and raw exception details are not emitted.
