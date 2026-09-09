# MPR-2602 prepared identity and Linux qualification

Status: implementation checkpoint, not the completion of the installed flashloan
vertical and not permission to merge or enable live execution.

## Identity v2

`src/paper_shadow/mpr2602_runtime.py` binds the full candidate recursively.
Dataclass fields, including private fields, are encoded with an explicit type and
field namespace. String/integer enum types are preserved before scalar encoding.
Pubkey/Hash mapping keys cannot alias textual keys. Sets are canonicalized without
reusing the dataclass mapping variable. Concrete Solders instructions preserve
program, ordered accounts, signer/writable privileges and data. Resolved ALT
records include their provenance and their concrete SDK account's key and ordered
addresses. Opaque objects, private-only state, callables and unregistered SDK types
are rejected instead of being represented by incomplete public state.

The acquisition timestamp allowlist remains explicit and limited. Slot, expiry,
blockhash, decoder, raw state, required account, asset, fee and tip inputs remain
bound. This change does not claim to bind execution inputs that are not represented
in the published candidate (for example, a future lifecycle proof field or a
separately configured execution policy). Those must be supplied by the final
producer and checked on the exact-attempt path, not inferred from this helper.

The schema is `mpr2602.prepared-plan-identity.v2`. V1 intents/terminals are not
rewritten or relabelled. Reuse of the same attempt/generation with a different
schema is an immutable-intent conflict. No migration may silently release or
replace an in-flight reservation.

## Regression boundaries

`tests/test_mpr2602_semantic_identity_adversarial.py` covers every instruction
bucket on both Jupiter legs, nested route order/content, actual SDK privileges,
resolved ALT contents/provenance, payer/accounts/slots/safety, opaque policies,
typed mapping keys/enums, canonical digest syntax and the schema boundary.
Committed negative terminals are exercised with the actual PR-02 authority:
cleanup, route, ALT, decoder and capital-decision changes cannot reuse the old
identity or create another terminal/outbox event.

The WSOL/rent tests assert the public `AtomicVerticalError` code and the precise
chained `PR115StateEvidenceError`, rather than incorrectly expecting the inner
ValueError to escape. Consumer failure/qualification tests use the real shared
capital and lifecycle authority and assert that the intended vertical boundary
was actually reached. An earlier rejection at an unrelated mock boundary is not
accepted as evidence that economic qualification was exercised.

## Installed import boundary

The real installed paper invocation exposed an eager compatibility import of
quarantined `src.execution.shadow` through the execution package initializer.
The legacy simulator, lifecycle and live-gate exports now resolve lazily only
when explicitly requested; existing source compatibility remains tested.
The package smoke invokes `scripts/mpr2602_installed_default_probe.py` in its
isolated wheel interpreter, outside the checkout. This probe traps attempted
forbidden imports and network connections before calling the real canonical
CLI and records the actual A3 report. It does not replace the missing producer.

The observed default is `BLOCKED` with exit 5 and reason
`blocked_a3_b3_provider_evidence_missing`, not the requested `BLOCKED_EXTERNAL`.
Its sender/submission/live flags are false, with no forbidden imports or network
attempts. The probe explicitly reports that the requested external-profile
contract has not been satisfied; it does not manufacture that contract by
renaming the older missing-B3 result.

## Reproducible Linux evidence

`.github/workflows/mpr2602-sender-free-qualification.yml` runs offline tests,
compile/fatal-lint/Black/mypy/Bandit, rebuilds a wheel, compares required wheel
members byte-for-byte with the tested source, and runs installed package smoke
outside the checkout. Failed gates remain failures; other checks continue only
to preserve complete diagnostics. Artifacts contain the exact PR head and tested
merge SHA, source archive, JUnit/logs, wheel digest and offline replay dependencies.
Runtime wheels are downloaded against `requirements.lock` with required hashes.
Development replay tools use repository pins and have an artifact SHA-256 list.

Passing this workflow does not mean that an approved external profile exists,
that an installed producer/replay loop is complete, or that offline source vectors
prove deployed protocol conformance. Inspect the per-SHA evidence, rather than
copying an older wheel or an earlier test count into a completion claim.

## Unresolved checkpoint reconciliation

The supplied continuation describes 26 staged Windows files, but the supplied
attachment is a specification, not their patch or source archive. This pass can
operate only on the published branch and cannot attest that the Windows staged
implementation was uploaded. In the reviewed published tree, the A3 default
factory still supplies missing-B3 evidence and accepts injected batch/runtime
ports; `mpr2602_runtime.py` is an identity helper, not the claimed complete
installed discovery/materializer/terminal-replay engine.

Keep PR #473 draft and unmerged until the actual final tree contains and proves
the full D01-D52/F01-F40 implementation, the default external-profile block, the
positive installed A3 path, durable terminal integrity and replay without repeat
RPC, full lifecycle/capital/transport evidence, and every required final-SHA Linux
check. Sender, submission, funding, airdrops and live activation remain disabled.
