# Pinned source reference snapshots

These are selected upstream source/specification files copied for offline code reading and decoder design. They are **not runtime dependencies** and files with `.rs.txt` / `.ts.txt` suffixes must not be compiled or imported.

## Included references

### Raydium CPMM and CLMM

Selected pool/config state layouts, swap instruction handling, fee/constant-product math, CLMM tick arrays, tick bitmap, tick math and swap math are copied from pinned upstream commits. Both upstream Rust repositories include the Apache-2.0 license; the license text is retained here in `LICENSE-APACHE-2.0.txt`.

This is a targeted set of account/layout/math references, not a complete reproducible build of either Solana program. The main `DIRECT_STATE_RAYDIUM_ORCA_METEORA.md` still defines the expected verification boundaries.

### Meteora DLMM

The pinned `lb_clmm.idl.json` is a full Anchor IDL snapshot (IDL metadata version 0.12.0) for program `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`. It is not the same as the npm SDK package version `1.9.15`; both are pinned independently. Helpers and a quote example are retained for offline inspection.

The package metadata declares SPDX license `ISC`. The upstream source checkout did not expose a root LICENSE file at the pinned path; verify the exact published package notice before copying additional SDK files into runtime. These are inert reference files only.

### Orca

No Orca source or generated SDK/IDL is copied here. The current upstream repository's custom Orca License is an explicit legal review blocker for code reuse in this profit-generating project. Public account facts remain in the hand-authored technical dossier.

## Integrity

- `VENDOR_SOURCE_MANIFEST.json` gives upstream repository, commit, path, source blob SHA-1, local path and license metadata for every mirrored file.
- Run `python docs/integrations/offline/solana-p0/verify_offline_bundle.py` from repo root. The verifier has no network dependency and checks local Git blob identity against the pinned upstream blob IDs.
- SHA-256 hashes are printed for local audit output. Git blob SHA-1 is the exact upstream object identifier used for byte-identical source verification.

## Safe usage

The coding agent may read these references offline to implement independent Python decoders and differential tests. Do not vendor an SDK or create a runtime dependency merely because its source file is present. Reconcile the relevant account version, deployment/program ID and exact account slot before decoding live data.
