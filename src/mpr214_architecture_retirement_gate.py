"""MPR-214 architecture-retirement and domain/schema consolidation gate.

This module is intentionally offline and side-effect free.  It validates an
evidence bundle that must be produced by later inventory/reachability tooling.
The gate is fail-closed: caller-supplied success flags are not enough unless the
bundle proves module dispositions, schema ownership, domain vocabulary,
durability authority and import graph retirement boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr214.architecture-retirement-domain-schema.v1"
REQUIRED_FINDINGS = frozenset(
    {
        "F-269",
        "F-270",
        "F-271",
        "F-272",
        "F-273",
        "F-274",
        "F-275",
        "F-276",
        "F-277",
        "F-278",
        "F-279",
    }
)

_ALLOWED_DISPOSITIONS = frozenset({"promoted", "library", "tooling", "archive", "delete"})
_PRODUCTION_DISPOSITIONS = frozenset({"promoted", "library"})
_SCHEMA_STATUSES = frozenset({"current", "superseded", "archived", "deprecated"})
_PR_NUMBERED_RUNTIME_RE = re.compile(r"(?:^|[._/-])pr\d{2,4}(?:[._/-]|$)", re.IGNORECASE)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MPR214Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR214Report:
    schema_version: str
    ready: bool
    evidence_hash: str
    violations: tuple[MPR214Violation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violations": [violation.__dict__ for violation in self.violations],
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
        }


def validate_mpr214_architecture_retirement(evidence: Mapping[str, Any]) -> MPR214Report:
    """Validate the MPR-214 architecture retirement evidence bundle."""

    violations: list[MPR214Violation] = []

    if evidence.get("schema_version") != SCHEMA_VERSION:
        violations.append(
            MPR214Violation(
                "SCHEMA_VERSION",
                f"expected {SCHEMA_VERSION}",
            )
        )

    coverage = set(_as_str_list(evidence.get("finding_coverage")))
    missing_findings = REQUIRED_FINDINGS - coverage
    if missing_findings:
        violations.append(
            MPR214Violation(
                "FINDING_COVERAGE",
                "missing finding coverage: " + ", ".join(sorted(missing_findings)),
            )
        )

    _validate_module_inventory(evidence.get("module_inventory"), violations)
    _validate_import_graph(evidence.get("production_import_graph"), violations)
    _validate_stable_domain_migration(evidence.get("stable_domain_migration"), violations)
    _validate_schema_registry(evidence.get("schema_registry"), violations)
    _validate_domain_vocabulary(evidence.get("domain_vocabulary"), violations)
    _validate_durability_api(evidence.get("durability_public_api"), violations)
    _validate_legacy_retirement(evidence.get("legacy_retirement"), violations)
    _validate_reachability_manifest(evidence.get("reachability_manifest"), violations)
    _validate_capabilities(evidence.get("capabilities"), violations)

    return MPR214Report(
        schema_version=SCHEMA_VERSION,
        ready=not violations,
        evidence_hash=_stable_hash(evidence),
        violations=tuple(violations),
    )


def assert_mpr214_ready(evidence: Mapping[str, Any]) -> MPR214Report:
    report = validate_mpr214_architecture_retirement(evidence)
    if not report.ready:
        details = "; ".join(f"{item.code}: {item.message}" for item in report.violations)
        raise ValueError(f"MPR-214 architecture-retirement gate failed: {details}")
    return report


def _validate_module_inventory(value: Any, violations: list[MPR214Violation]) -> None:
    inventory = _mapping(value)
    if not inventory:
        violations.append(MPR214Violation("MODULE_INVENTORY_MISSING", "module inventory is required"))
        return

    if inventory.get("generated_from_installed_artifact") is not True:
        violations.append(
            MPR214Violation(
                "MODULE_INVENTORY_SOURCE",
                "module inventory must be generated from the installed artifact",
            )
        )

    total = _non_negative_int(inventory.get("total_src_modules"))
    reachable = _non_negative_int(inventory.get("reachable_modules"))
    items = _sequence(inventory.get("items"))
    if total is None or total <= 0:
        violations.append(MPR214Violation("MODULE_TOTAL", "total_src_modules must be positive"))
    if reachable is None or reachable <= 0:
        violations.append(MPR214Violation("REACHABLE_TOTAL", "reachable_modules must be positive"))
    if not items:
        violations.append(MPR214Violation("MODULE_ITEMS", "module inventory items are required"))
        return
    if total is not None and len(items) != total:
        violations.append(
            MPR214Violation(
                "MODULE_COUNT_MISMATCH",
                "module inventory item count must equal total_src_modules",
            )
        )

    unknown_runtime = []
    for item in items:
        module = _mapping(item)
        path = str(module.get("path", ""))
        disposition = str(module.get("disposition", ""))
        owner = str(module.get("owner", ""))
        reachable_flag = bool(module.get("reachable_from_installed_entrypoint", False))

        if not path.endswith(".py"):
            violations.append(MPR214Violation("MODULE_PATH", f"invalid module path: {path!r}"))
        if disposition not in _ALLOWED_DISPOSITIONS:
            unknown_runtime.append(path or "<missing>")
        if not owner:
            violations.append(MPR214Violation("MODULE_OWNER", f"missing owner for {path!r}"))
        if reachable_flag and disposition not in _PRODUCTION_DISPOSITIONS:
            violations.append(
                MPR214Violation(
                    "REACHABLE_DISPOSITION",
                    f"reachable module {path!r} must be promoted/library, not {disposition!r}",
                )
            )
        if disposition in {"archive", "delete"} and not module.get("retirement_deadline"):
            violations.append(
                MPR214Violation(
                    "RETIREMENT_DEADLINE",
                    f"archived/deleted module {path!r} needs a retirement deadline",
                )
            )

    if unknown_runtime:
        violations.append(
            MPR214Violation(
                "UNKNOWN_MODULE_DISPOSITION",
                "modules without allowed disposition: " + ", ".join(sorted(unknown_runtime)[:10]),
            )
        )


def _validate_import_graph(value: Any, violations: list[MPR214Violation]) -> None:
    graph = _mapping(value)
    if not graph:
        violations.append(MPR214Violation("IMPORT_GRAPH_MISSING", "production import graph is required"))
        return

    if graph.get("generated_from_installed_entrypoints") is not True:
        violations.append(
            MPR214Violation(
                "IMPORT_GRAPH_SOURCE",
                "import graph must be generated from installed entrypoints",
            )
        )

    for field, code in (
        ("unknown_runtime_modules", "UNKNOWN_RUNTIME_MODULE"),
        ("cycles", "IMPORT_CYCLE"),
        ("import_time_global_mutations", "IMPORT_TIME_MUTATION"),
        ("new_pr_numbered_runtime_filenames", "NEW_PR_NUMBERED_RUNTIME"),
    ):
        values = _sequence(graph.get(field))
        if values:
            violations.append(MPR214Violation(code, f"{field} must be empty"))

    pr_numbered = [str(item) for item in _sequence(graph.get("pr_numbered_runtime_modules"))]
    if pr_numbered and graph.get("compatibility_shim_deadline_required") is not True:
        violations.append(
            MPR214Violation(
                "PR_NUMBERED_RUNTIME_DEADLINE",
                "reachable PR-numbered modules require compatibility-shim deadlines",
            )
        )

    for module_name in pr_numbered:
        if not _PR_NUMBERED_RUNTIME_RE.search(module_name):
            violations.append(
                MPR214Violation(
                    "PR_NUMBERED_RUNTIME_FORMAT",
                    f"declared PR-numbered runtime module does not match pattern: {module_name}",
                )
            )


def _validate_stable_domain_migration(value: Any, violations: list[MPR214Violation]) -> None:
    migration = _mapping(value)
    if not migration:
        violations.append(MPR214Violation("DOMAIN_MIGRATION_MISSING", "stable domain migration is required"))
        return

    if migration.get("new_runtime_pr_numbered_filenames_allowed") is not False:
        violations.append(
            MPR214Violation(
                "PR_NUMBERED_FILENAME_POLICY",
                "new runtime PR-numbered filenames must be forbidden",
            )
        )

    promoted = _as_str_list(migration.get("promoted_domain_modules"))
    if not promoted:
        violations.append(MPR214Violation("PROMOTED_DOMAIN_MODULES", "promoted domain modules are required"))

    for shim in _sequence(migration.get("compatibility_shims")):
        shim_map = _mapping(shim)
        source = str(shim_map.get("module", ""))
        target = str(shim_map.get("target", ""))
        deadline = str(shim_map.get("expires_on", ""))
        if not source or not target or not _parse_date(deadline):
            violations.append(
                MPR214Violation(
                    "COMPATIBILITY_SHIM",
                    "each compatibility shim needs module, target and ISO expires_on",
                )
            )


def _validate_schema_registry(value: Any, violations: list[MPR214Violation]) -> None:
    registry = _mapping(value)
    if not registry:
        violations.append(MPR214Violation("SCHEMA_REGISTRY_MISSING", "schema registry is required"))
        return

    if registry.get("generated_from_installed_artifact") is not True:
        violations.append(
            MPR214Violation(
                "SCHEMA_REGISTRY_SOURCE",
                "schema registry must be generated from the installed artifact",
            )
        )

    if _sequence(registry.get("unregistered_schema_ids")):
        violations.append(
            MPR214Violation("UNREGISTERED_SCHEMA", "all schema ids must be registered")
        )

    entries = _sequence(registry.get("entries"))
    if not entries:
        violations.append(MPR214Violation("SCHEMA_ENTRIES", "schema registry entries are required"))
        return

    seen: set[str] = set()
    current_count = 0
    for entry in entries:
        entry_map = _mapping(entry)
        schema_id = str(entry_map.get("schema_id", ""))
        status = str(entry_map.get("status", ""))
        owner = str(entry_map.get("owner", ""))
        if not schema_id or schema_id in seen:
            violations.append(MPR214Violation("SCHEMA_ID_UNIQUE", "schema ids must be non-empty and unique"))
        seen.add(schema_id)
        if status not in _SCHEMA_STATUSES:
            violations.append(MPR214Violation("SCHEMA_STATUS", f"invalid schema status for {schema_id}"))
        if status == "current":
            current_count += 1
        if not owner:
            violations.append(MPR214Violation("SCHEMA_OWNER", f"missing schema owner for {schema_id}"))
        if "compatibility" not in entry_map:
            violations.append(
                MPR214Violation("SCHEMA_COMPATIBILITY", f"missing compatibility for {schema_id}")
            )
    if current_count == 0:
        violations.append(MPR214Violation("SCHEMA_CURRENT", "at least one current schema is required"))


def _validate_domain_vocabulary(value: Any, violations: list[MPR214Violation]) -> None:
    vocabulary = _mapping(value)
    if not vocabulary:
        violations.append(MPR214Violation("DOMAIN_VOCABULARY_MISSING", "domain vocabulary is required"))
        return

    if vocabulary.get("canonical_commitment_type") != "ChainCommitment":
        violations.append(
            MPR214Violation(
                "COMMITMENT_TYPE",
                "canonical commitment type must be ChainCommitment",
            )
        )
    if vocabulary.get("local_commitment_enums_removed") is not True:
        violations.append(
            MPR214Violation(
                "LOCAL_COMMITMENT_ENUMS",
                "local commitment enums must be removed or isolated behind adapters",
            )
        )
    if vocabulary.get("canonical_lifecycle_state_type") != "LifecycleState":
        violations.append(
            MPR214Violation(
                "LIFECYCLE_STATE_TYPE",
                "canonical lifecycle state type must be LifecycleState",
            )
        )
    if _sequence(vocabulary.get("missing_exhaustive_mappings")):
        violations.append(
            MPR214Violation(
                "EXHAUSTIVE_MAPPING",
                "all provider/storage enum mappings must be exhaustive",
            )
        )


def _validate_durability_api(value: Any, violations: list[MPR214Violation]) -> None:
    api = _mapping(value)
    if not api:
        violations.append(MPR214Violation("DURABILITY_API_MISSING", "durability API evidence is required"))
        return

    if api.get("public_lifecycle_protocol") != "LifecycleStore":
        violations.append(
            MPR214Violation(
                "LIFECYCLE_PROTOCOL",
                "there must be exactly one public LifecycleStore protocol",
            )
        )
    if not api.get("production_implementation"):
        violations.append(
            MPR214Violation("LIFECYCLE_IMPLEMENTATION", "production lifecycle implementation is required")
        )
    if _sequence(api.get("historical_store_exports")):
        violations.append(
            MPR214Violation(
                "HISTORICAL_STORE_EXPORTS",
                "historical lifecycle stores must not be public exports",
            )
        )
    if api.get("composition_root_can_import_historical_stores") is not False:
        violations.append(
            MPR214Violation(
                "HISTORICAL_STORE_REACHABILITY",
                "composition root must be unable to import historical stores",
            )
        )


def _validate_legacy_retirement(value: Any, violations: list[MPR214Violation]) -> None:
    legacy = _mapping(value)
    if not legacy:
        violations.append(MPR214Violation("LEGACY_RETIREMENT_MISSING", "legacy retirement evidence is required"))
        return

    disposition = str(legacy.get("legacy_arb_bot_disposition", ""))
    if disposition not in {"archive", "delete", "quarantine"}:
        violations.append(
            MPR214Violation(
                "LEGACY_DISPOSITION",
                "legacy_arb_bot must be archive/delete/quarantine",
            )
        )
    if legacy.get("legacy_arb_bot_reachable") is not False:
        violations.append(
            MPR214Violation(
                "LEGACY_REACHABLE",
                "legacy_arb_bot must not be reachable from installed entrypoints",
            )
        )
    if legacy.get("mega_class_budget_enforced") is not True:
        violations.append(
            MPR214Violation(
                "MEGA_CLASS_BUDGET",
                "mega-class/module size budget must be enforced",
            )
        )
    if _sequence(legacy.get("unowned_mega_classes")):
        violations.append(
            MPR214Violation("UNOWNED_MEGA_CLASS", "mega classes need owners or decomposition plan")
        )


def _validate_reachability_manifest(value: Any, violations: list[MPR214Violation]) -> None:
    manifest = _mapping(value)
    if not manifest:
        violations.append(MPR214Violation("REACHABILITY_MANIFEST_MISSING", "reachability manifest is required"))
        return

    if manifest.get("generated_from_installed_artifact") is not True:
        violations.append(
            MPR214Violation(
                "REACHABILITY_SOURCE",
                "reachability manifest must be generated from the installed artifact",
            )
        )
    if _non_negative_int(manifest.get("unknown_runtime_modules")) != 0:
        violations.append(
            MPR214Violation(
                "UNKNOWN_REACHABILITY",
                "installed graph must have zero unknown runtime modules",
            )
        )
    if not _strict_hash(str(manifest.get("artifact_sha256", ""))):
        violations.append(MPR214Violation("ARTIFACT_DIGEST", "artifact_sha256 must be a strict digest"))
    if not _strict_hash(str(manifest.get("trace_hash", ""))):
        violations.append(MPR214Violation("TRACE_DIGEST", "trace_hash must be a strict digest"))


def _validate_capabilities(value: Any, violations: list[MPR214Violation]) -> None:
    capabilities = _mapping(value)
    if not capabilities:
        violations.append(MPR214Violation("CAPABILITIES_MISSING", "capabilities evidence is required"))
        return
    for field, code in (
        ("live_execution_allowed", "LIVE_ENABLED"),
        ("signer_allowed", "SIGNER_ENABLED"),
        ("sender_allowed", "SENDER_ENABLED"),
    ):
        if capabilities.get(field) is not False:
            violations.append(MPR214Violation(code, f"{field} must remain false"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (list, tuple)):
        return value
    return ()


def _as_str_list(value: Any) -> list[str]:
    return [str(item) for item in _sequence(value)]


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _strict_hash(value: str) -> bool:
    return bool(_HASH_RE.fullmatch(value)) and value not in {"0" * 64, "f" * 64}


def _stable_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
