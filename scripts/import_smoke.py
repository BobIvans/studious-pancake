import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
for name in [
    "src.decision",
    "src.decision.dataset",
    "src.decision.model",
    "src.strategy.ranker",
]:
    importlib.import_module(name)
print("import smoke ok")
