# MEGA8-06 — microstructure, portfolio risk and network execution intelligence

## Scope

This slice implements roadmap PR-255..270 / NF-705..768 as a deterministic,
offline/default-off contract layer. It follows the supplied MEGA8-06 prompt without
creating a signer, sender, economic ledger, settlement authority, or release authority.

The implementation is isolated in `src/mega8_06/`. Existing canonical owners remain
authoritative for exact simulation, reservations, signing, submission, finalized
reconciliation, evidence, and release.

## Child ownership

| Roadmap child | Owner | NF range |
|---|---|---|
| PR-255 MICRO-01 | `src/mega8_06/pr255.py` | NF-705..708 |
| PR-256 IMPACT-01 | `src/mega8_06/pr256.py` | NF-709..712 |
| PR-257 TCA-01 | `src/mega8_06/pr257.py` | NF-713..716 |
| PR-258 PORTFOLIO-02 | `src/mega8_06/pr258.py` | NF-717..720 |
| PR-259 RUIN-01 | `src/mega8_06/pr259.py` | NF-721..724 |
| PR-260 TAIL-01 | `src/mega8_06/pr260.py` | NF-725..728 |
| PR-261 COUNTERPARTY-01 | `src/mega8_06/pr261.py` | NF-729..732 |
| PR-262 ECON-02 | `src/mega8_06/pr262.py` | NF-733..736 |
| PR-263 NETWORK-01 | `src/mega8_06/pr263.py` | NF-737..740 |
| PR-264 NETWORK-02 | `src/mega8_06/pr264.py` | NF-741..744 |
| PR-265 NETWORK-03 | `src/mega8_06/pr265.py` | NF-745..748 |
| PR-266 SUBMIT-03 | `src/mega8_06/pr266.py` | NF-749..752 |
| PR-267 MEV-02 | `src/mega8_06/pr267.py` | NF-753..756 |
| PR-268 ORDERFLOW-02 | `src/mega8_06/pr268.py` | NF-757..760 |
| PR-269 RL-EXEC-01 | `src/mega8_06/pr269.py` | NF-761..764 |
| PR-270 RL-BID-01 | `src/mega8_06/pr270.py` | NF-765..768 |

## Safety and authority boundary

All functions consume captured observations, immutable evidence, or caller-provided
policy data. They do not open RPC/WSS/HTTP connections, load keys, sign transactions,
submit transactions, mutate remote state, fund wallets, or increase capital.

Fail-closed boundaries include ambiguous direct-send outcome → retry freeze; critical
reads reject incoherent fork evidence; portfolio allocation counts shared resources
once; microcapital keeps a protected reserve and has no martingale/loss chasing;
protective orderflow requires current opt-in consent and a user-output floor; MEV code
only simulates counterfactual ordering; offline execution/fee models remain advisory.

## Dependency truth

The eight-pack declares MEGA8-01..05 as prerequisites. The branch was re-synchronized
after MEGA8-03/#521 merged to main at `1426f75749f4091e886b94e9a919df4e90739198`.
MEGA8-01/#525 and MEGA8-02/#523 are also merged. MEGA8-04/#522 and MEGA8-05/#524
remain open, so this slice is `IMPLEMENTED_OFFLINE` but operationally
`BLOCKED_DEPENDENCIES_AND_EXTERNAL_EVIDENCE`.

A code merge must not be represented as integrated roadmap completion, production
readiness, profitability evidence, live authorization, or capital promotion.

## Upstream / source-copy decision

No third-party source file is copied, ported, or vendored. Upstreams named by the
roadmap remain `REFERENCE_ONLY_PENDING_IMMUTABLE_PIN_LICENSE_AND_CONFORMANCE`.
No external repository is executed during discovery or qualification.

## Verification

```text
python -m compileall -q src/mega8_06
python scripts/verify_mega8_06.py --json
python -m pytest -q tests/test_mega8_06.py
python -m black --check src/mega8_06 tests/test_mega8_06.py scripts/verify_mega8_06.py
```

Focused local verification before upload: 12 tests passed and structural verifier
reported 16 children, 64 functions, NF-705..768, zero safety errors. GitHub CI and
release authority remain authoritative.

## Rollback

Revert/disable this package while retaining coverage/evidence. There are no external
operations to unwind. Canonical reservation, sender, settlement, and release owners
remain responsible for any separately authorized work.
