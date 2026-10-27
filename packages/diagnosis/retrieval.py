import ast
from importlib.resources import files


def fixture_source(fixture_id: str) -> dict[str, str]:
    from packages.ingestion.fixtures import FIXTURE_IDS

    if fixture_id not in FIXTURE_IDS:
        raise ValueError("Source retrieval is restricted to registered fixtures")
    root = files("benchmarks").joinpath("fixtures", fixture_id, "source")
    return {
        path.name: path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for path in sorted(root.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".py")
    }


def inspect_source(source: dict[str, str]) -> dict:
    result = {}
    for path, text in source.items():
        tree = ast.parse(text, filename=path)
        result[path] = {
            "text": text,
            "symbols": [
                {"name": node.name, "line": node.lineno, "end_line": node.end_lineno}
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ],
        }
    return result
