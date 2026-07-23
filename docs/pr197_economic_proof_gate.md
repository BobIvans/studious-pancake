# PR-197 — Economic proof gate

This document describes the safe continuation slice for roadmap PR-197:
**Atomic Flash-Loan Transaction and Economic Proof Kernel**.

The goal of this slice is not to enable live execution. The goal is to make the
minimum evidence contract explicit before any later runtime path can claim that a
flash-loan candidate has a safe atomic plan, immutable message identity, rooted
simulation evidence and conservative integer PnL accounting.

## Boundary

`src/production_economic_proof_pr197.py` validates only offline evidence. It does
not import signer, sender, RPC, Jito, wallet, private-key or live runtime code.

The report always keeps these capabilities disabled:

- `live_capability_allowed() == False`
- `signer_capability_allowed() == False`
- `sender_capability_allowed() == False`

## Evidence schema

The validator accepts `pr197.economic-proof-gate.v1` evidence with these required
sections:

- release artifact hashes for rooted snapshots, route plan, firewall, compiled
  message, simulation report, account deltas, fee quote and economics;
- exact flash-loan sequence:
  `setup -> flash_start -> borrow -> swap_a -> swap_b -> repay -> cleanup -> flash_end`;
- semantic firewall evidence for MarginFi, Jupiter, System, ATA, SPL Token and
  Compute Budget decoders;
- forbidden-effect fixtures for System/SPL Token transfer, approve, set-authority,
  close-account and authority/delegate changes;
- compiler evidence binding v0/legacy wire size, blockhash, ALT set, public API
  size enforcement and simulation message identity;
- simulation evidence binding `minContextSlot`, valid blockhash, expected invoke
  graph and raw account snapshots;
- integer-only economics where RPC total message fee is included exactly once;
- a single raw-state decoder as the only source of economic observations;
- Token-2022 fail-closed policy until extension-specific economics are proven.

## Findings addressed by this gate

This slice turns several PR-197 acceptance criteria into machine-checkable
failure codes:

- weak program allowlists that do not constrain economic account effects;
- optional or unwired semantic instruction firewall;
- public compile/sign APIs bypassing the 1232-byte v0/legacy size limit;
- exact simulation not bound to raw account state and expected CPI graph;
- caller-supplied PnL observations bypassing canonical account decoding;
- `getFeeForMessage` being double-counted as base fee plus priority fee;
- Token-2022 being treated as safe before extension semantics are supported;
- accidental signer, sender or live enablement inside the PR-197 boundary.

## Deliberate non-goals

This PR does not:

- construct a real transaction;
- simulate against Solana RPC;
- load wallet keys;
- sign bytes;
- submit through RPC or Jito;
- consume permits or reservations;
- reconcile finalized settlement;
- migrate production DB state.

## Remaining full PR-197 work

Later PR-197 slices still need to wire this evidence contract into the canonical
planner/compiler/simulator, delete legacy caller-supplied reconciliation paths,
add real MarginFi/Jupiter golden vectors, preserve bounded raw account envelopes
and connect conservative economics to the durable PR-195 reservation authority.
