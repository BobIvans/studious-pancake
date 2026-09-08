# MPR-043 — Dependency governance, provider entitlement and deadline-aware admission

## Scope

This compressed residual Mega-PR absorbs the former PR-047, PR-051 and PR-044 workstreams. It establishes one installed runtime authority for provider dependency state, entitlement/spend accounting and admission scheduling.

## Runtime authority

`src.provider_governance` owns:

- immutable provider entitlement manifests bound to reviewed capability generations;
- request, cost-unit, monetary-spend and concurrency reservations;
- protected finalization capacity that discovery cannot consume;
- leased work states (`reserved`, `issued`, `completed`, `released`, `expired`);
- fail-closed degraded, cooldown and disabled dependency transitions;
- fair deadline-aware queuing across independent fairness keys;
- cancellation semantics that commit an issued external request rather than falsely releasing it;
- snapshots suitable for startup diagnostics and operational evidence.

## Discovery-plane cutover

`src.routing.registry.DiscoveryPlane` now requests a governance lease before every enabled provider call. Admission denial is materialized as a typed provider failure and the provider is not contacted. Provider results feed the dependency state machine, while the existing Jupiter quota manager remains a provider-specific secondary hard boundary below the unified admission authority.

## Safety properties

1. Work built for an old entitlement generation cannot consume a new generation.
2. Expired or unauthorized manifests fail closed.
3. Non-finalization work cannot consume protected finalization request/cost/spend capacity.
4. A degraded provider cannot refine or finalize executable routes.
5. Rate limits and circuit failures move the provider into bounded cooldown.
6. Invalid schemas and disabled/auth failures require a new generation or explicit health-probe recovery.
7. Work that expires in the queue never reaches the provider.
8. Once work is marked issued, cancellation still consumes its reserved budget.
9. Startup reports expose dependency mode, manifest hash, generation and limits.

## Traceability

The implementation preserves the compressed-roadmap identifiers `R047-*`, `R051-*` and `R044-*` at the Mega-PR level. The former individual PR scopes are internal workstreams, not separate merge units.
