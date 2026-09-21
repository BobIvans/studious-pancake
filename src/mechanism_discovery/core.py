"""Sender-free deterministic kernel for PR-354 mechanism-discovery research."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping


class MechanismDiscoveryError(ValueError):
    """Typed fail-closed PR-354 contract violation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ResearchState(StrEnum):
    DISABLED = "DISABLED"
    RECORDED_OFFLINE = "RECORDED_OFFLINE"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    SHADOW_CANDIDATE = "SHADOW_CANDIDATE"
    VERIFIED_SHADOW = "VERIFIED_SHADOW"
    REJECTED_WITH_EVIDENCE = "REJECTED_WITH_EVIDENCE"
    BLOCKED = "BLOCKED"
    INCONCLUSIVE = "INCONCLUSIVE"


_ALLOWED_FINALITY = {"ROOTED", "FINALIZED", "CONFIRMED", "SYNTHETIC"}
_TIME_FIELDS = ("event_time", "received_at", "available_at")
_SECRET_FIELDS = {
    "private_key",
    "secret_key",
    "auth_header",
    "authorization",
    "signed_transaction",
    "raw_signed_transaction",
    "seed_phrase",
    "mnemonic",
}
_EFFECT_FIELDS = {
    "live_enabled",
    "live_authority",
    "signing",
    "submission",
    "sender",
    "signer",
    "wallet_funding",
    "auto_promotion",
    "remote_mutation",
}


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise MechanismDiscoveryError("NON_EXACT_RESEARCH_VALUE")


def stable_hash(domain: str, value: Any) -> str:
    if not isinstance(domain, str) or not domain.strip():
        raise MechanismDiscoveryError("DOMAIN_REQUIRED")
    encoded = json.dumps(
        {"domain": domain, "value": _canonical(value)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_secrets_and_effects(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SECRET_FIELDS and item not in (None, "", False):
                raise MechanismDiscoveryError("SECRET_DETECTED")
            if lowered in _EFFECT_FIELDS and bool(item):
                raise MechanismDiscoveryError("EFFECT_AUTHORITY_FORBIDDEN")
            _reject_secrets_and_effects(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _reject_secrets_and_effects(item)


def validate_point_in_time(payload: Mapping[str, Any], *, required: bool = False) -> None:
    present = tuple(field in payload for field in _TIME_FIELDS)
    if required and not all(present):
        raise MechanismDiscoveryError("POINT_IN_TIME_FIELDS_REQUIRED")
    if any(present):
        if not all(present):
            raise MechanismDiscoveryError("POINT_IN_TIME_FIELDS_REQUIRED")
        event_time = payload["event_time"]
        received_at = payload["received_at"]
        available_at = payload["available_at"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (event_time, received_at, available_at)):
            raise MechanismDiscoveryError("POINT_IN_TIME_INTEGER_REQUIRED")
        if not event_time <= received_at <= available_at:
            raise MechanismDiscoveryError("FUTURE_DATA_LEAKAGE")
    finality = payload.get("finality")
    if finality is not None and finality not in _ALLOWED_FINALITY:
        raise MechanismDiscoveryError("FINALITY_UNVERIFIED")


@dataclass(frozen=True, slots=True)
class ResearchRecord:
    contract: str
    package: str
    payload: Mapping[str, Any]
    evidence_hash: str
    state: ResearchState = ResearchState.RECORDED_OFFLINE

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(_canonical(self.payload))))


def research_contract(
    name: str,
    package: str,
    payload: Mapping[str, Any],
    *,
    require_point_in_time: bool = False,
) -> ResearchRecord:
    data = dict(payload)
    _reject_secrets_and_effects(data)
    validate_point_in_time(data, required=require_point_in_time)
    if data.get("source_licensed") is False or data.get("source_entitled") is False:
        raise MechanismDiscoveryError("SOURCE_NOT_ADMITTED")
    if data.get("stale") or data.get("contradicted"):
        raise MechanismDiscoveryError("STALE_OR_CONTRADICTED_STATE")
    normalized = {
        **data,
        "research_only": True,
        "execution_queue_allowed": False,
        "live_authority": False,
        "auto_promotion": False,
    }
    return ResearchRecord(
        contract=name,
        package=package,
        payload=normalized,
        evidence_hash=stable_hash(f"pr354:{package}:{name}", normalized),
    )


_POINT_IN_TIME_PREFIXES = (
    "ingest_",
    "capture_",
    "join_",
    "watch_",
    "track_",
    "detect_",
    "validate_primitives_",
)


def make_research_function(name: str, package: str) -> Callable[..., ResearchRecord]:
    """Build a named deterministic research contract without execution authority."""

    require_clock = name.startswith(_POINT_IN_TIME_PREFIXES)

    def _function(
        payload: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> ResearchRecord:
        data = dict(payload or {})
        data.update(kwargs)
        return research_contract(
            name,
            package,
            data,
            require_point_in_time=require_clock,
        )

    _function.__name__ = name
    _function.__qualname__ = name
    _function.__doc__ = (
        f"PR-354 {package} research contract; sender-free and default-off."
    )
    return _function
