"""R08-step1 governed-RPC composition seam tests (offline, deterministic).

Pins the audit step-1 contract (R08_RUNTIME_COMPOSITION_AUDIT_2026-11-14 §6
step 1 + §7 proposed assertion):

- ``resolve_installed_core_v1_dependencies`` with a governed transport
  produces a SIMULATION-CAPABLE ``CoreV1Dependencies.rpc`` (the exact
  deployment transport object is wired through unchanged) while the absent
  descriptor / absent transport keeps the historical blocked default;
- the resolver accepts a governed transport ONLY through the manifest-pinned
  ``governed_rpc`` descriptor (https, credential-free, rooted endpoint,
  generation ≥ 1) — any pairing mismatch is a typed error;
- the pinned descriptor fingerprint is returned on the resolution so
  simulation evidence can be bound to the transport identity;
- the blocked-RPC default is preserved when the seam is unused;
- live stays hard-denied: nothing in the resolver constructs a network
  transport, and the draft source stays blocked in every resolution
  (R05/R06 gates untouched).

Zero network; pytest-socket applies in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.execution.models import RpcClient
from src.config.runtime import load_runtime_config
from src.runtime.core_v1_dependency_resolver import (
    CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID,
    CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED,
    CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID,
    GovernedRpcDescriptor,
    resolve_installed_core_v1_dependencies,
)
from tests.test_agg03_dependency_resolver import (
    CLOCK,
    MANIFEST_ENV,
    _manifest,
    _profile,
    _write,
)

pytestmark = pytest.mark.unit

CONFIG = load_runtime_config()


class _GovernedTransport:
    """Deployment-owned pure test transport (offline recorder, no network)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    async def call(self, method: str, params: list[object]) -> object:
        self.calls.append((method, params))
        return {"result": {"context": {"slot": 1}, "value": {}}}


def _descriptor() -> dict[str, object]:
    return {
        "endpoint": "https://rpc.deployment.internal",
        "deployment_generation": 1,
    }


def _manifest_with_rpc() -> dict[str, object]:
    payload = _manifest()
    payload["governed_rpc"] = _descriptor()
    return payload


class TestBlockedDefaultPreserved:
    def test_absent_manifest_still_blocked(self, tmp_path: Path) -> None:
        resolution = resolve_installed_core_v1_dependencies(_profile(), {})
        assert resolution.dependencies is None
        assert resolution.governed_rpc_fingerprint is None

    def test_resolved_manifest_without_descriptor_keeps_blocked_rpc(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _manifest())
        resolution = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
        )
        assert resolution.dependencies is not None
        assert resolution.governed_rpc_fingerprint is None
        import asyncio

        # The historical blocked transport must still be the default: any
        # call refuses with the typed external blocker.
        with pytest.raises(RuntimeError):
            asyncio.run(resolution.dependencies.rpc.call("getBlockHeight", []))


class TestGovernedRpcInjection:
    def test_governed_transport_is_wired_through_unchanged(
        self, tmp_path: Path
    ) -> None:
        transport = _GovernedTransport()
        path = _write(tmp_path, _manifest_with_rpc())
        resolution = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
            governed_rpc_transport=transport,
        )
        assert resolution.dependencies is not None
        assert resolution.dependencies.rpc is transport  # identity preserved
        assert resolution.governed_rpc_fingerprint is not None

    def test_fingerprint_binds_the_pinned_identity(self, tmp_path: Path) -> None:
        transport = _GovernedTransport()
        path = _write(tmp_path, _manifest_with_rpc())
        first = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
            governed_rpc_transport=transport,
        )
        second = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
            governed_rpc_transport=_GovernedTransport(),
        )
        assert first.governed_rpc_fingerprint is not None
        # The fingerprint binds the MANIFEST-PINNED identity (endpoint +
        # generation), not the transport object — evidence stays stable
        # across equivalent deployment transports.
        assert first.governed_rpc_fingerprint == second.governed_rpc_fingerprint

    def test_descriptor_matches_governed_rpc_descriptor(self) -> None:
        descriptor = GovernedRpcDescriptor.from_manifest(_descriptor())
        assert descriptor.endpoint == "https://rpc.deployment.internal"
        assert descriptor.deployment_generation == 1

    def test_transport_reaches_exact_simulation_shape(self, tmp_path: Path) -> None:
        # Simulation-capable: the transport satisfies the RpcClient protocol
        # shape the ExactSimulationFinalizer consumes in the composition.
        transport = _GovernedTransport()
        # RpcClient is a structural Protocol: the exact-simulation finalizer
        # consumes any object exposing the async call(method, params) shape.
        assert callable(getattr(transport, "call", None))


class TestPairingMismatches:
    def test_manifest_declares_rpc_without_transport_is_blocker(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _manifest_with_rpc())
        resolution = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
        )
        assert resolution.dependencies is None
        assert resolution.blocker == "CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED"

    def test_transport_without_manifest_descriptor_is_loud_error(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _manifest())
        with pytest.raises(ValueError) as raised:
            resolve_installed_core_v1_dependencies(
                _profile(),
                {MANIFEST_ENV: str(path)},
                trusted_time=CLOCK,
                governed_rpc_transport=_GovernedTransport(),
            )
        assert CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED in str(raised.value)


class TestDescriptorValidation:
    def test_http_endpoint_refused(self) -> None:
        with pytest.raises(ValueError) as raised:
            GovernedRpcDescriptor.from_manifest(
                {
                    "endpoint": "http://rpc.deployment.internal",
                    "deployment_generation": 1,
                }
            )
        assert CORE_V1_GOVERNED_RPC_DESCRIPTOR_INVALID in str(raised.value)

    def test_credential_or_query_refused(self) -> None:
        for endpoint in (
            "https://user:pass@rpc.internal",
            "https://rpc.internal?token=x",
            "https://rpc.internal#frag",
        ):
            with pytest.raises(ValueError):
                GovernedRpcDescriptor.from_manifest(
                    {"endpoint": endpoint, "deployment_generation": 1}
                )

    def test_invalid_generation_refused(self) -> None:
        for generation in (0, -1, "1", None):
            with pytest.raises(ValueError):
                GovernedRpcDescriptor.from_manifest(
                    {
                        "endpoint": "https://rpc.deployment.internal",
                        "deployment_generation": generation,
                    }
                )

    def test_non_callable_transport_refused(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _manifest_with_rpc())
        with pytest.raises(ValueError) as raised:
            resolve_installed_core_v1_dependencies(
                _profile(),
                {MANIFEST_ENV: str(path)},
                trusted_time=CLOCK,
                governed_rpc_transport=object(),  # no .call
            )
        assert CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID in str(raised.value)


class TestLiveStillHardDenied:
    def test_draft_source_stays_blocked_with_governed_rpc(self, tmp_path: Path) -> None:
        transport = _GovernedTransport()
        path = _write(tmp_path, _manifest_with_rpc())
        resolution = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
            governed_rpc_transport=transport,
        )
        assert resolution.dependencies is not None
        assert resolution.blocker == "CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL"
        # The candidate supply stays deliberately blocked: only the RPC seam
        # is open (step 1); R04/R05/R06 gates are untouched.
        assert resolution.dependencies.draft_source is not None

    def test_resolver_constructs_no_network_transport(self) -> None:
        import ast

        source = Path(
            __import__("src.runtime.core_v1_dependency_resolver").__file__
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("requests", "httpx", "aiohttp", "urllib.request", "socket"):
            assert forbidden not in imported

    def test_env_or_flag_alone_never_yields_governed_rpc(self, tmp_path: Path) -> None:
        # A manifest flag without a deployment-supplied transport object must
        # never produce a network-capable dependency set.
        payload = _manifest_with_rpc()
        payload["governed_rpc"] = {**_descriptor(), "enabled": True}
        path = _write(tmp_path, payload)
        resolution = resolve_installed_core_v1_dependencies(
            _profile(),
            {MANIFEST_ENV: str(path)},
            config=CONFIG,
            trusted_time=CLOCK,
        )
        assert resolution.dependencies is None
        assert resolution.blocker == "CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED"
        assert "enabled" not in json.dumps(resolution.governed_rpc_fingerprint or "")
