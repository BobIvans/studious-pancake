# PR-169 current end-to-end threat model

PR-169 extends the early PR-043 wallet/supply-chain threat model into a
launch-certification threat model for the production release. The PR-043
document remains valid for its signer/supply-chain slice, but it is not broad
enough to certify a release that has provider admission, durable stores,
deployment controls, operator approvals, external providers, and settlement.

## Assets

- Wallet signing authority and signer IPC boundary.
- Treasury, fee buffers, reservations, settlement evidence, and durable latches.
- Unsigned transaction messages, instruction/CPI allowlists, ALT decoding and
  exact message-hash authorization.
- MarginFi/Kamino/Jupiter/RPC/Jito/provider evidence and freshness.
- Release manifests, deployment images, config/policy bundles and rollback
  bundles.
- Operator identities, approval records, alerts, recovery runbooks and audit
  evidence.
- Databases, WAL/checkpoint state, backups, object-store evidence and archive
  manifests.

## Actors

- External market/provider adversary.
- Compromised or drifting RPC/provider endpoint.
- Malicious dependency or supply-chain actor.
- Operator with insufficient or conflicting authority.
- Signer-boundary attacker trying to obtain raw key access.
- Release attacker trying to promote or roll back to an unsafe artifact.
- Recovery attacker trying to rewrite, suppress or replay evidence.
- Independent reviewer validating evidence without authoring the release.

## Trust boundaries

1. **Network runtime to signer boundary** — the networked process must not
   access private key material and may only request authorization for the exact
   unsigned message already proven by policy.
2. **Provider/RPC boundary** — every external payload is untrusted until schema,
   freshness, program/asset pins and economic/security proofs accept it.
3. **Instruction/CPI boundary** — unknown program IDs, unknown CPI paths and
   unpinned executable state fail closed.
4. **Durable state boundary** — restart must not reset reservations, outbox
   entries, settlement latches or unresolved submission state.
5. **Release/deployment boundary** — a green release gate cannot deploy by
   itself; actual desired-vs-observed release must match the certified digest.
6. **Operator approval boundary** — no single operator may self-approve critical
   release or recovery actions.
7. **Evidence boundary** — release evidence is immutable, signed, producer-
   identified and independently verified before launch certification.

## Abuse cases and PR-169 controls

| Abuse case | PR-169 launch-certification control |
| --- | --- |
| Self-declared `passed=true` evidence is submitted without raw report provenance. | `IndependentEvidenceArtifact` requires command, tool/version, source commit, image digest, runner identity, raw report hash, verifier identity and signature reference. |
| The release author signs off as the independent reviewer. | `IndependentLaunchSignoff` rejects an independent reviewer who authored release changes. |
| A critical/high finding is left open or merely accepted. | `evaluate_independent_launch_certification()` blocks unresolved high-severity risk before launch. |
| A signoff applies to a different release digest. | The gate blocks any signoff whose exact release digest differs from the package digest. |
| Required fuzz/property/mutation/differential evidence is absent. | The gate checks the full required independent-evidence set. |
| The threat model remains limited to the early wallet slice. | This maintained PR-169 document enumerates active external, admin, signing, data, release and recovery boundaries. |

## Machine-checkable launch invariants

PR-169 treats these as launch-blocking invariant families:

- network runtime never accesses private key material;
- unknown instruction/CPI is never authorized;
- exactly one unsigned message is bound to one authorization;
- duplicate unresolved submissions are impossible;
- repayment is proven before success;
- restart cannot reset financial latches;
- only one submission-capable generation is active;
- evidence cannot be silently rewritten;
- an operator cannot self-approve a critical release.

## Residual risks

PR-169 does not prove the implementation correct by itself. It creates the
certification contract that external and independent evidence must satisfy.
Actual fuzzing, mutation testing, differential vectors and external penetration
test reports must be produced by the required toolchain and pinned to the exact
release digest before meaningful funds are handled.
