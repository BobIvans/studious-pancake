# pmm-sim caller-profile harness (isolated, research-only)

Harness for the caller-profile differential benchmark defined in
`research/pmm-sim-caller-profile/market_matrix_v1.json`
(pack: `docs/strategy-expansion/2026-11-21/prop-amm-competitive-toolchain/PMM_SIM_CALLER_PROFILE_RESEARCH_RU.md`).

**Production boundary:** local LiteSVM research only. No signing, no sending, no borrowing, no mainnet
caller impersonation. The spoof binaries (`magnus-router-spoof-{jupiter,dflow,okxlabs,titan}.so`) exist
only inside the local LiteSVM instance and have no mainnet meaning. Nothing in this directory is linked
into the installed Python runtime.

## Build (isolated)

The build happens in an isolated checkout of the pinned mirror — never inside the repository
(no `target/` is ever committed):

```
# isolated clone of vendor/strategy-research/pmm-sim-cc4ae891 at the pinned commit
cargo build --locked --release        # pmm-sim.exe
cargo test  --locked                  # upstream tests
```

Toolchain: rustup `stable-x86_64-pc-windows-gnu` (rustc 1.100.0) + winlibs MinGW-w64 binutils on PATH
(`as.exe`/`dlltool.exe` dependency of the rust-mingw self-contained linker). MSVC BuildTools were not
available (installer requires elevation); GNU toolchain is the documented fallback. Toolchain versions
are recorded in every run receipt.

Magnus git dependency: the upstream Cargo.toml selects mutable branch `extend-router-ixs`; the
original `Cargo.lock` pins it to immutable rev `9ecd34b634031f5dfdf5747c33a329605ea6e7c4` and all
builds use `--locked`, so the branch selector can never float. A standalone harness workspace applying
a `[patch]` to the immutable rev is permitted but not required for the research matrix; the lockfile
pin is authoritative.

## Run the matrix

```
bash run_matrix.sh <path-to-isolated-pmm-sim.exe> <snapshot-root> <results-out-dir>
```

- Snapshot root contains `cfg/setup.toml`, `cfg/accounts/`, `cfg/programs/` (either the upstream
  static snapshot at slot 401101387 or a captured snapshot from
  `research/pmm-sim-caller-profile/snapshot/<slot>/`).
- Matrix: 3 HumidiFi instruction variants × 6 caller profiles × 2 directions × 15 amounts.
- Every invocation uses `--jit-accounts=false --jit-programs=false` and
  `--http-url=http://127.0.0.1:1` — an unroutable URL so that any accidental RPC fetch fails hard
  (negative control: zero outbound network during runs).
- `min_return`/`expect_amount_out` remain the upstream permissive benchmark defaults (1); this is
  NOT a production slippage or repayment guard.
- Per-row records are merged by `merge_results.py` into CSV + hash-anchored JSON receipts under the
  results dir; failures and negative results are preserved, never dropped.

## Negative controls

1. Identity control: CPI without spoof must reproduce the MAGNUS_NATIVE baseline exactly.
2. Corrupted snapshot digest → refuse to run (no silent fallback).
3. Wrong discriminator / market-account mismatch → simulator error recorded, never a number.
4. Unknown simulator result → recorded UNKNOWN, counted as neither positive nor negative.
5. Determinism: re-run → byte-identical CSV/JSON digests.
6. Zero outbound: unroutable `--http-url` makes any implicit RPC fail.
7. Synthetic fixtures in repo tests declare "None of these bytes came from mainnet".
