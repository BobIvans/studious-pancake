import asyncio
from collections.abc import Awaitable
from typing import TypeVar
from .envelope import ErrorEnvelope,Result
from .categories import ResultState
T=TypeVar('T')
async def supervise(operation:Awaitable[T],*,correlation_id:str,operation_id:str)->Result:
 try:return Result(ResultState.SUCCESS,value=await operation)
 except asyncio.CancelledError: raise
 except Exception as exc:
  envelope=ErrorEnvelope('INTERNAL_INVARIANT_UNKNOWN',correlation_id,operation_id)
  result=Result(ResultState.FAILED,error=envelope)
  result.__cause__=exc  # type: ignore[attr-defined]
  return result
