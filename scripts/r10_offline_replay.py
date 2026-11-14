"""R10 bounded offline replay runner (read-only strategies/intelligence audit).

Re-runs the four deterministic experiments from
tests/test_r10_strategy_inventory_replay.py against the existing intelligence
owners and prints a machine-readable receipt:

A. residual family fail-closed gates (src/research/correlation_ledger/residuals.py)
B. correlation-ledger lead/lag provenance gating (src/research/correlation_ledger/ledger.py)
C. multihop bounded search + exact-evaluation binding (src/strategy/multihop_solver.py)
D. relation-generator discovery + identity/capital fail-closed gates
   (src/strategy/relation_generators/generators.py)

No network access, no sender, no live evidence. Correlation/model outputs in
this receipt are advisory research signals (DISCOVERY_ONLY) and never qualify a
route; they cannot promote any strategy family past shadow/paper.

Convention mirror: scripts/verify_agg14_research.py (verify(root) -> dict,
argparse --json, exit 0 on success).
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_r10_strategy_inventory_replay import (  # noqa: E402
    _experiment_graph,
    _fixture_universe,
    _ledger_observation,
    _LIMITS,
    _variant,
)
from tests.test_dynamic_asset_resolution import MINT, OTHER, evidence  # noqa: E402
from tests.test_dynamic_flash_capital import capital  # noqa: E402
from tests.test_relation_h_generators import THIRD, asset  # noqa: E402

from src.assets.resolution.resolver import ResolutionState  # noqa: E402
from src.research.correlation_ledger.ledger import (  # noqa: E402
    CorrelationLedger,
)
from src.research.correlation_ledger.residuals import (  # noqa: E402
    lst_premium_residual,
    oracle_market_residual,
    residual_observation,
)
from src.strategy.multihop_solver import (  # noqa: E402
    RouteRejection,
    evaluate_shortlisted_routes,
    rank_resource_feasible_routes,
    search_bounded_cycles,
)
from src.strategy.relation_generators.generators import (  # noqa: E402
    generate,
)


def _experiment_a_residual_gates() -> dict[str, object]:
    """Unproven proofs are excluded with typed reasons; proven aligned samples
    compute exact residual values and materialize as ledger observations."""
    excluded = {
        "lst_rate_unproven": lst_premium_residual(
            lst_price=1.05,
            underlying_price=1.0,
            exchange_rate=1.02,
            scale=1.0,
            rate_proven=False,
            instant_exit_available=True,
            instant_exit_cost=0.005,
            evidences=(
                evidence("oracle", position=1000, timestamp=200),
                evidence("amm", position=1001, timestamp=200.5),
            ),
        ),
        "oracle_slot_misaligned": oracle_market_residual(
            market_price=100.5,
            oracle_price=100.0,
            confidence_scale=0.2,
            evidences=(
                evidence("oracle", position=1000, timestamp=200),
                evidence("amm", position=1005, timestamp=200),
            ),
        ),
    }
    for name, sample in excluded.items():
        if sample.value is not None or not sample.exclusions:
            raise ValueError(f"R10_EXCLUSION_GATE_NOT_FAIL_CLOSED:{name}")
    proven = lst_premium_residual(
        lst_price=1.05,
        underlying_price=1.0,
        exchange_rate=1.02,
        scale=1.0,
        rate_proven=True,
        instant_exit_available=True,
        instant_exit_cost=0.005,
        evidences=(
            evidence("oracle", position=1000, timestamp=200),
            evidence("amm", position=1001, timestamp=200.5),
        ),
    )
    if proven.value is None or proven.exclusions:
        raise ValueError("R10_PROVEN_RESIDUAL_NOT_COMPUTED")
    with tempfile.TemporaryDirectory(prefix="r10-ledger-") as scratch:
        ledger = CorrelationLedger(Path(scratch), "campaign")
        materialized = residual_observation(
            proven,
            chain="solana",
            market_id="lst-amm",
            relation_id="relation-lst",
            evidence=evidence("amm", position=1001, timestamp=200.5),
            liquidity_resources=("lst-amm",),
            regime="quiet",
        )
        if materialized is None:
            raise ValueError("R10_PROVEN_OBSERVATION_NOT_MATERIALIZED")
        ledger.append(materialized)
        stored = len(ledger.observations())
    if stored != 1:
        raise ValueError("R10_LEDGER_ROW_COUNT_MISMATCH")
    return {
        "excluded_samples_value_none": sorted(excluded),
        "excluded_reasons_typed": True,
        "proven_lst_premium_value": round(proven.value, 12),
        "materialized_ledger_rows": stored,
    }


def _experiment_b_lead_lag_gating() -> dict[str, object]:
    """Lead/lag windows run only over CHAIN_ALIGNED samples; UNALIGNED samples
    are excluded with a typed reason; shared groups collapse confidence."""
    values = (0.2, -0.4, 0.6, -0.1, 0.3)
    aligned = tuple(
        observation
        for i, value in enumerate(values)
        for observation in (
            _ledger_observation("amms", 200 + i, value),
            _ledger_observation("clob", 200.1 + i, value * 2),
        )
    )
    with tempfile.TemporaryDirectory(prefix="r10-leadlag-") as scratch:
        ledger = CorrelationLedger(Path(scratch), "campaign")
        ledger.append_many(
            aligned + (_ledger_observation("clob", 204.5, 9.9, aligned=False),)
        )
        report = ledger.lead_lag_report(
            "amms", "clob", (5,), feature="stable_residual", now=205, lags=(0, 0.1)
        )
        shared = CorrelationLedger(Path(scratch) / "shared", "campaign")
        shared.append_many(
            tuple(
                observation
                for i in range(5)
                for observation in (
                    _ledger_observation("amms", 200 + i, i, group="shared"),
                    _ledger_observation("clob", 200.1 + i, i * 2, group="shared"),
                )
            )
        )
        shared_report = shared.lead_lag_report(
            "amms", "clob", (5,), feature="stable_residual", now=205, lags=(0.1,)
        )
    best = max(
        (f for f in report.findings if f.sample_count),
        key=lambda f: f.sample_count,
    )
    if not report.exclusions or report.exclusions[0].reason != (
        "timestamp_alignment_unproven"
    ):
        raise ValueError("R10_ALIGNMENT_EXCLUSION_MISSING")
    if best.correlation is None or abs(best.correlation - 1.0) > 1e-9:
        raise ValueError("R10_LEAD_LAG_CORRELATION_UNEXPECTED")
    if shared_report.findings[0].confidence != 0:
        raise ValueError("R10_ALIAS_PENALTY_NOT_APPLIED")
    return {
        "observations_total": 11,
        "unaligned_excluded_typed": True,
        "exclusion_reason": report.exclusions[0].reason,
        "best_lag_seconds": best.lag_seconds,
        "best_sample_count": best.sample_count,
        "best_correlation": round(best.correlation, 12),
        "best_confidence": round(best.confidence, 12),
        "shared_group_confidence": 0,
        "verification_state": best.verification_state,
    }


def _experiment_c_multihop_binding() -> dict[str, object]:
    """Bounded shortlist finds 2-3-hop cycles; a 0.99-product cycle stays
    excluded; exact evaluation with negative net rejects NON_POSITIVE_NET."""
    result = search_bounded_cycles(_experiment_graph(), start_asset="A")
    two_hop = next(route for route in result.routes if route.hop_count == 2)
    three_hop = next(route for route in result.routes if route.hop_count == 3)
    strict = search_bounded_cycles(
        _experiment_graph(), start_asset="A", minimum_marginal_gain_ppm=5000
    )
    lossy = evaluate_shortlisted_routes(
        (two_hop,),
        exact_evaluator=lambda route: _variant(route, conservative_net_units=-50),
        max_evaluations=8,
    )
    ranked = rank_resource_feasible_routes(lossy.variants, limits=_LIMITS)
    if ranked.rejections != ((two_hop.route_id, RouteRejection.NON_POSITIVE_NET),):
        raise ValueError("R10_EXACT_BINDING_NOT_FAIL_CLOSED")
    profitable = evaluate_shortlisted_routes(
        (three_hop,),
        exact_evaluator=lambda route: _variant(route, conservative_net_units=40),
        max_evaluations=8,
    )
    accepted = rank_resource_feasible_routes(profitable.variants, limits=_LIMITS)
    if len(accepted.accepted) != 1:
        raise ValueError("R10_POSITIVE_EXACT_EVALUATION_UNEXPECTED")
    return {
        "default_shortlist_hops": sorted(route.hop_count for route in result.routes),
        "default_stop_reason": result.stop_reason.value,
        "strict_50ppm_shortlist_hops": sorted(
            route.hop_count for route in strict.routes
        ),
        "negative_net_rejection": ranked.rejections[0][1].value,
        "positive_net_accepted": len(accepted.accepted),
        "exact_evaluations": 2,
    }


def _experiment_d_relation_gates() -> dict[str, object]:
    """Discovery emissions carry liquidity provenance; the identity gate and
    FLASH_CAPITAL lender-qualification gates fail closed."""
    assets, markets = _fixture_universe()
    batch = generate(
        assets, markets, (), hubs=frozenset((OTHER,)), now=101, generation="campaign"
    )
    counts = dict(sorted(Counter(r.kind for r in batch.relations).items()))
    for relation in batch.relations:
        if relation.market_ids and not (
            relation.correlation_groups and relation.liquidity_resources
        ):
            raise ValueError("R10_MARKET_RELATION_MISSING_PROVENANCE")
    unverified_hub = replace(asset(OTHER), verification_state=ResolutionState.CANDIDATE)
    gated = generate(
        (asset(MINT), unverified_hub, asset(THIRD)),
        markets,
        (),
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
    )
    if [r.kind for r in gated.relations] != ["DIRECT_MARKET"]:
        raise ValueError("R10_IDENTITY_GATE_NOT_FAIL_CLOSED")
    qualified = capital()
    capital_batch = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(qualified,),
    )
    denied = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(
            replace(qualified, max_amount_live=0),
            replace(qualified, evidence=evidence("lender", 10, timestamp=1)),
            replace(qualified, asset_id="unverified"),
        ),
    )
    if [r.kind for r in capital_batch.relations] != [
        "FLASH_CAPITAL"
    ] or denied.relations:
        raise ValueError("R10_CAPITAL_GATE_NOT_FAIL_CLOSED")
    return {
        "discovered_relation_kinds": counts,
        "market_relations_carry_provenance": True,
        "unverified_hub_relation_kinds": [r.kind for r in gated.relations],
        "qualified_capital_relations": [r.kind for r in capital_batch.relations],
        "denied_capital_relations": len(denied.relations),
    }


def verify(root: Path) -> dict[str, object]:  # noqa: ARG001 - convention signature
    return {
        "schema": "r10.offline-replay.v1",
        "ok": True,
        "base_sha": "e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8",
        "experiments": {
            "a_residual_gates": _experiment_a_residual_gates(),
            "b_lead_lag_gating": _experiment_b_lead_lag_gating(),
            "c_multihop_binding": _experiment_c_multihop_binding(),
            "d_relation_gates": _experiment_d_relation_gates(),
        },
        "advisory_only": True,
        "live_enabled": False,
        "signing_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(ROOT)
    print(json.dumps(result, sort_keys=True, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
