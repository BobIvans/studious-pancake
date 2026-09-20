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

