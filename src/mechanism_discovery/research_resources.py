"""PR-355 agent research-resource economy; mock/testnet/zero-cost only."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import stable_hash
from .evidence_native_core import (
    EvidenceNativeError,
    ResearchResourceSpec,
    record,
    require_int,
    require_ppm,
    require_text,
)


def register_paid_research_resource(payload: Mapping[str, Any]) -> ResearchResourceSpec:
    return ResearchResourceSpec(
        resource_uri=require_text(payload.get("resource_uri"), "resource_uri"),
        input_schema=require_text(payload.get("input_schema"), "input_schema"),
        output_schema=require_text(payload.get("output_schema"), "output_schema"),
        price_atoms=require_int(payload.get("price_atoms", 0), "price_atoms", minimum=0),
        payment_scheme=require_text(payload.get("payment_scheme"), "payment_scheme").upper(),
        latency_ms=require_int(payload.get("latency_ms", 0), "latency_ms", minimum=0),
        error_rate_ppm=require_ppm(payload.get("error_rate_ppm", 0), "error_rate_ppm"),
        trust_evidence=require_text(payload.get("trust_evidence"), "trust_evidence"),
        provenance=require_text(payload.get("provenance"), "provenance"),
        budget_cap_atoms=require_int(payload.get("budget_cap_atoms", 0), "budget_cap_atoms", minimum=0),
        expiry=require_int(payload.get("expiry"), "expiry", minimum=0),
        response_hash=payload.get("response_hash"),
        information_value_ppm=payload.get("information_value_ppm"),
        real_purchase_allowed=False,
    )


def discover_paid_resource(resources: Sequence[ResearchResourceSpec]):
    return record(
        "discover_paid_resource",
        {
            "resources": tuple(
                {
                    "resource_uri": item.resource_uri,
                    "payment_scheme": item.payment_scheme,
                    "price_atoms": item.price_atoms,
                    "expiry": item.expiry,
                }
                for item in resources
            ),
            "payment_performed": False,
            "credential_exposure": False,
        },
    )


def quote_research_purchase(payload: Mapping[str, Any]):
    price = require_int(payload.get("price_atoms"), "price_atoms", minimum=0)
    expected_value = require_ppm(payload.get("expected_information_value_ppm"), "expected_information_value_ppm")
    cap = require_int(payload.get("budget_cap_atoms"), "budget_cap_atoms", minimum=0)
    return record(
        "quote_research_purchase",
        {"price_atoms": price, "budget_cap_atoms": cap, "expected_information_value_ppm": expected_value, "within_cap": price <= cap},
    )


def authorize_bounded_resource_purchase(payload: Mapping[str, Any]):
    scheme = require_text(payload.get("payment_scheme"), "payment_scheme").upper()
    if scheme not in {"ZERO_COST", "MOCK", "TESTNET"}:
        raise EvidenceNativeError("PRODUCTION_RESOURCE_PAYMENT_FORBIDDEN")
    quoted = require_int(payload.get("quoted_atoms"), "quoted_atoms", minimum=0)
    cap = require_int(payload.get("cap_atoms"), "cap_atoms", minimum=0)
    if quoted > cap:
        raise EvidenceNativeError("RESOURCE_PURCHASE_CAP_EXCEEDED")
    return record(
        "authorize_bounded_resource_purchase",
        {"authorized_for_fixture": True, "payment_scheme": scheme, "quoted_atoms": quoted, "real_payment": False},
    )


def reconcile_resource_payment(payload: Mapping[str, Any]):
    scheme = require_text(payload.get("payment_scheme"), "payment_scheme").upper()
    if scheme not in {"ZERO_COST", "MOCK", "TESTNET"}:
        raise EvidenceNativeError("PRODUCTION_RESOURCE_PAYMENT_FORBIDDEN")
    status = require_text(payload.get("status"), "status").upper()
    charged = require_int(payload.get("charged_atoms", 0), "charged_atoms", minimum=0)
    if status in {"ERROR", "CANCELLED"} and charged != 0:
        raise EvidenceNativeError("ERROR_OR_CANCEL_CHARGED")
    response_hash = stable_hash("pr355:resource-response", payload.get("response", {}))
    return record(
        "reconcile_resource_payment",
        {
            "payment_scheme": scheme,
            "status": status,
            "charged_atoms": charged,
            "response_hash": response_hash,
            "latency_ms": require_int(payload.get("latency_ms", 0), "latency_ms", minimum=0),
            "real_payment": False,
        },
    )


def score_information_value_after_payment(payload: Mapping[str, Any]):
    utility = require_int(payload.get("utility_units"), "utility_units")
    cost = require_int(payload.get("cost_atoms"), "cost_atoms", minimum=0)
    reliability = require_ppm(payload.get("reliability_ppm"), "reliability_ppm")
    denominator = max(1, cost)
    score = utility * reliability // denominator
    return record(
        "score_information_value_after_payment",
        {"utility_units": utility, "cost_atoms": cost, "reliability_ppm": reliability, "value_per_cost_units": score, "retire": utility <= 0},
    )
