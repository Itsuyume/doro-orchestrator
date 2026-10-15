"""AST-based layer, cycle, size and nesting checks; does not run any providers."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
LAYERS = {"domain": {"domain"}, "application": {"domain", "application"},
          "infrastructure": {"domain", "infrastructure"},
          "interface": {"domain", "application", "infrastructure", "interface"}}
BLOCKS = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.AsyncFor)


def nesting(node: ast.AST, depth: int = 0) -> int:
    current = depth + int(isinstance(node, BLOCKS))
    return max([current, *(nesting(child, current) for child in ast.iter_child_nodes(node))])


def inspect(path: Path) -> tuple[str, set[str], list[str]]:
    relative = path.relative_to(ROOT)
    module = ".".join(relative.with_suffix("").parts)
    source = path.read_text()
    tree = ast.parse(source)
    failures: list[str] = []
    dependencies: set[str] = set()
    if len(source.splitlines()) > 220:
        failures.append(f"{module}: file exceeds 220 lines")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.end_lineno or node.lineno) - node.lineno + 1 > 65:
                failures.append(f"{module}:{node.lineno}: function exceeds 65 lines")
            if nesting(node) > 3:
                failures.append(f"{module}:{node.lineno}: nesting exceeds 3 levels")
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("doro."):
            dependencies.add(node.module)
        if isinstance(node, ast.Import):
            dependencies.update(alias.name for alias in node.names if alias.name.startswith("doro."))
    layer = relative.parts[1]
    for dependency in dependencies:
        if dependency.split(".")[1] not in LAYERS[layer]:
            failures.append(f"{module}: forbidden dependency on {dependency}")
    return module, dependencies, failures


def check_cycles(graph: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set()
    active: set[str] = set()
    failures: list[str] = []

    def visit(module: str) -> None:
        if module in active:
            failures.append(f"Circular dependency: {module}")
            return
        if module in visited:
            return
        active.add(module)
        for dependency in graph.get(module, set()):
            visit(dependency)
        active.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)
    return failures


def main() -> int:
    graph: dict[str, set[str]] = {}
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        module, dependencies, messages = inspect(path)
        graph[module] = dependencies
        failures.extend(messages)
    failures.extend(check_cycles(graph))
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Architecture OK: {len(graph)} modules; layers, cycles, size and depth checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
