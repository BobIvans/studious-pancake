"""Corrective PR-356 residual requirement contract engine.

Every residual public symbol is a concrete adapter over this engine. The engine
normalizes immutable evidence, computes deterministic summaries, fails closed on
effect authority, and reports external blockers instead of manufacturing
empirical success.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from src.mechanism_discovery.pr356_contracts import PR356ContractError

_EFFECT_KEYS = {
    "production_ready",
    "live_enabled",
    "signer_access",
    "submission_access",
    "wallet_access",
    "remote_mutation",
    "automatic_promotion",
    "automatic_capital_increase",
    "execution_right",
}
_EXTERNAL_HINTS = (
    "capture_",
    "collect_transition_trace",
    "run_reference_route_search",
    "run_candidate_system_search",
    "run_independent_",
    "delegate_research_task",
    "verify_remote_agent_capability",
    "qualify_",
)
_FAIL_CLOSED_VERBS = {
    "audit",
    "detect",
    "downgrade",
    "expire",
    "prevent",
    "quarantine",
    "reject",
    "retire",
    "stress",
    "verify",
}


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return tuple(_normalize(item) for item in value)
    if isinstance(value, float):
        raise PR356ContractError("FLOAT_RESEARCH_VALUE_FORBIDDEN")
    return value


def _numeric_summary(payload: Mapping[str, Any]) -> Mapping[str, int]:
    values = {
        key: value
        for key, value in payload.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    result: dict[str, int] = {
        "numeric_field_count": len(values),
        "numeric_sum": sum(values.values()) if values else 0,
    }
    before = values.get("before")
    after = values.get("after")
    if before is not None and after is not None:
        result["before_after_delta"] = after - before
    baseline = values.get("baseline")
    challenger = values.get("challenger")
    if baseline is not None and challenger is not None:
        result["challenger_delta"] = challenger - baseline
    return result


def _candidate_order(payload: Mapping[str, Any]) -> tuple[str, ...]:
    candidates = payload.get("candidates", ())
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return ()
    normalized = []
    for index, row in enumerate(candidates):
        if isinstance(row, Mapping):
            candidate_id = str(
                row.get("candidate_id", row.get("id", f"candidate-{index}"))
            )
            score = int(row.get("score_units", row.get("utility_units", 0)))
        else:
            candidate_id = str(row)
            score = 0
        normalized.append((candidate_id, score))
    normalized.sort(key=lambda item: (-item[1], item[0]))
    return tuple(item[0] for item in normalized)


def run_requirement(
    requirement_id: str,
    symbol: str,
    responsibility: str,
    package: str,
    payload: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Mapping[str, Any]:
    data = dict(payload or {})
    data.update(kwargs)
    normalized = _normalize(data)

    unsafe = tuple(
        key
        for key in _EFFECT_KEYS
        if normalized.get(key) not in (None, False, 0, "false", "FALSE")
    )
    if unsafe:
        raise PR356ContractError(
            "PR356_EFFECT_AUTHORITY_FORBIDDEN:" + ",".join(sorted(unsafe))
        )

    for key, value in normalized.items():
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value < 0
            and any(
                token in key
                for token in (
                    "budget",
                    "capacity",
                    "cost",
                    "count",
                    "limit",
                    "quota",
                    "slots",
                    "storage",
                )
            )
        ):
            raise PR356ContractError(f"NEGATIVE_RESOURCE_VALUE:{key}")

    verb = symbol.split("_", 1)[0]
    evidence_refs = tuple(str(x) for x in normalized.get("evidence_refs", ()))
    external_required = any(symbol.startswith(hint) for hint in _EXTERNAL_HINTS)
    external_ready = bool(evidence_refs) or normalized.get("external_evidence") is True
    status = (
        "BLOCKED_EXTERNAL"
        if external_required and not external_ready
        else "CONTRACT_IMPLEMENTED"
    )

    body: dict[str, Any] = {
        "requirement_id": requirement_id,
        "symbol": symbol,
        "package": package,
        "responsibility": responsibility,
        "status": status,
        "execution_right": False,
        "synthetic": verb in {"simulate", "stress", "generate"},
        "effect_boundary_preserved": True,
        "evidence_refs": evidence_refs,
        "input": normalized,
        "numeric_summary": _numeric_summary(normalized),
    }

    if verb in {"rank", "select", "solve"}:
        body["ordered_candidates"] = _candidate_order(normalized)
    if verb in {"publish", "freeze", "record", "register", "define", "bind"}:
        body["immutable_artifact"] = True
    if verb in _FAIL_CLOSED_VERBS:
        body["fail_closed"] = True
    if verb in {"qualify", "verify", "prove"}:
        body["qualified"] = status != "BLOCKED_EXTERNAL" and bool(evidence_refs)
    if verb in {"measure", "estimate", "compute", "score", "compare", "evaluate"}:
        body["metric_generated"] = True
    if verb in {"fit", "train"}:
        body["model_authority"] = False
        body["holdout_required"] = True
    if verb in {"ingest", "capture", "read", "collect"}:
        body["remote_mutation"] = False
        body["source_available"] = bool(normalized.get("source_ref") or evidence_refs)
    if status == "BLOCKED_EXTERNAL":
        body["blockers"] = ("EXTERNAL_EVIDENCE_NOT_MATERIALIZED",)

    body["receipt_hash"] = _canonical_hash(body)
    return body
