# fmt: off
"""PR-139 scheduled external and on-chain drift operations.

Offline/fail-closed evaluator for scheduled provider, on-chain, and RPC drift
checks. It does not perform live HTTP or RPC calls; scheduled workflows and
operators feed it already-collected observations and it decides whether current
evidence still permits execution capability.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR139_SCHEMA_VERSION = "pr139.scheduled-drift.v1"
PR139_RESULT_SCHEMA_VERSION = "pr139.scheduled-drift-result.v1"

REQUIRED_EXTERNAL_APIS = frozenset(
    {"jupiter", "jito", "okx", "openocean", "odos"}
)
REQUIRED_ONCHAIN_TARGETS = frozenset(
    {
        "programdata-hash",
        "upgrade-authority",
        "deployment-slot",
        "marginfi-group-bank-oracle",
        "token-mint-extensions",
        "alt-lifecycle",
    }
)
REQUIRED_RPC_TARGETS = frozenset(
    {"genesis", "node-version", "feature-capability"}
)
RUN_PROFILES = frozenset({"daily-lightweight", "weekly-full", "manual"})
SECRET_FIELD_RE = re.compile(r"(authorization|token|secret|api[_-]?key)", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR139DriftError(ValueError):
    """Raised when PR-139 drift input is structurally invalid."""


class ProbeKind(StrEnum):
    EXTERNAL_API = "external-api"
    ONCHAIN = "on-chain"
    RPC = "rpc"


class ProbeStatus(StrEnum):
    MATCH = "match"
    DRIFT = "drift"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class ProbeDecision:
    probe_id: str
    kind: str
    target: str
    admission_allowed: bool
    status: str
    blockers: tuple[str, ...]
    drift_events: tuple[str, ...]
    operator_alert: bool


@dataclass(frozen=True, slots=True)
class PR139EvaluationResult:
    schema_version: str
    run_profile: str
    execution_capability_allowed: bool
    operator_alert: bool
    pin_rotation_pr_required: bool
    immutable_evidence_hash: str
    historical_timeline_hash: str
    probe_results: tuple[ProbeDecision, ...]
    blockers: tuple[str, ...]
    drift_events: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_pr139_scheduled_drift(
    manifest: Mapping[str, object],
    observations: Mapping[str, object],
    *,
    run_profile: str,
) -> PR139EvaluationResult:
    """Evaluate scheduled drift evidence without live provider/RPC calls."""

    if run_profile not in RUN_PROFILES:
        raise PR139DriftError(f"unsupported run profile: {run_profile}")

    blockers: list[str] = []
    drift_events: list[str] = []
    if _string(manifest, "schema_version") != PR139_SCHEMA_VERSION:
        blockers.append("PR139_SCHEMA_UNSUPPORTED")
    if bool(manifest.get("allow_automated_acceptance", False)):
        blockers.append("PR139_AUTOMATED_ACCEPTANCE_FORBIDDEN")

    now_unix = _positive_int(manifest, "now_unix")
    max_age_seconds = _positive_int(manifest, "max_evidence_age_seconds")
    probes = tuple(_probe_spec(item) for item in _sequence(manifest, "probes"))
    observed_by_id = {
        _string(item, "probe_id"): _mapping(item, "observation")
        for item in _sequence(observations, "observations", default=())
    }

    _coverage_blockers(probes, run_profile, blockers)

    probe_results: list[ProbeDecision] = []
    for probe in probes:
        result = _evaluate_probe(
            probe,
            observed_by_id.get(str(probe["probe_id"])),
            now_unix=now_unix,
            max_age_seconds=max_age_seconds,
        )
        probe_results.append(result)
        blockers.extend(result.blockers)
        drift_events.extend(result.drift_events)

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_drift = tuple(dict.fromkeys(drift_events))
    evidence_hash = immutable_evidence_hash(manifest, observations)
    timeline_hash = historical_timeline_hash(
        observations.get("historical_drift_timeline", ())
    )
    execution_allowed = not unique_blockers and not unique_drift and bool(probe_results)
    return PR139EvaluationResult(
        schema_version=PR139_RESULT_SCHEMA_VERSION,
        run_profile=run_profile,
        execution_capability_allowed=execution_allowed,
        operator_alert=bool(unique_blockers or unique_drift),
        pin_rotation_pr_required=bool(unique_drift),
        immutable_evidence_hash=evidence_hash,
        historical_timeline_hash=timeline_hash,
        probe_results=tuple(probe_results),
        blockers=unique_blockers,
        drift_events=unique_drift,
    )


def immutable_evidence_hash(
    manifest: Mapping[str, object],
    observations: Mapping[str, object],
) -> str:
    """Return a stable hash of redacted evidence suitable for artifacts."""

    redacted = {
        "manifest": redact_secrets(manifest),
        "observations": redact_secrets(observations),
    }
    encoded = json.dumps(redacted, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def historical_timeline_hash(value: object) -> str:
    """Hash the drift timeline so evidence can prove continuity across runs."""

    timeline = list(value) if isinstance(value, (list, tuple)) else []
    encoded = json.dumps(
        redact_secrets(timeline),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def redact_secrets(value: object) -> object:
    """Deterministically redact secret-shaped evidence fields before hashing."""

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key in sorted(value):
            if SECRET_FIELD_RE.search(str(key)):
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = redact_secrets(value[key])
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    return value


def _coverage_blockers(
    probes: Sequence[Mapping[str, object]],
    run_profile: str,
    blockers: list[str],
) -> None:
    external = {str(item["target"]) for item in probes if item["kind"] is ProbeKind.EXTERNAL_API}
    onchain = {str(item["target"]) for item in probes if item["kind"] is ProbeKind.ONCHAIN}
    rpc = {str(item["target"]) for item in probes if item["kind"] is ProbeKind.RPC}

    for target in sorted(REQUIRED_EXTERNAL_APIS - external):
        blockers.append(f"PR139_EXTERNAL_API_PROBE_MISSING:{target}")
    for target in sorted(REQUIRED_RPC_TARGETS - rpc):
        blockers.append(f"PR139_RPC_PROBE_MISSING:{target}")
    if run_profile in {"weekly-full", "manual"}:
        for target in sorted(REQUIRED_ONCHAIN_TARGETS - onchain):
            blockers.append(f"PR139_ONCHAIN_PROBE_MISSING:{target}")


def _evaluate_probe(
    probe: Mapping[str, object],
    observation: Mapping[str, object] | None,
    *,
    now_unix: int,
    max_age_seconds: int,
) -> ProbeDecision:
    probe_id = str(probe["probe_id"])
    kind = ProbeKind(str(probe["kind"]))
    target = str(probe["target"])
    blockers: list[str] = []
    drift_events: list[str] = []

    if observation is None:
        blockers.append(f"PR139_PROBE_OBSERVATION_MISSING:{probe_id}")
        return _decision(probe_id, kind, target, ProbeStatus.UNAVAILABLE, blockers, drift_events)

    status = ProbeStatus(_string(observation, "status"))
    observed_at = _positive_int(observation, "observed_at_unix")
    age = now_unix - observed_at
    if age < 0:
        blockers.append(f"PR139_PROBE_FROM_FUTURE:{probe_id}")
    if age > max_age_seconds or status is ProbeStatus.STALE:
        blockers.append(f"PR139_EVIDENCE_STALE:{probe_id}")

    if bool(probe.get("credential_required", False)):
        if not bool(observation.get("credentialed", False)):
            blockers.append(f"PR139_CREDENTIALED_PROBE_UNAVAILABLE:{probe_id}")
        if not bool(probe.get("protected_environment", False)):
            blockers.append(f"PR139_PROTECTED_ENVIRONMENT_REQUIRED:{probe_id}")

    expected_hash = _optional_sha(probe, "expected_hash")
    observed_hash = _optional_sha(observation, "observed_hash")
    if status is ProbeStatus.DRIFT:
        drift_events.append(f"PR139_DRIFT:{probe_id}:{target}")
    if status is ProbeStatus.UNAVAILABLE:
        blockers.append(f"PR139_PROBE_UNAVAILABLE:{probe_id}")
    if status is ProbeStatus.INDETERMINATE:
        blockers.append(f"PR139_PROBE_INDETERMINATE:{probe_id}")
    if expected_hash and observed_hash and expected_hash != observed_hash:
        drift_events.append(f"PR139_HASH_DRIFT:{probe_id}:{target}")
    if not _valid_sha(_optional_string(observation, "evidence_hash")):
        blockers.append(f"PR139_EVIDENCE_HASH_INVALID:{probe_id}")

    return _decision(probe_id, kind, target, status, blockers, drift_events)


def _decision(
    probe_id: str,
    kind: ProbeKind,
    target: str,
    status: ProbeStatus,
    blockers: Sequence[str],
    drift_events: Sequence[str],
) -> ProbeDecision:
    return ProbeDecision(
        probe_id=probe_id,
        kind=str(kind),
        target=target,
        admission_allowed=not blockers and not drift_events,
        status=str(status),
        blockers=tuple(dict.fromkeys(blockers)),
        drift_events=tuple(dict.fromkeys(drift_events)),
        operator_alert=bool(blockers or drift_events),
    )


def _probe_spec(raw: object) -> dict[str, object]:
    item = _mapping(raw, "probe")
    expected_hash = _optional_sha(item, "expected_hash")
    return {
        "probe_id": _string(item, "probe_id"),
        "kind": ProbeKind(_string(item, "kind")),
        "target": _string(item, "target"),
        "expected_hash": expected_hash,
        "credential_required": _bool(item, "credential_required", default=False),
        "protected_environment": _bool(item, "protected_environment", default=False),
    }


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PR139DriftError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _sequence(
    payload: Mapping[str, object],
    field: str,
    *,
    default: Sequence[object] | None = None,
) -> Sequence[object]:
    value = payload.get(field, default)
    if not isinstance(value, (list, tuple)):
        raise PR139DriftError(f"FIELD_NOT_LIST:{field}")
    return value


def _string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PR139DriftError(f"FIELD_NOT_STRING:{field}")
    return value


def _optional_string(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PR139DriftError(f"FIELD_NOT_STRING:{field}")
    return value


def _positive_int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PR139DriftError(f"FIELD_NOT_NON_NEGATIVE_INT:{field}")
    return value


def _bool(
    payload: Mapping[str, object],
    field: str,
    *,
    default: bool,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PR139DriftError(f"FIELD_NOT_BOOL:{field}")
    return value


def _optional_sha(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    if not _valid_sha(value):
        raise PR139DriftError(f"FIELD_NOT_SHA256:{field}")
    return value


def _valid_sha(value: str | None) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value)) and value != (
        "0" * 64
    )


def _fixture_manifest() -> tuple[dict[str, object], dict[str, object]]:
    now = 1_785_000_000
    manifest: dict[str, object] = {
        "schema_version": PR139_SCHEMA_VERSION,
        "now_unix": now,
        "max_evidence_age_seconds": 86_400,
        "allow_automated_acceptance": False,
        "probes": _fixture_probes(),
    }
    observations = {
        "observations": [
            _observation(str(probe["probe_id"]), now - 60)
            for probe in manifest["probes"]
        ],
        "historical_drift_timeline": [
            {"run_id": "pr139-self-check", "outcome": "match", "at_unix": now}
        ],
    }
    return manifest, observations


def _fixture_probes() -> list[dict[str, object]]:
    probes: list[dict[str, object]] = []
    for target in sorted(REQUIRED_EXTERNAL_APIS):
        probes.append(_probe(f"api-{target}", "external-api", target))
    for target in sorted(REQUIRED_ONCHAIN_TARGETS):
        probes.append(_probe(f"chain-{target}", "on-chain", target))
    for target in sorted(REQUIRED_RPC_TARGETS):
        probes.append(_probe(f"rpc-{target}", "rpc", target))
    return probes


def _probe(probe_id: str, kind: str, target: str) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "kind": kind,
        "target": target,
        "expected_hash": "a" * 64,
        "credential_required": kind == "external-api",
        "protected_environment": kind == "external-api",
    }


def _observation(probe_id: str, observed_at: int) -> dict[str, object]:
    return {
        "probe_id": probe_id,
        "status": "match",
        "observed_at_unix": observed_at,
        "observed_hash": "a" * 64,
        "evidence_hash": "b" * 64,
        "credentialed": True,
        "authorization": "fixture-secret-is-redacted",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline PR-139 scheduled drift self-check."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    manifest, observations = _fixture_manifest()
    result = evaluate_pr139_scheduled_drift(
        manifest,
        observations,
        run_profile="weekly-full",
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"PR-139 execution capability allowed: {result.execution_capability_allowed}")
    return 0 if result.execution_capability_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PR139DriftError",
    "PR139EvaluationResult",
    "PR139_RESULT_SCHEMA_VERSION",
    "PR139_SCHEMA_VERSION",
    "ProbeDecision",
    "ProbeKind",
    "ProbeStatus",
    "REQUIRED_EXTERNAL_APIS",
    "REQUIRED_ONCHAIN_TARGETS",
    "REQUIRED_RPC_TARGETS",
    "evaluate_pr139_scheduled_drift",
    "historical_timeline_hash",
    "immutable_evidence_hash",
    "main",
    "redact_secrets",
]
# fmt: on
