# MPR-2602 implementation status

This branch continues accepted MPR-2601 main commit
`68788d7f7f7da8a2e03b170f93c48af7421ee805`. It is an implementation
checkpoint, not a production-readiness or full MPR-2602 completion claim.

## Offline external connection configuration

Start at [config/external_connections/README.md](../config/external_connections/README.md).
Jupiter, Solana RPC, Helius, webhook and future API records share one bounded
offline loader. Examples are disabled, unreviewed, use placeholder endpoints,
and grant no network permissions. Credentials are references and environment
variable names only. Unknown services and inbound webhooks remain disabled
until their consumer contracts are implemented. Configuration validation is
not external qualification.

## Implemented components under review

- Provider governance selectively continued from PR #467: durable obligations
  in the accepted lifecycle database, additive migration, shared quota pools,
  physical-attempt accounting, preserved unknown effects, generation binding,
  bounded queue/cleanup and read-only dependency diagnostics.
- Bounded HTTP decoding, per-attempt admission and sender-free method scope.
- Immutable raw simulation account retention, source-bound narrow MarginFi
  repayment decoding, raw economic reconciliation and conservative valuation.
- Compiler rebinding of MarginFi instruction indices after compute-budget
  insertion; default-deny instruction checks; bounded stage cache identity.
- Awaitable A3 batch source with a shared cycle deadline.
- Production planner/compiler/finalizer/decoder tests using isolated source
  vectors. `SOURCE_VECTOR_OFFLINE` does not satisfy deployed conformance.

## Outstanding completion gates

The concrete Discovery/detector producer, native-unit-safe durable capital
integration, raw-evidence PR152 admission, accepted attempt terminal/outbox
commit and installed A3 positive-path replay are not yet complete. The legacy
handoff status must not be relabelled as a durable successful outcome.

Broader Jupiter semantic/lifecycle proof (including supported ATA/WSOL setup
and cleanup), DNS rebinding protection and full requirement-by-requirement
adversarial qualification remain open. Supported Linux file-store,
multi-process, complete regression suite, installed wheel and image evidence
must be generated for the final revision. Windows-only platform failures are
not passing Linux evidence and must not be hidden by stubbing POSIX functions.

External qualification is `BLOCKED_EXTERNAL`: no approved endpoint,
credential-reference, method and budget profile has been supplied. Source
fixtures do not resolve the differing source/deployment pins or substitute
for SDK/deployment/operator evidence. No signing, sending, funding, external
resource mutation or automatic merge is authorized by this checkpoint.

The existing production debt inventory and readiness flags remain authoritative;
this document does not close any debt item.
