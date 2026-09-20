import pytest
from src.errors import *
from src.errors.retry import decide
from src.errors.deadline import Deadline
def test_categories(): assert len(FailureCategory)==12
def test_unknown_fails_closed():
 with pytest.raises(UnknownReasonCode): reason('NOPE')
def test_safe_envelope():
 e=ErrorEnvelope('INTERNAL_INVARIANT_UNKNOWN','c','o'); assert 'exception' not in str(e.to_dict()).lower()
def test_retry_ambiguity(): assert not decide(operation_class='non_idempotent_submission',category=FailureCategory.PROVIDER_TRANSIENT,attempt=0,remaining_seconds=2,ambiguity=Ambiguity.POSSIBLE_EFFECT).allowed
def test_deadline_child():
 now=[1.0]; d=Deadline.after(5,clock=lambda:now[0]); assert d.child(9).expires_at<=d.expires_at
