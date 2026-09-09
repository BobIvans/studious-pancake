# MPR-2613 ownership collision map

| Requirement | Accepted owner consumed by 2613 | 2613 responsibility | Current status |
| --- | --- | --- | --- |
| runtime/lifecycle/capital | MPR-2601 | current-state admission consumer only | consume |
| provider governance | MPR-2602 | provider identity/freshness admission only | consume |
| human control | MPR-2603 | upward-state authorization reference only | consume |
| release/rollback | MPR-2604 | release identity/rollback classification only | consume |
| protocol conformance | MPR-2605 | protocol evidence boolean/adapter seam only | consume |
| vertical execution | MPR-2606 / 2602-v3 | no planner/simulator reimplementation | consume |
| shadow/soak | MPR-2607 | shadow-only fallback target | consume |
| signer/submission | MPR-2608 | signer/submission generation checks only | consume |
| canary | MPR-2609 | tier/envelope boundary only | consume |
| finalized economics | MPR-2610 | realized loss/balance facts seam only | consume; direct adapter pending |
| qualification | MPR-2611 | evidence identity only | accepted in main |
| final release gate | MPR-2612 | accepted release decision required before envelope materialization | BLOCKED_INTEGRATION |

`src/operations/operator_readiness.py` remains an offline evidence gate. `src/operations/mpr2613_guarded_operations.py` is intentionally a separate post-release operating-envelope/state authority and does not promote readiness evidence into production authority by itself.
