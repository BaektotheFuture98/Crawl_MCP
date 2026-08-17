from __future__ import annotations

import ast
from pathlib import Path

_SOURCE = Path("src/crawling_mcp")


def imports_under(root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.append((path, node.module))
            elif isinstance(node, ast.Import):
                found.extend((path, alias.name) for alias in node.names)
    return found


def test_domain_does_not_depend_on_application_adapters_or_bootstrap() -> None:
    violations = [
        (path, module)
        for path, module in imports_under(_SOURCE / "domain")
        if module.startswith(
            (
                "crawling_mcp.application",
                "crawling_mcp.adapters",
                "crawling_mcp.bootstrap",
            )
        )
    ]
    assert violations == []


def test_application_does_not_depend_on_adapters_or_bootstrap() -> None:
    violations = [
        (path, module)
        for path, module in imports_under(_SOURCE / "application")
        if module.startswith(("crawling_mcp.adapters", "crawling_mcp.bootstrap"))
    ]
    assert violations == []


def test_package_layout_has_explicit_hexagonal_boundaries() -> None:
    assert (_SOURCE / "application/ports/inbound").is_dir()
    assert (_SOURCE / "application/ports/outbound").is_dir()
    assert (_SOURCE / "adapters/inbound").is_dir()
    assert (_SOURCE / "adapters/outbound").is_dir()
    assert (_SOURCE / "bootstrap/composition.py").is_file()
    assert not (_SOURCE / "infrastructure").exists()
    assert not (_SOURCE / "ports").exists()
