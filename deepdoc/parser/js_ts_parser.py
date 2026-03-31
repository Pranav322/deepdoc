"""JavaScript / TypeScript parser using tree-sitter.

Extracts: functions, arrow functions, classes, methods, interfaces, type aliases,
enums, constants, React components, custom hooks — with JSDoc/TSDoc, body previews,
export tracking, and decorator extraction.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ParsedFile, Symbol

try:
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Parser

    JS_LANGUAGE = Language(tsjs.language())
    TS_LANGUAGE = Language(tsts.language_typescript())
    TSX_LANGUAGE = Language(tsts.language_tsx())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_js_ts(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        if path.suffix in (".tsx",):
            lang = TSX_LANGUAGE
        elif language == "typescript":
            lang = TS_LANGUAGE
        else:
            lang = JS_LANGUAGE

        parser = Parser(lang)
        tree = parser.parse(bytes(content, "utf8"))
        lines = content.splitlines()
        _walk(tree.root_node, lines, symbols, imports, exported=False)
    else:
        symbols, imports = _regex_fallback(content, language)

    # Post-process: detect React components and hooks by naming convention
    _tag_react_symbols(symbols, content)

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

def _walk(node, lines: list[str], symbols: list[Symbol], imports: list[str],
          exported: bool = False) -> None:
    t = node.type

    # Imports
    if t in ("import_declaration", "import_statement"):
        imports.append(_node_text(node, lines)[:200])
        return

    # Function declarations
    if t == "function_declaration":
        sym = _fn_symbol(node, lines, "function", exported=exported)
        if sym:
            symbols.append(sym)
        return

    # Arrow functions / const foo = () => {}
    if t in ("variable_declaration", "lexical_declaration"):
        for child in node.children:
            if child.type == "variable_declarator":
                _handle_declarator(child, node, lines, symbols, exported=exported)
        return

    # Class declarations
    if t == "class_declaration":
        sym = _class_symbol(node, lines, exported=exported)
        if sym:
            symbols.append(sym)
        # Extract methods
        for child in node.children:
            if child.type == "class_body":
                for member in child.children:
                    if member.type == "method_definition":
                        msym = _method_symbol(member, lines)
                        if msym:
                            symbols.append(msym)
                    elif member.type in ("public_field_definition", "property_definition",
                                         "field_definition"):
                        # Class fields/properties
                        pass
        return

    # TypeScript interfaces
    if t == "interface_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            fields = _extract_interface_fields(node, lines)
            symbols.append(Symbol(
                name=_node_text(name_node, lines),
                kind="interface",
                signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
                docstring=doc,
                body_preview=_body_preview(node, lines),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
                fields=fields,
            ))
        return

    # TypeScript type aliases
    if t == "type_alias_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            symbols.append(Symbol(
                name=_node_text(name_node, lines),
                kind="type",
                signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
                docstring=doc,
                body_preview=_body_preview(node, lines),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
            ))
        return

    # TypeScript enums
    if t == "enum_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            members = _extract_enum_members(node, lines)
            symbols.append(Symbol(
                name=_node_text(name_node, lines),
                kind="enum",
                signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
                docstring=doc,
                body_preview=_body_preview(node, lines, max_lines=10),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
                fields=members,
            ))
        return

    # Export statements — set exported flag and recurse
    if t in ("export_statement", "export_named_declaration"):
        for child in node.children:
            _walk(child, lines, symbols, imports, exported=True)
        return

    # Decorators on classes/methods (NestJS, Angular, etc.)
    if t == "decorator":
        # Decorators are siblings; they'll be picked up by the class/method handler
        return

    for child in node.children:
        _walk(child, lines, symbols, imports, exported=exported)


# ─────────────────────────────────────────────────────────────────────────────
# Symbol extractors
# ─────────────────────────────────────────────────────────────────────────────

def _fn_symbol(node, lines, kind="function", exported=False) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    doc = _get_jsdoc(node, lines)
    decorators = _get_decorators(node, lines)
    return Symbol(
        name=_node_text(name_node, lines),
        kind=kind,
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=decorators,
        is_exported=exported,
    )


def _handle_declarator(node, parent_node, lines, symbols, exported=False):
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if not name_node:
        return

    name = _node_text(name_node, lines)

    if value_node and value_node.type in ("arrow_function", "function", "function_expression"):
        doc = _get_jsdoc(parent_node, lines)
        symbols.append(Symbol(
            name=name,
            kind="function",
            signature=lines[parent_node.start_point[0]].strip() if parent_node.start_point[0] < len(lines) else "",
            docstring=doc,
            body_preview=_body_preview(value_node, lines),
            start_line=parent_node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=exported,
        ))
    elif value_node and value_node.type in ("call_expression",):
        # e.g. const router = express.Router() — detect as constant
        doc = _get_jsdoc(parent_node, lines)
        sig = lines[parent_node.start_point[0]].strip() if parent_node.start_point[0] < len(lines) else ""
        # Only record if it looks meaningful (not just a temp variable)
        if re.match(r"(?:export\s+)?const\s+", sig):
            symbols.append(Symbol(
                name=name,
                kind="constant",
                signature=sig,
                docstring=doc,
                start_line=parent_node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
            ))
    elif value_node and value_node.type in ("string", "number", "true", "false",
                                             "template_string", "object", "array",
                                             "new_expression"):
        # const FOO = "bar" or const config = { ... }
        sig = lines[parent_node.start_point[0]].strip() if parent_node.start_point[0] < len(lines) else ""
        if re.match(r"(?:export\s+)?const\s+[A-Z_]", sig) or name.isupper():
            doc = _get_jsdoc(parent_node, lines)
            symbols.append(Symbol(
                name=name,
                kind="constant",
                signature=sig,
                docstring=doc,
                body_preview=_body_preview(parent_node, lines, max_lines=3),
                start_line=parent_node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
            ))


def _class_symbol(node, lines, exported=False) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    doc = _get_jsdoc(node, lines)
    decorators = _get_decorators(node, lines)
    return Symbol(
        name=_node_text(name_node, lines),
        kind="class",
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=decorators,
        is_exported=exported,
    )


def _method_symbol(node, lines) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    doc = _get_jsdoc(node, lines)
    decorators = _get_decorators(node, lines)

    # Determine visibility from modifiers
    visibility = ""
    for child in node.children:
        if child.type in ("accessibility_modifier", "readonly"):
            visibility = _node_text(child, lines)
            break

    return Symbol(
        name=_node_text(name_node, lines),
        kind="method",
        signature=lines[node.start_point[0]].strip() if node.start_point[0] < len(lines) else "",
        docstring=doc,
        body_preview=_body_preview(node, lines),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        decorators=decorators,
        visibility=visibility,
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSDoc / TSDoc extraction
# ─────────────────────────────────────────────────────────────────────────────

def _get_jsdoc(node, lines: list[str]) -> str:
    """Extract JSDoc/TSDoc comment immediately preceding a node.

    Looks for /** ... */ style comments in the sibling nodes before this one,
    or in the lines immediately above the node start.
    """
    # Strategy 1: check previous sibling in the AST
    prev = node.prev_named_sibling
    if prev and prev.type == "comment":
        text = _node_text(prev, lines)
        if text.startswith("/**"):
            return _clean_jsdoc(text)

    # Strategy 2: scan lines above the node for /** ... */ blocks
    start_line = node.start_point[0]
    if start_line == 0:
        return ""

    # Walk backwards from the line above the node
    doc_lines = []
    in_block = False
    for i in range(start_line - 1, max(start_line - 30, -1), -1):
        if i < 0 or i >= len(lines):
            break
        line = lines[i].strip()

        if not in_block:
            if line.endswith("*/"):
                in_block = True
                doc_lines.insert(0, line)
            elif line.startswith("//"):
                # Single-line comment directly above
                doc_lines.insert(0, line.lstrip("/ "))
            elif line == "":
                # Allow one blank line between comment and declaration
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
            return _clean_jsdoc(raw)
        return " ".join(doc_lines)[:300]

    return ""


def _clean_jsdoc(raw: str) -> str:
    """Clean a JSDoc block into readable text."""
    # Remove /** and */ markers
    text = raw.strip()
    text = re.sub(r"^/\*\*\s*", "", text)
    text = re.sub(r"\s*\*/$", "", text)
    # Remove leading * from each line
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^\*\s?", "", line)
        cleaned_lines.append(line)
    result = "\n".join(cleaned_lines).strip()
    return result[:500]


# ─────────────────────────────────────────────────────────────────────────────
# Decorator extraction (NestJS, Angular, etc.)
# ─────────────────────────────────────────────────────────────────────────────

def _get_decorators(node, lines: list[str]) -> list[str]:
    """Extract @Decorator annotations from preceding siblings or lines."""
    decorators = []

    # Check previous siblings for decorator nodes
    prev = node.prev_named_sibling
    while prev and prev.type == "decorator":
        text = _node_text(prev, lines).strip()
        decorators.insert(0, text)
        prev = prev.prev_named_sibling

    # Fallback: scan lines above the node for @Something patterns
    if not decorators:
        start_line = node.start_point[0]
        for i in range(start_line - 1, max(start_line - 10, -1), -1):
            if i < 0 or i >= len(lines):
                break
            line = lines[i].strip()
            if line.startswith("@"):
                decorators.insert(0, line)
            elif line == "" or line.startswith("//") or line.startswith("*"):
                continue
            else:
                break

    return decorators[:10]


# ─────────────────────────────────────────────────────────────────────────────
# Enum member extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_enum_members(node, lines: list[str]) -> list[str]:
    """Extract enum member names from a TS enum declaration."""
    members = []
    for child in node.children:
        if child.type == "enum_body":
            for member in child.children:
                if member.type in ("enum_member", "property_identifier"):
                    name_node = member.child_by_field_name("name")
                    if name_node:
                        members.append(_node_text(name_node, lines))
                    elif member.type == "property_identifier":
                        members.append(_node_text(member, lines))
    return members[:30]


# ─────────────────────────────────────────────────────────────────────────────
# Interface field extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_interface_fields(node, lines: list[str]) -> list[str]:
    """Extract field names from a TS interface body."""
    fields = []
    for child in node.children:
        if child.type in ("interface_body", "object_type"):
            for member in child.children:
                if member.type in ("property_signature", "method_signature"):
                    name_node = member.child_by_field_name("name")
                    if name_node:
                        # Include the full signature line for context
                        sig = lines[member.start_point[0]].strip() if member.start_point[0] < len(lines) else ""
                        fields.append(sig.rstrip(";,").strip())
    return fields[:30]


# ─────────────────────────────────────────────────────────────────────────────
# React component & hook detection
# ─────────────────────────────────────────────────────────────────────────────

def _tag_react_symbols(symbols: list[Symbol], content: str) -> None:
    """Post-process symbols to detect React components and hooks."""
    has_react = "react" in content.lower() or "from 'react'" in content or 'from "react"' in content

    for sym in symbols:
        if sym.kind != "function":
            continue

        name = sym.name

        # Custom hooks: useXxx
        if name.startswith("use") and len(name) > 3 and name[3].isupper():
            sym.kind = "hook"
            continue

        # React components: PascalCase functions that likely return JSX
        if has_react and name[0].isupper() and not name.isupper():
            # Check body preview or signature for JSX indicators
            body = (sym.body_preview or "") + (sym.signature or "")
            if any(indicator in body for indicator in
                   ("<", "jsx", "tsx", "React.FC", "React.Component",
                    "return (", "useState", "useEffect", "props")):
                sym.kind = "component"
                # Try to extract props from signature
                props = _extract_react_props(sym.signature, content)
                if props:
                    sym.props = props
            elif any(indicator in content for indicator in ("React.FC", "JSX.Element", "<div", "<>")):
                # If the file is clearly React, PascalCase = component
                sym.kind = "component"


def _extract_react_props(signature: str, content: str) -> list[str]:
    """Try to extract React component props from signature or nearby type."""
    props = []
    # Pattern: function Foo({ prop1, prop2 }: Props)
    m = re.search(r"\{\s*([^}]+)\s*\}", signature)
    if m:
        parts = m.group(1).split(",")
        for p in parts:
            p = p.strip().split("=")[0].strip().split(":")[0].strip()
            if p and not p.startswith("..."):
                props.append(p)
    return props[:20]


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

def _regex_fallback(content: str, language: str):
    """Fallback parser when tree-sitter is not available."""
    symbols = []
    imports = []
    lines = content.splitlines()
    pending_jsdoc = ""

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track JSDoc blocks
        if stripped.startswith("/**"):
            # Collect until */
            doc_lines = [stripped]
            if "*/" not in stripped:
                for j in range(i + 1, min(i + 30, len(lines))):
                    doc_lines.append(lines[j].strip())
                    if "*/" in lines[j]:
                        break
            pending_jsdoc = _clean_jsdoc("\n".join(doc_lines))
            continue

        # Imports
        if stripped.startswith(("import ", "require(")):
            imports.append(stripped[:200])
            continue

        # Exported function
        is_exported = stripped.startswith("export ")
        clean = re.sub(r"^export\s+(default\s+)?", "", stripped)

        # Function declaration
        m = re.match(r"(?:async\s+)?function\s+(\w+)\s*\(", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="function", signature=stripped,
                docstring=pending_jsdoc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Class declaration
        m = re.match(r"class\s+(\w+)", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="class", signature=stripped,
                docstring=pending_jsdoc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Arrow function / const assignment
        m = re.match(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="function", signature=stripped,
                docstring=pending_jsdoc,
                body_preview="\n".join(lines[i:i + 5]),
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Enum
        m = re.match(r"(?:const\s+)?enum\s+(\w+)", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="enum", signature=stripped,
                docstring=pending_jsdoc,
                body_preview="\n".join(lines[i:i + 8]),
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Interface
        m = re.match(r"interface\s+(\w+)", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="interface", signature=stripped,
                docstring=pending_jsdoc,
                body_preview="\n".join(lines[i:i + 8]),
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Type alias
        m = re.match(r"type\s+(\w+)", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="type", signature=stripped,
                docstring=pending_jsdoc,
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # UPPER_CASE constants
        m = re.match(r"(?:const|let|var)\s+([A-Z][A-Z_0-9]+)\s*=", clean)
        if m:
            symbols.append(Symbol(
                name=m.group(1), kind="constant", signature=stripped,
                docstring=pending_jsdoc,
                start_line=i + 1,
                is_exported=is_exported,
            ))
            pending_jsdoc = ""
            continue

        # Reset pending jsdoc if we hit a non-comment, non-blank line
        if stripped and not stripped.startswith(("*", "//")):
            pending_jsdoc = ""

    return symbols, imports
