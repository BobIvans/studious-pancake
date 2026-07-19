from __future__ import annotations
import base64, json
from dataclasses import dataclass
from .contracts import DeploymentContract
from .models import RawAccount, ReasonCode
from .contracts import ContractError

@dataclass(frozen=True, slots=True)
class DecodedAccount:
    account_type: str; pubkey: str; fields: dict

def raw_from_base64(pubkey:str, owner:str, data_b64:str, executable:bool, slot:int, commitment):
    try: data=base64.b64decode(data_b64, validate=True)
    except Exception as exc: raise ContractError(ReasonCode.INVALID_ACCOUNT_SIZE, "invalid base64 fixture") from exc
    return RawAccount(pubkey,owner,data,executable,slot,commitment)

def decode_fixture_json(contract:DeploymentContract, account_type:str, account:RawAccount)->DecodedAccount:
    contract.require_enabled(); contract.validate_typed_account(account_type, account)
    payload=account.data[len(contract.account_types[account_type].discriminator):]
    try: fields=json.loads(payload.decode())
    except Exception as exc: raise ContractError(ReasonCode.INVALID_LAYOUT_VERSION, "fixture payload is not pinned canonical json") from exc
    if fields.get("layout_version") != contract.version: raise ContractError(ReasonCode.INVALID_LAYOUT_VERSION, "layout version mismatch")
    return DecodedAccount(account_type, account.pubkey, fields)
