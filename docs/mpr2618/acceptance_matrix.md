# MPR-2618 acceptance matrix

| Area | Current status |
| --- | --- |
| C2618-01 issued-handle revocation fence | IMPLEMENTED_OFFLINE |
| C2618-02 single preferred generation / atomic cutover | IMPLEMENTED_OFFLINE |
| C2618-03 stale trust snapshot fence | IMPLEMENTED_OFFLINE |
| durable metadata / epochs / replay receipts | IMPLEMENTED_OFFLINE |
| multi-writer competing rotation | TESTED_BY_FOCUSED_REGRESSION |
| bounded overlap | IMPLEMENTED_OFFLINE |
| PR-183 crypto verifier reuse | IMPLEMENTED; real solders qualification delegated to repository CI |
| provider-governance physical request integration | BLOCKED_INTEGRATION |
| MPR-2608 signer-generation physical integration | BLOCKED_INTEGRATION |
| inbound webhook rotation | BLOCKED_INTEGRATION |
| conformance sentinel invalidation | BLOCKED_INTEGRATION / RESERVED_MPR2614 |
| HA/restore propagation | BLOCKED_INTEGRATION / RESERVED_MPR2616 |
| MPR-2617 collision | RESERVED_UNOBSERVED; recheck before merge |
| real KMS/HSM/provider rotation | BLOCKED_EXTERNAL |
| real secret/private-key handling | NOT_EXECUTED |
| mainnet transaction submission | NOT_EXECUTED |
| live/canary/auto-scale enablement | NOT_EXECUTED |
