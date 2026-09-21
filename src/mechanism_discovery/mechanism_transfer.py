"""PR-355 mechanism fingerprints and transfer-learning research harness."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import stable_hash
from .evidence_native_core import EvidenceNativeError, record, require_int, require_ppm, require_text


def build_mechanism_fingerprint(payload: Mapping[str, Any]):
    canonical = {
        "rights": tuple(sorted(str(x) for x in payload.get("rights", ()))),
        "cashflows": tuple(sorted(str(x) for x in payload.get("cashflows", ()))),
        "capacity_class": require_text(payload.get("capacity_class"), "capacity_class"),
        "liquidity_shape": require_text(payload.get("liquidity_shape"), "liquidity_shape"),
        "timing_class": require_text(payload.get("timing_class"), "timing_class"),
        "failure_modes": tuple(sorted(str(x) for x in payload.get("failure_modes", ()))),
    }
    return record(
        "build_mechanism_fingerprint",
        {**canonical, "fingerprint": stable_hash("pr355:mechanism-fingerprint", canonical)},
    )


def build_marketpack_adapter_features(payload: Mapping[str, Any]):
    features = payload.get("features")
    if not isinstance(features, Mapping) or not features:
        raise EvidenceNativeError("MARKETPACK_FEATURES_REQUIRED")
    normalized = {}
    for key, value in features.items():
        normalized[require_text(key, "feature_name")] = require_int(value, str(key))
    return record(
        "build_marketpack_adapter_features",
        {
            "marketpack_id": require_text(payload.get("marketpack_id"), "marketpack_id"),
            "features": dict(sorted(normalized.items())),
            "shared_representation_unchanged": True,
        },
    )


def _mae(values: Sequence[int], prediction: int) -> int:
    if not values:
        raise EvidenceNativeError("EVALUATION_VALUES_REQUIRED")
    return sum(abs(int(value) - prediction) for value in values) // len(values)


def train_local_only_baseline(payload: Mapping[str, Any]):
    train = tuple(require_int(x, "train_value") for x in payload.get("train_values", ()))
    holdout = tuple(require_int(x, "holdout_value") for x in payload.get("holdout_values", ()))
    if not train or not holdout:
        raise EvidenceNativeError("LOCAL_BASELINE_SPLIT_REQUIRED")
    prediction = sum(train) // len(train)
    return record(
        "train_local_only_baseline",
        {
            "prediction_atoms": prediction,
            "holdout_mae_atoms": _mae(holdout, prediction),
            "train_count": len(train),
            "holdout_count": len(holdout),
        },
    )


def train_mechanism_transfer_challenger(payload: Mapping[str, Any]):
    local = require_int(payload.get("local_prediction_atoms"), "local_prediction_atoms")
    shared = require_int(payload.get("shared_prediction_atoms"), "shared_prediction_atoms")
    shared_weight = require_ppm(payload.get("shared_weight_ppm"), "shared_weight_ppm")
    prediction = (
        local * (1_000_000 - shared_weight) + shared * shared_weight
    ) // 1_000_000
    holdout = tuple(require_int(x, "holdout_value") for x in payload.get("holdout_values", ()))
    return record(
        "train_mechanism_transfer_challenger",
        {
            "prediction_atoms": prediction,
            "holdout_mae_atoms": _mae(holdout, prediction),
            "shared_weight_ppm": shared_weight,
        },
    )


def measure_negative_transfer(payload: Mapping[str, Any]):
    local_mae = require_int(payload.get("local_holdout_mae_atoms"), "local_holdout_mae_atoms", minimum=0)
    transfer_mae = require_int(payload.get("transfer_holdout_mae_atoms"), "transfer_holdout_mae_atoms", minimum=0)
    old_before = require_int(payload.get("old_regime_mae_before_atoms"), "old_regime_mae_before_atoms", minimum=0)
    old_after = require_int(payload.get("old_regime_mae_after_atoms"), "old_regime_mae_after_atoms", minimum=0)
    degradation = old_after - old_before
    return record(
        "measure_negative_transfer",
        {
            "target_delta_mae_atoms": transfer_mae - local_mae,
            "old_regime_degradation_atoms": degradation,
            "negative_transfer": transfer_mae >= local_mae or degradation > 0,
        },
    )


def promote_or_reject_transfer(payload: Mapping[str, Any]):
    baseline = require_int(payload.get("local_holdout_mae_atoms"), "local_holdout_mae_atoms", minimum=0)
    challenger = require_int(payload.get("transfer_holdout_mae_atoms"), "transfer_holdout_mae_atoms", minimum=0)
    degradation = require_int(payload.get("old_regime_degradation_atoms"), "old_regime_degradation_atoms")
    max_degradation = require_int(payload.get("max_old_regime_degradation_atoms", 0), "max_old_regime_degradation_atoms", minimum=0)
    accepted = challenger < baseline and degradation <= max_degradation
    return record(
        "promote_or_reject_transfer",
        {
            "research_registry_action": "PROMOTE_CHALLENGER" if accepted else "REJECT_CHALLENGER",
            "accepted": accepted,
            "live_promotion": False,
        },
    )
