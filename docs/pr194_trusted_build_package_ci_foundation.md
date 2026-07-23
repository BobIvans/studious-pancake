# PR-194 — Trusted Build, Package and CI Foundation

This slice starts the consolidated PR-194 foundation track with a narrow,
reviewable gate: the repository must prove that the supported checkout,
packaged capability resource, package boundary and CI verifier describe the
same sender-free runtime surface.

## Why this slice exists

The consolidated audit identifies PR-194 as the first P0 foundation because the
project needs one exact commit, wheel and image surface before later lifecycle,
protocol and live work can be trusted. This patch does not attempt the full
PR-194 mega-scope. It installs a deterministic gate that later PR-194 slices can
extend without turning the review into an unbounded rewrite.

## Added verifier

`python scripts/verify_pr194_trusted_foundation.py --json`

The verifier is offline and uses only repository files. It fails closed when any
of these contracts drift:

- `config/capabilities.json` and `src/resources/capabilities.json` are not
  byte-identical.
- the capability matrix no longer says `product_state=not-production-ready`;
- the live runtime mode is no longer hard-denied;
- any capability component allows `live`;
- required console scripts drift from the supported package entrypoints;
- `src.resources` no longer packages `capabilities.json`;
- `src.ingest*` or `src.execution.senders*` are no longer excluded from the
  production package boundary;
- `scripts/package_smoke.py` no longer checks forbidden wheel members and
  packaged capability resource presence;
- mandatory repository verification no longer runs the PR-194 verifier;
- the PR-194 verifier and its tests are missing from the incremental Black
  manifest.

## CI integration

`scripts/verify_repo.py` now runs the PR-194 verifier after package smoke and
before the wider compile/CLI/pytest checks. The verifier prints a
machine-readable JSON evidence payload containing exact hashes of the files that
define this slice.

## Safety invariants

- live trading remains hard-denied;
- signer and sender modules remain outside the active package surface;
- no RPC/Jito/Helius network calls are added;
- no credentials or secrets are introduced;
- no production runtime behavior is activated.

## Follow-up PR-194 slices

This patch intentionally leaves larger PR-194 work for subsequent slices:

- a single required `verify.yml` cleanup;
- full wheel import/public-export closure;
- dependency lock graph and SBOM provenance;
- GitHub Action SHA pinning;
- resource shutdown semantics and historical-layer archive map.
