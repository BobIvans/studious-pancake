# NEW-MEGA-PR-03 start note

This branch starts **NEW-MEGA-PR-03 — Canonical Chain Registry, Jupiter V2 и Hardened Exact-Message Economic Proof**.

Initial scope in this starting patch:
- establish a narrow, fail-closed verification spine
- do not claim that the full NEW-MEGA-PR-03 implementation is complete
- do not enable live trading, signer paths, sender paths, submission, or private-key handling

Intended follow-up in this branch:
1. create one canonical genesis-bound chain registry and remove duplicated protocol/program literals
2. freeze canonical Jupiter build surface to V2 `/build` and reject V1/hybrid/ExactOut request paths
3. bind exact simulation to one hardened compiler and one final immutable message hash
4. materialize raw pre/post simulation account bytes and derive decoder-owned economics from those bytes
5. fail closed on stale heights, missing rooted slots, caller-selected monitored accounts, and float-based economics

Safety posture:
- sender-free only
- fail-closed only
- no live enablement
