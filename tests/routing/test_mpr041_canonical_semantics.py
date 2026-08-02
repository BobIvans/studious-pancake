from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest

from src.routing.adapters import JupiterRouterAdapter, OdosAdapter, OkxDexAdapter
from src.routing.dimensions import (
    BasisPoints,
    DimensionError,
    PercentMicros,
    exact_non_negative_int,
)
from src.routing.limiter import FakeClock
from src.routing.models import (
    EchoProofState,
    ExecutionArtifactKind,
    FreshnessSource,
    GuaranteeSource,
    MinimumOutputState,
    NormalizedQuote,
    QuoteRequest,
    SwapMode,
)
from src.routing.route_graph import (
    RouteEdge,
    RouteEdgeKind,
    RouteGraph,
    RouteGraphError,
)

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"
TOKEN_B = "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utD2TQMg1Fy"
TOKEN_C = "Es9vMFrzaCERmJfrF4H2FYD3vA8MouS3xJdVug28"


def request(*, bps: int = 50) -> QuoteRequest:
    return QuoteRequest(
        input_mint=SOL,
        output_mint=USDC,
        amount_base_units=1_000_000,
        user_wallet=WALLET,
        slippage_bps=bps,
        input_decimals=9,
        output_decimals=6,
    )


@pytest.mark.parametrize(
    ("bps", "percent"),
    [
        (1, "0.01"),
        (5, "0.05"),
        (10, "0.1"),
        (25, "0.25"),
        (50, "0.5"),
        (100, "1"),
        (10_000, "100"),
    ],
)
def test_basis_points_serialize_without_binary_float(bps: int, percent: str) -> None:
    assert BasisPoints(bps).to_percent_text() == percent
    assert PercentMicros.parse(percent).to_decimal_text() == percent


def test_dimension_boundary_rejects_bool_scientific_notation_and_overprecision() -> (
    None
):
    with pytest.raises(DimensionError):
        BasisPoints(True)  # type: ignore[arg-type]
    with pytest.raises(DimensionError):
        exact_non_negative_int(True, "slot")
    with pytest.raises(DimensionError):
        PercentMicros.parse("1e-3")
    with pytest.raises(DimensionError):
        PercentMicros.parse("0.0000001")


def test_quote_request_rejects_self_swap() -> None:
    with pytest.raises(ValueError, match="must differ"):
        QuoteRequest(SOL, SOL, 1, WALLET, 50)


def _edge(
    *,
    stage: int,
    branch: int,
    pool: str,
    input_mint: str,
    output_mint: str,
    input_amount: int,
    output_amount: int,
    bps: int,
) -> RouteEdge:
    return RouteEdge(
        stage=stage,
        branch=branch,
        kind=RouteEdgeKind.SWAP,
        provider="fixture",
        venue="venue",
        pool_key=pool,
        program_id="program",
        input_mint=input_mint,
        output_mint=output_mint,
        input_amount=input_amount,
        output_amount=output_amount,
        allocation_bps=BasisPoints(bps),
        source_path=f"route[{stage}][{branch}]",
        writable_accounts=(f"account-{pool}",),
    )


def test_split_merge_graph_conserves_value_and_hashes_independent_of_order() -> None:
    edges = (
        _edge(
            stage=0,
            branch=0,
            pool="pool-a",
            input_mint=SOL,
            output_mint=TOKEN_B,
            input_amount=600,
            output_amount=60,
            bps=6000,
        ),
        _edge(
            stage=0,
            branch=1,
            pool="pool-b",
            input_mint=SOL,
            output_mint=TOKEN_C,
            input_amount=400,
            output_amount=40,
            bps=4000,
        ),
        _edge(
            stage=1,
            branch=0,
            pool="pool-c",
            input_mint=TOKEN_B,
            output_mint=USDC,
            input_amount=60,
            output_amount=55,
            bps=6000,
        ),
        _edge(
            stage=1,
            branch=1,
            pool="pool-d",
            input_mint=TOKEN_C,
            output_mint=USDC,
            input_amount=40,
            output_amount=35,
            bps=4000,
        ),
    )
    first = RouteGraph(
        provider="fixture",
        input_mint=SOL,
        output_mint=USDC,
        input_amount=1000,
        expected_output=90,
        guaranteed_output=85,
        edges=edges,
        asset_generation="asset-gen-1",
    )
    second = RouteGraph(
        provider="fixture",
        input_mint=SOL,
        output_mint=USDC,
        input_amount=1000,
        expected_output=90,
        guaranteed_output=85,
        edges=tuple(reversed(edges)),
        asset_generation="asset-gen-1",
    )
    assert first.semantic_hash == second.semantic_hash
    assert first.resource_footprint.pools == (
        "pool-a",
        "pool-b",
        "pool-c",
        "pool-d",
    )
    assert first.resource_footprint.writable_accounts == (
        "account-pool-a",
        "account-pool-b",
        "account-pool-c",
        "account-pool-d",
    )


def test_route_graph_rejects_allocation_and_conservation_errors() -> None:
    bad_allocation = (
        _edge(
            stage=0,
            branch=0,
            pool="pool-a",
            input_mint=SOL,
            output_mint=USDC,
            input_amount=1000,
            output_amount=900,
            bps=9000,
        ),
    )
    with pytest.raises(RouteGraphError, match="sum to 10000"):
        RouteGraph("fixture", SOL, USDC, 1000, 900, 850, bad_allocation)

    overconsuming = (
        _edge(
            stage=0,
            branch=0,
            pool="pool-a",
            input_mint=SOL,
            output_mint=USDC,
            input_amount=1001,
            output_amount=900,
            bps=10_000,
        ),
    )
    with pytest.raises(RouteGraphError, match="only 1000 available"):
        RouteGraph("fixture", SOL, USDC, 1000, 900, 850, overconsuming)


def test_provider_request_serialization_is_exact_text() -> None:
    req = request(bps=1)
    okx = OkxDexAdapter(api_key="k", passphrase="p", secret="s")
    assert okx.build_params(req)["slippagePercent"] == "0.01"
    assert OdosAdapter().quote_body(req)["slippageLimitPercent"] == "0.01"


def test_jupiter_preserves_full_hop_identity_and_validates_echo() -> None:
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    adapter = JupiterRouterAdapter(clock=FakeClock(now))
    payload = {
        "inputMint": SOL,
        "outputMint": USDC,
        "inAmount": "1000000",
        "outAmount": "150000",
        "otherAmountThreshold": "148000",
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "routePlan": [
            {
                "bps": 10000,
                "swapInfo": {
                    "ammKey": "Pool11111111111111111111111111111111111111",
                    "label": "Meteora",
                    "inputMint": SOL,
                    "outputMint": USDC,
                    "inAmount": "1000000",
                    "outAmount": "150000",
                    "programId": "11111111111111111111111111111111",
                },
            }
        ],
        "requestId": "request-1",
        "contextSlot": 350000000,
        "priceImpactPct": "0.001",
    }
    quote = adapter.normalize_build(request(), payload)
    assert quote.route_graph is not None
    edge = quote.route_graph.edges[0]
    assert edge.pool_key == "Pool11111111111111111111111111111111111111"
    assert edge.input_mint == SOL and edge.output_mint == USDC
    assert edge.input_amount == 1_000_000 and edge.output_amount == 150_000
    assert quote.minimum_output == 148_000
    assert quote.guarantee_source is GuaranteeSource.PROVIDER_THRESHOLD
    assert quote.response_echo_state is EchoProofState.PROVEN
    assert quote.freshness_source is FreshnessSource.REVIEWED_CONTRACT_TTL
    assert quote.price_impact_percent_micros == PercentMicros(1000)

    with pytest.raises(ValueError, match="swap mode"):
        adapter.normalize_build(request(), payload | {"swapMode": "ExactOut"})
    with pytest.raises(ValueError, match="slippage"):
        adapter.normalize_build(request(), payload | {"slippageBps": 51})


def test_missing_expiry_fails_closed() -> None:
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    capabilities = JupiterRouterAdapter.capabilities
    quote = NormalizedQuote(
        provider="fixture",
        request_fingerprint="fingerprint",
        raw_response_hash="hash",
        external_id="external",
        input_mint=SOL,
        output_mint=USDC,
        input_amount=1,
        expected_output=1,
        minimum_output=1,
        minimum_output_state=MinimumOutputState.PROVEN,
        swap_mode=SwapMode.EXACT_IN,
        slippage_bps=1,
        route_provenance=("route",),
        dex_sources=("venue",),
        price_impact_pct="0",
        provider_fee=None,
        platform_fee=None,
        context_slot=1,
        received_at=now,
        expires_at=None,
        artifact_kind=ExecutionArtifactKind.RAW_INSTRUCTIONS,
        capabilities=capabilities,
        diagnostic_trace_id="trace",
    )
    assert not quote.is_fresh(now)


def test_active_boundary_contains_no_float_percent_serialization() -> None:
    root = Path(__file__).parents[2]
    source = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in ("src/routing/adapters.py", "src/routing/clients.py")
    )
    assert "/ 100" not in source
    assert "float(" not in source


def test_validation_remains_active_under_optimized_python() -> None:
    code = """
from src.routing.models import QuoteRequest
SOL='So11111111111111111111111111111111111111112'
W='11111111111111111111111111111111'
try:
    QuoteRequest(SOL, SOL, 1, W, 50)
except ValueError:
    print('blocked')
else:
    raise SystemExit(2)
"""
    result = subprocess.run(
        [sys.executable, "-O", "-c", code],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "blocked"


def test_review_regressions_fail_closed() -> None:
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    adapter = JupiterRouterAdapter(clock=FakeClock(now))
    payload = {
        "inputMint": SOL,
        "outputMint": USDC,
        "inAmount": "1000000",
        "outAmount": "150000",
        "otherAmountThreshold": "148000",
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "routePlan": [
            {
                "bps": 10000,
                "percent": 100,
                "swapInfo": {
                    "ammKey": "Pool11111111111111111111111111111111111111",
                    "label": "Meteora",
                    "inputMint": SOL,
                    "outputMint": USDC,
                    "inAmount": "1000000",
                    "outAmount": "150000",
                },
            }
        ],
    }

    missing_mode = deepcopy(payload)
    missing_mode.pop("swapMode")
    with pytest.raises(ValueError, match="swap mode echo"):
        adapter.normalize_build(request(), missing_mode)

    missing_slippage = deepcopy(payload)
    missing_slippage.pop("slippageBps")
    with pytest.raises(ValueError, match="slippage echo"):
        adapter.normalize_build(request(), missing_slippage)

    missing_pool = deepcopy(payload)
    missing_pool["routePlan"][0]["swapInfo"].pop("ammKey")
    with pytest.raises(ValueError, match="ammKey"):
        adapter.normalize_build(request(), missing_pool)

    fractional_bps = deepcopy(payload)
    fractional_bps["routePlan"][0]["bps"] = 9999.9
    with pytest.raises((ValueError, DimensionError)):
        adapter.normalize_build(request(), fractional_bps)

    fractional_percent = deepcopy(payload)
    fractional_percent["routePlan"][0].pop("bps")
    fractional_percent["routePlan"][0]["percent"] = 99.9
    with pytest.raises((ValueError, DimensionError)):
        adapter.normalize_build(request(), fractional_percent)

    conflicting = deepcopy(payload)
    conflicting["routePlan"][0]["percent"] = 99
    with pytest.raises(ValueError, match="allocation fields disagree"):
        adapter.normalize_build(request(), conflicting)


def test_route_graph_rejects_overproduction_and_residual_input() -> None:
    overproducing = (
        _edge(
            stage=0,
            branch=0,
            pool="pool-over",
            input_mint=SOL,
            output_mint=USDC,
            input_amount=1000,
            output_amount=901,
            bps=10_000,
        ),
    )
    with pytest.raises(RouteGraphError, match="must equal"):
        RouteGraph("fixture", SOL, USDC, 1000, 900, 850, overproducing)

    residual_input = (
        _edge(
            stage=0,
            branch=0,
            pool="pool-residual",
            input_mint=SOL,
            output_mint=USDC,
            input_amount=999,
            output_amount=900,
            bps=10_000,
        ),
    )
    with pytest.raises(RouteGraphError, match="unconsumed"):
        RouteGraph("fixture", SOL, USDC, 1000, 900, 850, residual_input)
