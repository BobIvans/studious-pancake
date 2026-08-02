import json
from dataclasses import dataclass
from importlib.resources import files
from .categories import Ambiguity,FailureCategory
@dataclass(frozen=True)
class RetryDecision: allowed:bool; terminal_state:str; reason:str
def decide(*,operation_class:str,category:FailureCategory,attempt:int,remaining_seconds:float,ambiguity:Ambiguity=Ambiguity.NONE)->RetryDecision:
 rows=json.loads(files('src.resources').joinpath('retry_idempotency_matrix.json').read_text())['operations']; row=next((x for x in rows if x['operation_class']==operation_class),None)
 if row is None:return RetryDecision(False,'failed','unknown operation class')
 if ambiguity is not Ambiguity.NONE or operation_class in ('non_idempotent_submission','ambiguous_settlement'):return RetryDecision(False,'ambiguous','reconciliation required')
 allowed=bool(row['retries_allowed'] and category.value in row['retryable_categories'] and attempt<row['maximum_attempts'] and remaining_seconds>0)
 return RetryDecision(allowed,'retry' if allowed else row['terminal_result'],'typed bounded decision')
