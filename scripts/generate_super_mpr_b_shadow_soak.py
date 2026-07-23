#!/usr/bin/env python3
"""Generate a bounded SUPER-MPR-B shadow-soak report.

The CI/default report is intentionally synthetic and must not unlock promotion.
It exercises the exact schema used by real multi-day shadow campaigns while
keeping live/Jito/signer access unavailable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.economic_authority_super_mpr_b import build_shadow_soak_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("release_artifacts/shadow_soak_report.json"))
    parser.add_argument("--runtime-version", default="ci-bounded-shadow-soak")
    parser.add_argument("--wheel-digest", default="sha256:missing-real-wheel-digest")
    parser.add_argument("--config-digest", default="sha256:missing-real-config-digest")
    args = parser.parse_args(argv)

    report = build_shadow_soak_report(
        runtime_version=args.runtime_version,
        wheel_digest=args.wheel_digest,
        config_digest=args.config_digest,
        provider_set=("ci-offline-provider",),
        rpc_set=("ci-offline-rpc",),
        opportunities_seen=0,
        opportunities_rejected_by_reason={"ci_bounded_soak_no_live_data": 0},
        opportunities_admitted=0,
        paper_simulations=0,
        paper_settlements=0,
        expired_quotes=0,
        provider_errors=0,
        rpc_errors=0,
        restart_count=0,
        recovery_count=0,
        capital_ledger_reconciled=True,
        max_drawdown_paper=0,
        gross_pnl_paper=0,
        net_pnl_paper=0,
        fee_rent_repayment_impact=0,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
