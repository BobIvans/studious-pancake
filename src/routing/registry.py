from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .adapters import JupiterRouterAdapter, OkxDexAdapter, OpenOceanAdapter, OdosAdapter, ProviderAdapter
from .models import *

@dataclass(frozen=True)
class CandidateSelection:
    selected: NormalizedQuote | None
    reasons: dict[str, NonSelectionReason]

class ProviderRegistry:
    def __init__(self, adapters: tuple[ProviderAdapter, ...]): self.adapters=adapters
    @classmethod
    def from_env(cls, env: dict[str,str]):
        return cls((JupiterRouterAdapter(), OkxDexAdapter(api_key=env.get("OKX_API_KEY"), passphrase=env.get("OKX_PASSPHRASE"), secret=env.get("OKX_SECRET_KEY")), OpenOceanAdapter(api_key=env.get("OPENOCEAN_API_KEY")), OdosAdapter()))
    def startup_report(self) -> tuple[dict[str,str], ...]:
        allowed={"ready","discovery_only","disabled_missing_credentials","unhealthy"}; rows=[]
        for a in self.adapters:
            row=a.startup_state()
            if a.circuit.health is ProviderHealth.DISABLED_MISSING_CREDENTIALS: row["state"]="disabled_missing_credentials"
            elif a.circuit.health is ProviderHealth.UNHEALTHY: row["state"]="unhealthy"
            elif a.capabilities.role is ProviderRole.DISCOVERY_ONLY: row["state"]="discovery_only"
            elif a.capabilities.role is ProviderRole.EXECUTABLE: row["state"]="ready"
            assert row["state"] in allowed
            rows.append(row)
        return tuple(rows)

class RouteDiscoveryService:
    def __init__(self, registry: ProviderRegistry): self.registry=registry
    def classify(self, quotes: tuple[NormalizedQuote, ...], now: datetime | None=None) -> DiscoveryResult:
        discovery=[]; executable=[]; reasons={}; seen=set()
        for q in quotes:
            key=q.dedupe_key()
            if key in seen: reasons[q.external_id]=NonSelectionReason.DUPLICATE; continue
            seen.add(key)
            if not q.is_fresh(now): reasons[q.external_id]=NonSelectionReason.STALE; discovery.append(q); continue
            discovery.append(q)
            if q.minimum_output_state is not MinimumOutputState.PROVEN: reasons[q.external_id]=NonSelectionReason.UNPROVEN_MIN_OUTPUT; continue
            if not q.capabilities.admits_raw_instructions() or q.artifact_kind is not ExecutionArtifactKind.RAW_INSTRUCTIONS:
                reasons[q.external_id]=NonSelectionReason.NON_COMPOSABLE; continue
            executable.append(q)
        return DiscoveryResult(tuple(discovery), tuple(executable), reasons)
    def select_executable(self, quotes: tuple[NormalizedQuote, ...]) -> CandidateSelection:
        now = max((q.received_at for q in quotes), default=None)
        result=self.classify(quotes, now=now); reasons=dict(result.non_selection_reasons)
        candidates=[q for q in result.executable_candidates if q.conservative_net_result is not None]
        for q in result.executable_candidates:
            if q.conservative_net_result is None: reasons[q.external_id]=NonSelectionReason.MISSING_COST
        if not candidates: return CandidateSelection(None, reasons)
        selected=max(candidates, key=lambda q: q.conservative_net_result or -10**30)
        for q in candidates:
            if q is not selected: reasons[q.external_id]=NonSelectionReason.LOWER_CONSERVATIVE_NET
        return CandidateSelection(selected, reasons)
