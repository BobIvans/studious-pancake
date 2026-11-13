"""Immutable partitioned Parquet residual observations with typed provenance.

Stream H extensions:
- Residual FEATURES cover the typed series families; raw nominal prices are
  never features and residuals are always computed against proven anchors.
- Every observation carries a timestamp-alignment provenance flag. Lead/lag
  windows (100ms/500ms/1s/5s/30s/5m) are computed only over
  CHAIN_ALIGNED samples; unalignable samples are excluded with a typed reason.
- Findings remain DISCOVERY_ONLY: no correlation output can alter
  execution_class, evidence_state, heat or any promotion boundary.
- Partition directories use bounded-length content labels so the immutable
  content-addressed Parquet layout stays under Windows MAX_PATH while the
  storage pattern (partitioned, content-addressed, exclusive-create, capped
  queries) is unchanged; legacy 64-hex directories remain readable via the
  same glob and fail-closed row verification.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.assets.resolution.evidence import Evidence, EvidenceStore, digest, text

WINDOWS = (0.1, 0.5, 1.0, 5.0, 30.0, 300.0)
FEATURES = frozenset(
    (
        "stable_residual",
        "lst_premium",
        "wrapper_basis",
        "venue_residual",
        "direct_synthetic_residual",
        "nav_basis",
        "chain_basis",
        "route_topology_change",
        "depth_shock",
        "flash_capacity_change",
        "vwap_execution_residual",
        "oracle_residual",
    )
)
CHAIN_ALIGNED = "CHAIN_ALIGNED"
UNALIGNED = "UNALIGNED"
ALIGNMENT_STATES = frozenset((CHAIN_ALIGNED, UNALIGNED))
TIMESTAMP_ALIGNMENT_UNPROVEN = "timestamp_alignment_unproven"
# Bounded-length partition labels: 64 bits per directory component and 128
# bits per file name. Collisions fail closed (content verification on
# FileExistsError), and full digests remain inside every row payload.
PARTITION_LABEL_HEX = 16
FILE_LABEL_HEX = 32


@dataclass(frozen=True)
class NormalizedObservation:
    chain: str
    market_id: str
    relation_id: str
    evidence: Evidence
    features: tuple[tuple[str, float], ...]
    liquidity_resources: tuple[str, ...]
    regime: str
    timestamp_alignment: str = UNALIGNED

    def __post_init__(self) -> None:
        for value in (self.chain, self.market_id, self.relation_id, self.regime):
            text(value)
        if self.evidence.slot_or_checkpoint is None or self.evidence.negative_reason:
            raise ValueError(
                "normalized observations require positive chain provenance"
            )
        if self.timestamp_alignment not in ALIGNMENT_STATES:
            raise ValueError("timestamp alignment must be an explicit provenance flag")
        features = tuple(sorted(self.features))
        if (
            not features
            or len({k for k, _ in features}) != len(features)
            or any(k not in FEATURES or not math.isfinite(v) for k, v in features)
        ):
            raise ValueError(
                "unique finite residual features required; raw prices are not features"
            )
        if not self.liquidity_resources:
            raise ValueError("liquidity provenance required")
        object.__setattr__(self, "features", features)

    @property
    def identity(self) -> str:
        return digest(asdict(self))


def normalized_residual(
    value: float, anchor: float, *, conversion_cost: float = 0, scale: float = 1
) -> float:
    if (
        any(not math.isfinite(x) for x in (value, anchor, conversion_cost, scale))
        or scale <= 0
        or conversion_cost < 0
    ):
        raise ValueError("finite residual inputs required")
    return (value - anchor - conversion_cost) / scale


def partition_label(value: str) -> str:
    return digest(value)[:PARTITION_LABEL_HEX]


@dataclass(frozen=True)
class CorrelationFinding:
    x: str
    y: str
    feature: str
    window_seconds: float
    lag_seconds: float
    correlation: float | None
    sample_count: int
    confidence: float
    source_correlation_penalty: float
    regime: str
    sample_refs: tuple[str, ...]
    generation: str
    verification_state: str = "DISCOVERY_ONLY"


@dataclass(frozen=True)
class LeadLagExclusion:
    x: str
    y: str
    feature: str
    window_seconds: float | None
    reason: str
    sample_count: int


@dataclass(frozen=True)
class LeadLagReport:
    findings: tuple[CorrelationFinding, ...]
    exclusions: tuple[LeadLagExclusion, ...]


class CorrelationLedger:
    """Immutable Parquet partitions. Queries are explicitly bounded by row caps.

    Each append_many is a small immutable batch, allowing caller-side buffering
    without turning SQLite into a time-series store. Proof/anomaly manifests
    live separately and remain durable independently of raw retention.
    """

    def __init__(self, root: Path, generation: str, *, max_query_rows: int = 100_000):
        text(generation)
        if type(max_query_rows) is not int or not 1 <= max_query_rows <= 1_000_000:
            raise ValueError("invalid query cap")
        self.root, self.generation, self.max_query_rows = (
            root,
            generation,
            max_query_rows,
        )
        root.mkdir(parents=True, exist_ok=True)
        self.proofs = EvidenceStore(root / "proofs")

    def append(self, observation: NormalizedObservation) -> str:
        self.append_many((observation,))
        return observation.identity

    def append_many(
        self, observations: tuple[NormalizedObservation, ...]
    ) -> tuple[str, ...]:
        if not 1 <= len(observations) <= 4096 or any(
            o.evidence.generation != self.generation for o in observations
        ):
            raise ValueError("bounded batch in current generation required")
        partitions: dict[tuple[str, str, str, str], list[NormalizedObservation]] = {}
        for o in observations:
            day = datetime.fromtimestamp(o.evidence.observed_at, UTC).strftime(
                "%Y-%m-%d"
            )
            key = (
                partition_label(o.chain),
                day,
                partition_label(o.evidence.source),
                partition_label(o.market_id),
            )
            partitions.setdefault(key, []).append(o)
        for key, values in sorted(partitions.items()):
            folder = self.root / "normalized" / key[0] / key[1] / key[2] / key[3]
            folder.mkdir(parents=True, exist_ok=True)
            rows = [
                {
                    "identity": o.identity,
                    "observed_at": o.evidence.observed_at,
                    "payload": json.dumps(asdict(o), sort_keys=True, allow_nan=False),
                }
                for o in sorted(
                    {o.identity: o for o in values}.values(), key=lambda o: o.identity
                )
            ]
            path = folder / (digest(rows)[:FILE_LABEL_HEX] + ".parquet")
            table = pa.Table.from_pylist(rows)
            # Exclusive creation avoids replacing history; retry verifies it.
            try:
                with path.open("xb") as stream:
                    pq.write_table(table, stream, compression="zstd")
            except FileExistsError:
                if pq.ParquetFile(path).read().to_pylist() != rows:
                    raise ValueError("immutable parquet collision")
        return tuple(o.identity for o in observations)

    def observations(
        self, *, since: float = 0, until: float = float("inf")
    ) -> tuple[NormalizedObservation, ...]:
        result: dict[str, NormalizedObservation] = {}
        scanned = 0
        for path in sorted((self.root / "normalized").glob("*/*/*/*/*.parquet")):
            file = pq.ParquetFile(path)
            scanned += file.metadata.num_rows
            if scanned > self.max_query_rows:
                raise ValueError(
                    "ledger query cap exceeded; narrow partitions or compact"
                )
            for row in file.read().to_pylist():
                payload = json.loads(row["payload"])
                # Pre-alignment payloads remain readable and stay UNALIGNED:
                # missing provenance is never promoted to chain alignment, and
                # the stored identity is verified against the exact stored
                # payload shape.
                legacy_alignment = "timestamp_alignment" not in payload
                legacy_identity = digest(payload) if legacy_alignment else None
                payload.setdefault("timestamp_alignment", UNALIGNED)
                payload["evidence"] = Evidence(**payload["evidence"])
                payload["features"] = tuple(tuple(f) for f in payload["features"])
                payload["liquidity_resources"] = tuple(payload["liquidity_resources"])
                o = NormalizedObservation(**payload)
                if (legacy_identity if legacy_alignment else o.identity) != row[
                    "identity"
                ] or o.evidence.observed_at != row["observed_at"]:
                    raise ValueError("corrupt normalized observation")
                if (
                    o.evidence.generation == self.generation
                    and since <= o.evidence.observed_at <= until
                ):
                    result[o.identity] = o
        return tuple(
            sorted(result.values(), key=lambda o: (o.evidence.observed_at, o.identity))
        )

    def replay(self, sample_refs: tuple[str, ...]) -> tuple[NormalizedObservation, ...]:
        index = {o.identity: o for o in self.observations()}
        if any(ref not in index for ref in sample_refs):
            raise ValueError("missing replay observation")
        return tuple(index[ref] for ref in sample_refs)

    def features(
        self, market_or_relation: str, window: float, *, now: float
    ) -> tuple[NormalizedObservation, ...]:
        if not math.isfinite(window) or window <= 0 or not math.isfinite(now):
            raise ValueError("invalid feature window")
        return tuple(
            o
            for o in self.observations(since=now - window, until=now)
            if market_or_relation in (o.market_id, o.relation_id)
        )

    def lead_lag_report(
        self,
        x: str,
        y: str,
        windows: tuple[float, ...] = WINDOWS,
        *,
        feature: str,
        now: float,
        lags: tuple[float, ...] = (0, 0.1, 0.5, 1.0),
    ) -> LeadLagReport:
        if (
            feature not in FEATURES
            or not math.isfinite(now)
            or not 1 <= len(windows) <= 6
            or not 1 <= len(lags) <= 16
            or any(not math.isfinite(v) or v <= 0 for v in windows)
            or any(not math.isfinite(v) or v < 0 for v in lags)
        ):
            raise ValueError("bounded finite lead/lag windows required")
        observations = self.observations(
            since=now - max(windows) - max(lags), until=now
        )
        # Provenance gate: lead/lag windows are computed only over samples
        # whose source and chain timestamps are alignable; unalignable samples
        # are excluded with a typed reason (unknown provenance is not zero).
        aligned = tuple(
            o for o in observations if o.timestamp_alignment == CHAIN_ALIGNED
        )
        exclusions: list[LeadLagExclusion] = []
        excluded = len(observations) - len(aligned)
        if excluded:
            exclusions.append(
                LeadLagExclusion(
                    x, y, feature, None, TIMESTAMP_ALIGNMENT_UNPROVEN, excluded
                )
            )
        series: dict[str, dict[int, NormalizedObservation]] = {x: {}, y: {}}
        for o in aligned:
            if feature not in dict(o.features):
                continue
            for name in series:
                if name in (o.market_id, o.relation_id):
                    timestamp = round(o.evidence.observed_at * 1_000_000)
                    previous = series[name].get(timestamp)
                    if previous is not None and previous.identity != o.identity:
                        raise ValueError("ambiguous residual sample at same timestamp")
                    series[name][timestamp] = o
        findings = []
        for window in windows:
            for lag in lags:
                pairs = [
                    (a, series[y][t + round(lag * 1_000_000)])
                    for t, a in sorted(series[x].items())
                    if now - window <= a.evidence.observed_at
                    and t + round(lag * 1_000_000) in series[y]
                ]
                xs = [dict(a.features)[feature] for a, _ in pairs]
                ys = [dict(b.features)[feature] for _, b in pairs]
                correlation = None
                if len(pairs) >= 3:
                    xm, ym = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
                    xx = math.fsum((v - xm) ** 2 for v in xs)
                    yy = math.fsum((v - ym) ** 2 for v in ys)
                    if xx > 0 and yy > 0:
                        correlation = max(
                            -1,
                            min(
                                1,
                                math.fsum((a - xm) * (b - ym) for a, b in zip(xs, ys))
                                / math.sqrt(xx * yy),
                            ),
                        )
                aliases = sum(
                    a.evidence.provider == b.evidence.provider
                    or a.evidence.correlation_group == b.evidence.correlation_group
                    or bool(set(a.liquidity_resources) & set(b.liquidity_resources))
                    for a, b in pairs
                )
                penalty = aliases / len(pairs) if pairs else 1.0
                regimes = sorted({o.regime for pair in pairs for o in pair})
                findings.append(
                    CorrelationFinding(
                        x,
                        y,
                        feature,
                        window,
                        lag,
                        correlation,
                        len(pairs),
                        (
                            min(1, len(pairs) / 30) * (1 - penalty)
                            if correlation is not None
                            else 0
                        ),
                        penalty,
                        "+".join(regimes) or "no_samples",
                        tuple(sorted({o.identity for pair in pairs for o in pair})),
                        self.generation,
                    )
                )
        return LeadLagReport(tuple(findings), tuple(exclusions))

    def lead_lag(
        self,
        x: str,
        y: str,
        windows: tuple[float, ...] = WINDOWS,
        *,
        feature: str,
        now: float,
        lags: tuple[float, ...] = (0, 0.1, 0.5, 1.0),
    ) -> tuple[CorrelationFinding, ...]:
        return self.lead_lag_report(
            x, y, windows, feature=feature, now=now, lags=lags
        ).findings

    def preserve_anomaly(
        self, candidate: str, *, at: float, findings: tuple[CorrelationFinding, ...]
    ) -> str:
        samples = self.observations(since=at - 300, until=at + 300)
        payload = {
            "candidate": candidate,
            "samples": [asdict(o) for o in samples],
            "findings": [asdict(f) for f in findings],
            "generation": self.generation,
        }
        return self.proofs.append(
            Evidence(
                "anomaly-window",
                "correlation-ledger",
                "ledger",
                self.generation,
                at,
                digest(payload),
                digest(candidate),
            ),
            payload,
        )
