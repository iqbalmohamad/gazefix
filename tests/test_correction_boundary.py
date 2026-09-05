import ast
from pathlib import Path


def test_provider_neutral_boundaries():
    root=Path(__file__).parents[1]/"gazefix"/"correction"
    forbidden=("mediapipe","PySide6","Qt","gazefix.pipeline","gazefix.camera","gazefix.ui")
    libraries={"__init__","models","engine","geometry","masks","geometric","policy"}
    for path in root.glob("*.py"):
        imports=[]
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Import): imports.extend(a.name for a in node.names)
            if isinstance(node,ast.ImportFrom):
                imports.append(node.module or "")
                imports.extend((node.module+"." if node.module else "")+a.name for a in node.names)
        assert not any(i==f or i.startswith(f+".") for i in imports for f in forbidden), (path,imports)
        if path.stem in libraries:
            assert not any("mediapipe_tracker" in i or i.endswith((".harness",".debug")) for i in imports)
        if path.stem in ("geometric","engine"):
            assert not any(i.endswith(".policy") for i in imports)
        if path.stem=="geometry": assert not any(i.startswith("cv2") for i in imports)
        if path.stem=="models": assert not any(i.startswith("gazefix.") and not
            (i.startswith("gazefix.tracking.models") or i.startswith("gazefix.gaze.models")) for i in imports)
    for path in (root.parent/"tracking").glob("*.py"):
        assert "gazefix.correction" not in path.read_text()
