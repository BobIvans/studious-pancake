# PR-018 incident runbook

For every incident: stop new submissions first, inspect durable journal/control tables, do not resend ambiguous attempts, reconcile first, then clear the latch and re-arm only after fresh readiness passes for the exact current config hash.

## Manual stop

```bash
bot live stop --reason "operator incident" --config config/live_risk.yaml
bot live status --json --config config/live_risk.yaml
```

## Stale RPC or cluster mismatch

1. Stop/latch live if not already latched.
2. Compare observed genesis, block height, slot and `minContextSlot` evidence.
3. Do not issue permits until readiness passes with fresh RPC evidence.

## Provider quota exhaustion or unhealthy route

1. Stop live and retain provider traces.
2. Confirm route capability/role allowlist; discovery-only providers are never fallback execution.
3. Re-arm only after quota and health evidence is fresh.

## Ambiguous submission

1. Keep the attempt outstanding.
2. Preserve signature and Jito bundle ID as distinct fields.
3. Run PR-014 reconciliation/status polling read-only; never resend ambiguity.

## Unexpected landing, reserve breach, config drift or divergence

1. Stop live and inspect attempts, budget reservations and actual outcomes.
2. Reconcile final balances, fees, tip, rent and repayment in integer units.
3. If the config hash changed, discard old readiness/arm state.
4. Clear stop only with `bot live clear-stop --confirm-config-hash <full-hash>` after terminal reconciliation and fresh readiness.
