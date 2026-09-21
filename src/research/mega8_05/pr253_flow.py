"""PR-253 / FLOW-01: public flow/meta-order/toxicity research."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, mean, probability


def classify_wallet_flow(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    classes = []
    for item in observations:
        signed_amount = float(item.get("signed_amount", 0.0))
        classes.append(
            {
                "wallet": str(item.get("wallet", "UNKNOWN")),
                "direction": (
                    "buy"
                    if signed_amount > 0
                    else "sell" if signed_amount < 0 else "flat"
                ),
                "magnitude": abs(signed_amount),
                "public_evidence_only": True,
            }
        )
    return artifact(
        "wallet-flow-classes",
        {"classes": classes, "deanonymization_claimed": False},
    )


def infer_meta_order(
    signed_amounts: Sequence[float],
    *,
    minimum_run: int = 3,
) -> ResearchArtifact:
    values = tuple(float(value) for value in signed_amounts)
    if not values:
        raise ValueError("signed_amounts cannot be empty")
    sign = 1 if values[0] > 0 else -1 if values[0] < 0 else 0
    run = 0
    for value in values:
        current = 1 if value > 0 else -1 if value < 0 else 0
        if current == sign and sign != 0:
            run += 1
        else:
            break
    inferred = run >= minimum_run
    confidence = min(1.0, run / max(minimum_run * 2, 1))
    return artifact(
        "meta-order-hypothesis",
        {"inferred": inferred, "run": run, "confidence": confidence},
        disposition=Disposition.PASS if inferred else Disposition.UNKNOWN,
        reason="bounded-public-hypothesis" if inferred else "insufficient-pattern",
    )


def estimate_flow_toxicity(
    signed_amounts: Sequence[float],
    subsequent_markouts: Sequence[float],
) -> ResearchArtifact:
    if len(signed_amounts) != len(subsequent_markouts) or not signed_amounts:
        raise ValueError("flow and markouts must be non-empty and aligned")
    adverse = [
        1.0 if float(flow) * float(markout) < 0.0 else 0.0
        for flow, markout in zip(signed_amounts, subsequent_markouts, strict=True)
    ]
    return artifact(
        "flow-toxicity",
        {"toxicity": mean(adverse), "sample_count": len(adverse)},
    )


def route_flow_signal(
    signal: ResearchArtifact,
    *,
    destination: str,
    minimum_confidence: float = 0.5,
) -> ResearchArtifact:
    if destination not in {"ranking", "stress"}:
        raise ValueError("flow signals may route only to ranking or stress")
    confidence = float(signal.payload.get("confidence", 1.0))
    passed = confidence >= probability(minimum_confidence, "minimum_confidence")
    return artifact(
        "flow-signal-route",
        {
            "signal": signal.identity,
            "destination": destination,
            "execution_authority": False,
            "harmful_frontrunning_allowed": False,
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason="research-route" if passed else "confidence-too-low",
    )


__all__ = [
    "classify_wallet_flow",
    "estimate_flow_toxicity",
    "infer_meta_order",
    "route_flow_signal",
]
