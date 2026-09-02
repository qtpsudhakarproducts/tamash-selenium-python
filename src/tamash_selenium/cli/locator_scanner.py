"""Scans Python test source for Selenium locators — an AST walk (not a regex guess), so
``(By.CSS_SELECTOR, "…")`` tuples, ``driver.find_element(By.XPATH, "…")`` inline forms, and
page-object class attributes are all found reliably.

Flags a *brittle* locator (css / xpath / class name / partial link text) bound to a
non-descriptive variable name — ``By.ID`` / ``By.NAME`` carry their own meaning and are never
flagged.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import List, Optional

from ..source_locations import decode_variable_name

_BRITTLE_BY = {"CSS_SELECTOR", "XPATH", "CLASS_NAME", "PARTIAL_LINK_TEXT"}
_ALL_BY = _BRITTLE_BY | {"ID", "NAME", "TAG_NAME", "LINK_TEXT"}
_SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "venv", ".venv", "node_modules", "site-packages"}


@dataclass
class Occurrence:
    file: str
    line: int
    by: str          # ID | NAME | CSS_SELECTOR | ...
    snippet: str
    described: bool   # bound to a name decode_variable_name recognises
    priority: str     # "high" (brittle + undescribed) | "normal"
    in_test_file: bool


def _by_name(node: ast.AST) -> Optional[str]:
    """``By.CSS_SELECTOR`` -> ``"CSS_SELECTOR"`` (also bare ``"css selector"`` string constants)."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "By":
        return node.attr if node.attr in _ALL_BY else None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        mapped = {"css selector": "CSS_SELECTOR", "xpath": "XPATH", "id": "ID", "name": "NAME",
                  "class name": "CLASS_NAME", "link text": "LINK_TEXT", "partial link text": "PARTIAL_LINK_TEXT",
                  "tag name": "TAG_NAME"}.get(node.value)
        return mapped
    return None


def is_test_file(path: str) -> bool:
    name = os.path.basename(path)
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith("_steps.py") or "step" in name.lower()


class _Visitor(ast.NodeVisitor):
    def __init__(self, file_path: str, lines: List[str]):
        self.file_path = file_path
        self.lines = lines
        self.occurrences: List[Occurrence] = []
        self._is_test = is_test_file(file_path)

    def _record(self, by: str, lineno: int, bound_name: Optional[str]) -> None:
        described = bool(bound_name and decode_variable_name(bound_name) is not None)
        brittle = by in _BRITTLE_BY
        snippet = self.lines[lineno - 1].strip() if 0 <= lineno - 1 < len(self.lines) else ""
        self.occurrences.append(Occurrence(
            file=self.file_path, line=lineno, by=by, snippet=snippet[:100],
            described=described, priority="high" if brittle and not described else "normal",
            in_test_file=self._is_test,
        ))

    def visit_Assign(self, node: ast.Assign) -> None:
        by = self._tuple_by(node.value)
        name = None
        if isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node.targets[0], ast.Attribute):
            name = node.targets[0].attr
        if by:
            self._record(by, node.lineno, name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        by = self._tuple_by(node.value) if node.value else None
        name = node.target.attr if isinstance(node.target, ast.Attribute) else (
            node.target.id if isinstance(node.target, ast.Name) else None)
        if by:
            self._record(by, node.lineno, name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in ("find_element", "find_elements") and node.args:
            by = _by_name(node.args[0])
            if by:
                self._record(by, node.lineno, None)
        self.generic_visit(node)

    @staticmethod
    def _tuple_by(value: Optional[ast.AST]) -> Optional[str]:
        if isinstance(value, ast.Tuple) and len(value.elts) == 2:
            return _by_name(value.elts[0])
        return None


def scan_file(file_path: str, content: str) -> List[Occurrence]:
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return []
    visitor = _Visitor(file_path, content.split("\n"))
    visitor.visit(tree)
    return visitor.occurrences


def scan_directory(directory: str) -> List[Occurrence]:
    occurrences: List[Occurrence] = []
    if not os.path.isdir(directory):
        return occurrences
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    occurrences.extend(scan_file(path, handle.read()))
            except OSError:
                continue
    return occurrences
