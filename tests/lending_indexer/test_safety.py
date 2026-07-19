from pathlib import Path
import ast

FORBIDDEN={"sender","jito","sendTransaction","keypair","wallet","TransactionBuilder","transaction_compiler","execute_liquidation"}

def test_lending_indexer_has_no_execution_surface_imports_or_calls():
    for path in Path("src/lending_indexer").glob("*.py"):
        text=path.read_text()
        tree=ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import, ast.ImportFrom)):
                mod=getattr(node,"module","") or " ".join(a.name for a in node.names)
                assert not any(term in mod for term in FORBIDDEN), (path, mod)
            if isinstance(node, ast.Name):
                assert node.id not in {"execute_liquidation","sendTransaction","TransactionBuilder"}, (path,node.id)
        assert "jsonParsed" not in text

def test_application_keeps_liquidation_disabled():
    from src.application import build_application
    app=build_application()
    m={e.name:e for e in app.manifest()}
    assert m["kamino_liquidation"].effective_mode == "disabled"
