# MPR-02 V6 — protocol correctness gate

This checkpoint continues **MPR-02** after the initial provider/protocol rooted data-plane gate.

It is an offline, sender-free acceptance contract. It does not call Solana RPC, Jupiter, Helius, MarginFi, Kamino, OKX, OpenOcean or Odos; it does not read secrets, construct messages, sign, submit or promote paper/live readiness.

## V6 scope

The V6 audit adds MPR-02 protocol-correctness blockers around self-certifying program identities, Jupiter Swap V2 drift, rooted token-account binding, Token-2022 rent sizing and CA bundle hash/load TOCTOU.

This checkpoint covers:

- `IMPL-81` — official Token-2022 identity and no ineffective local allow flag.
- `IMPL-82` — no duplicated Token-2022 literals in asset/governance checks.
- `IMPL-83` — official Token-2022 and Associated Token Program IDs.
- `IMPL-84` — rooted provider attestation must use an independent registry.
- `IMPL-87` — cooldown semantics remain part of account-wide MPR-02 evidence.
- `IMPL-88` — strict non-empty Jupiter V2 `routePlan` with canonical `bps`.
- `IMPL-89` — one canonical `/swap/v2/build` request DTO.
- `IMPL-90` — positive `lastValidBlockHeight` and remaining-height margin.
- `IMPL-91` — MarginFi token accounts bound to rooted owner/mint/program/state.
- `IMPL-92` — extension-aware Token-2022 token-account size/rent.
- `IMPL-93` — ExactIn-only Jupiter V2 model; no `swapMode`/ExactOut request.
- `IMPL-95` — reviewed CA bytes must be the same bytes loaded by SSL.

## Added files

- `src/mpr02_v6_protocol_correctness_gate.py`
- `tests/test_mpr02_v6_protocol_correctness_gate.py`
- `docs/mpr02_v6_protocol_correctness_gate.md`

## Safety boundary

A passing report allows only physical protocol-cutover review:

```text
protocol_correctness_review_allowed=true
operational_paper_ready_allowed=false
live_execution_allowed=false
sender_allowed=false
```

The full physical cutover still has to wire these validators into the active chain registry, Jupiter request/response path, MarginFi account admission, Token-2022 rent reservation and CA-bundle transport boundary.
