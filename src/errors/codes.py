import json
from dataclasses import dataclass
from importlib.resources import files
from .categories import FailureCategory,RetryClass
class UnknownReasonCode(ValueError): pass
@dataclass(frozen=True)
class ReasonDefinition:
 reason_code:str; owner:str; category:FailureCategory; safe_message:str; severity:str; retry_class:RetryClass; allowed_safe_context_fields:frozenset[str]
def registry()->dict[str,ReasonDefinition]:
 data=json.loads(files('src.resources').joinpath('reason_code_registry.json').read_text())
 return {x['reason_code']:ReasonDefinition(x['reason_code'],x['owner'],FailureCategory(x['category']),x['safe_message'],x['severity'],RetryClass(x['retry_class']),frozenset(x['safe_context_fields'])) for x in data['reason_codes']}
def reason(code:str)->ReasonDefinition:
 try:return registry()[code]
 except KeyError as exc: raise UnknownReasonCode(f'unregistered reason code: {code!r}') from exc
