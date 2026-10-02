# PR-359 — Wave 15 INST-01 Autonomous Market Institution

This PR turns the first Wave 15 research specification into executable repository-owned code without claiming the entire 96-capability Wave 15 catalog is implemented.

## Implemented scope

INST-01 now has a deterministic offline vertical for one homogeneous sum-int-v1 service:

TASK_OPEN -> OFFER -> AWARD -> ACCEPTED -> DELIVERED -> VERIFIED -> CLOSED

with explicit NO_TRADE, REJECTED, LATE, and HELD_UNKNOWN outcomes.

The implementation adds immutable institution, rule, agent, task, offer, allocation, commitment, evidence, receipt and verdict contracts. It implements fixed-eligibility posted-price, reverse first-price and capped reverse critical-price procurement with precommitted supplier-id tie-breaking. Allocation and payment are deterministic and use integer synthetic base units only.

## Evidence ownership and semantic verification

The semantic resolver layers on the existing AGG-14 DataEvidenceApi for artifact registration, distribution rights, access scope and query budget. Wave 15 adds the missing task-specific semantic layer: bytes/hash/version, task/state/rule/supplier binding, deadline and independent recomputation of the allowed service.

A nonempty reference is not evidence. A wrong answer with a valid hash is rejected. An observed artifact that attempts to claim actual PnL without finalized economic proof is rejected as economic success. HELD_UNKNOWN keeps the synthetic reservation held and is not treated as success or failure.

## Finite mechanism evidence

The repository executes the bounded Wave 15 reference experiment inside the real research owner path:

- 125 true-cost profiles per mechanism;
- 2,625 unilateral reports for reverse first-price;
- 2,625 unilateral reports for capped reverse critical-price;
- 5,250 total checks;
- at least one profitable unilateral report exists for truthful first-price on the finite grid;
- no profitable unilateral report is found for the specified capped critical-price rule on that finite grid.

This is explicitly not a general equilibrium or global incentive-compatibility certificate.

## Safety / authority boundary

Always false in this PR: production_ready, live_enabled, execution_right, signer_access, submission_access, wallet_access, remote_mutation, customer_billing, real payment and actual-PnL claims.

No RPC send, signer, wallet, external paid API, remote governance or real settlement is introduced.

## Verification

Focused commands:

    python scripts/verify_pr359.py
    python -m pytest -q tests/research/test_pr359_wave15_market_institution.py --disable-socket --allow-unix-socket

The dedicated PR workflow also runs PR-358 and the canonical repository verifier.

## Not implemented by this PR

Wave 15 Batches D-F remain future work: strategic effort/shirking, participation/entry/exit, subsidy removal, population adaptation, coalition/Sybil stress, external demand, real task shadowing and independent population replication. The rest of the 96 Wave 15 proposed capabilities therefore remain partially or wholly unimplemented.

Published-head validation is performed from the pull-request synchronize event after all implementation files are present.
