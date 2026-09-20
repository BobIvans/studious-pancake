# SUPER-08 — product boundary and full release traceability

SUPER-08 closes the code-level overlap of W2-22 (PRODUCT-01 / PR-148) and
W2-23 (RELEASE-01 / PR-150) without creating a second product engine or release
authority.

## Reused merged owners

- AGG-14 / PR #509 owns PRODUCT-01 NF-318…NF-322 in `src.research`.
- AGG-09 / PR #505 provides the merged OPS-03 code/evidence prerequisite.
- AGG-15 / PR #503 owns RELEASE-01 NF-324…NF-328 and remains only an audit
  consumer of MPR-2612 release authority.
- MPR-2612 remains canonical release/promotion authority.

SUPER-08 does not duplicate those systems.

## Residual implemented here

The post-AGG continuation introduced NF-329…NF-352. Existing AGG-15 v1 still
required exactly 328 NF identities, which allowed a structurally complete old
manifest to omit the six continuation scopes entirely.

SUPER-08 therefore:

1. migrates the existing release-handoff schema to
   `agg15.release-handoff.v2`;
2. requires exactly NF-001…NF-352;
3. binds NF-329…NF-352 to their original PR-073…078 primary owners;
4. rejects an incorrect primary owner for those extension NF;
5. requires product-boundary evidence showing that the existing PRODUCT-01
   accounting/effect surface cannot inflate trading PnL or execution authority;
6. adds one structural verifier over the existing AGG-14 and AGG-15 owners.

## Continuation crosswalk

| Source PR | NF | Primary owner |
|---|---|---|
| PR-073 | NF-329…332 | TREASURY-01 |
| PR-074 | NF-333…336 | BATCH-01 |
| PR-075 | NF-337…340 | UNIVERSE-01 |
| PR-076 | NF-341…344 | ALT-01 |
| PR-077 | NF-345…348 | FORMAT-01 |
| PR-078 | NF-349…352 | FORMAT-02 |

This is traceability, not a claim that every external prerequisite is qualified.

## PRODUCT-01 status

The code owner is reused from AGG-14. In particular:

- sponsored/paymaster planning is offline and cannot sign/submit;
- keeper operations remain permission- and debit-bound;
- the data evidence API has distribution/access/query budgets;
- grant/bounty receipts cannot claim remote submission;
- `RevenueAttributionLedger` separates arbitrage PnL from service fees,
  rebates, grants, rent reclaim and client funds.

External Kora funding/capability, customer keeper authorization, customer data
service/payment evidence and grant/bounty submission remain operational blockers
where recorded by AGG-14. SUPER-08 does not fabricate them.

## Release semantics

A 328-row legacy handoff is no longer current full-target evidence. It must be
regenerated under v2 with all 352 NF dispositions.

A structurally complete or code-complete report still does not authorize live
execution. The report hard-keeps:

- `production_ready=false`;
- `release_claim_allowed=false`;
- `live_enabled=false`;
- `automatic_scale_up_allowed=false`.

Canonical release review still requires the existing MPR-2612 receipt and all
selected-profile/campaign evidence.

## Verification

Focused verifier:

```bash
python scripts/verify_super08_product_release.py --json
python -m pytest -q \
  tests/test_agg14_research_system.py \
  tests/test_agg15_release_handoff.py \
  tests/test_super08_product_release.py
```

The dedicated SUPER-08 GitHub Actions workflow and repository-wide CI are
authoritative for the exact PR head.

## Rollback

Revert the SUPER-08 schema/audit changes. No product service, signer, sender,
wallet, remote resource, transaction, treasury movement or live mode needs
rollback because this PR performs none of those effects.
