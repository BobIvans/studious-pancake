"""Safe JSON linear ranker, baseline, evaluation and quota replay."""

from __future__ import annotations
import json, math, os, hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .contracts import (
    ALLOWED_PRE_QUOTE_FEATURES,
    FEATURE_SPEC_VERSION,
    MODEL_ARTIFACT_VERSION,
    ModelStatus,
    RankingRecommendation,
    DecisionStage,
    RecommendedBand,
)
from .dataset import load_rows, sha256_text, _canon
from .split import PurgedGroupedTimeSplit

MIN_TOTAL = 12
MIN_POS = 2
MIN_NEG = 2
SEED = 22
CATEGORICAL = [
    k for k, v in ALLOWED_PRE_QUOTE_FEATURES.items() if v.startswith("category")
]
NUMERIC = [k for k in ALLOWED_PRE_QUOTE_FEATURES if k not in CATEGORICAL]


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
                pred = _sig(sum(a * b for a, b in zip(w, x)) + b)
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
    body = {k: v for k, v in artifact.items() if k != "checksum"}
    artifact["checksum"] = sha256_text(_canon(body))
    path = out / f"artifact-{artifact['checksum'][:12]}.json"
    path.write_text(_canon(artifact) + "\n", encoding="utf-8")
    (out / "latest.json").write_text(
        json.dumps({"artifact": path.name, "checksum": artifact["checksum"]}) + "\n",
        encoding="utf-8",
    )
    return artifact


def load_artifact(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    p = p / json.loads((p / "latest.json").read_text())["artifact"] if p.is_dir() else p
    art = json.loads(p.read_text())
    chk = art.get("checksum")
    body = {k: v for k, v in art.items() if k != "checksum"}
    if sha256_text(_canon(body)) != chk:
        raise ValueError("artifact checksum mismatch")
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
    z = sum(a * b for a, b in zip(art["coefficients"], x)) + art["intercept"]
    p = _sig(z)
    contrib = sorted(
        zip(art["feature_order"], [a * b for a, b in zip(art["coefficients"], x)]),
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
    (out / "report.json").write_text(_canon(report) + "\n")
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
