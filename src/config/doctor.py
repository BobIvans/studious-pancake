"""Configuration diagnostics and optional read-only RPC identity checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Callable, Mapping
from urllib import request

from src.config.chain_registry import ChainRegistry, ChainRegistryError
from src.config.runtime import RuntimeConfig

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    schema_version: str
    ok: bool
    config_fingerprint: str
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "config_fingerprint": self.config_fingerprint,
            "diagnostics": [asdict(item) for item in self.diagnostics],
        }


RpcCall = Callable[[str, list[Any]], Any]


def _http_rpc(url: str) -> RpcCall:
    counter = 0

    def call(method: str, params: list[Any]) -> Any:
        nonlocal counter
        counter += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": counter, "method": method, "params": params}
        ).encode("utf-8")
        req = request.Request(
            url,
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with request.urlopen(
            req, timeout=10
        ) as response:  # nosec B310 - validated HTTP(S) RPC URL
            body = json.loads(response.read().decode("utf-8"))
        if body.get("error"):
            raise RuntimeError(f"RPC {method} failed: {body['error']}")
        if "result" not in body:
            raise RuntimeError(f"RPC {method} returned no result")
        return body["result"]

    return call


def _offline_diagnostics(
    config: RuntimeConfig,
    registry: ChainRegistry,
    *,
    environ: Mapping[str, str],
    check_secrets: bool,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    try:
        registry.validate_cluster(config.cluster.name, config.cluster.genesis_hash)
        diagnostics.append(
            Diagnostic(
                "CLUSTER_IDENTITY_VALID", "info", "cluster identity matches registry"
            )
        )
    except ChainRegistryError as exc:
        diagnostics.append(Diagnostic("CLUSTER_IDENTITY_INVALID", "error", str(exc)))

    additional = []
    if config.providers.marginfi.program_id:
        additional.append(config.providers.marginfi.program_id)
    try:
        registry.validate_allowlisted_programs(
            config.allowlist.program_ids,
            cluster=config.cluster.name,
            additional_addresses=additional,
        )
        diagnostics.append(
            Diagnostic(
                "PROGRAM_ALLOWLIST_VALID", "info", "all program IDs are registered"
            )
        )
    except ChainRegistryError as exc:
        diagnostics.append(Diagnostic("PROGRAM_ALLOWLIST_INVALID", "error", str(exc)))

    if config.providers.marginfi.enabled:
        diagnostics.append(
            Diagnostic(
                "MARGINFI_EXTERNAL_PIN_PENDING",
                "warning",
                "MarginFi addresses are explicit but remain unpinned until PR-027",
            )
        )

    secret_refs = {
        "wallet.signer_reference": config.wallet.signer_reference,
        "providers.jupiter.api_key_reference": config.providers.jupiter.api_key_reference,
        "providers.jito.auth_reference": config.providers.jito.auth_reference,
    }
    for label, reference in secret_refs.items():
        if reference is None:
            continue
        diagnostics.append(
            Diagnostic(
                "SECRET_REFERENCE_VALID", "info", f"{label} uses {reference.display()}"
            )
        )
        if not check_secrets:
            continue
        if reference.scheme != "env":
            diagnostics.append(
                Diagnostic(
                    "SECRET_NOT_RESOLVED",
                    "warning",
                    f"{label} is not an env reference and was not resolved by config doctor",
                )
            )
            continue
        secret = reference.resolve_from_environment(environ)
        if not secret:
            diagnostics.append(
                Diagnostic(
                    "SECRET_MISSING",
                    "error",
                    f"{label} points to missing environment variable {reference.locator}",
                )
            )
        elif label == "providers.jito.auth_reference" and not _UUID_RE.fullmatch(
            secret
        ):
            diagnostics.append(
                Diagnostic(
                    "JITO_AUTH_NOT_UUID",
                    "error",
                    "Jito authentication value is not an issued UUID-shaped credential",
                )
            )

    if config.cluster.rpc_http_url is None:
        diagnostics.append(
            Diagnostic(
                "RPC_NOT_CONFIGURED",
                "info",
                "RPC is intentionally absent in fail-closed defaults",
            )
        )
    return diagnostics


def _online_diagnostics(
    config: RuntimeConfig,
    registry: ChainRegistry,
    rpc_call: RpcCall,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    try:
        observed_genesis = rpc_call("getGenesisHash", [])
        if observed_genesis != config.cluster.genesis_hash:
            diagnostics.append(
                Diagnostic(
                    "RPC_CLUSTER_MISMATCH",
                    "error",
                    f"RPC genesis hash {observed_genesis} does not match configured cluster",
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    "RPC_CLUSTER_MATCH",
                    "info",
                    "RPC genesis hash matches configuration",
                )
            )
    except Exception as exc:
        return [Diagnostic("RPC_IDENTITY_UNAVAILABLE", "error", str(exc))]

    expected: dict[str, tuple[str, str]] = {}
    for entry in registry.entries:
        if entry.owner and config.cluster.name in entry.clusters:
            expected[entry.address] = (entry.owner, entry.id)
    for item in config.validation.owner_expectations:
        expected[item.account] = (item.owner, item.label)
    marginfi = config.providers.marginfi
    if marginfi.program_id:
        dynamic = next(
            item for item in registry.dynamic_entries if item.id == "marginfi_program"
        )
        if dynamic.owner:
            expected[marginfi.program_id] = (dynamic.owner, dynamic.id)

    addresses = list(expected)
    if not addresses:
        return diagnostics
    try:
        result = rpc_call(
            "getMultipleAccounts",
            [
                addresses,
                {"encoding": "base64", "commitment": config.cluster.commitment.value},
            ],
        )
        values = result.get("value") if isinstance(result, dict) else None
        if not isinstance(values, list) or len(values) != len(addresses):
            raise RuntimeError("getMultipleAccounts returned an unexpected shape")
        for address, account in zip(addresses, values, strict=True):
            expected_owner, label = expected[address]
            if account is None:
                diagnostics.append(
                    Diagnostic(
                        "ACCOUNT_MISSING",
                        "error",
                        f"{label} account is missing: {address}",
                    )
                )
                continue
            observed_owner = account.get("owner")
            if observed_owner != expected_owner:
                diagnostics.append(
                    Diagnostic(
                        "ACCOUNT_OWNER_MISMATCH",
                        "error",
                        f"{label} owner mismatch: expected {expected_owner}, got {observed_owner}",
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(
                        "ACCOUNT_OWNER_MATCH", "info", f"{label} owner is attested"
                    )
                )
    except Exception as exc:
        diagnostics.append(Diagnostic("ACCOUNT_OWNER_CHECK_FAILED", "error", str(exc)))
    return diagnostics


def run_config_doctor(
    config: RuntimeConfig,
    *,
    registry: ChainRegistry | None = None,
    online: bool = False,
    check_secrets: bool = False,
    environ: Mapping[str, str] | None = None,
    rpc_call: RpcCall | None = None,
) -> DoctorReport:
    active_registry = registry or ChainRegistry.load_default()
    active_env = {} if environ is None else environ
    diagnostics = _offline_diagnostics(
        config,
        active_registry,
        environ=active_env,
        check_secrets=check_secrets,
    )
    if online:
        if config.cluster.rpc_http_url is None and rpc_call is None:
            diagnostics.append(
                Diagnostic(
                    "RPC_REQUIRED",
                    "error",
                    "online config doctor requires cluster.rpc_http_url",
                )
            )
        else:
            diagnostics.extend(
                _online_diagnostics(
                    config,
                    active_registry,
                    rpc_call or _http_rpc(config.cluster.rpc_http_url or ""),
                )
            )
    ok = not any(item.severity == "error" for item in diagnostics)
    return DoctorReport(
        schema_version="pr026.config-doctor.v1",
        ok=ok,
        config_fingerprint=config.fingerprint(),
        diagnostics=tuple(diagnostics),
    )
