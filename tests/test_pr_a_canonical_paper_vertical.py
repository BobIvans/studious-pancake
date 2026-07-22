from types import SimpleNamespace

from src.paper_shadow.canonical_paper_vertical import (
    PR_A_CANONICAL_VERTICAL_INVALID,
    PR_A_CANONICAL_VERTICAL_UNWIRED,
    build_canonical_paper_vertical_startup,
)


class EmptyDependencies:
    def missing(self):
        return (
            "atomic_stage_suite",
            "exact_fee_workflow",
            "verified_marginfi_provider",
            "jupiter_v2_build",
        )

    def invalid(self):
        return ()


class InvalidDependencies:
    atomic_stage_suite = object()
    exact_fee_workflow = object()
    verified_marginfi_provider = object()
    jupiter_v2_build = object()

    def missing(self):
        return ()

    def invalid(self):
        return ("atomic_stage_suite_type",)


class CompleteDependencies:
    atomic_stage_suite = object()
    exact_fee_workflow = object()
    verified_marginfi_provider = object()
    jupiter_v2_build = object()

    def missing(self):
        return ()

    def invalid(self):
        return ()


def _config():
    return SimpleNamespace(
        fingerprint=lambda: "cfg-hash",
        runtime=SimpleNamespace(mode=SimpleNamespace(value="paper")),
    )


def test_default_paper_vertical_startup_is_named_blocked_state():
    startup = build_canonical_paper_vertical_startup(_config(), EmptyDependencies())

    assert startup.ready is False
    assert startup.reason_code == PR_A_CANONICAL_VERTICAL_UNWIRED
    assert startup.live_allowed is False
    assert startup.sender_reachable is False
    assert startup.signer_reachable is False
    assert "missing_atomic_stage_suite" in startup.dependency_reasons()


def test_invalid_dependencies_are_distinguished_from_missing_dependencies():
    startup = build_canonical_paper_vertical_startup(_config(), InvalidDependencies())

    assert startup.ready is False
    assert startup.reason_code == PR_A_CANONICAL_VERTICAL_INVALID
    assert "invalid_atomic_stage_suite_type" in startup.dependency_reasons()


def test_complete_dependencies_are_ready_but_still_sender_free():
    startup = build_canonical_paper_vertical_startup(_config(), CompleteDependencies())

    assert startup.ready is True
    assert startup.reason_code is None
    assert startup.dependency_reasons() == ()
    assert startup.to_dict()["runtime_mode"] == "paper"
    assert startup.to_dict()["live_allowed"] is False
    assert startup.to_dict()["fake_success_permitted"] is False


def test_startup_dict_is_deterministic_and_bounded_to_required_surfaces():
    startup = build_canonical_paper_vertical_startup(_config(), EmptyDependencies())
    payload = startup.to_dict()

    assert payload["schema_version"] == "mega-pr-a.canonical-paper-vertical.startup.v1"
    assert payload["required_surfaces"] == [
        "atomic_stage_suite",
        "exact_fee_workflow",
        "verified_marginfi_provider",
        "jupiter_v2_build",
    ]
    assert payload["available_surfaces"] == {
        "atomic_stage_suite": False,
        "exact_fee_workflow": False,
        "verified_marginfi_provider": False,
        "jupiter_v2_build": False,
    }
