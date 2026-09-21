"""PR-303 / NF-897..901: closed replay witness contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_id, require_int, require_keys, require_positive, stable_hash


def seed_replay_witness_from_message(
    message: Mapping[str, Any],
    state_frame: Mapping[str, Any],
    *,
    format_version: str = "v0",
) -> ContractResult:
    require_keys(message, ("account_metas",), "UNKNOWN_FORMAT")
    require_keys(state_frame, ("slot", "bank_context", "accounts"), "MIXED_BANK_CONTEXT")
    slot = require_int(state_frame["slot"], "slot")
    accounts = state_frame["accounts"]
    if not isinstance(accounts, Mapping):
        raise UltimateMegaError("MISSING_ACCOUNT")
    metas = tuple(str(x) for x in message["account_metas"])
    available = tuple(sorted(key for key in metas if key in accounts))
    missing = tuple(sorted(key for key in metas if key not in accounts))
    payload = {
        "candidate_variant_hash": stable_hash("candidate-message", message),
        "format_version": require_id(format_version, "format_version"),
        "slot": slot,
        "bank_context": state_frame["bank_context"],
        "required_accounts": metas,
        "available_accounts": available,
        "missing_dependencies": missing,
        "closure_complete": not missing,
    }
    return record(
        "seed_replay_witness_from_message",
        payload,
        status="OK" if not missing else "INCOMPLETE",
        blockers=("MISSING_ACCOUNT",) if missing else (),
    )


def expand_witness_dependency_closure(
    seed: Mapping[str, Any],
    account_reader: Mapping[str, Any],
    access_trace: Sequence[str],
    *,
    max_dependencies: int = 512,
) -> ContractResult:
    require_positive(max_dependencies, "max_dependencies")
    required = list(dict.fromkeys(str(x) for x in seed.get("required_accounts", ())))
    for key in access_trace:
        key = str(key)
        if key not in required:
            required.append(key)
        if len(required) > max_dependencies:
            raise UltimateMegaError("DEPENDENCY_CYCLE_LIMIT")
    missing = tuple(sorted(key for key in required if key not in account_reader))
    payload = {
        "slot": seed.get("slot"),
        "bank_context": seed.get("bank_context"),
        "dependencies": tuple(required),
        "dependency_hashes": {
            key: stable_hash("replay-account", account_reader[key])
            for key in required
            if key in account_reader
        },
        "missing_dependencies": missing,
        "closure_complete": not missing,
    }
    return record(
        "expand_witness_dependency_closure",
        payload,
        status="OK" if not missing else "INCOMPLETE",
        blockers=("ARCHIVAL_STATE_UNAVAILABLE",) if missing else (),
    )


def minimize_replay_witness(
    witness: Mapping[str, Any],
    *,
    required_reads: Sequence[str],
    optional_entries: Sequence[str] = (),
    expected_fingerprint: str,
) -> ContractResult:
    require_id(expected_fingerprint, "expected_fingerprint")
    dependencies = tuple(str(x) for x in witness.get("dependencies", ()))
    required = set(str(x) for x in required_reads)
    optional = set(str(x) for x in optional_entries)
    if not required.issubset(set(dependencies)):
        raise UltimateMegaError("REQUIRED_OBJECT_REMOVED")
    retained = tuple(
        item for item in dependencies if item in required or item not in optional
    )
    return record(
        "minimize_replay_witness",
        {
            "dependencies": retained,
            "removed": tuple(item for item in dependencies if item not in retained),
            "expected_fingerprint": expected_fingerprint,
            "locally_irreducible": True,
        },
    )


def replay_witness_without_network(
    witness: Mapping[str, Any],
    *,
    observed_result: Mapping[str, Any],
    expected_result: Mapping[str, Any],
    network_accessed: bool = False,
) -> ContractResult:
    if network_accessed:
        raise UltimateMegaError("HIDDEN_NETWORK_ACCESS")
    if witness.get("closure_complete") is False or witness.get("missing_dependencies"):
        raise UltimateMegaError("INCOMPLETE_WITNESS")
    observed = stable_hash("witness-replay-result", observed_result)
    expected = stable_hash("witness-replay-result", expected_result)
    if observed != expected:
        raise UltimateMegaError("RESULT_DIVERGENCE")
    return record(
        "replay_witness_without_network",
        {
            "result_fingerprint": observed,
            "network_accessed": False,
            "ordered_logs_hash": stable_hash(
                "witness-logs", observed_result.get("logs", ())
            ),
            "raw_deltas_hash": stable_hash(
                "witness-deltas", observed_result.get("raw_deltas", {})
            ),
        },
    )


def export_witness_reproduction_bundle(
    replay_report: Mapping[str, Any],
    *,
    source_permissions: Mapping[str, bool],
    reproduction_command: Sequence[str],
) -> ContractResult:
    if not source_permissions.get("export_allowed", False):
        raise UltimateMegaError("EXPORT_NOT_ALLOWED")
    if source_permissions.get("contains_secret_material", False):
        raise UltimateMegaError("SECRET_MATERIAL_DETECTED")
    if not reproduction_command:
        raise UltimateMegaError("REPRODUCTION_COMMAND_REQUIRED")
    return record(
        "export_witness_reproduction_bundle",
        {
            "report_hash": stable_hash("witness-report", replay_report),
            "command": tuple(str(x) for x in reproduction_command),
            "raw_private_data_exported": False,
            "source_permissions_hash": stable_hash(
                "witness-source-permissions", source_permissions
            ),
        },
    )
