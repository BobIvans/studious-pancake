# PR-354 mechanism-discovery architecture

PR-354 is one sender-free research boundary layered on merged PR-353. Its canonical flow is:

```text
admitted point-in-time source
  -> mechanism-specific RND contract
  -> existing EVO-09 residual/correlation owner
  -> preregistered replay/walk-forward/null/FDR evaluation
  -> RESEARCH_CLOSED / REJECTED / BLOCKED / INCONCLUSIVE / VERIFIED_SHADOW
```

All twelve RND packages are checked in DISABLED. Research records are content-addressed, exact-value only, preserve event_time/received_at/available_at when time-bearing, reject stale/contradicted state, and embed explicit no-execution/no-live/no-auto-promotion fields.

The new Protocol Mechanism Compiler emits only quarantined dossiers, adapter skeleton descriptions and test-vector descriptions. It cannot install code, mutate configuration, enqueue opportunities, sign, submit, fund a wallet, or grant live permission.

The Deployment Watcher is also research-only: registry/deployment deltas become quarantined hypotheses and coverage gaps routed to the existing EVO-09 owner.
