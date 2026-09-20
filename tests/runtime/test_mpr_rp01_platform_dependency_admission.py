from __future__ import annotations

from types import SimpleNamespace

from src.runtime.command_capabilities import (
    CommandCapabilityManifest,
    DependencyClass,
    DependencyReason,
    DependencySpec,
)
from src.runtime.platform_identity import (
    PlatformIdentity,
    qualify_platform,
)


def _identity() -> PlatformIdentity:
    return PlatformIdentity(
        schema_version="mpr-rp-01.platform-identity.v1",
        system="Linux",
        release="test",
        kernel="test",
        machine="x86_64",
        python_version="3.13.5",
        python_implementation="CPython",
        python_abi="cp313",
        libc_name="glibc",
        libc_version="2.41",
        openssl_version="OpenSSL test",
        event_loop_policy="asyncio",
        executable_realpath="/opt/python",
        native_distributions=(),
        environment_fingerprint="0" * 64,
    )


def test_platform_policy_admits_only_declared_modes() -> None:
    policy = {
        "platforms": [
            {
                "id": "linux-test",
                "system": "Linux",
                "machines": ["x86_64"],
                "libc": ["glibc"],
                "python_abi": "cp313",
                "event_loops": ["asyncio"],
                "allowed_modes": ["disabled", "paper"],
            }
        ]
    }
    paper = qualify_platform(_identity(), requested_mode="paper", policy=policy)
    shadow = qualify_platform(_identity(), requested_mode="shadow", policy=policy)

    assert paper.admitted is True
    assert shadow.admitted is False
    assert shadow.blockers == ("PLATFORM_MODE_NOT_QUALIFIED",)


def test_nested_import_failure_cannot_masquerade_as_optional_absence() -> None:
    manifest = CommandCapabilityManifest(
        schema_version="mpr-rp-01.command-capabilities.v1",
        commands={
            "test": (
                DependencySpec(
                    module="authority",
                    dependency_class=DependencyClass.MANDATORY_SAFETY_AUTHORITY,
                ),
            )
        },
        manifest_sha256="1" * 64,
    )

    def broken_importer(name: str) -> object:
        assert name == "authority"
        error = ModuleNotFoundError("nested dependency unavailable")
        error.name = "authority.inner"
        raise error

    report = manifest.evaluate("test", importer=broken_importer)

    assert report.admitted is False
    assert report.dependencies[0].reason is DependencyReason.DEPENDENCY_BROKEN
    assert report.dependencies[0].blocking is True


def test_optional_enhancement_never_changes_command_admission() -> None:
    manifest = CommandCapabilityManifest(
        schema_version="mpr-rp-01.command-capabilities.v1",
        commands={
            "test": (
                DependencySpec(
                    module="optional_metrics",
                    dependency_class=(
                        DependencyClass.OPTIONAL_NON_AUTHORITATIVE_ENHANCEMENT
                    ),
                ),
                DependencySpec(
                    module="authority",
                    symbol="admit",
                    dependency_class=DependencyClass.MANDATORY_SAFETY_AUTHORITY,
                ),
            )
        },
        manifest_sha256="2" * 64,
    )

    def importer(name: str) -> object:
        if name == "optional_metrics":
            error = ModuleNotFoundError("optional package unavailable")
            error.name = name
            raise error
        return SimpleNamespace(admit=lambda: True)

    report = manifest.evaluate("test", importer=importer)

    assert report.admitted is True
    assert report.dependencies[0].reason is DependencyReason.OPTIONAL_UNAVAILABLE
    assert report.dependencies[1].reason is DependencyReason.READY
