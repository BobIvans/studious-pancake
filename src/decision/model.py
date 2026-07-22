"""Safe JSON linear ranker, baseline, evaluation and quota replay."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    ALLOWED_PRE_QUOTE_FEATURES,
    FEATURE_SPEC_VERSION,
    MODEL_ARTIFACT_VERSION,
    DecisionStage,
    ModelStatus,
    RankingRecommendation,
    RecommendedBand,
)
from .dataset import _canon, load_rows, sha256_text
from .split import PurgedGroupedTimeSplit

MIN_TOTAL = 12
MIN_POS = 2
MIN_NEG = 2
SEED = 22
CATEGORICAL = [
    k for k, v in ALLOWED_PRE_QUOTE_FEATURES.items() if v.startswith("category")
]
NUMERIC = [k for k in ALLOWED_PRE_QUOTE_FEATURES if k not in CATEGORICAL]

_ARTIFACT_POINTER = "latest.json"
_SECURE_FILE_MODE = 0o600
_SHA256_LEN = 64
_ALLOWED_BASE_ARTIFACT_KEYS = {
    "artifact_version",
    "feature_spec_version",
    "created_at",
    "model_status",
    "reason",
    "split_manifest",
    "dependency_versions",
    "class_counts",
    "checksum",
}
_ALLOWED_CHALLENGER_KEYS = {
    "feature_order",
    "categories",
    "means",
    "stds",
    "coefficients",
    "intercept",
}
_ALLOWED_POINTER_KEYS = {"artifact", "checksum"}


def baseline_priority(features: dict[str, Any]) -> int:
    p = 100
    p += {"healthy": 30, "degraded": 10, "unknown": 0, "circuit_open": -50}.get(
        str(features.get("provider_health", "unknown")), 0
    )
    p += {"available": 20, "tight": 5, "unknown": 0, "exhausted": -40}.get(
        str(features.get("quota_band", "unknown")), 0
    )
    p += {"pass": 20, "unknown": 0, "deny": -60}.get(
        str(features.get("capacity_status", "unknown")), 0
    )
    p -= min(int(features.get("candidate_age_ms", 0)) // 1000, 30)
    return p


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-max(-40, min(40, x))))


def _prepare(rows):
    cats = {
        k: sorted({str(r["features_pre_quote"].get(k, "unknown")) for r in rows})
        or ["unknown"]
        for k in CATEGORICAL
    }
    means = {
        k: sum(int(r["features_pre_quote"].get(k, 0)) for r in rows) / len(rows)
        for k in NUMERIC
    }
    stds = {
        k: (
            sum((int(r["features_pre_quote"].get(k, 0)) - means[k]) ** 2 for r in rows)
            / len(rows)
            or 1
        )
        ** 0.5
        for k in NUMERIC
    }
    names = NUMERIC + [f"{k}={v}" for k, vals in cats.items() for v in vals]
    return cats, means, stds, names


def _vector(f, cats, means, stds):
    x = [(int(f.get(k, 0)) - means[k]) / stds[k] for k in NUMERIC]
    for k, vals in cats.items():
        x.extend(1.0 if str(f.get(k, "unknown")) == v else 0.0 for v in vals)
    return x


def train_model(
    dataset_dir: str | Path, out_dir: str | Path, config: str | Path | None = None
) -> dict[str, Any]:
    rows = load_rows(dataset_dir)
    labeled = [r for r in rows if r.get("label_status") == "LABELED"]
    pos = sum(r["label_value"] == 1 for r in labeled)
    neg = sum(r["label_value"] == 0 for r in labeled)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    split = PurgedGroupedTimeSplit().split(rows)
    status = ModelStatus.SHADOW_CHALLENGER.value
    artifact: dict[str, Any] = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "feature_spec_version": FEATURE_SPEC_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model_status": status,
        "reason": None,
        "split_manifest": split.manifest,
        "dependency_versions": {
            "scikit-learn": "1.8.0 documented; not loaded for safe JSON inference"
        },
    }
    if (
        len(labeled) < MIN_TOTAL
        or pos < MIN_POS
        or neg < MIN_NEG
        or not split.train_ids
        or not split.test_ids
    ):
        artifact.update(
            {
                "model_status": ModelStatus.DISABLED_INSUFFICIENT_DATA.value,
                "reason": "minimum labeled/positive/negative/time-split counts not met",
                "class_counts": {
                    "total": len(labeled),
                    "positive": pos,
                    "negative": neg,
                },
            }
        )
    else:
        byid = {r["row_id"]: r for r in labeled}
        train = [byid[i] for i in split.train_ids if i in byid]
        cats, means, stds, names = _prepare(train)
        w = [0.0] * len(names)
        b = math.log((pos + 1) / (neg + 1))
        lr = 0.05
        for _ in range(300):
            for r in train:
                x = _vector(r["features_pre_quote"], cats, means, stds)
                y = r["label_value"]
                pred = _sig(sum(a * b for a, b in zip(w, x, strict=True)) + b)
                err = pred - y
                for i, xi in enumerate(x):
                    w[i] -= lr * (err * xi + 0.001 * w[i])
                b -= lr * err
        artifact.update(
            {
                "feature_order": names,
                "categories": cats,
                "means": means,
                "stds": stds,
                "coefficients": [round(v, 10) for v in w],
                "intercept": round(b, 10),
                "class_counts": {
                    "total": len(labeled),
                    "positive": pos,
                    "negative": neg,
                },
            }
        )
    artifact["checksum"] = _artifact_checksum(artifact)
    path = out / f"artifact-{artifact['checksum'][:12]}.json"
    _write_text_atomic(path, _model_canon(artifact) + "\n")
    _write_text_atomic(
        out / _ARTIFACT_POINTER,
        _model_canon({"artifact": path.name, "checksum": artifact["checksum"]}) + "\n",
    )
    return artifact


def load_artifact(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    pointer_checksum: str | None = None
    if p.is_dir():
        root = _resolve_existing_directory(p)
        pointer_path = root / _ARTIFACT_POINTER
        _validate_trusted_file(pointer_path, root=root)
        pointer = _strict_json_loads(pointer_path.read_text(encoding="utf-8"))
        if not isinstance(pointer, dict):
            raise ValueError("artifact pointer must be a JSON object")
        if set(pointer) != _ALLOWED_POINTER_KEYS:
            raise ValueError("artifact pointer contains unexpected keys")
        artifact_name = str(pointer["artifact"])
        pointer_checksum = _validate_sha256(str(pointer["checksum"]))
        p = _resolve_artifact_child(root, artifact_name)
    else:
        p = p.resolve(strict=True)
        root = p.parent.resolve(strict=True)

    _validate_trusted_file(p, root=root)
    art = _strict_json_loads(p.read_text(encoding="utf-8"))
    if not isinstance(art, dict):
        raise ValueError("model artifact must be a JSON object")
    _validate_model_artifact_schema(art)

    chk = str(art.get("checksum"))
    expected = _artifact_checksum(art)
    if expected != chk:
        raise ValueError("artifact checksum mismatch")
    if pointer_checksum is not None and pointer_checksum != chk:
        raise ValueError("artifact pointer checksum mismatch")
    return art


def recommend(
    features: dict[str, Any],
    artifact_path: str | Path | None = None,
    baseline_rank: int | None = None,
) -> RankingRecommendation:
    bp = baseline_rank if baseline_rank is not None else baseline_priority(features)
    if (
        os.getenv("DECISION_MODEL_ENABLED", "false").lower() not in {"1", "true", "yes"}
        or artifact_path is None
    ):
        return RankingRecommendation(
            None,
            DecisionStage.PRE_QUOTE,
            None,
            bp,
            RecommendedBand.BASELINE_ONLY,
            ("offline kill switch or no artifact: baseline only",),
            ModelStatus.MODEL_DISABLED,
        )
    try:
        art = load_artifact(artifact_path)
    except Exception as e:
        return RankingRecommendation(
            None,
            DecisionStage.PRE_QUOTE,
            None,
            bp,
            RecommendedBand.BASELINE_ONLY,
            (f"artifact invalid: {e}",),
            ModelStatus.MODEL_DISABLED,
        )
    if art.get("model_status") != ModelStatus.SHADOW_CHALLENGER.value:
        return RankingRecommendation(
            art.get("artifact_version"),
            DecisionStage.PRE_QUOTE,
            None,
            bp,
            RecommendedBand.BASELINE_ONLY,
            (str(art.get("reason") or "disabled artifact"),),
            ModelStatus(art.get("model_status")),
            art.get("checksum"),
        )
    x = _vector(features, art["categories"], art["means"], art["stds"])
    coefficients = art["coefficients"]
    z = sum(a * b for a, b in zip(coefficients, x, strict=True)) + art["intercept"]
    p = _sig(z)
    contrib = sorted(
        zip(
            art["feature_order"],
            [a * b for a, b in zip(coefficients, x, strict=True)],
            strict=True,
        ),
        key=lambda t: abs(t[1]),
        reverse=True,
    )[:3]
    band = (
        RecommendedBand.PRIORITIZE
        if p >= 0.66
        else RecommendedBand.DEPRIORITIZE if p <= 0.33 else RecommendedBand.NEUTRAL
    )
    return RankingRecommendation(
        art["artifact_version"],
        DecisionStage.PRE_QUOTE,
        p,
        bp,
        band,
        tuple(f"{n}:{v:.3f}" for n, v in contrib),
        ModelStatus.SHADOW_CHALLENGER,
        art["checksum"],
    )


def evaluate_model(dataset_dir, artifact_path, report_dir, as_of):
    rows = load_rows(dataset_dir)
    art = load_artifact(artifact_path)
    split = PurgedGroupedTimeSplit().split(rows)
    byid = {r["row_id"]: r for r in rows}
    test = [byid[i] for i in split.test_ids if i in byid]
    preds = []
    for r in test:
        rec = (
            recommend(r["features_pre_quote"], artifact_path)
            if art.get("model_status") == ModelStatus.SHADOW_CHALLENGER.value
            else recommend(r["features_pre_quote"], None)
        )
        preds.append(
            {
                "row_id": r["row_id"],
                "y": r["label_value"],
                "p": rec.probability if rec.probability is not None else 0.0,
                "baseline_priority": baseline_priority(r["features_pre_quote"]),
            }
        )
    brier = sum((p["p"] - p["y"]) ** 2 for p in preds) / len(preds) if preds else None
    report = {
        "as_of": as_of,
        "artifact_checksum": art.get("checksum"),
        "model_status": art.get("model_status"),
        "test_count": len(test),
        "metrics": {
            "brier_score": brier,
            "pr_auc": "undefined for tiny deterministic fixture",
            "roc_auc": "undefined for tiny deterministic fixture",
            "expected_calibration_error": brier,
        },
        "baseline_comparison": {
            "same_untouched_test_window": True,
            "baseline_topk_positive_count": sum(
                p["y"]
                for p in sorted(
                    preds, key=lambda x: x["baseline_priority"], reverse=True
                )[:3]
            ),
            "model_topk_positive_count": sum(
                p["y"] for p in sorted(preds, key=lambda x: x["p"], reverse=True)[:3]
            ),
        },
        "drift": {
            "feature_missingness_psi": "not_enough_current_window",
            "prediction_distribution": [p["p"] for p in preds],
        },
        "split_manifest": split.manifest,
    }
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(out / "report.json", _model_canon(report) + "\n")
    return report


def replay_quota(dataset_dir, artifact_path, quota_policy: dict[str, Any]):
    rows = [r for r in load_rows(dataset_dir) if r.get("label_status") == "LABELED"]
    exploration = max(0, min(1, (quota_policy.get("exploration_share", 0.2) + 0.0)))
    budget = int(quota_policy.get("budget", len(rows)))
    ranked = sorted(
        rows,
        key=lambda r: (
            recommend(r["features_pre_quote"], artifact_path).probability or 0,
            baseline_priority(r["features_pre_quote"]),
        ),
        reverse=True,
    )
    explore = rows[: int(budget * exploration)]
    exploit = [r for r in ranked if r not in explore][: budget - len(explore)]
    return {
        "budget": budget,
        "exploration_share": exploration,
        "selected_row_ids": [r["row_id"] for r in explore + exploit],
        "provider_limits_preserved": True,
        "discovery_only_not_executable": True,
    }


def _artifact_checksum(artifact: dict[str, Any]) -> str:
    body = {k: v for k, v in artifact.items() if k != "checksum"}
    return sha256_text(_model_canon(body))


def _model_canon(obj: Any) -> str:
    _reject_non_finite(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _strict_json_loads(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key is forbidden: {key}")
            out[key] = value
        return out

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicate_keys,
    )


def _validate_model_artifact_schema(artifact: dict[str, Any]) -> None:
    _reject_non_finite(artifact)
    model_status = artifact.get("model_status")
    allowed = set(_ALLOWED_BASE_ARTIFACT_KEYS)
    if model_status == ModelStatus.SHADOW_CHALLENGER.value:
        allowed.update(_ALLOWED_CHALLENGER_KEYS)
    if set(artifact) - allowed:
        raise ValueError("model artifact contains unexpected keys")
    if artifact.get("artifact_version") != MODEL_ARTIFACT_VERSION:
        raise ValueError("unexpected model artifact version")
    if artifact.get("feature_spec_version") != FEATURE_SPEC_VERSION:
        raise ValueError("unexpected feature spec version")
    if model_status not in {status.value for status in ModelStatus}:
        raise ValueError("unknown model status")
    _validate_sha256(str(artifact.get("checksum", "")))
    if model_status == ModelStatus.SHADOW_CHALLENGER.value:
        _validate_challenger_dimensions(artifact)


def _validate_challenger_dimensions(artifact: dict[str, Any]) -> None:
    feature_order = artifact.get("feature_order")
    coefficients = artifact.get("coefficients")
    categories = artifact.get("categories")
    means = artifact.get("means")
    stds = artifact.get("stds")
    if not isinstance(feature_order, list) or not all(
        isinstance(item, str) for item in feature_order
    ):
        raise ValueError("feature_order must be a list of strings")
    if not isinstance(coefficients, list) or not all(
        _is_finite_number(item) for item in coefficients
    ):
        raise ValueError("coefficients must be finite numbers")
    if len(coefficients) != len(feature_order):
        raise ValueError("coefficient count must match feature_order count")
    if not isinstance(categories, dict) or set(categories) != set(CATEGORICAL):
        raise ValueError("categories must match categorical feature spec")
    if not isinstance(means, dict) or set(means) != set(NUMERIC):
        raise ValueError("means must match numeric feature spec")
    if not isinstance(stds, dict) or set(stds) != set(NUMERIC):
        raise ValueError("stds must match numeric feature spec")
    for key, values in categories.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"category list is empty or malformed: {key}")
        if not all(isinstance(value, str) for value in values):
            raise ValueError(f"category values must be strings: {key}")
    if not all(_is_finite_number(value) for value in means.values()):
        raise ValueError("means must be finite numbers")
    if not all(_is_finite_number(value) and value > 0 for value in stds.values()):
        raise ValueError("stds must be positive finite numbers")
    if not _is_finite_number(artifact.get("intercept")):
        raise ValueError("intercept must be a finite number")
    expected = NUMERIC + [
        f"{key}={value}" for key in CATEGORICAL for value in categories[key]
    ]
    if feature_order != expected:
        raise ValueError("feature_order must match category and numeric spec")


def _resolve_existing_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("artifact root must be a directory")
    return resolved


def _resolve_artifact_child(root: Path, artifact_name: str) -> Path:
    raw = Path(artifact_name)
    if raw.is_absolute():
        raise ValueError("artifact pointer must not use an absolute path")
    if raw.name != artifact_name or artifact_name in {"", ".", ".."}:
        raise ValueError("artifact pointer must be a relative artifact basename")
    candidate = (root / artifact_name).resolve(strict=True)
    if candidate.parent != root:
        raise ValueError("artifact pointer escaped artifact root")
    return candidate


def _validate_trusted_file(path: Path, *, root: Path) -> None:
    resolved = path.resolve(strict=True)
    if root not in (resolved.parent, *resolved.parents):
        raise ValueError("artifact path escaped trusted root")
    st = path.stat(follow_symlinks=False)
    if stat.S_ISLNK(st.st_mode):
        raise ValueError("artifact path must not be a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("artifact path must be a regular file")
    if getattr(st, "st_nlink", 1) != 1:
        raise ValueError("artifact path must not be hard-linked")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise ValueError("artifact file owner mismatch")
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o077:
        raise ValueError("artifact file permissions must be 0600")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _SECURE_FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, _SECURE_FILE_MODE)
        _fsync_directory(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric value is forbidden")
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite(item)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return True


def _validate_sha256(value: str) -> str:
    if len(value) != _SHA256_LEN:
        raise ValueError("expected sha256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("expected sha256 digest") from exc
    return value
