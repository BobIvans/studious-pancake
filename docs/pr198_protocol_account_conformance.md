# PR-198 — Protocol/account conformance authority

## Purpose

This slice implements the first fail-closed authority for roadmap PR-198.  It
does not enable live trading or transaction submission.  It gives the runtime a
single typed place to decide whether already-materialized protocol/account
evidence is coherent enough for shadow-only planning.

The roadmap requires MarginFi/Kamino protocol conformance, token-program
handling, ATA/wSOL lifecycle checks and deployed program attestation before any
execution path can be promoted.  This implementation makes those checks
machine-readable and default-deny.

## Scope

`src/protocol_account_conformance_pr198.py` validates:

- protocol decision evidence for MarginFi and Kamino;
- deployed program executable/loader/programdata attestation and expiry;
- canonical SPL Token vs Token-2022 mint/account evidence;
- unsupported Token-2022 extension, transfer-fee and transfer-hook fail-close;
- token account owner/mint/token-program/rent/frozen/delegate constraints;
- ATA account binding and canonical derivation-proof identity;
- wSOL lifecycle rules that forbid closing pre-existing balances;
- live execution denial regardless of shadow conformance.

## Deliberate limits

The ATA derivation proof is a stable PR-198 evidence identity over the canonical
ATA seeds.  It is not a Solana PDA implementation and does not claim that a
caller-provided address is valid merely because the proof hash matches.  A later
full PR-198/PR-199 slice must bind this to rooted RPC account bytes and exact
transaction compilation.

Kamino is accepted only when it is explicitly removed from the production route
or when supported combinations are backed by complete credentialed evidence.
MarginFi similarly requires the caller to supply a positive complete-evidence
decision from the existing MarginFi evidence gates.

## Safety

The report always returns `live_execution_allowed=false`.  A clean report only
means "shadow-conformant account/protocol evidence"; it is not a permit, signer
authority, final-message proof or settlement result.

## Verification note

The branch is rebuilt from the current `main`; `config/format_targets.txt`
preserves all existing formatter targets and adds only the PR-198 authority and
its focused regression test.
