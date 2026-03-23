"""PHP / Laravel parser using tree-sitter.

Extracts: functions, classes, methods, traits, interfaces, enums (PHP 8.1),
constants, class properties — with PHPDoc comments, body previews,
PHP 8 attribute extraction, visibility modifiers, and Laravel route detection.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ParsedFile, Symbol

try:
    import tree_sitter_php as tsphp
    from tree_sitter import Language, Parser

    PHP_LANGUAGE = Language(tsphp.language_php())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_php(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        parser = Parser(PHP_LANGUAGE)
        tree = parser.parse(bytes(content, "utf8"))
        lines = content.splitlines()
        _walk(tree.root_node, lines, symbols, imports)
    else:
        symbols, imports = _regex_fallback(content)

    # Laravel-specific: detect routes from route files
    if _is_route_file(path, content):
        route_syms = _extract_laravel_routes(content)
        symbols = route_syms + symbols

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

    if t in ("namespace_use_declaration",):
        imports.append(_node_text(node, lines)[:200])
        return

    if t == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            name = _node_text(name_node, lines)
            doc = _get_phpdoc(node, lines)
            attrs = _get_php_attributes(node, lines)
            symbols.append(Symbol(
                name=name,
                kind="function",
                signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
                docstring=doc,
                body_preview=_body_preview(node, lines),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                decorators=attrs,
                is_exported=True,  # PHP functions are always accessible
            ))
        return

    if t in ("class_declaration", "trait_declaration", "interface_declaration"):
        _extract_class_like(node, t, lines, symbols)
        return

    # PHP 8.1 enums
    if t == "enum_declaration":
        _extract_enum(node, lines, symbols)
        return

    # Class constants defined outside class (rare but possible)
    if t == "const_declaration":
        _extract_const_declaration(node, lines, symbols, visibility="public")
        return

    for child in node.children:
        _walk(child, lines, symbols, imports)


# ─────────────────────────────────────────────────────────────────────────────
# Class / Trait / Interface extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_class_like(node, node_type: str, lines: list[str], symbols: list[Symbol]) -> None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return

    name = _node_text(name_node, lines)
    doc = _get_phpdoc(node, lines)
    attrs = _get_php_attributes(node, lines)

    if node_type == "class_declaration":
        kind = "class"
    elif node_type == "interface_declaration":
        kind = "interface"
    else:
        kind = "type"  # trait

    # Extract class-level fields summary (properties)
    class_fields = []
    for child in node.children:
        if child.type == "declaration_list":
            for member in child.children:
                if member.type == "property_declaration":
                    prop_line = lines[member.start_point[0]].strip() if member.start_point[0] < len(lines) else ""
                    if prop_line:
                        class_fields.append(prop_line.rstrip(";"))

    symbols.append(Symbol(
        name=name,
        kind=kind,
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines, max_lines=8),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=attrs,
        is_exported=True,
        fields=class_fields[:20],
    ))

    # Extract methods, constants, and properties within the class
    for child in node.children:
        if child.type == "declaration_list":
            for member in child.children:
                if member.type == "method_declaration":
                    _extract_method(member, lines, symbols)
                elif member.type == "const_declaration":
                    _extract_const_declaration(member, lines, symbols)


def _extract_method(node, lines: list[str], symbols: list[Symbol]) -> None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return

    name = _node_text(name_node, lines)
    doc = _get_phpdoc(node, lines)
    attrs = _get_php_attributes(node, lines)
    visibility = _get_visibility(node, lines)

    symbols.append(Symbol(
        name=name,
        kind="method",
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=attrs,
        visibility=visibility,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Enum extraction (PHP 8.1+)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_enum(node, lines: list[str], symbols: list[Symbol]) -> None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return

    name = _node_text(name_node, lines)
    doc = _get_phpdoc(node, lines)
    attrs = _get_php_attributes(node, lines)

    # Extract enum cases
    cases = []
    for child in node.children:
        if child.type in ("enum_declaration_list", "declaration_list"):
            for member in child.children:
                if member.type == "enum_case":
                    case_name_node = member.child_by_field_name("name")
                    if case_name_node:
                        case_line = lines[member.start_point[0]].strip() if member.start_point[0] < len(lines) else ""
                        cases.append(case_line.rstrip(";"))

    symbols.append(Symbol(
        name=name,
        kind="enum",
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines, max_lines=min(len(cases) + 3, 15)),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=attrs,
        is_exported=True,
        fields=cases[:30],
    ))

    # Also extract methods inside the enum
    for child in node.children:
        if child.type in ("enum_declaration_list", "declaration_list"):
            for member in child.children:
                if member.type == "method_declaration":
                    _extract_method(member, lines, symbols)


# ─────────────────────────────────────────────────────────────────────────────
# Constant extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_const_declaration(node, lines: list[str], symbols: list[Symbol],
                                visibility: str = "") -> None:
    """Extract class constants or global constants."""
    doc = _get_phpdoc(node, lines)
    if not visibility:
        visibility = _get_visibility(node, lines)

    for child in node.children:
        if child.type == "const_element":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, lines)
                sig = lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else ""
                symbols.append(Symbol(
                    name=name,
                    kind="constant",
                    signature=sig.rstrip(";"),
                    docstring=doc,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    visibility=visibility or "public",
                    is_exported=True,
                ))


# ─────────────────────────────────────────────────────────────────────────────
# PHPDoc extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_phpdoc(node, lines: list[str]) -> str:
    """Extract PHPDoc comment block (/** ... */) preceding a declaration."""
    start_line = node.start_point[0]
    if start_line == 0:
        return ""

    # Check previous sibling in AST
    prev = node.prev_named_sibling
    if prev and prev.type == "comment":
        text = _node_text(prev, lines)
        if text.strip().startswith("/**"):
            return _clean_phpdoc(text)

    # Scan lines above the node
    doc_lines = []
    in_block = False
    for i in range(start_line - 1, max(start_line - 40, -1), -1):
        if i < 0 or i >= len(lines):
            break
        line = lines[i].strip()

        if not in_block:
            if line.endswith("*/"):
                in_block = True
                doc_lines.insert(0, line)
            elif line.startswith("#["):
                # PHP attribute — skip over it
                continue
            elif line == "":
                continue
            else:
                break
        else:
            doc_lines.insert(0, line)
            if line.startswith("/**") or line.startswith("/*"):
                break

    if doc_lines:
        raw = "\n".join(doc_lines)
        if "/**" in raw:
            return _clean_phpdoc(raw)

    return ""


def _clean_phpdoc(raw: str) -> str:
    """Clean a PHPDoc block into readable text."""
    text = raw.strip()
    text = re.sub(r"^/\*\*\s*", "", text)
    text = re.sub(r"\s*\*/$", "", text)
    cleaned = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^\*\s?", "", line)
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    return result[:500]


# ─────────────────────────────────────────────────────────────────────────────
# PHP 8 Attribute extraction (#[Route('/path')], #[Middleware('auth')])
# ─────────────────────────────────────────────────────────────────────────────

def _get_php_attributes(node, lines: list[str]) -> list[str]:
    """Extract PHP 8 attributes (#[...]) preceding a declaration."""
    attrs = []
    start_line = node.start_point[0]

    # Check previous siblings for attribute nodes
    prev = node.prev_named_sibling
    while prev and prev.type == "attribute_list":
        text = _node_text(prev, lines).strip()
        attrs.insert(0, text)
        prev = prev.prev_named_sibling

    # Fallback: scan lines above for #[...] patterns
    if not attrs:
        for i in range(start_line - 1, max(start_line - 10, -1), -1):
            if i < 0 or i >= len(lines):
                break
            line = lines[i].strip()
            if line.startswith("#["):
                attrs.insert(0, line)
            elif line == "" or line.startswith("*") or line.startswith("/**") or line.endswith("*/"):
                continue
            else:
                break

    return attrs[:10]


# ─────────────────────────────────────────────────────────────────────────────
# Visibility extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_visibility(node, lines: list[str]) -> str:
    """Extract visibility modifier (public/protected/private) from a declaration."""
    for child in node.children:
        if child.type in ("visibility_modifier",):
            return _node_text(child, lines).strip()
    # Check the line text as fallback
    if node.start_point[0] < len(lines):
        line = lines[node.start_point[0]].strip()
        for vis in ("public", "protected", "private"):
            if vis in line.split()[:3]:
                return vis
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Laravel route detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_route_file(path: Path, content: str) -> bool:
    """Detect Laravel route files."""
    return "routes" in str(path).lower() and "Route::" in content


def _extract_laravel_routes(content: str) -> list[Symbol]:
    """Extract Laravel route definitions as symbols."""
    routes = []
    pattern = re.compile(
        r"Route::(get|post|put|patch|delete|any)\s*\(\s*['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    )
    lines = content.splitlines()
    for m in pattern.finditer(content):
        method, uri = m.group(1).upper(), m.group(2)
        line_num = content[:m.start()].count("\n") + 1

        # Try to extract middleware from chained ->middleware() call
        middleware = []
        region = content[m.start():m.start() + 500]
        mw_match = re.search(r"->middleware\s*\(\s*\[?([^\])\n]+)", region)
        if mw_match:
            middleware = [mw.strip().strip("'\"") for mw in mw_match.group(1).split(",")]

        routes.append(Symbol(
            name=f"{method} {uri}",
            kind="route",
            signature=m.group(0),
            start_line=line_num,
            decorators=middleware,  # Store middleware as "decorators" for display
        ))
    return routes


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
    pending_attrs = []
    in_class = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track PHPDoc blocks
        if stripped.startswith("/**"):
            doc_lines = [stripped]
            if "*/" not in stripped:
                for j in range(i + 1, min(i + 40, len(lines))):
                    doc_lines.append(lines[j].strip())
                    if "*/" in lines[j]:
                        break
            pending_doc = _clean_phpdoc("\n".join(doc_lines))
            continue

        # Track PHP 8 attributes
        if stripped.startswith("#["):
            pending_attrs.append(stripped)
            continue

        # Imports
        if stripped.startswith("use ") and not in_class:
            imports.append(stripped[:200])
            pending_doc = ""
            pending_attrs = []
            continue

        # Enum (PHP 8.1)
        m = re.match(r"enum\s+(\w+)", stripped)
        if m:
            name = m.group(1)
            # Collect cases
            cases = []
            for j in range(i + 1, min(i + 50, len(lines))):
                cline = lines[j].strip()
                if cline == "}" or cline.startswith("}"):
                    break
                cm = re.match(r"case\s+(\w+)", cline)
                if cm:
                    cases.append(cline.rstrip(";"))
            symbols.append(Symbol(
                name=name, kind="enum", signature=stripped,
                docstring=pending_doc,
                body_preview="\n".join(lines[i:i + min(len(cases) + 3, 15)]),
                start_line=i + 1,
                decorators=pending_attrs,
                fields=cases[:20],
                is_exported=True,
            ))
            pending_doc = ""
            pending_attrs = []
            continue

        # Class / trait / interface
        m = re.match(r"(?:abstract\s+)?(?:final\s+)?(class|trait|interface)\s+(\w+)", stripped)
        if m:
            kind_str = m.group(1)
            name = m.group(2)
            kind = "class" if kind_str == "class" else ("interface" if kind_str == "interface" else "type")
            symbols.append(Symbol(
                name=name, kind=kind, signature=stripped,
                docstring=pending_doc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                decorators=pending_attrs,
                is_exported=True,
            ))
            in_class = True
            pending_doc = ""
            pending_attrs = []
            continue

        # Method / function
        m = re.match(
            r"(?:(public|protected|private)\s+)?(?:static\s+)?function\s+(\w+)\s*\(",
            stripped,
        )
        if m:
            visibility = m.group(1) or ""
            name = m.group(2)
            kind = "method" if in_class else "function"
            symbols.append(Symbol(
                name=name, kind=kind, signature=stripped,
                docstring=pending_doc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                decorators=pending_attrs,
                visibility=visibility,
            ))
            pending_doc = ""
            pending_attrs = []
            continue

        # Class constants
        m = re.match(r"(?:public|protected|private)?\s*const\s+(\w+)\s*=", stripped)
        if m and in_class:
            name = m.group(1)
            symbols.append(Symbol(
                name=name, kind="constant", signature=stripped.rstrip(";"),
                docstring=pending_doc,
                start_line=i + 1,
                is_exported=True,
            ))
            pending_doc = ""
            pending_attrs = []
            continue

        # Reset on non-comment non-blank non-attr lines
        if stripped and not stripped.startswith(("*", "//", "#[")):
            pending_doc = ""
            pending_attrs = []

    return symbols, imports
