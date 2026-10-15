"""Repo-wide rules from CLAUDE.md that code can check."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def imported_top_level_modules(package_dir: Path) -> set[str]:
    modules = set()
    for path in package_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module.split(".")[0])
    return modules


def test_sdk_does_not_import_server():
    assert "retrack_server" not in imported_top_level_modules(ROOT / "sdk")


def test_server_does_not_import_sdk():
    assert "retrack" not in imported_top_level_modules(ROOT / "server" / "src")


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert value == "", f"{name} must not have a value in .env.example"
