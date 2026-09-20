from .categories import Ambiguity
class InvalidAmbiguityTransition(ValueError):pass
def transition(current:Ambiguity,target:Ambiguity,*,reconciled:bool=False)->Ambiguity:
 if current in (Ambiguity.POSSIBLE_EFFECT,Ambiguity.QUARANTINED) and target is Ambiguity.RECONCILED and reconciled:return target
 if current is Ambiguity.POSSIBLE_EFFECT and target is Ambiguity.QUARANTINED:return target
 if current is target:return target
 raise InvalidAmbiguityTransition(f'illegal ambiguity transition: {current.value} -> {target.value}')
