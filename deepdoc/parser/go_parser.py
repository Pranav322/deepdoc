"""Go parser using tree-sitter.

Extracts: functions, methods, structs (with fields), interfaces (with methods),
type aliases, const blocks, enums (iota patterns) — with GoDoc comments,
body previews, and exported/unexported tracking.

Covers Gin, Echo, Fiber, Chi, net/http patterns via the API detector.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ParsedFile, Symbol

try:
    import tree_sitter_go as tsgo
    from tree_sitter import Language, Parser

    GO_LANGUAGE = Language(tsgo.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_go(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        parser = Parser(GO_LANGUAGE)
        tree = parser.parse(bytes(content, "utf8"))
        lines = content.splitlines()
        _walk(tree.root_node, lines, symbols, imports)
    else:
        symbols, imports = _regex_fallback(content)

    return ParsedFile(
        path=path,
        language=language,
        symbols=symbols,
        imports=imports,
        raw_content=content[:8000],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tree-sitter walk
# ─────────────────────────────────────────────────────────────────────────────

def _walk(node, lines: list[str], symbols: list[Symbol], imports: list[str]) -> None:
    t = node.type

    if t == "import_declaration":
        imports.append(_node_text(node, lines)[:200])
        return

    if t == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            name = _node_text(name_node, lines)
            doc = _get_godoc(node, lines)
            symbols.append(Symbol(
                name=name,
                kind="function",
                signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
                docstring=doc,
                body_preview=_body_preview(node, lines),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=name[0].isupper() if name else False,
                visibility="exported" if (name and name[0].isupper()) else "unexported",
            ))
        return

    if t == "method_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            name = _node_text(name_node, lines)
            doc = _get_godoc(node, lines)
            # Extract receiver type
            receiver = ""
            for child in node.children:
                if child.type == "parameter_list" and child == node.children[1]:
                    # First param list is the receiver
                    receiver = _node_text(child, lines)
                    break
            sig = lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else ""
            symbols.append(Symbol(
                name=name,
                kind="method",
                signature=sig,
                docstring=doc,
                body_preview=_body_preview(node, lines),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=name[0].isupper() if name else False,
                visibility="exported" if (name and name[0].isupper()) else "unexported",
            ))
        return

    if t == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                _extract_type_spec(child, node, lines, symbols)
        return

    # const / var blocks
    if t in ("const_declaration", "var_declaration"):
        _extract_const_block(node, lines, symbols, is_const=(t == "const_declaration"))
        return

    for child in node.children:
        _walk(child, lines, symbols, imports)


# ─────────────────────────────────────────────────────────────────────────────
# Type spec extraction (structs, interfaces, type aliases)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_type_spec(spec_node, parent_node, lines: list[str], symbols: list[Symbol]) -> None:
    name_node = spec_node.child_by_field_name("name")
    type_node = spec_node.child_by_field_name("type")
    if not name_node:
        return

    name = _node_text(name_node, lines)
    doc = _get_godoc(parent_node, lines)
    is_exported = name[0].isupper() if name else False

    if type_node and type_node.type == "struct_type":
        fields = _extract_struct_fields(type_node, lines)
        symbols.append(Symbol(
            name=name,
            kind="type",
            signature=f"type {name} struct",
            docstring=doc,
            body_preview=_body_preview(parent_node, lines, max_lines=15),
            start_line=parent_node.start_point[0] + 1,
            end_line=parent_node.end_point[0] + 1,
            is_exported=is_exported,
            visibility="exported" if is_exported else "unexported",
            fields=fields,
        ))
    elif type_node and type_node.type == "interface_type":
        methods = _extract_interface_methods(type_node, lines)
        symbols.append(Symbol(
            name=name,
            kind="interface",
            signature=f"type {name} interface",
            docstring=doc,
            body_preview=_body_preview(parent_node, lines, max_lines=15),
            start_line=parent_node.start_point[0] + 1,
            end_line=parent_node.end_point[0] + 1,
            is_exported=is_exported,
            visibility="exported" if is_exported else "unexported",
            fields=methods,
        ))
    else:
        # Type alias: type Foo = Bar or type Foo int
        sig = lines[parent_node.start_point[0]].strip() if parent_node.start_point[0] < len(lines) else ""
        symbols.append(Symbol(
            name=name,
            kind="type",
            signature=sig,
            docstring=doc,
            start_line=parent_node.start_point[0] + 1,
            end_line=parent_node.end_point[0] + 1,
            is_exported=is_exported,
            visibility="exported" if is_exported else "unexported",
        ))


def _extract_struct_fields(struct_node, lines: list[str]) -> list[str]:
    """Extract struct field definitions as readable strings."""
    fields = []
    for child in struct_node.children:
        if child.type == "field_declaration_list":
            for field_node in child.children:
                if field_node.type == "field_declaration":
                    field_line = lines[field_node.start_point[0]].strip() if field_node.start_point[0] < len(lines) else ""
                    if field_line:
                        fields.append(field_line)
    return fields[:30]


def _extract_interface_methods(iface_node, lines: list[str]) -> list[str]:
    """Extract interface method signatures."""
    methods = []
    for child in iface_node.children:
        if child.type in ("method_spec", "method_elem"):
            method_line = lines[child.start_point[0]].strip() if child.start_point[0] < len(lines) else ""
            if method_line:
                methods.append(method_line)
        elif child.type == "type_elem":
            # Embedded interface
            text = _node_text(child, lines).strip()
            if text:
                methods.append(text)
    return methods[:30]


# ─────────────────────────────────────────────────────────────────────────────
# Const/var block extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_const_block(node, lines: list[str], symbols: list[Symbol],
                         is_const: bool = True) -> None:
    """Extract constants from const/var blocks, detecting iota enums."""
    doc = _get_godoc(node, lines)
    has_iota = "iota" in _node_text(node, lines)

    # Collect all const specs
    specs = []
    for child in node.children:
        if child.type == "const_spec":
            name_node = child.child_by_field_name("name")
            if name_node:
                specs.append(_node_text(name_node, lines))

    if not specs:
        return

    if has_iota and len(specs) > 1:
        # This is an enum-like const block — treat as a single enum symbol
        # Use the first constant's name as the enum group name
        sig = lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else ""
        symbols.append(Symbol(
            name=specs[0] + " (enum)",
            kind="enum",
            signature=sig,
            docstring=doc,
            body_preview=_body_preview(node, lines, max_lines=min(len(specs) + 2, 15)),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            fields=specs,
            is_exported=specs[0][0].isupper() if specs[0] else False,
            visibility="exported" if (specs[0] and specs[0][0].isupper()) else "unexported",
        ))
    else:
        # Individual constants
        for child in node.children:
            if child.type == "const_spec":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = _node_text(name_node, lines)
                    sig = lines[child.start_point[0]].strip() if child.start_point[0] < len(lines) else ""
                    # Get inline comment as doc for individual consts
                    inline_doc = doc or _get_inline_comment(child, lines)
                    symbols.append(Symbol(
                        name=name,
                        kind="constant",
                        signature=sig,
                        docstring=inline_doc,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        is_exported=name[0].isupper() if name else False,
                        visibility="exported" if (name and name[0].isupper()) else "unexported",
                    ))


# ─────────────────────────────────────────────────────────────────────────────
# GoDoc extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_godoc(node, lines: list[str]) -> str:
    """Extract GoDoc comment block preceding a declaration.

    Go convention: // comments immediately above a declaration, with no blank lines.
    Also handles /* */ block comments.
    """
    start_line = node.start_point[0]
    if start_line == 0:
        return ""

    doc_lines = []
    for i in range(start_line - 1, max(start_line - 40, -1), -1):
        if i < 0 or i >= len(lines):
            break
        line = lines[i].strip()

        if line.startswith("//"):
            # Strip // prefix
            comment_text = line[2:].strip()
            doc_lines.insert(0, comment_text)
        elif line.endswith("*/"):
            # Block comment — collect until /*
            block_lines = [line]
            for j in range(i - 1, max(i - 30, -1), -1):
                if j < 0 or j >= len(lines):
                    break
                bline = lines[j].strip()
                block_lines.insert(0, bline)
                if bline.startswith("/*"):
                    break
            raw = "\n".join(block_lines)
            raw = re.sub(r"^/\*\s*", "", raw)
            raw = re.sub(r"\s*\*/$", "", raw)
            doc_lines = [raw.strip()]
            break
        elif line == "":
            # Blank line breaks the GoDoc chain
            break
        else:
            break

    if not doc_lines:
        return ""

    return "\n".join(doc_lines)[:500]


def _get_inline_comment(node, lines: list[str]) -> str:
    """Extract inline comment on the same line as a node (// comment after code)."""
    end_line = node.end_point[0]
    if end_line >= len(lines):
        return ""
    line = lines[end_line]
    m = re.search(r"//\s*(.+)$", line)
    if m:
        return m.group(1).strip()[:200]
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Body preview
# ─────────────────────────────────────────────────────────────────────────────

def _body_preview(node, lines: list[str], max_lines: int = 5) -> str:
    """Extract the first few lines of a node's body."""
    start = node.start_point[0]
    end = min(node.end_point[0] + 1, start + max_lines)
    if start >= len(lines):
        return ""
    return "\n".join(lines[start:end])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Regex fallback
# ─────────────────────────────────────────────────────────────────────────────

def _regex_fallback(content: str):
    """Fallback parser when tree-sitter is not available."""
    symbols = []
    imports = []
    lines = content.splitlines()
    pending_doc = ""

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track GoDoc comments
        if stripped.startswith("//"):
            comment = stripped[2:].strip()
            if pending_doc:
                pending_doc += "\n" + comment
            else:
                pending_doc = comment
            continue

        if stripped.startswith("import "):
            imports.append(stripped[:200])
            pending_doc = ""
            continue

        # Function/method
        m = re.match(r"func\s+(?:\((\w+)\s+\*?(\w+)\)\s+)?(\w+)\s*\(", stripped)
        if m:
            receiver_type = m.group(2)
            name = m.group(3)
            kind = "method" if receiver_type else "function"
            symbols.append(Symbol(
                name=name,
                kind=kind,
                signature=stripped,
                docstring=pending_doc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                is_exported=name[0].isupper() if name else False,
                visibility="exported" if (name and name[0].isupper()) else "unexported",
            ))
            pending_doc = ""
            continue

        # Struct / interface
        m = re.match(r"type\s+(\w+)\s+(struct|interface)\s*\{?", stripped)
        if m:
            name = m.group(1)
            is_iface = m.group(2) == "interface"
            # Collect fields
            fields = []
            for j in range(i + 1, min(i + 50, len(lines))):
                fline = lines[j].strip()
                if fline == "}" or fline.startswith("}"):
                    break
                if fline and not fline.startswith("//"):
                    fields.append(fline)

            symbols.append(Symbol(
                name=name,
                kind="interface" if is_iface else "type",
                signature=stripped,
                docstring=pending_doc,
                body_preview="\n".join(lines[i:i + min(len(fields) + 2, 15)]),
                start_line=i + 1,
                is_exported=name[0].isupper() if name else False,
                visibility="exported" if (name and name[0].isupper()) else "unexported",
                fields=fields[:20],
            ))
            pending_doc = ""
            continue

        # Const block with iota
        if stripped.startswith("const (") or stripped == "const (":
            const_names = []
            for j in range(i + 1, min(i + 50, len(lines))):
                cline = lines[j].strip()
                if cline == ")" or cline.startswith(")"):
                    break
                cm = re.match(r"(\w+)", cline)
                if cm and not cline.startswith("//"):
                    const_names.append(cm.group(1))
            if const_names:
                has_iota = "iota" in content[content.find("const ("):content.find(")", content.find("const (")) + 1]
                if has_iota and len(const_names) > 1:
                    symbols.append(Symbol(
                        name=const_names[0] + " (enum)",
                        kind="enum",
                        signature=stripped,
                        docstring=pending_doc,
                        body_preview="\n".join(lines[i:i + min(len(const_names) + 2, 15)]),
                        start_line=i + 1,
                        fields=const_names,
                        is_exported=const_names[0][0].isupper() if const_names[0] else False,
                    ))
                else:
                    for cname in const_names:
                        symbols.append(Symbol(
                            name=cname, kind="constant", signature=cname,
                            docstring=pending_doc, start_line=i + 1,
                            is_exported=cname[0].isupper() if cname else False,
                        ))
            pending_doc = ""
            continue

        # Single const
        m = re.match(r"const\s+(\w+)\s+", stripped)
        if m:
            name = m.group(1)
            symbols.append(Symbol(
                name=name, kind="constant", signature=stripped,
                docstring=pending_doc, start_line=i + 1,
                is_exported=name[0].isupper() if name else False,
            ))
            pending_doc = ""
            continue

        # Reset pending doc on non-comment non-blank lines
        if stripped and not stripped.startswith("//"):
            pending_doc = ""

    return symbols, imports
