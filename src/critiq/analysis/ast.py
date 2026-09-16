from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter
import tree_sitter_python


@dataclass(slots=True)
class Symbol:
    name: str
    kind: str  # "function" | "class" | ...
    start_line: int  # 1-based
    end_line: int


@dataclass(slots=True)
class ModuleInfo:
    path: str
    imports: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    source: str = ""

    @property
    def top_level_symbols(self) -> list[Symbol]:
        return [s for s in self.symbols if s.kind in ("function", "class")]

    def has_symbol(self, name: str) -> bool:
        return any(s.name == name for s in self.symbols)


class PythonParser:
    """Tree-sitter wrapper for Python source analysis."""

    def __init__(self) -> None:
        self._language = tree_sitter.Language(tree_sitter_python.language())
        self._parser = tree_sitter.Parser(self._language)

    def validate(self, source: str) -> bool:
        """True when `source` parses without tree-sitter syntax errors."""
        tree = self._parser.parse(source.encode("utf-8"))
        return not tree.root_node.has_error

    def parse_module(self, path: str, source: str) -> ModuleInfo:
        data = source.encode("utf-8")
        tree = self._parser.parse(data)
        info = ModuleInfo(path=path, source=source)

        root = tree.root_node
        self._collect_imports(root, info, data)
        self._collect_symbols(root, info, data)
        return info

    def _collect_imports(self, root, info: ModuleInfo, data: bytes) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in ("import_statement", "import_from_statement"):
                text = data[node.start_byte : node.end_byte].decode("utf-8", "replace")
                info.imports.append(text.strip())
            stack.extend(reversed(node.children))

    def _collect_symbols(self, root, info: ModuleInfo, data: bytes) -> None:
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in ("function_definition", "class_definition"):
                name_node = None
                for child in node.children:
                    if child.type == "identifier":
                        name_node = child
                        break
                if name_node is None:
                    continue
                name = data[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", "replace"
                )
                kind = "function" if node.type == "function_definition" else "class"
                info.symbols.append(
                    Symbol(
                        name=name,
                        kind=kind,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                    )
                )
            stack.extend(reversed(node.children))
