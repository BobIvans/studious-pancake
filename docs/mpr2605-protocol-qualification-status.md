# MPR-2605 protocol qualification checkpoint

This branch is a sender-free residual implementation checkpoint against main `68788d7f7f7da8a2e03b170f93c48af7421ee805`.

Implemented in this checkpoint:

- Jupiter `/swap/v2/build` request contract is cut over from the historical POST/`quoteResponse` shape to the reviewed GET/query parameter shape already isolated in predecessor PR #447.
- Jupiter contract pins now fail closed when the configured method is not GET.
- Legacy quoteResponse payloads are rejected before transport.
- Existing sender/signer/live denial remains unchanged.

Prerequisites and blockers:

- MPR-2602 is still open as PR #473 and is not accepted on main.
- No MPR-2603 or MPR-2604 PR was found during this preflight; therefore release-bound/human-recovery acceptance is BLOCKED_INTEGRATION.
- MarginFi 0.1.10/0.1.11 ABI/oracle/deployment changes, trusted-clock receipt freshness, raw artifact provenance, exact simulation/economics and authorised external observations remain residual work for full MPR-2605 acceptance.
- No credentials, trading private keys, signing, sendTransaction/sendRawTransaction/sendBundle, airdrop, live/canary activation, external paid fallback, or auto-merge were used.

This file intentionally does not claim production readiness, protocol qualification, deployed binary equivalence, profitability, or external observation.
