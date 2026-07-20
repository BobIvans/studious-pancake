from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from .dataset import parse_utc


@dataclass(frozen=True, slots=True)
class SplitResult:
    train_ids: tuple[str, ...]
    calibration_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    manifest: dict


class PurgedGroupedTimeSplit:
    def __init__(
        self,
        *,
        calibration_fraction: float = 0.2,
        test_fraction: float = 0.2,
        embargo_seconds: int = 3600,
    ) -> None:
        self.calibration_fraction = calibration_fraction
        self.test_fraction = test_fraction
        self.embargo = timedelta(seconds=embargo_seconds)

    def split(self, rows: list[dict]) -> SplitResult:
        labeled = [r for r in rows if r.get("label_status") == "LABELED"]
        ordered = sorted(
            labeled, key=lambda r: (r["candidate_observed_at"], r["row_id"])
        )
        groups = []
        seen = set()
        for r in ordered:
            g = r["lineage_group_id"]
            if g not in seen:
                seen.add(g)
                groups.append(g)
        n = len(groups)
        test_n = max(1, int(n * self.test_fraction)) if n >= 3 else 0
        cal_n = max(1, int(n * self.calibration_fraction)) if n >= 3 else 0
        train_g = set(groups[: max(0, n - cal_n - test_n)])
        cal_g = set(groups[max(0, n - cal_n - test_n) : max(0, n - test_n)])
        test_g = set(groups[max(0, n - test_n) :])
        parts: dict[str, list[str]] = {
            "train": [],
            "calibration": [],
            "test": [],
            "excluded": [],
        }
        last_train = max(
            (
                parse_utc(r["candidate_observed_at"])
                for r in ordered
                if r["lineage_group_id"] in train_g
            ),
            default=None,
        )
        last_cal = max(
            (
                parse_utc(r["candidate_observed_at"])
                for r in ordered
                if r["lineage_group_id"] in cal_g
            ),
            default=None,
        )
        for r in ordered:
            t = parse_utc(r["candidate_observed_at"])
            g = r["lineage_group_id"]
            if g in cal_g and last_train and t <= last_train + self.embargo:
                parts["excluded"].append(r["row_id"])
            elif g in test_g and last_cal and t <= last_cal + self.embargo:
                parts["excluded"].append(r["row_id"])
            elif g in train_g:
                parts["train"].append(r["row_id"])
            elif g in cal_g:
                parts["calibration"].append(r["row_id"])
            elif g in test_g:
                parts["test"].append(r["row_id"])
        manifest = {
            "policy": "purged_grouped_time_split/v1",
            "embargo_seconds": int(self.embargo.total_seconds()),
            "groups": {
                "train": sorted(train_g),
                "calibration": sorted(cal_g),
                "test": sorted(test_g),
            },
            "counts": {k: len(v) for k, v in parts.items()},
        }
        return SplitResult(
            tuple(parts["train"]),
            tuple(parts["calibration"]),
            tuple(parts["test"]),
            tuple(parts["excluded"]),
            manifest,
        )
