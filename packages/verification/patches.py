import ast
import difflib
from pathlib import PurePosixPath

from packages.diagnosis.contracts import PatchProposal


def validate_patch(proposal: PatchProposal, original: dict[str, str]) -> tuple[dict[str, str], str]:
    changes = {}
    diff = []
    for change in proposal.files:
        path = PurePosixPath(change.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in change.path
            or str(path) != change.path
            or change.path != "calculator.py"
            or change.path not in original
            or change.path in changes
        ):
            raise ValueError("Protected, duplicate, unsupported, or unsafe patch path")
        tree = ast.parse(change.content, filename=change.path)
        baseline = ast.parse(original[change.path], filename=change.path)
        # The initial execution policy supports pure expression repairs only. This
        # excludes module side effects and test/process bypasses, even in application files.
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            raise ValueError("Controlled policy only permits changing the add return expression")
        function = tree.body[0]
        if len(function.body) != 2 or not isinstance(function.body[-1], ast.Return):
            raise ValueError("Controlled policy requires the original function structure")
        expression = function.body[-1].value
        allowed = (
            ast.BinOp,
            ast.UnaryOp,
            ast.Name,
            ast.Load,
            ast.Constant,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.USub,
            ast.UAdd,
        )
        for node in ast.walk(expression):
            if not isinstance(node, allowed):
                raise ValueError("Only pure arithmetic expressions are supported")
            if isinstance(node, ast.Name) and node.id not in {"left", "right"}:
                raise ValueError("Only original operands are supported")
            if isinstance(node, ast.Constant) and type(node.value) not in {int, float}:
                raise ValueError("Only numeric constants are supported")
        function.body[-1].value = baseline.body[0].body[-1].value
        if ast.dump(tree) != ast.dump(baseline):
            raise ValueError("Protected function structure changed")
        if change.content == original[change.path]:
            raise ValueError("Candidate makes no change")
        changes[change.path] = change.content
        diff.extend(
            difflib.unified_diff(
                original[change.path].splitlines(keepends=True),
                change.content.splitlines(keepends=True),
                fromfile=f"a/{change.path}",
                tofile=f"b/{change.path}",
            )
        )
    return changes, "".join(diff)
