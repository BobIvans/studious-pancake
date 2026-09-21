"""PR-355 Liquidity Shape / Hybrid Execution IR specialization."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_native_core import (
    EvidenceNativeError,
    LiquidityShapeSpec,
    record,
    require_int,
    require_ppm,
    require_text,
)


def define_liquidity_shape(payload: Mapping[str, Any]) -> LiquidityShapeSpec:
    return LiquidityShapeSpec(
        shape_id=require_text(payload.get("shape_id"), "shape_id"),
        deployment_id=require_text(payload.get("deployment_id"), "deployment_id"),
        shape_family=require_text(payload.get("shape_family"), "shape_family"),
        parameters=dict(payload.get("parameters", {})),
        support_low_atoms=require_int(payload.get("support_low_atoms"), "support_low_atoms"),
        support_high_atoms=require_int(payload.get("support_high_atoms"), "support_high_atoms"),
        total_liquidity_atoms=require_int(payload.get("total_liquidity_atoms"), "total_liquidity_atoms", minimum=0),
        withdrawable_liquidity_atoms=require_int(payload.get("withdrawable_liquidity_atoms"), "withdrawable_liquidity_atoms", minimum=0),
        dynamic_fee_ppm=require_ppm(payload.get("dynamic_fee_ppm", 0), "dynamic_fee_ppm"),
        contexts=tuple(str(x) for x in payload.get("contexts", ())),
        transition_at=require_int(payload.get("transition_at", 0), "transition_at", minimum=0),
        shared_dependencies=tuple(str(x) for x in payload.get("shared_dependencies", ())),
        available_at=require_int(payload.get("available_at"), "available_at", minimum=0),
        revision=require_int(payload.get("revision", 0), "revision", minimum=0),
    )


def compile_liquidity_shape_surface(payload: Mapping[str, Any]):
    capacity = require_int(payload.get("capacity_atoms"), "capacity_atoms", minimum=0)
    requested = require_int(payload.get("requested_atoms"), "requested_atoms", minimum=0)
    fee_ppm = require_ppm(payload.get("fee_ppm", 0), "fee_ppm")
    executable = min(capacity, requested)
    fee_atoms = executable * fee_ppm // 1_000_000
    return record(
        "compile_liquidity_shape_surface",
        {
            "direction": require_text(payload.get("direction"), "direction"),
            "caller_context": require_text(payload.get("caller_context"), "caller_context"),
            "requested_atoms": requested,
            "executable_atoms": executable,
            "fee_atoms": fee_atoms,
            "fully_supported": executable == requested,
        },
    )


def project_dynamic_liquidity_shape(payload: Mapping[str, Any]):
    base = require_int(payload.get("base_capacity_atoms"), "base_capacity_atoms", minimum=0)
    withdrawal = require_int(payload.get("withdrawal_atoms", 0), "withdrawal_atoms", minimum=0)
    jit = require_int(payload.get("jit_add_atoms", 0), "jit_add_atoms", minimum=0)
    virtual_delta = require_int(payload.get("virtual_balance_delta_atoms", 0), "virtual_balance_delta_atoms")
    uncertainty = require_int(payload.get("uncertainty_atoms", 0), "uncertainty_atoms", minimum=0)
    projected = max(0, base - withdrawal + jit + virtual_delta - uncertainty)
    return record(
        "project_dynamic_liquidity_shape",
        {
            "projected_capacity_atoms": projected,
            "uncertainty_atoms": uncertainty,
            "transition_at": require_int(payload.get("transition_at"), "transition_at", minimum=0),
        },
    )


def compare_hybrid_execution_paths(paths: Sequence[Mapping[str, Any]]):
    normalized = []
    constraint_id: str | None = None
    for item in paths:
        cid = require_text(item.get("constraint_id"), "constraint_id")
        if constraint_id is None:
            constraint_id = cid
        elif cid != constraint_id:
            raise EvidenceNativeError("HYBRID_CONSTRAINT_MISMATCH")
        normalized.append(
            {
                "path_id": require_text(item.get("path_id"), "path_id"),
                "kind": require_text(item.get("kind"), "kind"),
                "net_output_atoms": require_int(item.get("net_output_atoms"), "net_output_atoms"),
                "latency_ms": require_int(item.get("latency_ms"), "latency_ms", minimum=0),
                "capacity_atoms": require_int(item.get("capacity_atoms"), "capacity_atoms", minimum=0),
            }
        )
    if not normalized:
        raise EvidenceNativeError("HYBRID_PATH_REQUIRED")
    best = max(normalized, key=lambda row: (row["net_output_atoms"], -row["latency_ms"]))
    return record(
        "compare_hybrid_execution_paths",
        {"constraint_id": constraint_id, "paths": tuple(normalized), "best_path_id": best["path_id"]},
    )


def estimate_lvr_and_lp_response(payload: Mapping[str, Any]):
    external_move = require_int(payload.get("external_move_atoms"), "external_move_atoms")
    pool_move = require_int(payload.get("pool_move_atoms"), "pool_move_atoms")
    protective_fee = require_int(payload.get("protective_fee_atoms", 0), "protective_fee_atoms", minimum=0)
    lvr_proxy = abs(external_move - pool_move)
    return record(
        "estimate_lvr_and_lp_response",
        {
            "lvr_proxy_atoms": lvr_proxy,
            "protective_fee_atoms": protective_fee,
            "residual_after_fee_atoms": max(0, lvr_proxy - protective_fee),
            "research_feature_only": True,
        },
    )


def stress_liquidity_shape(payload: Mapping[str, Any]):
    capacity = require_int(payload.get("capacity_atoms"), "capacity_atoms", minimum=0)
    parameter_loss_ppm = require_ppm(payload.get("parameter_loss_ppm", 0), "parameter_loss_ppm")
    withdrawal_limit = require_int(payload.get("withdrawal_limit_atoms", capacity), "withdrawal_limit_atoms", minimum=0)
    stressed = min(withdrawal_limit, capacity * (1_000_000 - parameter_loss_ppm) // 1_000_000)
    return record(
        "stress_liquidity_shape",
        {
            "base_capacity_atoms": capacity,
            "stressed_capacity_atoms": stressed,
            "unsafe_if_zero": stressed == 0,
            "incident_replay": bool(payload.get("incident_replay", False)),
        },
    )
