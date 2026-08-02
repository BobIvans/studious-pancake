import asyncio,time
from dataclasses import dataclass
from typing import Callable
@dataclass(frozen=True)
class Deadline:
 expires_at:float; _clock:Callable[[],float]=time.monotonic
 @classmethod
 def after(cls,seconds:float,*,clock:Callable[[],float]=time.monotonic)->'Deadline': return cls(clock()+max(0.0,seconds),clock)
 @property
 def remaining(self)->float:return max(0.0,self.expires_at-self._clock())
 @property
 def expired(self)->bool:return self.remaining<=0
 def child(self,maximum_seconds:float)->'Deadline':return Deadline(min(self.expires_at,self._clock()+max(0.0,maximum_seconds)),self._clock)
 def timeout(self):return asyncio.timeout(self.remaining)
 def safe_context(self)->dict[str,int]:return {'deadline_remaining_ms':int(self.remaining*1000)}
