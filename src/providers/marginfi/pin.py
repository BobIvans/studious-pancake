"""Pinned MarginFi contract metadata with PR-027 compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
from pathlib import Path
from typing import Any, Mapping

from solders.pubkey import Pubkey

from .errors import MarginfiRejection, MarginfiRejectionCode


_SCHEMA = "pr028.marginfi-binary-conformance.v1"
_RESOURCE = "marginfi_pr028.json"


@dataclass(frozen=True, slots=True)
class MarginfiContractPin:
    raw: dict[str, Any]
    path: Path | None
    provenance: dict[str, Any] | None = None

    @property
    def program_id(self) -> str:
        return str(self.raw["program_id"])

    @property
    def source_commit(self) -> str:
        return str(self.raw["source_commit"])

    @property
    def pin_hash(self) -> str:
        payload = {"layout": self.raw, "provenance": self.provenance}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def ix_discriminator(self, name: str) -> bytes:
        try:
            return bytes.fromhex(
                str(self.raw["instructions"][name]["discriminator_hex"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"missing or invalid instruction discriminator: {name}",
            ) from exc

    def account_discriminator(self, name: str) -> bytes:
        try:
            return bytes.fromhex(
                str(self.raw["account_layouts"][name]["discriminator_hex"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"missing or invalid account discriminator: {name}",
            ) from exc

    def account_size(self, name: str) -> int:
        try:
            return int(self.raw["account_layouts"][name]["struct_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"missing or invalid account size: {name}",
            ) from exc

    def approved_policy(self, symbol: str) -> dict[str, str]:
        try:
            raw = self.raw["approved_assets"][symbol.upper()]
            return {
                "mint": str(raw["mint"]),
                "token_program": str(raw["token_program"]),
            }
        except (KeyError, TypeError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.UNSUPPORTED_TOKEN,
                f"unapproved bank policy: {symbol}",
            ) from exc

    def validate_program_account(self, account: Any) -> None:
        if account is None:
            raise MarginfiRejection(
                MarginfiRejectionCode.ACCOUNT_MISSING,
                "pinned program account missing",
            )
        if str(getattr(account, "address", "")) != self.program_id:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                "RPC program account address does not match the pin",
            )
        if str(getattr(account, "owner", "")) != str(self.raw["program_owner"]):
            raise MarginfiRejection(
                MarginfiRejectionCode.OWNER_MISMATCH,
                "pinned program owner does not match the upgradeable loader",
            )
        if not bool(getattr(account, "executable", False)):
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                "pinned program is not executable",
            )


def _read_packaged_pin() -> dict[str, Any]:
    try:
        resource = resources.files("src.resources").joinpath(_RESOURCE)
        raw = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError) as exc:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "packaged PR-028 MarginFi contract pin is missing or malformed",
        ) from exc
    if not isinstance(raw, dict):
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "packaged PR-028 pin root must be an object",
        )
    return raw


def _read_optional_provenance(
    path: str | Path | None,
) -> tuple[Path | None, dict[str, Any] | None]:
    if path is None:
        candidate = Path("docs/contracts/marginfi_mainnet.json")
        if not candidate.is_file():
            return None, None
        source = candidate
    else:
        source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            f"MarginFi provenance manifest is unreadable: {source}",
        ) from exc
    if not isinstance(raw, dict):
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi provenance manifest root must be an object",
        )
    return source, raw


def _anchor_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def _validate_pin(
    raw: Mapping[str, Any],
    provenance: Mapping[str, Any] | None,
) -> None:
    if raw.get("schema_version") != _SCHEMA:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "unsupported PR-028 MarginFi pin schema",
        )
    if raw.get("cluster") != "mainnet-beta":
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi pin is not mainnet-beta",
        )
    try:
        Pubkey.from_string(str(raw["program_id"]))
        Pubkey.from_string(str(raw["program_owner"]))
    except (KeyError, ValueError) as exc:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi program identity is malformed",
        ) from exc
    source_commit = str(raw.get("source_commit", ""))
    if len(source_commit) != 40 or any(
        char not in "0123456789abcdef" for char in source_commit
    ):
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi source commit must be a full lowercase SHA",
        )
    instructions = raw.get("instructions")
    if not isinstance(instructions, dict):
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi instructions pin is missing",
        )
    for name, spec in instructions.items():
        try:
            pinned = bytes.fromhex(str(spec["discriminator_hex"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"invalid instruction pin: {name}",
            ) from exc
        if pinned != _anchor_discriminator(str(name)):
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"instruction discriminator drift: {name}",
            )
    layouts = raw.get("account_layouts")
    if not isinstance(layouts, dict):
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            "MarginFi account-layout pins are missing",
        )
    for required in ("marginfi_group", "marginfi_account", "bank"):
        spec = layouts.get(required)
        if not isinstance(spec, dict):
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"missing account layout: {required}",
            )
        try:
            discriminator = bytes.fromhex(str(spec["discriminator_hex"]))
            size = int(spec["struct_size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"malformed account layout: {required}",
            ) from exc
        if len(discriminator) != 8 or size <= 0:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                f"invalid account layout values: {required}",
            )
    if provenance is not None:
        if str(provenance.get("program_id")) != str(raw["program_id"]):
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                "PR-027 program id and PR-028 layout pin disagree",
            )
        if str(provenance.get("source_commit")) != source_commit:
            raise MarginfiRejection(
                MarginfiRejectionCode.PIN_MISMATCH,
                "PR-027 source commit and PR-028 layout pin disagree",
            )


def load_marginfi_contract_pin(
    path: str | Path | None = None,
) -> MarginfiContractPin:
    raw = _read_packaged_pin()
    source_path, provenance = _read_optional_provenance(path)
    _validate_pin(raw, provenance)
    return MarginfiContractPin(
        raw=dict(raw),
        path=source_path,
        provenance=dict(provenance) if provenance is not None else None,
    )
