"""MEGA Market Data Layer Evolution sender-free research contracts.

This package is an additive view over existing AGG-02/AGG-10/PR-354/PR-355
owners.  It does not own provider I/O, execution, capital, signing, submission,
or a second feature/model registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,191}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MarketDataEvolutionError(ValueError):
    pass


def _id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise MarketDataEvolutionError(f"{field.upper()}_INVALID")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataEvolutionError(f"{field.upper()}_REQUIRED")
    return value.strip()


def _int(value: object, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataEvolutionError(f"{field.upper()}_INTEGER_REQUIRED")
    if minimum is not None and value < minimum:
        raise MarketDataEvolutionError(f"{field.upper()}_BELOW_MINIMUM")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise MarketDataEvolutionError(f"{field.upper()}_SHA256_REQUIRED")
    return value


def stable_hash(domain: str, payload: object) -> str:
    body = json.dumps(
        {"domain": domain, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceManifest:
    source_id: str
    title: str
    source_family: str
    licence_status: str
    entitlement_status: str
    endpoint_quota_units: int
    data_delay_ms: int
    retention_class: str
    source_version: str
    reference_only: bool = True
    external_fetch_performed: bool = False
    execution_right: bool = False

    def __post_init__(self) -> None:
        _id(self.source_id, "source_id")
        _text(self.title, "title")
        _id(self.source_family, "source_family")
        if self.licence_status not in {"VERIFIED", "REVERIFY", "BLOCKED"}:
            raise MarketDataEvolutionError("SOURCE_LICENCE_STATUS_INVALID")
        if self.entitlement_status not in {
            "VERIFIED_READ_ONLY",
            "REVERIFY",
            "BLOCKED",
        }:
            raise MarketDataEvolutionError("SOURCE_ENTITLEMENT_STATUS_INVALID")
        _int(self.endpoint_quota_units, "endpoint_quota_units", minimum=0)
        _int(self.data_delay_ms, "data_delay_ms", minimum=0)
        _id(self.retention_class, "retention_class")
        _text(self.source_version, "source_version")
        if self.external_fetch_performed:
            raise MarketDataEvolutionError("EXTERNAL_FETCH_FORBIDDEN_IN_CONTRACT_PR")
        if self.execution_right:
            raise MarketDataEvolutionError("DATA_SOURCE_CANNOT_GRANT_EXECUTION_RIGHT")

    @property
    def research_read_admitted(self) -> bool:
        return (
            not self.reference_only
            and self.licence_status == "VERIFIED"
            and self.entitlement_status == "VERIFIED_READ_ONLY"
        )


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    instrument_id: str
    ticker: str
    underlying_id: str
    issuer_id: str
    venue: str
    chain: str
    settlement_asset: str
    maturity: str
    multiplier_num: int
    multiplier_den: int
    session_id: str
    licence_id: str
    claim_rights_hash: str
    trading_access_verified: bool = False

    def __post_init__(self) -> None:
        for field in (
            "instrument_id",
            "ticker",
            "underlying_id",
            "issuer_id",
            "venue",
            "chain",
            "settlement_asset",
            "session_id",
            "licence_id",
        ):
            _id(getattr(self, field), field)
        _text(self.maturity, "maturity")
        _int(self.multiplier_num, "multiplier_num", minimum=0)
        _int(self.multiplier_den, "multiplier_den", minimum=1)
        _sha(self.claim_rights_hash, "claim_rights_hash")

    @property
    def identity_hash(self) -> str:
        return stable_hash("market-data-evolution:instrument", asdict(self))


@dataclass(frozen=True, slots=True)
class RawObservation:
    observation_id: str
    source_id: str
    instrument_id: str
    event_at: int
    first_seen_at: int
    available_at: int
    payload_hash: str
    schema_version: str
    units: str
    quality_flags: tuple[str, ...]
    published_at: int | None = None
    revision_id: int | None = None
    block_or_checkpoint: str | None = None
    source_sequence: int | None = None
    commitment: str | None = None
    request_hash: str | None = None
    licence_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("observation_id", "source_id", "instrument_id"):
            _id(getattr(self, field), field)
        event_at = _int(self.event_at, "event_at", minimum=0)
        first_seen = _int(self.first_seen_at, "first_seen_at", minimum=0)
        available = _int(self.available_at, "available_at", minimum=0)
        if not event_at <= first_seen <= available:
            raise MarketDataEvolutionError("OBSERVATION_CLOCK_ORDER_INVALID")
        if self.published_at is not None:
            published = _int(self.published_at, "published_at", minimum=0)
            if not event_at <= published <= available:
                raise MarketDataEvolutionError("PUBLICATION_CLOCK_ORDER_INVALID")
        if self.revision_id is not None:
            _int(self.revision_id, "revision_id", minimum=0)
        if self.source_sequence is not None:
            _int(self.source_sequence, "source_sequence", minimum=0)
        _sha(self.payload_hash, "payload_hash")
        _id(self.schema_version, "schema_version")
        _id(self.units, "units")
        for flag in self.quality_flags:
            _id(flag, "quality_flag")
        if self.request_hash is not None:
            _sha(self.request_hash, "request_hash")
        if self.licence_id is not None:
            _id(self.licence_id, "licence_id")


@dataclass(frozen=True, slots=True)
class GapEvent:
    source_id: str
    instrument_id: str
    detected_at: int
    gap_kind: str
    sequence_before: int | None
    sequence_after: int | None

    def __post_init__(self) -> None:
        _id(self.source_id, "source_id")
        _id(self.instrument_id, "instrument_id")
        _int(self.detected_at, "detected_at", minimum=0)
        _id(self.gap_kind, "gap_kind")
        for field in ("sequence_before", "sequence_after"):
            value = getattr(self, field)
            if value is not None:
                _int(value, field, minimum=0)


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    observation_id: str
    source_id: str
    instrument_id: str
    value_atoms: int
    event_at: int
    first_seen_at: int
    available_at: int
    revision_id: int
    effective_from: int
    effective_until: int | None
    instrument_version: str
    raw_payload_hash: str
    published_at: int | None = None
    missing: bool = False

    def __post_init__(self) -> None:
        for field in ("observation_id", "source_id", "instrument_id"):
            _id(getattr(self, field), field)
        _int(self.value_atoms, "value_atoms")
        event_at = _int(self.event_at, "event_at", minimum=0)
        first_seen = _int(self.first_seen_at, "first_seen_at", minimum=0)
        available = _int(self.available_at, "available_at", minimum=0)
        if not event_at <= first_seen <= available:
            raise MarketDataEvolutionError("NORMALIZED_CLOCK_ORDER_INVALID")
        _int(self.revision_id, "revision_id", minimum=0)
        start = _int(self.effective_from, "effective_from", minimum=0)
        if self.effective_until is not None:
            end = _int(self.effective_until, "effective_until", minimum=0)
            if end <= start:
                raise MarketDataEvolutionError("EFFECTIVE_INTERVAL_INVALID")
        _id(self.instrument_version, "instrument_version")
        _sha(self.raw_payload_hash, "raw_payload_hash")
        if self.published_at is not None:
            published = _int(self.published_at, "published_at", minimum=0)
            if not event_at <= published <= available:
                raise MarketDataEvolutionError("NORMALIZED_PUBLICATION_ORDER_INVALID")


@dataclass(frozen=True, slots=True)
class AvailabilityProof:
    cutoff: int
    selected_ids: tuple[str, ...]
    max_available_at: int
    future_revision_used: bool = False

    def __post_init__(self) -> None:
        cutoff = _int(self.cutoff, "cutoff", minimum=0)
        maximum = _int(self.max_available_at, "max_available_at", minimum=0)
        if maximum > cutoff or self.future_revision_used:
            raise MarketDataEvolutionError("POINT_IN_TIME_LEAKAGE")


def select_as_of(
    rows: Sequence[NormalizedObservation],
    *,
    cutoff: int,
) -> tuple[tuple[NormalizedObservation, ...], AvailabilityProof]:
    boundary = _int(cutoff, "cutoff", minimum=0)
    admitted = [
        row
        for row in rows
        if row.available_at <= boundary
        and row.effective_from <= boundary
        and (row.effective_until is None or boundary < row.effective_until)
    ]
    latest: dict[tuple[str, str], NormalizedObservation] = {}
    for row in admitted:
        key = (row.instrument_id, row.observation_id)
        previous = latest.get(key)
        if previous is None or row.revision_id > previous.revision_id:
            latest[key] = row
    selected = tuple(
        sorted(
            latest.values(),
            key=lambda row: (
                row.instrument_id,
                row.observation_id,
                row.revision_id,
            ),
        )
    )
    max_available = max((row.available_at for row in selected), default=0)
    return selected, AvailabilityProof(
        cutoff=boundary,
        selected_ids=tuple(row.observation_id for row in selected),
        max_available_at=max_available,
    )


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    snapshot_id: str
    cutoff: int
    observation_ids: tuple[str, ...]
    state_hash: str

    def __post_init__(self) -> None:
        _id(self.snapshot_id, "snapshot_id")
        _int(self.cutoff, "cutoff", minimum=0)
        _sha(self.state_hash, "state_hash")


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    snapshot_id: str
    input_hashes: tuple[str, ...]
    state_hash: str
    deterministic: bool
    latest_state_read: bool = False

    def __post_init__(self) -> None:
        _id(self.snapshot_id, "snapshot_id")
        for digest in self.input_hashes:
            _sha(digest, "input_hash")
        _sha(self.state_hash, "state_hash")
        if not self.deterministic or self.latest_state_read:
            raise MarketDataEvolutionError("REPLAY_NOT_DETERMINISTIC")


def materialize_state(
    rows: Sequence[NormalizedObservation],
    *,
    cutoff: int,
) -> tuple[StateSnapshot, ReplayManifest]:
    selected, proof = select_as_of(rows, cutoff=cutoff)
    payload = [
        {
            "instrument_id": row.instrument_id,
            "observation_id": row.observation_id,
            "revision_id": row.revision_id,
            "value_atoms": row.value_atoms,
            "available_at": row.available_at,
            "raw_payload_hash": row.raw_payload_hash,
        }
        for row in selected
    ]
    state_hash = stable_hash("market-data-evolution:state", payload)
    snapshot_id = f"MDE-{state_hash[:24]}"
    snapshot = StateSnapshot(
        snapshot_id=snapshot_id,
        cutoff=proof.cutoff,
        observation_ids=proof.selected_ids,
        state_hash=state_hash,
    )
    manifest = ReplayManifest(
        snapshot_id=snapshot_id,
        input_hashes=tuple(row.raw_payload_hash for row in selected),
        state_hash=state_hash,
        deterministic=True,
    )
    return snapshot, manifest


@dataclass(frozen=True, slots=True)
class MarketEpisode:
    episode_id: str
    feature_available_at: int
    label_available_at: int | None
    label_atoms: int | None
    outcome_state: str

    def __post_init__(self) -> None:
        _id(self.episode_id, "episode_id")
        feature_at = _int(
            self.feature_available_at,
            "feature_available_at",
            minimum=0,
        )
        if self.outcome_state not in {
            "MATURED",
            "NO_FILL",
            "MISSING",
            "CENSORED",
        }:
            raise MarketDataEvolutionError("EPISODE_OUTCOME_STATE_INVALID")
        if self.outcome_state == "MATURED":
            if self.label_available_at is None or self.label_atoms is None:
                raise MarketDataEvolutionError("MATURED_LABEL_REQUIRED")
            label_at = _int(
                self.label_available_at,
                "label_available_at",
                minimum=0,
            )
            if label_at <= feature_at:
                raise MarketDataEvolutionError("LABEL_LEAKAGE")
            _int(self.label_atoms, "label_atoms")
        elif self.label_atoms is not None:
            raise MarketDataEvolutionError("NON_MATURED_LABEL_MUST_BE_UNKNOWN")


@dataclass(frozen=True, slots=True)
class PredictiveRelation:
    relation_id: str
    source_features: tuple[str, ...]
    target: str
    lag: int
    horizon: str
    regime: str
    estimator_version: str
    fit_cutoff: int
    oos_period: str
    effect_estimate_ppm: int
    uncertainty_ppm: int
    multiple_test_family: str
    expiry: int
    executable: bool = False
    causal_claim: bool = False

    def __post_init__(self) -> None:
        _id(self.relation_id, "relation_id")
        if not self.source_features:
            raise MarketDataEvolutionError("RELATION_FEATURES_REQUIRED")
        for item in self.source_features:
            _id(item, "source_feature")
        for field in (
            "target",
            "horizon",
            "regime",
            "estimator_version",
            "oos_period",
            "multiple_test_family",
        ):
            _id(getattr(self, field), field)
        _int(self.lag, "lag", minimum=0)
        cutoff = _int(self.fit_cutoff, "fit_cutoff", minimum=0)
        _int(self.effect_estimate_ppm, "effect_estimate_ppm")
        _int(self.uncertainty_ppm, "uncertainty_ppm", minimum=0)
        expiry = _int(self.expiry, "expiry", minimum=0)
        if expiry <= cutoff:
            raise MarketDataEvolutionError("RELATION_EXPIRY_INVALID")
        if self.executable or self.causal_claim:
            raise MarketDataEvolutionError("STATISTICAL_RELATION_NOT_EXECUTABLE")


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    forecast_id: str
    model_version: str
    information_cutoff: int
    train_cutoff: int
    target: str
    horizon: str
    feature_snapshot_hash: str
    distribution_or_quantiles: tuple[int, ...]
    calibration_version: str
    valid_until: int
    market_regime: str
    abstention_reason: str | None
    execution_right: bool = False

    def __post_init__(self) -> None:
        for field in (
            "forecast_id",
            "model_version",
            "target",
            "horizon",
            "calibration_version",
            "market_regime",
        ):
            _id(getattr(self, field), field)
        info = _int(self.information_cutoff, "information_cutoff", minimum=0)
        train = _int(self.train_cutoff, "train_cutoff", minimum=0)
        until = _int(self.valid_until, "valid_until", minimum=0)
        if train > info or until <= info:
            raise MarketDataEvolutionError("FORECAST_CUTOFF_ORDER_INVALID")
        _sha(self.feature_snapshot_hash, "feature_snapshot_hash")
        if not self.distribution_or_quantiles:
            raise MarketDataEvolutionError("FORECAST_DISTRIBUTION_REQUIRED")
        for value in self.distribution_or_quantiles:
            _int(value, "forecast_quantile")
        if self.abstention_reason is not None:
            _id(self.abstention_reason, "abstention_reason")
        if self.execution_right:
            raise MarketDataEvolutionError("FORECAST_CANNOT_GRANT_EXECUTION_RIGHT")


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    experiment_id: str
    split_policy: str
    matured_labels_only: bool
    nonoverlapping_groups: bool
    held_out_market: bool
    unseen_forward_period: bool
    null_control_passed: bool
    fdr_control_passed: bool
    calibration_measured: bool
    net_utility_after_costs_atoms: int
    synthetic_pnl_as_real: bool = False
    live_authorized: bool = False

    def __post_init__(self) -> None:
        _id(self.experiment_id, "experiment_id")
        _id(self.split_policy, "split_policy")
        _int(
            self.net_utility_after_costs_atoms,
            "net_utility_after_costs_atoms",
        )
        if not (
            self.matured_labels_only
            and self.nonoverlapping_groups
            and self.held_out_market
            and self.unseen_forward_period
        ):
            raise MarketDataEvolutionError("QUALIFICATION_SPLIT_INCOMPLETE")
        if self.synthetic_pnl_as_real or self.live_authorized:
            raise MarketDataEvolutionError("QUALIFICATION_EFFECT_OR_PNL_OVERCLAIM")


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    candidate_id: str
    model_hash: str
    feature_schema_hash: str
    train_cutoff: int
    new_window_metric_ppm: int
    old_regime_metric_ppm: int
    rollback_hash: str
    live_authorized: bool = False

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        for field in ("model_hash", "feature_schema_hash", "rollback_hash"):
            _sha(getattr(self, field), field)
        _int(self.train_cutoff, "train_cutoff", minimum=0)
        _int(self.new_window_metric_ppm, "new_window_metric_ppm")
        _int(self.old_regime_metric_ppm, "old_regime_metric_ppm")
        if self.live_authorized:
            raise MarketDataEvolutionError("MODEL_CANNOT_AUTHORIZE_LIVE")


@dataclass(frozen=True, slots=True)
class RetentionReport:
    candidate_id: str
    accepted_for_research: bool
    new_window_delta_ppm: int
    old_regime_degradation_ppm: int
    rollback_required: bool
    live_authorized: bool = False


def evaluate_retention(
    *,
    candidate: ModelCandidate,
    incumbent_new_window_metric_ppm: int,
    incumbent_old_regime_metric_ppm: int,
    minimum_new_window_gain_ppm: int,
    maximum_old_regime_degradation_ppm: int,
) -> RetentionReport:
    incumbent_new = _int(
        incumbent_new_window_metric_ppm,
        "incumbent_new_window_metric_ppm",
    )
    incumbent_old = _int(
        incumbent_old_regime_metric_ppm,
        "incumbent_old_regime_metric_ppm",
    )
    minimum_gain = _int(
        minimum_new_window_gain_ppm,
        "minimum_new_window_gain_ppm",
        minimum=0,
    )
    max_degrade = _int(
        maximum_old_regime_degradation_ppm,
        "maximum_old_regime_degradation_ppm",
        minimum=0,
    )
    gain = candidate.new_window_metric_ppm - incumbent_new
    degradation = max(0, incumbent_old - candidate.old_regime_metric_ppm)
    accepted = gain >= minimum_gain and degradation <= max_degrade
    return RetentionReport(
        candidate_id=candidate.candidate_id,
        accepted_for_research=accepted,
        new_window_delta_ppm=gain,
        old_regime_degradation_ppm=degradation,
        rollback_required=not accepted,
        live_authorized=False,
    )


def research_effect_boundary() -> Mapping[str, bool]:
    return {
        "live_enabled": False,
        "signing_allowed": False,
        "submission_allowed": False,
        "funds_movement_allowed": False,
        "remote_mutation_allowed": False,
        "automatic_promotion_allowed": False,
    }


__all__ = [
    "AvailabilityProof",
    "ForecastRecord",
    "GapEvent",
    "InstrumentIdentity",
    "MarketDataEvolutionError",
    "MarketEpisode",
    "ModelCandidate",
    "NormalizedObservation",
    "PredictiveRelation",
    "QualificationEvidence",
    "RawObservation",
    "ReplayManifest",
    "RetentionReport",
    "SourceManifest",
    "StateSnapshot",
    "evaluate_retention",
    "materialize_state",
    "research_effect_boundary",
    "select_as_of",
    "stable_hash",
]
