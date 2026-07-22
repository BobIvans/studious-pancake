# PR-130 source notes

Checked before implementation on 2026-07-22:

- Roadmap PR-130 requires first production Jito policy to use exactly one
  strategy transaction, optional `bundleOnly=true`, a tip in the same
  transaction, no standalone tip transaction, no multi-transaction bundle for
  first live, and no bundle status as economic settlement proof.
- Current Jito low-latency transaction docs state that `bundleOnly=true` sends a
  single transaction exclusively as a single-transaction bundle, and that bundle
  acknowledgements/statuses do not guarantee on-chain landing.
- The same docs warn that uncled blocks can lead to individual bundle
  transactions being rebroadcast through the normal banking stage, which does
  not preserve bundle atomicity/revert protection.
- Jito tip best practices recommend integrating the tip instruction into the
  main transaction and caution against standalone tip transactions because of
  uncle-bandit exposure.

This PR implements the policy as a static, deterministic local guard only. It
adds no live sender enablement, no signer path, and no RPC/Jito endpoint access.
