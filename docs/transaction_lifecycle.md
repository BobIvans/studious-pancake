# PR-008 transaction lifecycle: generic Solana v0 compiler

Checked on 2026-07-19 against official Solana transaction/versioned-transaction/ALT documentation, solders API docs, and PyPI release metadata. The PR-008 dependency pair is Python 3.13 in CI, `solana==0.40.1`, and `solders==0.28.0`.

The safe runtime boundary from PR-007 remains shadow-only: live submission is disabled by CI/default environment and the execution compiler does not submit transactions, load wallets, fetch blockhashes, or call RPC/Jito send APIs.

## Compiler input/output contract

`TransactionPlan` is provider-agnostic. Provider/application layers pass ordered `PlannedInstruction` wrappers around real `solders.instruction.Instruction` values with `AccountMeta` and opaque `bytes` data. Metadata such as `role`/`name` is diagnostic only and is never encoded into wire data.

The compiler requires typed `Pubkey` payer/signers/ALT keys and a typed non-default `Hash` inside `BlockhashContext`. It owns only generic composition: official Compute Budget instructions at the front and, when `TipPolicy.lamports > 0`, exactly one official System Program transfer at the end.

`CompiledTransaction` contains a real `MessageV0`, canonical versioned message bytes from `to_bytes_versioned(message)`, an unsigned `VersionedTransaction.populate(...)` simulation envelope with default signatures, signer ordering, message hash, actual wire size, and account/ALT diagnostics. `SignedTransaction` is produced only by `TransactionCompiler.sign_fully(...)` from explicit `Keypair` signers and verifies signatures without mutating the compiled result.

## Message bytes vs transaction bytes

Canonical versioned message bytes are used for message hashing and `getFeeForMessage`. Transaction bytes are used for `simulateTransaction` and size checks. The unsigned envelope is valid only for `simulateTransaction(sigVerify=false)`; `sigVerify=true` requires a fully signed result.

## ALT policy

ALT account data is parsed with solders lookup-table state parsers (`AddressLookupTable.deserialize`, with solders `from_bytes` accepted for deterministic solders-generated state fixtures), then converted to `AddressLookupTableAccount(key, parsed.addresses)` for `MessageV0.try_compile`. Validation rejects wrong owner, corrupt bytes, empty/oversized tables, duplicate addresses, deactivated/deactivating tables, same-slot extensions, missing required lookup addresses, duplicate ALT accounts, and unresolved requested tables. The ALT source slot and data hash are retained for diagnostics.

## Size and non-goals

The 1232-byte limit is enforced fail-closed on `len(bytes(VersionedTransaction))`, including all 64-byte signature slots. Oversized plans return typed `TRANSACTION_TOO_LARGE` diagnostics; PR-008 does not requote routes, implement MarginFi/Jupiter instruction bytes, add capital feasibility, add token-aware PnL, enable live submission, or load secrets.

## Reproducible dependencies

Runtime dependencies are maintained in `requirements.in` and locked in `requirements.txt`; dev/test/lint dependencies are maintained in `requirements-dev.in` and locked in `requirements-dev.txt`. Regenerate deterministically with:

```bash
python -m piptools compile --resolver=backtracking --strip-extras -q -o requirements.txt requirements.in
python -m piptools compile --resolver=backtracking --strip-extras -q -o requirements-dev.txt requirements-dev.in
```
