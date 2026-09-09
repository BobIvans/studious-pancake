# PR-152 — Baseline truth, import graph and enforced quality/security gates

This PR implements the first safe slice of the renamed snapshot `(9)` task
formerly described as PR-146. The new follow-up roadmap states that PR-152 is
the first practical item before PR-159, PR-158 design/quarantine, PR-153 and
PR-154.

## Scope

This patch adds an offline, side-effect-free baseline truth module:

- `src/baseline/security_truth.py`
- `src/baseline/__init__.py`
- `tests/test_pr152_baseline_security_truth.py`

The module records the minimum aggregate verification contract that must be
true before deeper paper/live integration is trusted:

- compile/import gate;
- quality gate;
- security gate;
- offline pytest gate;
- installed package smoke gate;
- source-checkout import proof;
- installed-wheel import proof;
- optimized-mode import proof.

It also provides deterministic helper scanners for PR-152 blockers:

- direct `Keypair` imports;
- direct RPC `sendTransaction` / `send_transaction`;
- `skipPreflight=true`;
- imports from quarantined mutation modules;
- assert-based active validation;
- broad exception handling warnings;
- import-cycle detection.

## Safety boundaries

This slice does **not**:

- touch providers;
- call Jupiter/OKX/OpenOcean/Odos/Helius/RPC;
- change MarginFi logic;
- change DEX routing;
- start paper execution;
- introduce signer access;
- enable live trading;
- mutate existing aggregate verification scripts.

It is a stable contract that later PR-152 integration can wire into
`scripts/verify_repo.py`, `scripts/security_gate.py`, `scripts/quality_gate.py`
and package/import subprocess smoke tests once parallel PRs settle.

## Why additive

Parallel PRs are actively moving `main`. A small additive contract avoids
conflicts while still making the baseline truth explicit and testable. It also
avoids creating another runtime execution path.

## Acceptance mapping

| Roadmap requirement | Covered in this slice |
| --- | --- |
| Aggregate baseline command must be explicit | `BaselineManifest` + required gate IDs |
| Source/wheel/optimized import truth | `BaselineTruthReport` booleans and blocker reasons |
| Import graph cycles must be detected | `extract_import_edges()` + `detect_import_cycles()` |
| Active parser/security debt must be machine-readable | `scan_python_source()` findings |
| No provider/MarginFi/paper/signer/live scope | No imports or calls to those systems |

Full PR-152 completion still requires wiring these contracts into the existing
aggregate verify commands and closing any active findings found by the scanner.
