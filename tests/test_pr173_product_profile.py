from __future__ import annotations

import pytest

from src.product_profile_pr173 import (
    CORE_PROFILE_IDS,
    CoreArtifactEvidence,
    PluginApiContract,
    PluginLifecycleState,
    PluginMetadata,
    ProductProfile,
    ProductProfileEvidence,
    assert_product_profile_review_ready,
    evaluate_product_profile,
)

H = "a" * 64
H2 = "b" * 64


def core() -> CoreArtifactEvidence:
    return CoreArtifactEvidence(
        package_name="flashloan-bot-core",
        included_domains=("runtime", "routing", "marginfi_flashloan", "settlement"),
        explicitly_excluded_domains=(
            "ai_advisory",
            "lending",
            "lending_indexer",
            "liquidation",
            "providers/orderbook",
            "orderbook",
            "pump",
            "venues/pump",
            "kamino_liquidation",
            "lst_depeg",
            "lst_unstake",
            "circular_arbitrage",
        ),
        constructs_only_profile_features=True,
        optional_absence_breaks_import_or_health=False,
        core_sbom_hash=H,
        dependencies_are_core_only=True,
        product_docs_distinguish_modes=True,
        capability_status_from_installed_profile_and_admission=True,
        required_in_installed_package_flags={"liquidation": False, "pump": False},
    )


def api() -> PluginApiContract:
    return PluginApiContract(
        api_version="pr173.plugin-api.v1",
        surfaces=(
            "candidate_observation",
            "quote_request",
            "evidence_output",
            "reason_codes",
            "health",
            "shutdown",
        ),
        accepts_arbitrary_internal_objects=False,
        versioned_protocol_hash=H,
    )


def profile() -> ProductProfile:
    return ProductProfile(
        profile_id="core-flashloan-paper",
        signed_profile_hash=H,
        signature_verified=True,
        allowed_core_domains=("runtime", "routing", "marginfi_flashloan", "settlement"),
        allowed_plugin_profiles=("liquidation-plugin",),
    )


def plugin(**kw) -> PluginMetadata:
    base = dict(
        plugin_id="liquidation",
        distribution_name="flashloan-bot-plugin-kamino-liquidation",
        version="1.0.0",
        wheel_hash=H,
        signer="release-security",
        provenance_hash=H,
        api_version="pr173.plugin-api.v1",
        permissions=("rpc_reads", "program_marginfi_readonly"),
        supported_clusters=("mainnet-beta",),
        strategy_capabilities=("recorded_shadow",),
        evidence_hash=H,
        allowlisted=True,
        signature_verified=True,
        lifecycle_state=PluginLifecycleState.INSTALLED_DISABLED,
        process_isolated=True,
        separate_dependency_environment=True,
        bounded_ipc=True,
        crash_isolated_from_core_health=True,
        sbom_hash=H,
        license_inventory_hash=H,
    )
    base.update(kw)
    return PluginMetadata(**base)


def evidence(**kw) -> ProductProfileEvidence:
    base = dict(
        schema_version="pr173.product-profile.v1",
        active_profile=profile(),
        core_artifact=core(),
        plugin_api=api(),
        plugin_lifecycle_states=(
            "not_installed",
            "installed_disabled",
            "fixture_only",
            "recorded_shadow",
            "live_shadow",
            "reviewed_executable",
            "revoked",
        ),
        plugins=(plugin(),),
    )
    base.update(kw)
    return ProductProfileEvidence(**base)


def blockers(ev):
    return set(evaluate_product_profile(ev).blockers)


def test_valid_core_profile_review_ready_but_live_disabled():
    decision = evaluate_product_profile(evidence())
    assert decision.review_ready
    assert decision.production_artifact_allowed
    assert decision.first_canary_core_only
    assert not decision.live_claim_allowed
    assert not decision.sender_submission_allowed
    assert assert_product_profile_review_ready(evidence()).review_ready


def test_production_profile_must_be_core_and_signed():
    ev = evidence(
        active_profile=ProductProfile(
            "research", "bad", False, ("runtime",), first_canary_profile_id="research"
        )
    )
    b = blockers(ev)
    assert {
        "PRODUCTION_PROFILE_NOT_CORE",
        "PROFILE_HASH_MISSING_OR_MALFORMED",
        "PROFILE_SIGNATURE_NOT_VERIFIED",
        "FIRST_CANARY_NOT_CORE_PROFILE",
    } <= b
    assert CORE_PROFILE_IDS == {"core-flashloan-paper", "core-flashloan-live"}


def test_core_package_must_not_include_optional_domains():
    data = core().__dict__.copy()
    data["included_domains"] = ("runtime", "liquidation", "providers/orderbook")
    assert "OPTIONAL_DOMAIN_INCLUDED_IN_CORE" in blockers(
        evidence(core_artifact=CoreArtifactEvidence(**data))
    )


def test_core_must_not_construct_absent_disabled_features():
    data = core().__dict__.copy()
    data["constructs_only_profile_features"] = False
    assert "CORE_CONSTRUCTS_ABSENT_OR_DISABLED_FEATURES" in blockers(
        evidence(core_artifact=CoreArtifactEvidence(**data))
    )


def test_optional_absence_cannot_break_import_or_health():
    data = core().__dict__.copy()
    data["optional_absence_breaks_import_or_health"] = True
    assert "OPTIONAL_ABSENCE_BREAKS_CORE" in blockers(
        evidence(core_artifact=CoreArtifactEvidence(**data))
    )


def test_quarantined_feature_cannot_be_required_in_installed_package():
    data = core().__dict__.copy()
    data["required_in_installed_package_flags"] = {"pump": True}
    assert "QUARANTINED_FEATURE_REQUIRED_IN_INSTALLED_PACKAGE" in blockers(
        evidence(core_artifact=CoreArtifactEvidence(**data))
    )


def test_capability_status_and_docs_must_be_truthful():
    data = core().__dict__.copy()
    data["capability_status_from_installed_profile_and_admission"] = False
    data["product_docs_distinguish_modes"] = False
    b = blockers(evidence(core_artifact=CoreArtifactEvidence(**data)))
    assert {
        "CAPABILITY_STATUS_NOT_PROFILE_ADMISSION_DERIVED",
        "PRODUCT_DOCS_DO_NOT_DISTINGUISH_MODES",
    } <= b


def test_plugin_api_is_versioned_and_bounded():
    bad_api = PluginApiContract("v1", ("health",), True, "bad")
    b = blockers(evidence(plugin_api=bad_api))
    assert {
        "PLUGIN_API_PROTOCOL_HASH_MISSING",
        "PLUGIN_API_SURFACES_INCOMPLETE",
        "PLUGIN_API_ACCEPTS_INTERNAL_OBJECTS",
    } <= b


def test_plugin_must_be_separate_signed_and_allowlisted():
    bad = plugin(distribution_name="src.liquidation", allowlisted=False, signature_verified=False, signer="")
    b = blockers(evidence(plugins=(bad,)))
    assert {
        "PLUGIN_DISTRIBUTION_NOT_SEPARATE",
        "PLUGIN_NOT_SIGNED_AND_ALLOWLISTED",
        "PLUGIN_SIGNER_MISSING",
    } <= b


def test_plugin_has_no_signer_sender_or_treasury_by_default():
    bad = plugin(permissions=("rpc_reads", "signer_access", "sender_access", "treasury_mutation"))
    assert "PLUGIN_HAS_DEFAULT_DENIED_PERMISSION" in blockers(evidence(plugins=(bad,)))


def test_plugin_process_isolation_required():
    bad = plugin(
        process_isolated=False,
        separate_dependency_environment=False,
        bounded_ipc=False,
        crash_isolated_from_core_health=False,
    )
    b = blockers(evidence(plugins=(bad,)))
    assert {"PLUGIN_PROCESS_ISOLATION_INCOMPLETE", "PLUGIN_CRASH_CAN_BREAK_CORE_HEALTH"} <= b


def test_revoked_plugin_cannot_remain_executable():
    bad = plugin(revoked=True, lifecycle_state=PluginLifecycleState.REVIEWED_EXECUTABLE)
    b = blockers(evidence(plugins=(bad,)))
    assert {"REVOKED_PLUGIN_NOT_IN_REVOKED_STATE", "REVOKED_PLUGIN_EXECUTABLE"} <= b


def test_no_arbitrary_import_or_internal_object_return():
    bad = plugin(attempts_arbitrary_import_path=True, attempts_internal_object_return=True)
    b = blockers(evidence(plugins=(bad,)))
    assert {"PLUGIN_ARBITRARY_IMPORT_PATH", "PLUGIN_INTERNAL_OBJECT_RETURN"} <= b


def test_schema_hash_and_assertion_fail_closed():
    ev = evidence(expected_evidence_hash=H2, live_claim_requested=True, sender_submission_requested=True)
    b = blockers(ev)
    assert {
        "EVIDENCE_HASH_MISMATCH",
        "LIVE_CLAIM_REQUESTED_IN_REVIEW_GATE",
        "SENDER_SUBMISSION_REQUESTED_IN_REVIEW_GATE",
    } <= b
    with pytest.raises(AssertionError):
        assert_product_profile_review_ready(ev)
