"""Deterministic PR-022 dataset builder from immutable JSONL event trails."""

from __future__ import annotations

import hashlib, json
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

from .contracts import (
    ALLOWED_PRE_QUOTE_FEATURES,
    FORBIDDEN_PRE_QUOTE_TOKENS,
    DecisionFeatureRow,
    DecisionStage,
    FEATURE_SPEC_VERSION,
    SCHEMA_VERSION,
)

POSITIVE_TERMINAL = {"simulated_executable_profit"}
TERMINAL_TYPES = {"shadow_terminal", "terminal_outcome"}
CANDIDATE_TYPES = {"candidate_observed", "candidate"}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)


def validate_pre_quote_features(features: dict[str, Any]) -> None:
    bad = []
    for key, value in features.items():
        if key not in ALLOWED_PRE_QUOTE_FEATURES:
            bad.append(key)
        hay = f"{key} {value}"
        if any(token.lower() in hay.lower() for token in FORBIDDEN_PRE_QUOTE_TOKENS):
            bad.append(key)
        if isinstance(value, float):
            bad.append(key)
    if bad:
        raise ValueError(f"forbidden PRE_QUOTE features: {sorted(set(bad))}")


class DecisionDatasetBuilder:
    def __init__(
        self,
        *,
        label_horizon_seconds: int = 3600,
        min_profit_threshold_base_units: int = 1,
    ) -> None:
        self.label_horizon = timedelta(seconds=label_horizon_seconds)
        self.min_profit = int(min_profit_threshold_base_units)

    def build(
        self, event_paths: Iterable[str | Path], *, as_of: str, out_dir: str | Path
    ) -> dict[str, Any]:
        as_of_dt = parse_utc(as_of)
        events: list[dict[str, Any]] = []
        for path in event_paths:
            with Path(path).open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        event = json.loads(line)
                        if parse_utc(event["timestamp"]) <= as_of_dt:
                            event["_hash"] = sha256_text(_canon(event))
                            events.append(event)
        events.sort(key=lambda e: (e["timestamp"], e.get("event_id", "")))
        terminals = [e for e in events if e.get("event_type") in TERMINAL_TYPES]
        term_by_root: dict[str, list[dict[str, Any]]] = {}
        for e in terminals:
            root_value = e.get("root_opportunity_id") or e.get("opportunity_id")
            if root_value is None:
                continue
            root_key = str(root_value)
            term_by_root.setdefault(root_key, []).append(e)
        history: dict[tuple[str, str], list[int]] = {}
        rows: list[DecisionFeatureRow] = []
        excluded: dict[str, int] = {}
        for e in [x for x in events if x.get("event_type") in CANDIDATE_TYPES]:
            root_value = e.get("root_opportunity_id") or e.get("opportunity_id")
            if root_value is None:
                excluded["missing_root_opportunity_id"] = (
                    excluded.get("missing_root_opportunity_id", 0) + 1
                )
                continue
            root = str(root_value)
            lineage = str(e.get("lineage_group_id") or root)
            obs = parse_utc(e["timestamp"])
            raw_features = dict(e.get("features_pre_quote") or {})
            key = (
                str(raw_features.get("provider_health", "unknown")),
                str(raw_features.get("route_shape_class", "unknown")),
            )
            prior = history.get(key, [])
            raw_features.setdefault(
                "historical_success_rate_ppm",
                int(sum(prior) * 1_000_000 / len(prior)) if prior else 0,
            )
            raw_features.setdefault(
                "historical_reject_rate_ppm",
                int((len(prior) - sum(prior)) * 1_000_000 / len(prior)) if prior else 0,
            )
            try:
                validate_pre_quote_features(raw_features)
            except ValueError:
                excluded["forbidden_feature"] = excluded.get("forbidden_feature", 0) + 1
                continue
            terms = [
                t
                for t in term_by_root.get(root, [])
                if obs < parse_utc(t["timestamp"]) <= obs + self.label_horizon
            ]
            if not terms:
                excluded["censored_no_terminal_within_horizon"] = (
                    excluded.get("censored_no_terminal_within_horizon", 0) + 1
                )
                label_status, label_value, terminal_ts = (
                    "UNLABELED_CENSORED",
                    None,
                    None,
                )
            else:
                t = sorted(terms, key=lambda x: x["timestamp"])[-1]
                ok = (
                    t.get("outcome") in POSITIVE_TERMINAL
                    and t.get("simulation_success") is True
                    and t.get("reconciliation_complete") is True
                    and t.get("repayment_proven") is True
                    and t.get("post_simulation_feasibility_pass") is True
                    and int(t.get("simulated_executable_net_pnl_base_units", 0))
                    > self.min_profit
                )
                label_status, label_value, terminal_ts = (
                    "LABELED",
                    int(ok),
                    t["timestamp"],
                )
                history.setdefault(key, []).append(int(ok))
            rows.append(
                DecisionFeatureRow(
                    row_id=sha256_text(
                        f"{root}|{lineage}|{e.get('event_id')}|{e['timestamp']}"
                    )[:24],
                    root_opportunity_id=str(root),
                    lineage_group_id=str(lineage),
                    candidate_observed_at=e["timestamp"],
                    source_slot=int(e.get("source_slot", 0)),
                    observation_sequence=int(e.get("observation_sequence", 0)),
                    available_at_stage=DecisionStage.PRE_QUOTE,
                    features_pre_quote=raw_features,
                    label_status=label_status,
                    label_value=label_value,
                    terminal_timestamp=terminal_ts,
                    source_event_ids=(str(e.get("event_id", "")),),
                    source_event_hashes=(e["_hash"],),
                    row_quality="OK" if label_status == "LABELED" else "EXCLUDED",
                    exclusion_reason=(
                        None if label_status == "LABELED" else label_status
                    ),
                )
            )
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        data = [
            asdict(r) | {"available_at_stage": r.available_at_stage.value} for r in rows
        ]
        dataset_hash = sha256_text(_canon(data))
        (out / "rows.jsonl").write_text(
            "\n".join(_canon(r) for r in data) + ("\n" if data else ""),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "feature_spec_version": FEATURE_SPEC_VERSION,
            "feature_spec_hash": sha256_text(_canon(ALLOWED_PRE_QUOTE_FEATURES)),
            "as_of": as_of,
            "label_contract": "P(simulated_executable_profit | PRE_QUOTE); terminal PR-013 outcome within horizon",
            "label_horizon_seconds": int(self.label_horizon.total_seconds()),
            "dataset_hash": dataset_hash,
            "row_count": len(rows),
            "labeled_count": sum(r.label_status == "LABELED" for r in rows),
            "positive_count": sum(r.label_value == 1 for r in rows),
            "negative_count": sum(r.label_value == 0 for r in rows),
            "excluded_counts": excluded,
            "source_event_count": len(events),
        }
        (out / "manifest.json").write_text(_canon(manifest) + "\n", encoding="utf-8")
        return manifest


def load_rows(dataset_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(dataset_dir) / "rows.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
