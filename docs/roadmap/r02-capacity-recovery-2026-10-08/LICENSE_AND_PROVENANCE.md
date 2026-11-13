# Licensing and provenance of offline source reference kit
These are exact source files pinned at upstream Git commits, vendored only for offline inspection by Codex and integrity replay, not installed as a fully functioning SDK dependency. The local suffix `.ts.txt` prevents build auto-import.

## MIT projects
- **NAVI** `naviprotocol/naviprotocol-monorepo` MIT, bundled root `offline/vendor/navi/LICENSE.txt`. Source package `@naviprotocol/lending@2.0.12`.
- **Project 0** `0dotxyz/p0-ts-sdk` MIT, bundled root `offline/vendor/p0/LICENSE.txt`. Source package at inspected Git pin is `2.10.0`; online npm release/version parity NOT verified.
- **Kamino SDK** `Kamino-Finance/klend-sdk` `package.json` declares MIT (13.0.2). This repo's root has no standalone LICENSE file at pinned commit; retain package.json provenance, and verify distribution/attribution requirements before copying any module into shipping production code. Bundled small generated references are **research only**. Do not infer license of unrelated Kamino smart contract.

**CRITICAL:** `Kamino-Finance/klend` on-chain program uses **Business Source License 1.1**, change date 2027-11-17, and `Instadapp/fluid-solana-programs` uses BSL 1.1 (production use restricted). No source from these restricted repositories was copied into this kit. Their public ABI/PDA facts are cited for research, not a license to fork or deploy their smart contracts.

**Jupiter Lend IDL** `jup-ag/jupiter-lend@a484ddc...` exact raw file is not duplicated; only an original factual/structural field layout map with original source ref and blob pin. No implied redistribution license. `offline/probe_structural.py` is new independent limited reader; not a modified upstream program.

## Integrity
`offline/VENDOR_MANIFEST.json` records each original path, Git commit, Git blob SHA and size. The self-contained Python integrity verifier reproduces `git hash-object` semantics using hashlib and requires exact content equality. No web access. Never silently replace a pinned SDK file with an unverified later release.

## Security
No private keys, seeds, wallet tokens or RPC secrets in source pack. Public receiver addresses and Sui package IDs are not signing authority. No source pin is proof of current deployed bytecode or live liquidity.
