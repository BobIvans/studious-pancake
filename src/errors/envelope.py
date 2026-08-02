from dataclasses import dataclass,field
from datetime import datetime,timezone
from typing import Any,Mapping
from .categories import Ambiguity,FailureCategory,ResultState,RetryClass
from .codes import reason
@dataclass(frozen=True)
class ErrorEnvelope:
 reason_code:str; correlation_id:str; operation_id:str; run_id:str|None=None; provider_id:str|None=None; timestamp:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat()); safe_context:Mapping[str,Any]=field(default_factory=dict)
 schema_id:str=field(default='failure.error-envelope.v1',init=False)
 def __post_init__(self):
  d=reason(self.reason_code); unknown=set(self.safe_context)-d.allowed_safe_context_fields
  if unknown: raise ValueError(f'unsafe context fields: {sorted(unknown)!r}')
 def to_dict(self)->dict[str,Any]:
  d=reason(self.reason_code); return {'schema_id':self.schema_id,'reason_code':self.reason_code,'category':d.category.value,'safe_message':d.safe_message,'severity':d.severity,'correlation_id':self.correlation_id,'run_id':self.run_id,'operation_id':self.operation_id,'provider_id':self.provider_id,'retry_class':d.retry_class.value,'ambiguity':'possible_effect' if d.category is FailureCategory.SUBMISSION_AMBIGUITY else 'none','timestamp':self.timestamp,'safe_context':dict(self.safe_context)}
@dataclass(frozen=True)
class Result:
 state:ResultState; value:Any=None; error:ErrorEnvelope|None=None; ambiguity:Ambiguity=Ambiguity.NONE
 def __post_init__(self):
  if self.state is ResultState.SUCCESS and (self.error or self.ambiguity is not Ambiguity.NONE): raise ValueError('success cannot carry failure or ambiguity')
  if self.state is ResultState.AMBIGUOUS and self.ambiguity is Ambiguity.NONE: raise ValueError('ambiguous result requires ambiguity state')
