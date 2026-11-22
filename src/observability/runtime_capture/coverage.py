"""Route coverage matrix for runtime capture (OCA-W10).

Every supported route gets an explicit status: WIRED (real producer path
exercised), PARTIAL, NO_RUNTIME_PATH, BLOCKED, or UNKNOWN — never inferred
from static call graphs.
"""

from __future__ import annotations

from typing import Any

COVERAGE_SCHEMA = "studious.observability.capture-coverage.v1"


def coverage_matrix() -> dict[str, Any]:
    return {
        "schema": COVERAGE_SCHEMA,
        "routes": [
            {
                "route": "paper-shadow:solana:atomic-vertical",
                "status": "PARTIAL",
                "evidence": "tests/intelligence/test_runtime_capture.py::test_vertical_end_to_end_and_replay",
                "note": "P2-2 downgrade: capture path proven in tests only; no production caller invokes the adapter on the installed boot path yet (grep-verified). Upgrades to WIRED only with a wired production callsite + receipt.",
                "wiring_gap": "no production caller of RuntimeCaptureAdapter outside tests",
                "owner": "OCA-W10 follow-up",
            },
            {
                "route": "paper-shadow:solana:durable-service",
                "status": "PARTIAL",
                "note": "adapter reusable via default_vertical_adapter; durable-service integration not wired in this lane",
                "owner": "OCA-W10 follow-up",
            },
            {
                "route": "paper-shadow:sui",
                "status": "NO_RUNTIME_PATH",
                "note": "no supported Sui paper runtime route exists on this main",
            },
            {
                "route": "submission:any",
                "status": "BLOCKED",
                "note": "submission routes are hard-denied (no signing/sending authority); capture limited to pre-submission stages",
            },
            {
                "route": "live:any",
                "status": "BLOCKED",
                "note": "LIVE hard-denied by repository policy",
            },
        ],
        "counts": {
            "WIRED": 0,
            "PARTIAL": 2,
            "NO_RUNTIME_PATH": 1,
            "BLOCKED": 2,
            "UNKNOWN": 0,
        },
        "principle": "runtime coverage is measured only against enumerated supported routes; STATIC_ONLY graph edges never imply execution",
    }
