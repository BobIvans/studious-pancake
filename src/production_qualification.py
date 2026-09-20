"""MPR-2611 semantic evidence validation for production qualification.

This module is an evidence consumer only. It does not implement shadow, signer,
canary, economics, runtime, debt, or release-promotion authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

MPR2611_SCHEMA = "mpr-2611.production-evidence-validation.v1"

# Evidence whose mere existence must never close production debt.
SEMANTIC_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "database_schema_fingerprint": ("database-schema", "mpr-"),
    "backup_restore_report_digest": ("backup-restore", "mpr-"),
    "fault_injection_report_digest": ("fault-injection", "mpr-"),
    "provider_drift_probe_report_digest": ("provider-drift", "mpr-2605", "mpr-2611"),
    "shadow_campaign_report_digest": ("shadow-soak", "mpr-2607", "mpr2607"),
    "finalized_economics_report_digest": ("finalized-economics", "mpr-2610", "mpr2610"),
    "signer_canary_approval_bundle_digest": ("canary", "mpr-2609", "mpr2609"),
    "wheelhouse_manifest": ("wheelhouse", "dependency"),
    "sbom_digest": ("sbom",),
    "config_generation_digest": ("config-generation", "mpr-"),
}

_TRUE_VERDICTS = {"accepted", "passed", "qualified", "success", "succeeded", "settled"}
_FALSE_VERDICTS = {
    "ambiguous",
    "blocked",
    "failed",
    "failure",
    "fixture",
    "invalid",
    "pending",
    "planned",
    "rejected",
    "synthetic",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    accepted: bool
    artifact_id: str
    raw_sha256: str
    semantic_sha256: str | None
    reason_codes: tuple[str, ...]
    schema_version: str | None = None
    producer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MPR2611_SCHEMA,
            "accepted": self.accepted,
            "artifact_id": self.artifact_id,
            "raw_sha256": self.raw_sha256,
            "semantic_sha256": self.semantic_sha256,
            "reason_codes": list(self.reason_codes),
            "evidence_schema_version": self.schema_version,
            "producer": self.producer,
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number forbidden: {value}")


def load_strict_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("evidence symlink forbidden")
    raw = path.read_bytes()
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("evidence root must be an object")
    if not value:
        raise ValueError("empty evidence object forbidden")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _schema_matches(schema: str, prefixes: tuple[str, ...]) -> bool:
    lowered = schema.lower()
    return any(lowered.startswith(prefix) for prefix in prefixes)


def _string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _bool_true(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _verdict(payload: Mapping[str, Any]) -> str | None:
    for key in ("verdict", "qualification_status", "status", "result"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip().lower().replace("_", "-")
    for key in ("qualified", "accepted", "passed", "success"):
        if payload.get(key) is True:
            return "passed"
        if payload.get(key) is False:
            return "failed"
    return None


def validate_semantic_evidence(
    path: Path,
    *,
    artifact_id: str,
    source_commit: str | None,
    release_id: str,
) -> EvidenceValidation:
    raw = path.read_bytes()
    raw_sha = _sha256_bytes(raw)
    prefixes = SEMANTIC_ARTIFACTS.get(artifact_id)
    if prefixes is None:
        return EvidenceValidation(True, artifact_id, raw_sha, raw_sha, ())

    reasons: list[str] = []
    try:
        payload = load_strict_json(path)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return EvidenceValidation(
            False,
            artifact_id,
            raw_sha,
            None,
            ("INVALID_JSON_EVIDENCE", type(exc).__name__),
        )

    schema = _string(payload, "schema_version")
    if schema is None:
        reasons.append("MISSING_SCHEMA_VERSION")
    elif not _schema_matches(schema, prefixes):
        reasons.append("WRONG_SCHEMA_VERSION")

    evidence_source = _string(payload, "source_commit")
    if source_commit is None:
        reasons.append("SOURCE_COMMIT_UNAVAILABLE")
    elif evidence_source != source_commit:
        reasons.append("SOURCE_COMMIT_MISMATCH")

    evidence_release = _string(payload, "release_id")
    if evidence_release != release_id:
        reasons.append("RELEASE_ID_MISMATCH")

    producer = _string(payload, "producer") or _string(payload, "evidence_producer")
    if producer is None:
        reasons.append("MISSING_EVIDENCE_PRODUCER")

    if not _bool_true(payload, "production_evidence"):
        reasons.append("NOT_PRODUCTION_EVIDENCE")

    for key in ("synthetic", "fixture", "dry_run", "documentation_only", "source_vector_offline"):
        if payload.get(key) is True:
            reasons.append("NON_PRODUCTION_EVIDENCE")
            break

    evidence_kind = _string(payload, "evidence_kind")
    if evidence_kind and evidence_kind.lower() in {
        "fixture",
        "example",
        "dry-run",
        "documentation-review",
        "source-vector-offline",
        "synthetic",
    }:
        reasons.append("NON_PRODUCTION_EVIDENCE")

    verdict = _verdict(payload)
    if verdict is None:
        reasons.append("MISSING_POSITIVE_VERDICT")
    elif verdict in _FALSE_VERDICTS or verdict not in _TRUE_VERDICTS:
        reasons.append("NON_SUCCESS_VERDICT")

    if artifact_id == "finalized_economics_report_digest":
        realized = payload.get("realized_pnl_atomic_units")
        if isinstance(realized, bool) or not isinstance(realized, int):
            reasons.append("MISSING_REALIZED_INTEGER_PNL")
        reconciliation = _string(payload, "reconciliation_status")
        if reconciliation not in {"reconciled", "settled", "finalized-settled"}:
            reasons.append("ECONOMICS_NOT_RECONCILED")
        if payload.get("transaction_finalized") is not True:
            reasons.append("TRANSACTION_NOT_FINALIZED")

    if artifact_id == "shadow_campaign_report_digest":
        if payload.get("synthetic") is not False:
            reasons.append("SHADOW_SYNTHETIC_STATE_UNPROVEN")
        duration = payload.get("eligible_duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            reasons.append("INVALID_SHADOW_DURATION")

    if artifact_id == "signer_canary_approval_bundle_digest":
        if payload.get("second_human_approval") is not True:
            reasons.append("SECOND_HUMAN_APPROVAL_MISSING")
        if payload.get("auto_rearm") is not False:
            reasons.append("AUTO_REARM_NOT_DISABLED")
        if payload.get("unknown_outcome") is True:
            reasons.append("CANARY_UNKNOWN_OUTCOME")

    semantic_sha = None if reasons else _sha256_bytes(_canonical_json(payload))
    return EvidenceValidation(
        not reasons,
        artifact_id,
        raw_sha,
        semantic_sha,
        tuple(sorted(set(reasons))),
        schema,
        producer,
    )

# ---------------------------------------------------------------------------
# AGG-04: exact paper campaign qualification evidence
# ---------------------------------------------------------------------------

AGG04_SCHEMA = "agg-04.qualification-evidence.v1"
AGG04_QUALIFIED_SCOPE = "qualified-scope"
AGG04_INSUFFICIENT_EVIDENCE = "insufficient-evidence"
AGG04_NEGATIVE = "negative"

_AGG04_EVIDENCE_KINDS = frozenset(
    {"recorded", "simulated", "observed", "counterfactual", "synthetic"}
)


def _agg04_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _agg04_digest(value: str, field: str) -> str:
    candidate = _agg04_text(value, field).lower()
    if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
        raise ValueError(f"{field} must be a lowercase sha256")
    if candidate == "0" * 64:
        raise ValueError(f"{field} cannot be a placeholder digest")
    return candidate


def _agg04_int(value: int, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _agg04_unique(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(_agg04_text(item, field) for item in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} contains duplicates")
    return normalized


def _agg04_hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AGG04CampaignPolicy:
    """Frozen pre-measurement policy for the first full paper qualification."""

    campaign_id: str
    profile_id: str
    source_commit: str
    policy_version: str
    allowed_assets: tuple[str, ...]
    allowed_venues: tuple[str, ...]
    allowed_lenders: tuple[str, ...]
    survival_horizon_ms: int = 500
    min_simulated_episodes: int = 1
    min_horizon_episodes: int = 1
    min_positive_net_episodes: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", _agg04_text(self.campaign_id, "campaign_id"))
        object.__setattr__(self, "profile_id", _agg04_text(self.profile_id, "profile_id"))
        object.__setattr__(self, "source_commit", _agg04_text(self.source_commit, "source_commit"))
        object.__setattr__(
            self, "policy_version", _agg04_text(self.policy_version, "policy_version")
        )
        object.__setattr__(
            self, "allowed_assets", _agg04_unique(tuple(self.allowed_assets), "allowed_assets")
        )
        object.__setattr__(
            self, "allowed_venues", _agg04_unique(tuple(self.allowed_venues), "allowed_venues")
        )
        object.__setattr__(
            self, "allowed_lenders", _agg04_unique(tuple(self.allowed_lenders), "allowed_lenders")
        )
        if not self.allowed_assets or not self.allowed_venues or not self.allowed_lenders:
            raise ValueError("qualification scope cannot be empty")
        _agg04_int(self.survival_horizon_ms, "survival_horizon_ms", minimum=1)
        _agg04_int(self.min_simulated_episodes, "min_simulated_episodes", minimum=1)
        _agg04_int(self.min_horizon_episodes, "min_horizon_episodes", minimum=1)
        _agg04_int(self.min_positive_net_episodes, "min_positive_net_episodes", minimum=1)

    @property
    def policy_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "schema_version": AGG04_SCHEMA,
                "campaign_id": self.campaign_id,
                "profile_id": self.profile_id,
                "source_commit": self.source_commit,
                "policy_version": self.policy_version,
                "allowed_assets": list(self.allowed_assets),
                "allowed_venues": list(self.allowed_venues),
                "allowed_lenders": list(self.allowed_lenders),
                "survival_horizon_ms": self.survival_horizon_ms,
                "min_simulated_episodes": self.min_simulated_episodes,
                "min_horizon_episodes": self.min_horizon_episodes,
                "min_positive_net_episodes": self.min_positive_net_episodes,
            }
        )


@dataclass(frozen=True, slots=True)
class AGG04EpisodeEvidence:
    """One independent market episode, separate from amount/message variants."""

    episode_id: str
    observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _agg04_text(self.episode_id, "episode_id"))
        observations = _agg04_unique(tuple(self.observation_ids), "observation_id")
        if not observations:
            raise ValueError("episode must contain at least one observation")
        object.__setattr__(self, "observation_ids", observations)


@dataclass(frozen=True, slots=True)
class AGG04VariantEvidence:
    """Immutable amount/route/state/cost/message binding for one episode variant."""

    episode_id: str
    variant_id: str
    amount_atomic: int
    lender_id: str
    route_sha256: str
    frame_sha256: str
    cost_sha256: str
    message_sha256: str
    evidence_kind: str
    simulated: bool
    conservative_net_atomic: int | None = None
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _agg04_text(self.episode_id, "episode_id"))
        object.__setattr__(self, "variant_id", _agg04_text(self.variant_id, "variant_id"))
        object.__setattr__(self, "lender_id", _agg04_text(self.lender_id, "lender_id"))
        _agg04_int(self.amount_atomic, "amount_atomic", minimum=1)
        for field in ("route_sha256", "frame_sha256", "cost_sha256", "message_sha256"):
            object.__setattr__(self, field, _agg04_digest(getattr(self, field), field))
        kind = _agg04_text(self.evidence_kind, "evidence_kind").lower()
        if kind not in _AGG04_EVIDENCE_KINDS:
            raise ValueError("unsupported evidence_kind")
        object.__setattr__(self, "evidence_kind", kind)
        if not isinstance(self.simulated, bool):
            raise ValueError("simulated must be bool")
        if self.conservative_net_atomic is not None and (
            isinstance(self.conservative_net_atomic, bool)
            or not isinstance(self.conservative_net_atomic, int)
        ):
            raise ValueError("conservative_net_atomic must be an integer or null")
        if self.rejection_code is not None:
            object.__setattr__(
                self, "rejection_code", _agg04_text(self.rejection_code, "rejection_code")
            )

    @property
    def binding_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "episode_id": self.episode_id,
                "variant_id": self.variant_id,
                "amount_atomic": str(self.amount_atomic),
                "lender_id": self.lender_id,
                "route_sha256": self.route_sha256,
                "frame_sha256": self.frame_sha256,
                "cost_sha256": self.cost_sha256,
                "message_sha256": self.message_sha256,
                "evidence_kind": self.evidence_kind,
                "simulated": self.simulated,
                "conservative_net_atomic": (
                    None
                    if self.conservative_net_atomic is None
                    else str(self.conservative_net_atomic)
                ),
                "rejection_code": self.rejection_code,
            }
        )


@dataclass(frozen=True, slots=True)
class AGG04ProbeEvidence:
    """A later probe bound to the exact candidate variant and message generation."""

    variant_id: str
    message_sha256: str
    elapsed_ms: int
    positive: bool | None
    evidence_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_id", _agg04_text(self.variant_id, "variant_id"))
        object.__setattr__(
            self, "message_sha256", _agg04_digest(self.message_sha256, "message_sha256")
        )
        _agg04_int(self.elapsed_ms, "elapsed_ms")
        if self.positive is not None and not isinstance(self.positive, bool):
            raise ValueError("positive must be bool or null")
        kind = _agg04_text(self.evidence_kind, "evidence_kind").lower()
        if kind not in _AGG04_EVIDENCE_KINDS:
            raise ValueError("unsupported evidence_kind")
        object.__setattr__(self, "evidence_kind", kind)


@dataclass(frozen=True, slots=True)
class AGG04TemporalSplit:
    """Frozen time/episode split with purge/embargo-compatible boundaries."""

    train_episode_ids: tuple[str, ...]
    validation_episode_ids: tuple[str, ...]
    holdout_episode_ids: tuple[str, ...]
    train_end_ns: int
    validation_start_ns: int
    validation_end_ns: int
    holdout_start_ns: int
    embargo_ns: int

    def __post_init__(self) -> None:
        train = _agg04_unique(tuple(self.train_episode_ids), "train_episode_id")
        validation = _agg04_unique(
            tuple(self.validation_episode_ids), "validation_episode_id"
        )
        holdout = _agg04_unique(tuple(self.holdout_episode_ids), "holdout_episode_id")
        if set(train) & set(validation) or set(train) & set(holdout) or set(validation) & set(holdout):
            raise ValueError("episode leakage across temporal splits")
        for field in (
            "train_end_ns",
            "validation_start_ns",
            "validation_end_ns",
            "holdout_start_ns",
            "embargo_ns",
        ):
            _agg04_int(getattr(self, field), field)
        if self.train_end_ns + self.embargo_ns > self.validation_start_ns:
            raise ValueError("train/validation embargo violated")
        if self.validation_start_ns > self.validation_end_ns:
            raise ValueError("validation window is inverted")
        if self.validation_end_ns + self.embargo_ns > self.holdout_start_ns:
            raise ValueError("validation/holdout embargo violated")
        object.__setattr__(self, "train_episode_ids", train)
        object.__setattr__(self, "validation_episode_ids", validation)
        object.__setattr__(self, "holdout_episode_ids", holdout)

    @property
    def split_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "train_episode_ids": list(self.train_episode_ids),
                "validation_episode_ids": list(self.validation_episode_ids),
                "holdout_episode_ids": list(self.holdout_episode_ids),
                "train_end_ns": self.train_end_ns,
                "validation_start_ns": self.validation_start_ns,
                "validation_end_ns": self.validation_end_ns,
                "holdout_start_ns": self.holdout_start_ns,
                "embargo_ns": self.embargo_ns,
            }
        )


@dataclass(frozen=True, slots=True)
class AGG04FunnelReport:
    """Nested A/E/C/S/H/N cohorts expressed as episode identity sets."""

    observation_ids: tuple[str, ...]
    episode_ids: tuple[str, ...]
    candidate_episode_ids: tuple[str, ...]
    simulated_episode_ids: tuple[str, ...]
    horizon_episode_ids: tuple[str, ...]
    positive_net_episode_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        fields_to_normalize = (
            "observation_ids",
            "episode_ids",
            "candidate_episode_ids",
            "simulated_episode_ids",
            "horizon_episode_ids",
            "positive_net_episode_ids",
        )
        for field in fields_to_normalize:
            object.__setattr__(
                self, field, _agg04_unique(tuple(getattr(self, field)), field)
            )
        e = set(self.episode_ids)
        c = set(self.candidate_episode_ids)
        s = set(self.simulated_episode_ids)
        h = set(self.horizon_episode_ids)
        n = set(self.positive_net_episode_ids)
        if not (n <= h <= s <= c <= e):
            raise ValueError("A/E/C/S/H/N episode cohorts must be nested")

    @property
    def counts(self) -> dict[str, int]:
        return {
            "A": len(self.observation_ids),
            "E": len(self.episode_ids),
            "C": len(self.candidate_episode_ids),
            "S": len(self.simulated_episode_ids),
            "H": len(self.horizon_episode_ids),
            "N": len(self.positive_net_episode_ids),
        }

    @property
    def funnel_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "observation_ids": list(self.observation_ids),
                "episode_ids": list(self.episode_ids),
                "candidate_episode_ids": list(self.candidate_episode_ids),
                "simulated_episode_ids": list(self.simulated_episode_ids),
                "horizon_episode_ids": list(self.horizon_episode_ids),
                "positive_net_episode_ids": list(self.positive_net_episode_ids),
            }
        )


def build_agg04_funnel(
    *,
    episodes: tuple[AGG04EpisodeEvidence, ...],
    variants: tuple[AGG04VariantEvidence, ...],
    probes: tuple[AGG04ProbeEvidence, ...],
    survival_horizon_ms: int,
) -> AGG04FunnelReport:
    """Build nested cohorts without counting retries/amount variants as episodes."""

    _agg04_int(survival_horizon_ms, "survival_horizon_ms", minimum=1)
    episode_by_id: dict[str, AGG04EpisodeEvidence] = {}
    observation_ids: list[str] = []
    seen_observations: set[str] = set()
    for episode in episodes:
        if episode.episode_id in episode_by_id:
            raise ValueError("duplicate episode_id")
        episode_by_id[episode.episode_id] = episode
        for observation_id in episode.observation_ids:
            if observation_id in seen_observations:
                raise ValueError("observation belongs to multiple episodes")
            seen_observations.add(observation_id)
            observation_ids.append(observation_id)

    variant_by_id: dict[str, AGG04VariantEvidence] = {}
    candidate_episodes: set[str] = set()
    simulated_episodes: set[str] = set()
    for variant in variants:
        if variant.episode_id not in episode_by_id:
            raise ValueError("variant references unknown episode")
        if variant.variant_id in variant_by_id:
            raise ValueError("duplicate variant_id")
        variant_by_id[variant.variant_id] = variant
        candidate_episodes.add(variant.episode_id)
        if variant.simulated:
            simulated_episodes.add(variant.episode_id)

    horizon_variants: set[str] = set()
    for probe in probes:
        variant = variant_by_id.get(probe.variant_id)
        if variant is None:
            raise ValueError("probe references unknown variant")
        if probe.message_sha256 != variant.message_sha256:
            raise ValueError("probe/message generation mismatch")
        if (
            variant.simulated
            and probe.positive is True
            and probe.elapsed_ms > survival_horizon_ms
        ):
            horizon_variants.add(variant.variant_id)

    horizon_episodes = {
        variant_by_id[variant_id].episode_id for variant_id in horizon_variants
    }
    positive_net_episodes = {
        variant_by_id[variant_id].episode_id
        for variant_id in horizon_variants
        if variant_by_id[variant_id].conservative_net_atomic is not None
        and variant_by_id[variant_id].conservative_net_atomic > 0
    }

    return AGG04FunnelReport(
        observation_ids=tuple(observation_ids),
        episode_ids=tuple(episode_by_id),
        candidate_episode_ids=tuple(sorted(candidate_episodes)),
        simulated_episode_ids=tuple(sorted(simulated_episodes)),
        horizon_episode_ids=tuple(sorted(horizon_episodes)),
        positive_net_episode_ids=tuple(sorted(positive_net_episodes)),
    )


@dataclass(frozen=True, slots=True)
class AGG04QualificationVerdict:
    """Class-level qualification only; never a live/release authorization."""

    status: str
    campaign_id: str
    profile_id: str
    source_commit: str
    policy_sha256: str
    split_sha256: str
    funnel_sha256: str
    counts: Mapping[str, int]
    reason_codes: tuple[str, ...]
    allowed_assets: tuple[str, ...]
    allowed_venues: tuple[str, ...]
    allowed_lenders: tuple[str, ...]
    as_of_ns: int
    live_enabled: bool = False
    release_claim_allowed: bool = False
    production_ready: bool = False

    def __post_init__(self) -> None:
        if self.status not in {
            AGG04_QUALIFIED_SCOPE,
            AGG04_INSUFFICIENT_EVIDENCE,
            AGG04_NEGATIVE,
        }:
            raise ValueError("unsupported AGG-04 qualification status")
        for field in ("campaign_id", "profile_id", "source_commit"):
            object.__setattr__(self, field, _agg04_text(getattr(self, field), field))
        for field in ("policy_sha256", "split_sha256", "funnel_sha256"):
            object.__setattr__(self, field, _agg04_digest(getattr(self, field), field))
        _agg04_int(self.as_of_ns, "as_of_ns")
        if self.live_enabled or self.release_claim_allowed or self.production_ready:
            raise ValueError("AGG-04 class qualification cannot authorize live/release")
        object.__setattr__(
            self, "reason_codes", _agg04_unique(tuple(self.reason_codes), "reason_code")
        )

    @property
    def qualified(self) -> bool:
        return self.status == AGG04_QUALIFIED_SCOPE and not self.reason_codes

    @property
    def verdict_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "schema_version": AGG04_SCHEMA,
                "status": self.status,
                "campaign_id": self.campaign_id,
                "profile_id": self.profile_id,
                "source_commit": self.source_commit,
                "policy_sha256": self.policy_sha256,
                "split_sha256": self.split_sha256,
                "funnel_sha256": self.funnel_sha256,
                "counts": dict(sorted(self.counts.items())),
                "reason_codes": list(self.reason_codes),
                "allowed_assets": list(self.allowed_assets),
                "allowed_venues": list(self.allowed_venues),
                "allowed_lenders": list(self.allowed_lenders),
                "as_of_ns": self.as_of_ns,
                "live_enabled": self.live_enabled,
                "release_claim_allowed": self.release_claim_allowed,
                "production_ready": self.production_ready,
            }
        )


def qualify_agg04_campaign(
    *,
    policy: AGG04CampaignPolicy,
    funnel: AGG04FunnelReport,
    temporal_split: AGG04TemporalSplit,
    as_of_ns: int,
    external_blockers: tuple[str, ...] = (),
) -> AGG04QualificationVerdict:
    """Issue a scoped class verdict from frozen policy and nested evidence."""

    _agg04_int(as_of_ns, "as_of_ns")
    reasons: list[str] = []
    split_episode_ids = (
        set(temporal_split.train_episode_ids)
        | set(temporal_split.validation_episode_ids)
        | set(temporal_split.holdout_episode_ids)
    )
    if not set(funnel.episode_ids) <= split_episode_ids:
        reasons.append("EPISODE_OUTSIDE_FROZEN_SPLIT")
    for blocker in external_blockers:
        reasons.append(f"EXTERNAL_BLOCKER:{_agg04_text(blocker, 'external_blocker')}")
    counts = funnel.counts
    if counts["S"] < policy.min_simulated_episodes:
        reasons.append("INSUFFICIENT_SIMULATED_EPISODES")
    if counts["H"] < policy.min_horizon_episodes:
        reasons.append("INSUFFICIENT_HORIZON_EPISODES")

    if reasons:
        status = AGG04_INSUFFICIENT_EVIDENCE
    elif counts["N"] < policy.min_positive_net_episodes:
        status = AGG04_NEGATIVE
        reasons.append("POSITIVE_NET_THRESHOLD_NOT_MET")
    else:
        status = AGG04_QUALIFIED_SCOPE

    return AGG04QualificationVerdict(
        status=status,
        campaign_id=policy.campaign_id,
        profile_id=policy.profile_id,
        source_commit=policy.source_commit,
        policy_sha256=policy.policy_sha256,
        split_sha256=temporal_split.split_sha256,
        funnel_sha256=funnel.funnel_sha256,
        counts=counts,
        reason_codes=tuple(reasons),
        allowed_assets=policy.allowed_assets,
        allowed_venues=policy.allowed_venues,
        allowed_lenders=policy.allowed_lenders,
        as_of_ns=as_of_ns,
    )


@dataclass(frozen=True, slots=True)
class AGG04EvidencePackage:
    """Content-addressed evidence envelope for a reproducible AGG-04 campaign."""

    source_commit: str
    policy_sha256: str
    split_sha256: str
    funnel_sha256: str
    verdict_sha256: str
    reproducible_command: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_commit", _agg04_text(self.source_commit, "source_commit"))
        for field in (
            "policy_sha256",
            "split_sha256",
            "funnel_sha256",
            "verdict_sha256",
        ):
            object.__setattr__(self, field, _agg04_digest(getattr(self, field), field))
        object.__setattr__(
            self,
            "reproducible_command",
            _agg04_text(self.reproducible_command, "reproducible_command"),
        )
        object.__setattr__(
            self, "limitations", _agg04_unique(tuple(self.limitations), "limitation")
        )

    @property
    def manifest_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "schema_version": AGG04_SCHEMA,
                "source_commit": self.source_commit,
                "policy_sha256": self.policy_sha256,
                "split_sha256": self.split_sha256,
                "funnel_sha256": self.funnel_sha256,
                "verdict_sha256": self.verdict_sha256,
                "reproducible_command": self.reproducible_command,
                "limitations": list(self.limitations),
            }
        )


def build_agg04_evidence_package(
    *,
    policy: AGG04CampaignPolicy,
    temporal_split: AGG04TemporalSplit,
    funnel: AGG04FunnelReport,
    verdict: AGG04QualificationVerdict,
    reproducible_command: str,
    limitations: tuple[str, ...] = (),
) -> AGG04EvidencePackage:
    if verdict.campaign_id != policy.campaign_id:
        raise ValueError("verdict/policy campaign mismatch")
    if verdict.policy_sha256 != policy.policy_sha256:
        raise ValueError("verdict/policy digest mismatch")
    if verdict.split_sha256 != temporal_split.split_sha256:
        raise ValueError("verdict/split digest mismatch")
    if verdict.funnel_sha256 != funnel.funnel_sha256:
        raise ValueError("verdict/funnel digest mismatch")
    return AGG04EvidencePackage(
        source_commit=policy.source_commit,
        policy_sha256=policy.policy_sha256,
        split_sha256=temporal_split.split_sha256,
        funnel_sha256=funnel.funnel_sha256,
        verdict_sha256=verdict.verdict_sha256,
        reproducible_command=reproducible_command,
        limitations=limitations,
    )

AGG04_REJECTION_CODES = frozenset(
    {
        "STALE_OR_GAP",
        "INVALID_ASSET",
        "MISSING_ACCOUNTS",
        "FEES",
        "LIQUIDITY",
        "BUILD_SIZE",
        "GUARD",
        "SIMULATION_ERROR",
        "UNQUALIFIED_LENDER",
        "QUOTA_LIMIT",
        "AUTHORIZATION",
        "UNSAMPLED",
        "UNKNOWN",
    }
)


@dataclass(frozen=True, slots=True)
class AGG04AnomalyObservation:
    """Raw anomaly registration before filtering/ranking."""

    observation_id: str
    frame_sha256: str
    feature_set_sha256: str
    source_sha256: str
    decision_time_ns: int
    sampled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observation_id", _agg04_text(self.observation_id, "observation_id")
        )
        for field in ("frame_sha256", "feature_set_sha256", "source_sha256"):
            object.__setattr__(self, field, _agg04_digest(getattr(self, field), field))
        _agg04_int(self.decision_time_ns, "decision_time_ns")
        if not isinstance(self.sampled, bool):
            raise ValueError("sampled must be bool")

    @property
    def observation_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "observation_id": self.observation_id,
                "frame_sha256": self.frame_sha256,
                "feature_set_sha256": self.feature_set_sha256,
                "source_sha256": self.source_sha256,
                "decision_time_ns": self.decision_time_ns,
                "sampled": self.sampled,
            }
        )


def validate_agg04_rejection_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = _agg04_text(value, "rejection_code").upper()
    if code not in AGG04_REJECTION_CODES:
        raise ValueError("unsupported AGG-04 rejection_code")
    return code


@dataclass(frozen=True, slots=True)
class AGG04SurvivalObservation:
    """Interval/right-censored lifetime evidence for one exact variant."""

    variant_id: str
    last_positive_ms: int | None
    first_negative_ms: int | None
    positive_at_horizon: bool
    right_censored: bool
    interval_censored: bool
    unknown_probe_count: int
    horizon_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_id", _agg04_text(self.variant_id, "variant_id"))
        for field in ("last_positive_ms", "first_negative_ms"):
            value = getattr(self, field)
            if value is not None:
                _agg04_int(value, field)
        _agg04_int(self.unknown_probe_count, "unknown_probe_count")
        _agg04_int(self.horizon_ms, "horizon_ms", minimum=1)
        if not isinstance(self.positive_at_horizon, bool):
            raise ValueError("positive_at_horizon must be bool")
        if not isinstance(self.right_censored, bool):
            raise ValueError("right_censored must be bool")
        if not isinstance(self.interval_censored, bool):
            raise ValueError("interval_censored must be bool")
        if (
            self.last_positive_ms is not None
            and self.first_negative_ms is not None
            and self.first_negative_ms <= self.last_positive_ms
        ):
            raise ValueError("first negative must occur after last positive")


def build_agg04_survival_observation(
    *,
    variant: AGG04VariantEvidence,
    probes: tuple[AGG04ProbeEvidence, ...],
    horizon_ms: int,
) -> AGG04SurvivalObservation:
    """Classify probes without inventing continuous profitability between probes."""

    _agg04_int(horizon_ms, "horizon_ms", minimum=1)
    related: list[AGG04ProbeEvidence] = []
    for probe in probes:
        if probe.variant_id != variant.variant_id:
            continue
        if probe.message_sha256 != variant.message_sha256:
            raise ValueError("probe/message generation mismatch")
        related.append(probe)
    related.sort(key=lambda item: item.elapsed_ms)

    positives = [item.elapsed_ms for item in related if item.positive is True]
    last_positive = max(positives) if positives else None
    later_negatives = [
        item.elapsed_ms
        for item in related
        if item.positive is False
        and last_positive is not None
        and item.elapsed_ms > last_positive
    ]
    first_negative = min(later_negatives) if later_negatives else None
    positive_at_horizon = any(
        item.positive is True and item.elapsed_ms > horizon_ms for item in related
    )
    right_censored = bool(positives) and first_negative is None
    interval_censored = last_positive is not None and first_negative is not None

    return AGG04SurvivalObservation(
        variant_id=variant.variant_id,
        last_positive_ms=last_positive,
        first_negative_ms=first_negative,
        positive_at_horizon=positive_at_horizon,
        right_censored=right_censored,
        interval_censored=interval_censored,
        unknown_probe_count=sum(item.positive is None for item in related),
        horizon_ms=horizon_ms,
    )


@dataclass(frozen=True, slots=True)
class AGG04SelectionBiasReport:
    """Selection observability; it never claims unbiasedness when propensity is unknown."""

    tested_hypotheses: int
    sampled_episode_ids: tuple[str, ...]
    known_propensity_episode_ids: tuple[str, ...]
    correction_method: str | None

    def __post_init__(self) -> None:
        _agg04_int(self.tested_hypotheses, "tested_hypotheses", minimum=1)
        sampled = _agg04_unique(tuple(self.sampled_episode_ids), "sampled_episode_id")
        known = _agg04_unique(
            tuple(self.known_propensity_episode_ids), "known_propensity_episode_id"
        )
        if not set(known) <= set(sampled):
            raise ValueError("known propensity episodes must be sampled")
        if self.correction_method is not None:
            object.__setattr__(
                self,
                "correction_method",
                _agg04_text(self.correction_method, "correction_method"),
            )
        object.__setattr__(self, "sampled_episode_ids", sampled)
        object.__setattr__(self, "known_propensity_episode_ids", known)

    @property
    def unknown_propensity_episode_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.sampled_episode_ids) - set(self.known_propensity_episode_ids))
        )

    @property
    def unbiased_claim_allowed(self) -> bool:
        return (
            not self.unknown_propensity_episode_ids
            and self.correction_method is not None
            and self.tested_hypotheses >= 1
        )


@dataclass(frozen=True, slots=True)
class AGG04ClassStatistics:
    """Integer-only independent-episode net summary."""

    episode_count: int
    known_net_episode_count: int
    positive_net_episode_count: int
    negative_net_episode_count: int
    zero_net_episode_count: int
    unknown_net_episode_count: int
    total_net_atomic: int
    minimum_net_atomic: int | None
    maximum_net_atomic: int | None
    selection_policy_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "episode_count",
            "known_net_episode_count",
            "positive_net_episode_count",
            "negative_net_episode_count",
            "zero_net_episode_count",
            "unknown_net_episode_count",
        ):
            _agg04_int(getattr(self, field), field)
        if (
            self.known_net_episode_count + self.unknown_net_episode_count
            != self.episode_count
        ):
            raise ValueError("class statistics episode accounting mismatch")
        if (
            self.positive_net_episode_count
            + self.negative_net_episode_count
            + self.zero_net_episode_count
            != self.known_net_episode_count
        ):
            raise ValueError("known net sign accounting mismatch")
        if isinstance(self.total_net_atomic, bool) or not isinstance(
            self.total_net_atomic, int
        ):
            raise ValueError("total_net_atomic must be integer")
        for field in ("minimum_net_atomic", "maximum_net_atomic"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{field} must be integer or null")
        object.__setattr__(
            self,
            "selection_policy_sha256",
            _agg04_digest(self.selection_policy_sha256, "selection_policy_sha256"),
        )

    @property
    def mean_net_ratio(self) -> tuple[int, int] | None:
        if self.known_net_episode_count == 0:
            return None
        return (self.total_net_atomic, self.known_net_episode_count)


def compute_agg04_class_statistics(
    *,
    variants: tuple[AGG04VariantEvidence, ...],
    selected_variant_ids: tuple[str, ...],
    selection_policy_sha256: str,
) -> AGG04ClassStatistics:
    """Summarize exactly one preselected variant per independent episode."""

    by_id = {item.variant_id: item for item in variants}
    if len(by_id) != len(variants):
        raise ValueError("duplicate variant_id")
    selected = _agg04_unique(tuple(selected_variant_ids), "selected_variant_id")
    chosen: list[AGG04VariantEvidence] = []
    seen_episodes: set[str] = set()
    for variant_id in selected:
        variant = by_id.get(variant_id)
        if variant is None:
            raise ValueError("selected variant is unknown")
        if variant.episode_id in seen_episodes:
            raise ValueError("class statistics cannot cherry-pick two variants per episode")
        seen_episodes.add(variant.episode_id)
        chosen.append(variant)

    known = [
        item.conservative_net_atomic
        for item in chosen
        if item.conservative_net_atomic is not None
    ]
    positive = sum(value > 0 for value in known)
    negative = sum(value < 0 for value in known)
    zero = sum(value == 0 for value in known)
    return AGG04ClassStatistics(
        episode_count=len(chosen),
        known_net_episode_count=len(known),
        positive_net_episode_count=positive,
        negative_net_episode_count=negative,
        zero_net_episode_count=zero,
        unknown_net_episode_count=len(chosen) - len(known),
        total_net_atomic=sum(known),
        minimum_net_atomic=min(known) if known else None,
        maximum_net_atomic=max(known) if known else None,
        selection_policy_sha256=selection_policy_sha256,
    )


@dataclass(frozen=True, slots=True)
class AGG04PairedEpisodeResult:
    episode_id: str
    baseline_net_atomic: int | None
    challenger_net_atomic: int | None
    baseline_resource_cost_atomic: int
    challenger_resource_cost_atomic: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _agg04_text(self.episode_id, "episode_id"))
        for field in ("baseline_net_atomic", "challenger_net_atomic"):
            value = getattr(self, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{field} must be integer or null")
        for field in (
            "baseline_resource_cost_atomic",
            "challenger_resource_cost_atomic",
        ):
            _agg04_int(getattr(self, field), field)


@dataclass(frozen=True, slots=True)
class AGG04PairedComparison:
    paired_episode_count: int
    unknown_episode_count: int
    challenger_incremental_net_atomic: int
    improved_episode_count: int
    degraded_episode_count: int
    tied_episode_count: int

    def __post_init__(self) -> None:
        for field in (
            "paired_episode_count",
            "unknown_episode_count",
            "improved_episode_count",
            "degraded_episode_count",
            "tied_episode_count",
        ):
            _agg04_int(getattr(self, field), field)
        if (
            self.improved_episode_count
            + self.degraded_episode_count
            + self.tied_episode_count
            != self.paired_episode_count
        ):
            raise ValueError("paired comparison accounting mismatch")
        if isinstance(self.challenger_incremental_net_atomic, bool) or not isinstance(
            self.challenger_incremental_net_atomic, int
        ):
            raise ValueError("challenger_incremental_net_atomic must be integer")


def compare_agg04_baselines(
    rows: tuple[AGG04PairedEpisodeResult, ...],
) -> AGG04PairedComparison:
    """Paired comparison with explicit resource cost and unknown episodes."""

    seen: set[str] = set()
    deltas: list[int] = []
    unknown = 0
    for row in rows:
        if row.episode_id in seen:
            raise ValueError("duplicate paired episode")
        seen.add(row.episode_id)
        if row.baseline_net_atomic is None or row.challenger_net_atomic is None:
            unknown += 1
            continue
        baseline = row.baseline_net_atomic - row.baseline_resource_cost_atomic
        challenger = row.challenger_net_atomic - row.challenger_resource_cost_atomic
        deltas.append(challenger - baseline)
    return AGG04PairedComparison(
        paired_episode_count=len(deltas),
        unknown_episode_count=unknown,
        challenger_incremental_net_atomic=sum(deltas),
        improved_episode_count=sum(value > 0 for value in deltas),
        degraded_episode_count=sum(value < 0 for value in deltas),
        tied_episode_count=sum(value == 0 for value in deltas),
    )


@dataclass(frozen=True, slots=True)
class AGG04DelayStressSample:
    """Counterfactual delay outcome; never mislabeled as an observed market outcome."""

    episode_id: str
    latency_ms: int
    profitable_after_delay: bool | None
    state_evidence_sha256: str
    counterfactual: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "episode_id", _agg04_text(self.episode_id, "episode_id"))
        _agg04_int(self.latency_ms, "latency_ms")
        object.__setattr__(
            self,
            "state_evidence_sha256",
            _agg04_digest(self.state_evidence_sha256, "state_evidence_sha256"),
        )
        if self.profitable_after_delay is not None and not isinstance(
            self.profitable_after_delay, bool
        ):
            raise ValueError("profitable_after_delay must be bool or null")
        if self.counterfactual is not True:
            raise ValueError("delay stress samples must remain counterfactual")


@dataclass(frozen=True, slots=True)
class AGG04DelayStressReport:
    sample_count: int
    positive_count: int
    negative_count: int
    unknown_count: int
    maximum_latency_ms: int | None

    def __post_init__(self) -> None:
        for field in ("sample_count", "positive_count", "negative_count", "unknown_count"):
            _agg04_int(getattr(self, field), field)
        if self.positive_count + self.negative_count + self.unknown_count != self.sample_count:
            raise ValueError("delay stress accounting mismatch")
        if self.maximum_latency_ms is not None:
            _agg04_int(self.maximum_latency_ms, "maximum_latency_ms")


def summarize_agg04_delay_stress(
    samples: tuple[AGG04DelayStressSample, ...],
) -> AGG04DelayStressReport:
    return AGG04DelayStressReport(
        sample_count=len(samples),
        positive_count=sum(item.profitable_after_delay is True for item in samples),
        negative_count=sum(item.profitable_after_delay is False for item in samples),
        unknown_count=sum(item.profitable_after_delay is None for item in samples),
        maximum_latency_ms=max((item.latency_ms for item in samples), default=None),
    )


@dataclass(frozen=True, slots=True)
class AGG04RegressionCase:
    bug_class: str
    fixture_sha256: str
    expected_stage: str
    expected_code: str
    source_program_generation: str

    def __post_init__(self) -> None:
        for field in (
            "bug_class",
            "expected_stage",
            "expected_code",
            "source_program_generation",
        ):
            object.__setattr__(self, field, _agg04_text(getattr(self, field), field))
        object.__setattr__(
            self, "fixture_sha256", _agg04_digest(self.fixture_sha256, "fixture_sha256")
        )

    @property
    def regression_sha256(self) -> str:
        return _agg04_hash_payload(
            {
                "bug_class": self.bug_class,
                "fixture_sha256": self.fixture_sha256,
                "expected_stage": self.expected_stage,
                "expected_code": self.expected_code,
                "source_program_generation": self.source_program_generation,
            }
        )


@dataclass(frozen=True, slots=True)
class AGG04DemotionTransition:
    prior_verdict_sha256: str
    trigger: str
    affected_scope: tuple[str, ...]
    requalification_required: bool = True
    live_enabled: bool = False
    automatic_rearm_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prior_verdict_sha256",
            _agg04_digest(self.prior_verdict_sha256, "prior_verdict_sha256"),
        )
        object.__setattr__(self, "trigger", _agg04_text(self.trigger, "trigger"))
        scope = _agg04_unique(tuple(self.affected_scope), "affected_scope")
        if not scope:
            raise ValueError("demotion scope cannot be empty")
        object.__setattr__(self, "affected_scope", scope)
        if not self.requalification_required:
            raise ValueError("demotion must require requalification")
        if self.live_enabled or self.automatic_rearm_allowed:
            raise ValueError("demotion cannot arm live execution")


def build_agg04_dashboard(
    *,
    funnel: AGG04FunnelReport,
    verdict: AGG04QualificationVerdict,
    unresolved_reason_codes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Machine-readable dashboard projection; no demo rows or inferred zeroes."""

    unresolved = _agg04_unique(
        tuple(unresolved_reason_codes), "unresolved_reason_code"
    )
    return {
        "schema_version": AGG04_SCHEMA,
        "campaign_id": verdict.campaign_id,
        "profile_id": verdict.profile_id,
        "status": verdict.status,
        "counts": dict(funnel.counts),
        "reason_codes": list(verdict.reason_codes),
        "unresolved_reason_codes": list(unresolved),
        "live_enabled": False,
        "release_claim_allowed": False,
        "production_ready": False,
        "funnel_sha256": funnel.funnel_sha256,
        "verdict_sha256": verdict.verdict_sha256,
    }

