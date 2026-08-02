from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/provider_governance/models.py",
    "        retryable: bool,\n"
    "        retry_at: float | None = None,\n"
    "    ) -> None:\n"
    "        super().__init__(f\"{provider_id}: {code.value}: {detail}\")\n"
    "        self.provider_id = provider_id\n"
    "        self.code = code\n"
    "        self.detail = detail\n"
    "        self.retryable = retryable\n"
    "        self.retry_at = retry_at\n",
    "        retryable: bool,\n"
    "        retry_at: float | None = None,\n"
    "        failure_reason: str | None = None,\n"
    "    ) -> None:\n"
    "        super().__init__(f\"{provider_id}: {code.value}: {detail}\")\n"
    "        self.provider_id = provider_id\n"
    "        self.code = code\n"
    "        self.detail = detail\n"
    "        self.retryable = retryable\n"
    "        self.retry_at = retry_at\n"
    "        self.failure_reason = failure_reason\n"
    "        # Stable across module reloads and installed/source import aliases.\n"
    "        self.governance_error_kind = \"provider_admission\"\n",
)

replace_once(
    "src/provider_governance/dependency.py",
    "from .models import (\n"
    "    AdmissionCode,\n"
    "    DependencyFailureKind,\n"
    "    DependencyMode,\n"
    "    DependencySnapshot,\n"
    "    ProviderAdmissionError,\n"
    "    ProviderOperation,\n"
    ")\n\n\nclass DependencyController:\n",
    "from .models import (\n"
    "    AdmissionCode,\n"
    "    DependencyFailureKind,\n"
    "    DependencyMode,\n"
    "    DependencySnapshot,\n"
    "    ProviderAdmissionError,\n"
    "    ProviderOperation,\n"
    ")\n\n\n"
    "def _provider_failure_reason(reason: str) -> str | None:\n"
    "    raw = reason.rsplit(\":\", 1)[-1]\n"
    "    return {\n"
    "        \"rate_limited\": \"rate_limited\",\n"
    "        \"quota\": \"rate_limited\",\n"
    "        \"circuit_open\": \"circuit_open\",\n"
    "        \"timeout\": \"timeout\",\n"
    "        \"transport\": \"transport\",\n"
    "        \"invalid_schema\": \"invalid_schema\",\n"
    "        \"disabled\": \"disabled\",\n"
    "        \"auth\": \"disabled\",\n"
    "    }.get(raw)\n\n\n"
    "class DependencyController:\n",
)

replace_once(
    "src/provider_governance/dependency.py",
    "                    state.reason,\n"
    "                    retryable=False,\n"
    "                )\n"
    "            if state.mode is DependencyMode.COOLDOWN:\n",
    "                    state.reason,\n"
    "                    retryable=False,\n"
    "                    failure_reason=_provider_failure_reason(state.reason),\n"
    "                )\n"
    "            if state.mode is DependencyMode.COOLDOWN:\n",
)
replace_once(
    "src/provider_governance/dependency.py",
    "                    state.reason,\n"
    "                    retryable=True,\n"
    "                    retry_at=state.retry_at,\n"
    "                )\n"
    "            if state.mode is DependencyMode.DEGRADED and operation in {\n",
    "                    state.reason,\n"
    "                    retryable=True,\n"
    "                    retry_at=state.retry_at,\n"
    "                    failure_reason=_provider_failure_reason(state.reason),\n"
    "                )\n"
    "            if state.mode is DependencyMode.DEGRADED and operation in {\n",
)
replace_once(
    "src/provider_governance/dependency.py",
    "                    state.reason,\n"
    "                    retryable=True,\n"
    "                )\n\n"
    "    async def record_success",
    "                    state.reason,\n"
    "                    retryable=True,\n"
    "                    failure_reason=_provider_failure_reason(state.reason),\n"
    "                )\n\n"
    "    async def record_success",
)

replace_once(
    "src/routing/registry.py",
    "def _enum_value(value: Any) -> str:\n"
    "    return str(getattr(value, \"value\", value))\n\n\n"
    "def _bind_contract_admission",
    "def _enum_value(value: Any) -> str:\n"
    "    return str(getattr(value, \"value\", value))\n\n\n"
    "def _materialize_admission_failure(\n"
    "    provider_id: str, exc: RuntimeError\n"
    ") -> ProviderFailure | None:\n"
    "    if not (\n"
    "        isinstance(exc, ProviderAdmissionError)\n"
    "        or getattr(exc, \"governance_error_kind\", None)\n"
    "        == \"provider_admission\"\n"
    "    ):\n"
    "        return None\n"
    "    retryable = bool(getattr(exc, \"retryable\", False))\n"
    "    raw_reason = getattr(exc, \"failure_reason\", None)\n"
    "    try:\n"
    "        reason = ProviderFailureReason(raw_reason)\n"
    "    except (TypeError, ValueError):\n"
    "        reason = (\n"
    "            ProviderFailureReason.RATE_LIMITED\n"
    "            if retryable\n"
    "            else ProviderFailureReason.DISABLED\n"
    "        )\n"
    "    code = _enum_value(getattr(exc, \"code\", \"unknown\"))\n"
    "    detail = str(getattr(exc, \"detail\", str(exc)))\n"
    "    return ProviderFailure(\n"
    "        provider=provider_id,\n"
    "        reason=reason,\n"
    "        retryable=retryable,\n"
    "        detail=f\"admission:{code}:{detail}\",\n"
    "    )\n\n\n"
    "def _bind_contract_admission",
)

replace_once(
    "src/routing/registry.py",
    "        except ProviderAdmissionError as exc:\n"
    "            return ProviderFailure(\n"
    "                provider=adapter.provider_id,\n"
    "                reason=(\n"
    "                    ProviderFailureReason.RATE_LIMITED\n"
    "                    if exc.retryable\n"
    "                    else ProviderFailureReason.DISABLED\n"
    "                ),\n"
    "                retryable=exc.retryable,\n"
    "                detail=f\"admission:{exc.code.value}:{exc.detail}\",\n"
    "            )\n",
    "        except RuntimeError as exc:\n"
    "            failure = _materialize_admission_failure(\n"
    "                adapter.provider_id, exc\n"
    "            )\n"
    "            if failure is None:\n"
    "                raise\n"
    "            return failure\n",
)

replace_once(
    "tests/test_mpr043_provider_governance.py",
    "    ProviderFailureReason,\n",
    "    ProviderFailure,\n"
    "    ProviderFailureReason,\n",
)

append_marker = "\n\n@pytest.mark.asyncio\nasync def test_discovery_plane_uses_governance_before_provider_call() -> None:\n"
path = Path("tests/test_mpr043_provider_governance.py")
text = path.read_text(encoding="utf-8")
if text.count(append_marker) != 1:
    raise SystemExit("governance discovery test marker not found exactly once")
insert = '''\n\nclass CircuitOpenAdapter(DeniedAdapter):\n    provider_id = "circuit_provider"\n    capabilities = ProviderCapabilities(\n        provider_id=provider_id,\n        schema_version_pin="circuit-provider@test",\n        quote=True,\n        artifact_kind=ExecutionArtifactKind.NONE,\n        exact_in=True,\n        exact_out=False,\n        legacy_spl=True,\n        token_2022=False,\n        native_sol=True,\n        wsol=True,\n        jito_compatible=False,\n        exposes_accounts=False,\n        exposes_alts=False,\n        quote_ttl_seconds=5,\n        rate_limit_policy="test",\n        auth_kind=AuthKind.NONE,\n        role=ProviderRole.DISCOVERY_ONLY,\n        admission_reason="test circuit adapter",\n    )\n\n    async def request_quote(self, _: QuoteRequest):\n        self.calls += 1\n        return ProviderFailure(\n            provider=self.provider_id,\n            reason=ProviderFailureReason.CIRCUIT_OPEN,\n            retryable=True,\n            detail="probe failed",\n        )\n\n\n@pytest.mark.asyncio\nasync def test_cooldown_preserves_circuit_reason_without_second_call() -> None:\n    adapter = CircuitOpenAdapter()\n    registry = ProviderRegistry((adapter,))\n    plane = DiscoveryPlane(registry, provider_timeout_seconds=0.1)\n\n    first = await plane.discover(quote_request())\n    second = await plane.discover(quote_request())\n\n    assert first.failures[0].reason is ProviderFailureReason.CIRCUIT_OPEN\n    assert second.failures[0].reason is ProviderFailureReason.CIRCUIT_OPEN\n    assert adapter.calls == 1\n'''
path.write_text(text.replace(append_marker, insert + append_marker, 1), encoding="utf-8")
