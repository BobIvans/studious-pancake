from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_unique(path: str, lines: tuple[str, ...]) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    existing = set(text.splitlines())
    additions = [line for line in lines if line not in existing]
    if additions:
        target.write_text(
            text.rstrip("\n") + "\n" + "\n".join(additions) + "\n",
            encoding="utf-8",
        )


replace_once(
    "src/routing/registry.py",
    "from typing import Any, Mapping\n\nfrom src.providers.jupiter.quota import (\n",
    "from typing import Any, Mapping\n\n"
    "from src.provider_governance import (\n"
    "    AdmissionRequest,\n"
    "    ProviderAdmissionError,\n"
    "    ProviderGovernance,\n"
    "    ProviderOperation,\n"
    ")\n"
    "from src.providers.jupiter.quota import (\n",
)

replace_once(
    "src/routing/registry.py",
    "class ProviderRegistry:\n"
    "    def __init__(self, adapters: tuple[ProviderAdapter, ...]):\n"
    "        provider_ids = [adapter.provider_id for adapter in adapters]\n"
    "        if len(provider_ids) != len(set(provider_ids)):\n"
    "            raise ValueError(\"provider registry contains duplicate provider IDs\")\n"
    "        self.adapters = adapters\n",
    "class ProviderRegistry:\n"
    "    def __init__(\n"
    "        self,\n"
    "        adapters: tuple[ProviderAdapter, ...],\n"
    "        *,\n"
    "        governance: ProviderGovernance | None = None,\n"
    "    ) -> None:\n"
    "        provider_ids = [adapter.provider_id for adapter in adapters]\n"
    "        if len(provider_ids) != len(set(provider_ids)):\n"
    "            raise ValueError(\"provider registry contains duplicate provider IDs\")\n"
    "        self.adapters = adapters\n"
    "        self.governance = governance or ProviderGovernance.from_adapters(\n"
    "            adapters, {}\n"
    "        )\n",
)

replace_once(
    "src/routing/registry.py",
    "        jupiter_quota: JupiterQuotaManager | None = None,\n"
    "        contract_registry: Any = _LOAD_DEFAULT_CONTRACT_REGISTRY,\n"
    "    ) -> \"ProviderRegistry\":\n",
    "        jupiter_quota: JupiterQuotaManager | None = None,\n"
    "        contract_registry: Any = _LOAD_DEFAULT_CONTRACT_REGISTRY,\n"
    "        governance: ProviderGovernance | None = None,\n"
    "    ) -> \"ProviderRegistry\":\n",
)

replace_once(
    "src/routing/registry.py",
    "        return cls(adapters)\n",
    "        return cls(\n"
    "            adapters,\n"
    "            governance=governance\n"
    "            or ProviderGovernance.from_adapters(adapters, env),\n"
    "        )\n",
)

replace_once(
    "src/routing/registry.py",
    "            rows.append(row)\n",
    "            row.update(self.governance.startup_state(adapter.provider_id))\n"
    "            rows.append(row)\n",
)

old_signature = (
    "    async def _call_provider(\n"
    "        self,\n"
    "        adapter: ProviderAdapter,\n"
    "        request: QuoteRequest,\n"
    "    ) -> NormalizedQuote | ProviderFailure:\n"
)
new_methods = (
    "    async def _call_provider(\n"
    "        self,\n"
    "        adapter: ProviderAdapter,\n"
    "        request: QuoteRequest,\n"
    "    ) -> NormalizedQuote | ProviderFailure:\n"
    "        governance = self.registry.governance\n"
    "        manifest = governance.entitlement(adapter.provider_id)\n"
    "        admission = AdmissionRequest(\n"
    "            work_id=(\n"
    "                f\"discovery:{request.fingerprint}:{adapter.provider_id}\"\n"
    "            ),\n"
    "            provider_id=adapter.provider_id,\n"
    "            operation=ProviderOperation.DISCOVERY,\n"
    "            request_fingerprint=request.fingerprint,\n"
    "            fairness_key=request.fingerprint,\n"
    "            deadline_at=governance.clock() + self.provider_timeout_seconds,\n"
    "            expected_generation=manifest.generation,\n"
    "            estimated_cost_units=1,\n"
    "            estimated_spend_micros=0,\n"
    "            lease_ttl_seconds=self.provider_timeout_seconds,\n"
    "        )\n"
    "        try:\n"
    "            result = await governance.execute(\n"
    "                admission,\n"
    "                lambda: self._invoke_provider(adapter, request),\n"
    "            )\n"
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
    "            )\n"
    "        if isinstance(result, NormalizedQuote):\n"
    "            await governance.record_success(adapter.provider_id)\n"
    "        else:\n"
    "            await governance.record_failure(\n"
    "                adapter.provider_id, result.reason.value\n"
    "            )\n"
    "        return result\n\n"
    "    async def _invoke_provider(\n"
    "        self,\n"
    "        adapter: ProviderAdapter,\n"
    "        request: QuoteRequest,\n"
    "    ) -> NormalizedQuote | ProviderFailure:\n"
)
replace_once("src/routing/registry.py", old_signature, new_methods)

replace_once(
    "src/routing/registry.pyi",
    "from src.providers.jupiter.quota import JupiterQuotaManager\n",
    "from src.provider_governance import ProviderGovernance\n"
    "from src.providers.jupiter.quota import JupiterQuotaManager\n",
)
replace_once(
    "src/routing/registry.pyi",
    "class ProviderRegistry:\n"
    "    adapters: tuple[DiscoveryProvider, ...]\n\n"
    "    def __init__(self, adapters: tuple[DiscoveryProvider, ...]) -> None: ...\n",
    "class ProviderRegistry:\n"
    "    adapters: tuple[DiscoveryProvider, ...]\n"
    "    governance: ProviderGovernance\n\n"
    "    def __init__(\n"
    "        self,\n"
    "        adapters: tuple[DiscoveryProvider, ...],\n"
    "        *,\n"
    "        governance: ProviderGovernance | None = ...,\n"
    "    ) -> None: ...\n",
)
replace_once(
    "src/routing/registry.pyi",
    "        jupiter_quota: JupiterQuotaManager | None = ...,\n"
    "        contract_registry: Any = ...,\n"
    "    ) -> ProviderRegistry: ...\n",
    "        jupiter_quota: JupiterQuotaManager | None = ...,\n"
    "        contract_registry: Any = ...,\n"
    "        governance: ProviderGovernance | None = ...,\n"
    "    ) -> ProviderRegistry: ...\n",
)

replace_once(
    "src/provider_governance/scheduler.py",
    "from typing import Awaitable, Callable, Generic, TypeVar\n",
    "from typing import Awaitable, Callable, TypeVar\n",
)

append_unique(
    "config/format_targets.txt",
    (
        "src/provider_governance/__init__.py",
        "src/provider_governance/models.py",
        "src/provider_governance/authority.py",
        "src/provider_governance/dependency.py",
        "src/provider_governance/scheduler.py",
        "src/provider_governance/runtime.py",
        "tests/test_mpr043_provider_governance.py",
    ),
)
