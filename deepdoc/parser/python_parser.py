"""Python file parser using tree-sitter.

Extracts: functions, async functions, classes, methods, enums, constants,
dataclasses — with docstrings, body previews, decorator extraction,
and visibility tracking (public vs _private vs __dunder__).
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ParsedFile, Symbol

try:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser

    PY_LANGUAGE = Language(tspython.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_python(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        parser = Parser(PY_LANGUAGE)
        tree = parser.parse(bytes(content, "utf8"))
        lines = content.splitlines()

        _walk(tree.root_node, lines, symbols, imports)
    else:
        # Fallback: simple regex-based extraction
        symbols, imports = _regex_fallback(content)

    # Post-process: detect enums, dataclasses, constants
    _tag_special_classes(symbols, content)
    _extract_module_constants(content, symbols)

    return ParsedFile(
        path=path,
        language=language,
        symbols=symbols,
        imports=imports,
        raw_content=content[:12000],
    )


def _walk(node, lines: list[str], symbols: list[Symbol], imports: list[str], depth: int = 0) -> None:
    if node.type in ("import_statement", "import_from_statement"):
        imports.append(_node_text(node, lines))
        return

    if node.type in ("function_definition", "async_function_definition"):
        sym = _extract_function(node, lines)
        if sym:
            symbols.append(sym)
        return  # don't recurse into function bodies

    if node.type == "class_definition":
        sym = _extract_class(node, lines)
        if sym:
            symbols.append(sym)
        # Recurse into class body for methods
        for child in node.children:
            if child.type == "block":
                for method_node in child.children: 
                    if method_node.type in ("function_definition", "async_function_definition"):
                        msym = _extract_function(method_node, lines, kind="method")
                        if msym:
                            symbols.append(msym)
        return

    for child in node.children:
        _walk(child, lines, symbols, imports, depth + 1)


def _extract_function(node, lines: list[str], kind: str = "function") -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    name = _node_text(name_node, lines)
    signature = lines[node.start_point[0]] if node.start_point[0] < len(lines) else ""
    docstring = _get_docstring(node, lines)
    body_preview = _body_preview(node, lines)
    decorators = _get_decorators(node, lines)
    visibility = _python_visibility(name)

    return Symbol(
        name=name,
        kind=kind,
        signature=signature.strip(),
        docstring=docstring,
        body_preview=body_preview,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=decorators,
        visibility=visibility,
    )


def _extract_class(node, lines: list[str]) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    name = _node_text(name_node, lines)
    signature = lines[node.start_point[0]] if node.start_point[0] < len(lines) else ""
    docstring = _get_docstring(node, lines)
    decorators = _get_decorators(node, lines)
    visibility = _python_visibility(name)

    # Extract class-level fields from __init__ or class body
    fields = _extract_class_fields(node, lines)

    return Symbol(
        name=name,
        kind="class",
        signature=signature.strip(),
        docstring=docstring,
        body_preview=_body_preview(node, lines, max_lines=8),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=decorators,
        visibility=visibility,
        fields=fields,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decorator extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_decorators(node, lines: list[str]) -> list[str]:
    """Extract @decorator annotations from a function or class node."""
    decorators = []

    # In tree-sitter Python, decorators are children of decorated_definition
    # which wraps the actual function/class. Check parent.
    parent = node.parent
    if parent and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                text = _node_text(child, lines).strip()
                decorators.append(text)

    # Fallback: scan lines above the node
    if not decorators:
        start_line = node.start_point[0]
        for i in range(start_line - 1, max(start_line - 15, -1), -1):
            if i < 0 or i >= len(lines):
                break
            line = lines[i].strip()
            if line.startswith("@"):
                decorators.insert(0, line)
            elif line == "" or line.startswith("#"):
                continue
            else:
                break

    return decorators[:10]


# ─────────────────────────────────────────────────────────────────────────────
# Class field extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_class_fields(node, lines: list[str]) -> list[str]:
    """Extract class-level attributes from class body and __init__."""
    fields = []
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                # Class-level assignments: name: type = value (dataclass fields, etc.)
                if stmt.type in ("expression_statement", "assignment"):
                    line = lines[stmt.start_point[0]].strip() if stmt.start_point[0] < len(lines) else ""
                    # Match patterns like: name: str = "default" or name = value
                    if re.match(r"\w+\s*[:=]", line) and not line.startswith(("def ", "class ", "@", "#")):
                        fields.append(line.rstrip())

                # Look inside __init__ for self.x = assignments
                if stmt.type in ("function_definition",):
                    fname = stmt.child_by_field_name("name")
                    if fname and _node_text(fname, lines) == "__init__":
                        for bchild in stmt.children:
                            if bchild.type == "block":
                                for bstmt in bchild.children:
                                    bline = lines[bstmt.start_point[0]].strip() if bstmt.start_point[0] < len(lines) else ""
                                    m = re.match(r"self\.(\w+)\s*[:=]", bline)
                                    if m:
                                        fields.append(bline.rstrip())
    return fields[:20]


# ─────────────────────────────────────────────────────────────────────────────
# Enum and special class detection
# ─────────────────────────────────────────────────────────────────────────────

def _tag_special_classes(symbols: list[Symbol], content: str) -> None:
    """Post-process to detect Enum subclasses and dataclasses."""
    for sym in symbols:
        if sym.kind != "class":
            continue

        sig = sym.signature

        # Enum detection: class Foo(Enum), class Foo(IntEnum), class Foo(StrEnum)
        if re.search(r"\(\s*(?:\w+\.)?(?:Enum|IntEnum|StrEnum|Flag|IntFlag)\s*\)", sig):
            sym.kind = "enum"
            # Extract enum members from body
            if sym.body_preview:
                members = []
                for line in sym.body_preview.splitlines():
                    line = line.strip()
                    m = re.match(r"(\w+)\s*=\s*", line)
                    if m and m.group(1) not in ("class", "def", "self"):
                        members.append(line.rstrip())
                if members:
                    sym.fields = members

        # Dataclass detection
        if any("@dataclass" in d for d in sym.decorators):
            # Already has fields from _extract_class_fields — just note it
            if not sym.docstring:
                sym.docstring = "(dataclass)"


# ─────────────────────────────────────────────────────────────────────────────
# Module-level constant extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_module_constants(content: str, symbols: list[Symbol]) -> None:
    """Extract module-level UPPER_CASE constants."""
    existing_names = {s.name for s in symbols}
    lines = content.splitlines()

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match UPPER_CASE = value (module-level only, no leading whitespace)
        if not line[0:1].isspace() and not stripped.startswith(("#", "def ", "class ", "@", "import ", "from ")):
            m = re.match(r"([A-Z][A-Z_0-9]+)\s*[:=]\s*(.+)", stripped)
            if m and m.group(1) not in existing_names:
                name = m.group(1)
                symbols.append(Symbol(
                    name=name,
                    kind="constant",
                    signature=stripped,
                    start_line=i + 1,
                    visibility="public",
                    is_exported=True,
                ))
                existing_names.add(name)


# ─────────────────────────────────────────────────────────────────────────────
# Visibility
# ─────────────────────────────────────────────────────────────────────────────

def _python_visibility(name: str) -> str:
    """Determine Python visibility by naming convention."""
    if name.startswith("__") and name.endswith("__"):
        return "dunder"
    if name.startswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


# ─────────────────────────────────────────────────────────────────────────────
# Docstring extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_docstring(node, lines: list[str]) -> str:
    """Extract docstring from a function/class node."""
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "expression_statement":
                    for s in stmt.children:
                        if s.type == "string":
                            raw = _node_text(s, lines)
                            return raw.strip("\"'` \n").replace('"""', "").replace("'''", "")[:300]
    return ""


def _body_preview(node, lines: list[str], max_lines: int = 5) -> str:
    start = node.start_point[0]
    end = min(node.end_point[0] + 1, start + max_lines)
    return "\n".join(lines[start:end])


def _node_text(node, lines: list[str]) -> str:
    start_row, start_col = node.start_point
    end_row, end_col = node.end_point
    if start_row == end_row:
        return lines[start_row][start_col:end_col] if start_row < len(lines) else ""
    result = [lines[start_row][start_col:]] if start_row < len(lines) else []
    for row in range(start_row + 1, end_row):
        if row < len(lines):
            result.append(lines[row])
    if end_row < len(lines):
        result.append(lines[end_row][:end_col])
    return "\n".join(result)


def _regex_fallback(content: str):
    import re
    symbols = []
    imports = []
    lines = content.splitlines()
    pending_decorators = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track decorators
        if stripped.startswith("@"):
            pending_decorators.append(stripped)
            continue

        if stripped.startswith(("import ", "from ")):
            imports.append(stripped)
            pending_decorators = []
            continue

        if stripped.startswith("def ") or stripped.startswith("async def "):
            m = re.match(r"(?:async )?def (\w+)\(", stripped)
            if m:
                name = m.group(1)
                symbols.append(Symbol(
                    name=name,
                    kind="function",
                    signature=stripped,
                    body_preview="\n".join(lines[i:i + 5]),
                    start_line=i + 1,
                    decorators=pending_decorators,
                    visibility=_python_visibility(name),
                ))
            pending_decorators = []
            continue

        if stripped.startswith("class "):
            m = re.match(r"class (\w+)", stripped)
            if m:
                name = m.group(1)
                kind = "class"
                # Check for Enum
                if re.search(r"\(\s*(?:\w+\.)?(?:Enum|IntEnum|StrEnum)\s*\)", stripped):
                    kind = "enum"
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    signature=stripped,
                    body_preview="\n".join(lines[i:i + 8]),
                    start_line=i + 1,
                    decorators=pending_decorators,
                    visibility=_python_visibility(name),
                ))
            pending_decorators = []
            continue

        # Module-level constants
        if not line[0:1].isspace() and not stripped.startswith(("#", "@")):
            m = re.match(r"([A-Z][A-Z_0-9]+)\s*[:=]\s*(.+)", stripped)
            if m:
                symbols.append(Symbol(
                    name=m.group(1),
                    kind="constant",
                    signature=stripped,
                    start_line=i + 1,
                    visibility="public",
                    is_exported=True,
                ))

        # Reset decorators on non-decorator non-blank lines
        if stripped and not stripped.startswith(("@", "#")):
            pending_decorators = []

    return symbols, imports
