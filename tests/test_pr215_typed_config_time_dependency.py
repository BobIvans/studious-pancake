from __future__ import annotations

from dataclasses import replace

import pytest

from src.pr215_typed_config_time_dependency import (
    PR215Evidence,
    PR215EvidenceError,
    complete_pr215_evidence,
    evaluate_pr215_evidence,
    evaluate_pr215_mapping,
)


def _ready_report():
    report = evaluate_pr215_evidence(complete_pr215_evidence())
    assert report.ready is True
    return report


def test_complete_pr215_fixture_is_ready_and_sender_free():
    report = _ready_report()
    assert report.reason_codes == ()
    assert report.live_capability_allowed is False
    assert report.signer_capability_allowed is False
    assert report.sender_capability_allowed is False


def test_mapping_parser_rejects_unknown_top_level_field():
    evidence = complete_pr215_evidence()
    payload = evidence_to_payload(evidence)
    payload["extra"] = True
    with pytest.raises(PR215EvidenceError, match="unknown pr215"):
        evaluate_pr215_mapping(payload)


def test_unknown_runtime_env_key_requires_detection():
    evidence = complete_pr215_evidence()
    config = replace(
        evidence.config,
        runtime_observed_env_keys=evidence.config.runtime_observed_env_keys
        + ("UNTRACKED_ENV_KEY",),
        unknown_env_keys_detected=False,
    )
    report = evaluate_pr215_evidence(replace(evidence, config=config))
    assert not report.ready
    assert any("UNKNOWN_RUNTIME_ENV_KEYS_NOT_DETECTED" in code for code in report.reason_codes)


def test_stale_example_env_key_requires_detection():
    evidence = complete_pr215_evidence()
    config = replace(
        evidence.config,
        example_documented_env_keys=evidence.config.example_documented_env_keys
        + ("STALE_EXAMPLE_KEY",),
        stale_example_keys_detected=False,
    )
    report = evaluate_pr215_evidence(replace(evidence, config=config))
    assert not report.ready
    assert any("STALE_EXAMPLE_ENV_KEYS_NOT_DETECTED" in code for code in report.reason_codes)


def test_conflicting_defaults_fail_closed():
    evidence = complete_pr215_evidence()
    config = replace(
        evidence.config,
        no_conflicting_defaults=False,
        conflicting_default_keys=("FLASH_LOAN_SIZE_SOL",),
    )
    report = evaluate_pr215_evidence(replace(evidence, config=config))
    assert not report.ready
    assert any("CONFLICTING_DEFAULTS_PRESENT" in code for code in report.reason_codes)


def test_direct_env_reads_outside_bootstrap_fail_closed():
    evidence = complete_pr215_evidence()
    config = replace(
        evidence.config,
        direct_env_read_sites=("src/strategy/runtime.py",),
    )
    report = evaluate_pr215_evidence(replace(evidence, config=config))
    assert not report.ready
    assert any("DIRECT_ENV_READ_OUTSIDE_BOOTSTRAP" in code for code in report.reason_codes)


def test_root_and_installed_config_fingerprint_must_match():
    evidence = complete_pr215_evidence()
    config = replace(evidence.config, installed_config_fingerprint="1" * 63 + "2")
    report = evaluate_pr215_evidence(replace(evidence, config=config))
    assert not report.ready
    assert any("ROOT_AND_INSTALLED_CONFIG_FINGERPRINT_MISMATCH" in code for code in report.reason_codes)


def test_trusted_time_requires_all_clock_domains():
    evidence = complete_pr215_evidence()
    time = replace(evidence.time, trusted_utc_clock_port=False)
    report = evaluate_pr215_evidence(replace(evidence, time=time))
    assert not report.ready
    assert any("MISSING_TRUSTED_UTC_CLOCK_PORT" in code for code in report.reason_codes)


def test_direct_wall_clock_sites_fail_closed():
    evidence = complete_pr215_evidence()
    time = replace(
        evidence.time,
        direct_wall_clock_sites=("src/execution/journal.py",),
    )
    report = evaluate_pr215_evidence(replace(evidence, time=time))
    assert not report.ready
    assert any("DIRECT_WALL_CLOCK_SITES_PRESENT" in code for code in report.reason_codes)


def test_non_runtime_roots_in_runtime_lock_fail_closed():
    evidence = complete_pr215_evidence()
    deps = replace(
        evidence.dependencies,
        runtime_direct_roots=evidence.dependencies.runtime_direct_roots + ("psutil",),
    )
    report = evaluate_pr215_evidence(replace(evidence, dependencies=deps))
    assert not report.ready
    assert any("NON_RUNTIME_ROOTS_IN_RUNTIME_LOCK" in code for code in report.reason_codes)


def test_imported_dependency_must_be_declared_owned_and_evidenced():
    evidence = complete_pr215_evidence()
    deps = replace(
        evidence.dependencies,
        directly_imported_dependencies=evidence.dependencies.directly_imported_dependencies
        + ("yaml",),
    )
    report = evaluate_pr215_evidence(replace(evidence, dependencies=deps))
    assert not report.ready
    assert any("DIRECT_IMPORT_NOT_DECLARED" in code for code in report.reason_codes)
    assert any("DIRECT_IMPORT_EVIDENCE_MISSING" in code for code in report.reason_codes)


def test_certifi_direct_import_requires_direct_declaration():
    evidence = complete_pr215_evidence()
    deps = replace(evidence.dependencies, certifi_direct_dependency_declared=False)
    report = evaluate_pr215_evidence(replace(evidence, dependencies=deps))
    assert not report.ready
    assert any("CERTIFI_DIRECT_IMPORT_NOT_DECLARED" in code for code in report.reason_codes)


def test_placeholder_digests_are_rejected_by_mapping_parser():
    payload = evidence_to_payload(complete_pr215_evidence())
    payload["config"]["env_reference_hash"] = "0" * 64
    with pytest.raises(PR215EvidenceError, match="placeholder"):
        PR215Evidence.from_mapping(payload)


def evidence_to_payload(evidence: PR215Evidence) -> dict[str, object]:
    return {
        "schema_version": evidence.schema_version,
        "config": {
            "typed_schema_generates_env_reference": evidence.config.typed_schema_generates_env_reference,
            "env_reference_hash": evidence.config.env_reference_hash,
            "runtime_observed_env_keys": list(evidence.config.runtime_observed_env_keys),
            "example_documented_env_keys": list(evidence.config.example_documented_env_keys),
            "quarantined_legacy_env_keys": list(evidence.config.quarantined_legacy_env_keys),
            "unknown_env_keys_detected": evidence.config.unknown_env_keys_detected,
            "stale_example_keys_detected": evidence.config.stale_example_keys_detected,
            "no_conflicting_defaults": evidence.config.no_conflicting_defaults,
            "conflicting_default_keys": list(evidence.config.conflicting_default_keys),
            "env_access_bootstrap_only": evidence.config.env_access_bootstrap_only,
            "direct_env_read_sites": list(evidence.config.direct_env_read_sites),
            "root_config_fingerprint": evidence.config.root_config_fingerprint,
            "installed_config_fingerprint": evidence.config.installed_config_fingerprint,
            "config_fingerprint_materialized_from_schema": evidence.config.config_fingerprint_materialized_from_schema,
        },
        "time": {
            "duration_clock_port": evidence.time.duration_clock_port,
            "trusted_utc_clock_port": evidence.time.trusted_utc_clock_port,
            "chain_context_clock_port": evidence.time.chain_context_clock_port,
            "direct_wall_clock_banned": evidence.time.direct_wall_clock_banned,
            "direct_wall_clock_sites": list(evidence.time.direct_wall_clock_sites),
            "finite_duration_validation": evidence.time.finite_duration_validation,
            "maximum_duration_bound_seconds": evidence.time.maximum_duration_bound_seconds,
            "wall_clock_fault_injection_passed": evidence.time.wall_clock_fault_injection_passed,
            "chain_slot_height_context_bound": evidence.time.chain_slot_height_context_bound,
        },
        "dependencies": {
            "separated_lock_profiles": list(evidence.dependencies.separated_lock_profiles),
            "runtime_lock_hash": evidence.dependencies.runtime_lock_hash,
            "service_lock_hash": evidence.dependencies.service_lock_hash,
            "analytics_lock_hash": evidence.dependencies.analytics_lock_hash,
            "dev_lock_hash": evidence.dependencies.dev_lock_hash,
            "exact_sync_tested": evidence.dependencies.exact_sync_tested,
            "runtime_lock_excludes_non_runtime_roots": evidence.dependencies.runtime_lock_excludes_non_runtime_roots,
            "runtime_direct_roots": list(evidence.dependencies.runtime_direct_roots),
            "optional_extras_require_explicit_selection": evidence.dependencies.optional_extras_require_explicit_selection,
            "dependency_graph_compared_to_allowlist": evidence.dependencies.dependency_graph_compared_to_allowlist,
            "direct_dependency_owners": dict(evidence.dependencies.direct_dependency_owners),
            "direct_dependency_import_evidence": {
                key: list(value)
                for key, value in evidence.dependencies.direct_dependency_import_evidence.items()
            },
            "declared_direct_dependencies": list(evidence.dependencies.declared_direct_dependencies),
            "directly_imported_dependencies": list(evidence.dependencies.directly_imported_dependencies),
            "transitive_imports_forbidden": evidence.dependencies.transitive_imports_forbidden,
            "unmanaged_requirement_aliases_absent": evidence.dependencies.unmanaged_requirement_aliases_absent,
            "certifi_direct_dependency_declared": evidence.dependencies.certifi_direct_dependency_declared,
        },
        "live_capability_allowed": evidence.live_capability_allowed,
        "signer_capability_allowed": evidence.signer_capability_allowed,
        "sender_capability_allowed": evidence.sender_capability_allowed,
    }
