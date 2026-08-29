"""Java parser using tree-sitter.

Extracts: classes, methods, constructors, interfaces, enums, annotations,
imports — with Javadoc comments, body previews, visibility modifiers, and
annotation recording (Spring, JAX-RS, etc.).

Route detection for Spring MVC / JAX-RS comes later.
"""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedFile, Symbol

try:
    from tree_sitter import Language, Parser
    import tree_sitter_java as tsjava

    JAVA_LANGUAGE = Language(tsjava.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_java(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        parser = Parser(JAVA_LANGUAGE)
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
        raw_content=content[:12000],
    )


# ---------------------------------------------------------------------------
# Tree-sitter walk
# ---------------------------------------------------------------------------


def _walk(node, lines: list[str], symbols: list[Symbol], imports: list[str]) -> None:
    t = node.type

    if t == "import_declaration":
        imports.append(_node_text(node, lines)[:200])
        return

    if t == "class_declaration":
        _add_class(node, lines, symbols)
        return

    if t == "interface_declaration":
        _add_interface(node, lines, symbols)
        return

    if t == "enum_declaration":
        _add_enum(node, lines, symbols)
        return

    # Recurse into children for methods/constructors at all levels
    for child in node.children:
        _walk(child, lines, symbols, imports)


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _add_class(node, lines: list[str], symbols: list[Symbol]) -> None:
    name = _named_child_text(node, "identifier", lines)
    if not name:
        return
    attrs = _gather_annotations(node)
    vis = _visibility(node)
    doc = _gather_javadoc(node, lines)
    sig = _node_text(node, lines)[:300]
    fields = _extract_class_fields(node, lines)
    symbols.append(Symbol(
        name=name, kind="class", signature=sig, docstring=doc,
        fields=fields, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility=vis, is_exported=(vis == "public"),
    ))
    # Extract methods and constructors inside the class body
    body = _find_class_body(node)
    if body:
        _extract_members(body, attrs, lines, symbols)


def _add_interface(node, lines: list[str], symbols: list[Symbol]) -> None:
    name = _named_child_text(node, "identifier", lines)
    if not name:
        return
    attrs = _gather_annotations(node)
    vis = _visibility(node)
    doc = _gather_javadoc(node, lines)
    sig = _node_text(node, lines)[:300]
    # Extract method signatures from interface body
    method_sigs = []
    body = _find_class_body(node)
    if body:
        for child in body.children:
            if child.type in ("method_declaration",):
                mname = _named_child_text(child, "identifier", lines) or "?"
                msig = _node_text(child, lines)[:200]
                method_sigs.append(f"{mname}{msig.split(mname)[-1] if mname in msig else ''}"[:120])
    symbols.append(Symbol(
        name=name, kind="interface", signature=sig, docstring=doc,
        fields=method_sigs, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility=vis, is_exported=(vis == "public"),
    ))


def _add_enum(node, lines: list[str], symbols: list[Symbol]) -> None:
    name = _named_child_text(node, "identifier", lines)
    if not name:
        return
    attrs = _gather_annotations(node)
    vis = _visibility(node)
    doc = _gather_javadoc(node, lines)
    sig = _node_text(node, lines)[:300]
    constants = []
    body = _find_enum_body(node)
    if body:
        for child in body.children:
            if child.type == "enum_constant":
                cname = _named_child_text(child, "identifier", lines)
                if cname:
                    constants.append(cname)
    symbols.append(Symbol(
        name=name, kind="enum", signature=sig, docstring=doc,
        fields=constants, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility=vis, is_exported=(vis == "public"),
    ))


def _extract_members(body_node, class_annotations: list[str], lines: list[str], symbols: list[Symbol]) -> None:
    """Extract methods and constructors from a class/interface body."""
    for child in body_node.children:
        if child.type == "method_declaration":
            name = _named_child_text(child, "identifier", lines)
            if not name:
                continue
            attrs = _gather_annotations(child)
            vis = _visibility(child)
            doc = _gather_javadoc(child, lines)
            sig = _node_text(child, lines)[:300]
            body_txt = _node_body_preview(child, lines, 8)
            symbols.append(Symbol(
                name=name, kind="method", signature=sig, docstring=doc,
                body_preview=body_txt, start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1, decorators=list(attrs),
                visibility=vis, is_exported=(vis == "public"),
            ))
        elif child.type == "constructor_declaration":
            name = _named_child_text(child, "identifier", lines)
            if not name:
                name = _node_text(child, lines).split("(")[0].strip().split()[-1] if child.children else ""
            if not name:
                continue
            attrs = _gather_annotations(child)
            vis = _visibility(child)
            sig = _node_text(child, lines)[:300]
            symbols.append(Symbol(
                name=name, kind="method", signature=sig,
                start_line=child.start_point[0] + 1, end_line=child.end_point[0] + 1,
                decorators=list(attrs), visibility=vis, is_exported=(vis == "public"),
            ))


# ---------------------------------------------------------------------------
# Class fields (property declarations at class level)
# ---------------------------------------------------------------------------


def _extract_class_fields(node, lines: list[str]) -> list[str]:
    body = _find_class_body(node)
    if not body:
        return []
    fields = []
    for child in body.children:
        if child.type == "field_declaration":
            decls = _find_child_by_type(child, "variable_declarator")
            if decls:
                for d in decls:
                    name = _named_child_text(d, "identifier", lines)
                    if name:
                        fields.append(name)
    return fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text_raw(node) -> str:
    """Get raw text from any tree-sitter node."""
    return node.text.decode("utf-8") if hasattr(node, "text") else ""


def _node_text(node, lines: list[str]) -> str:
    ls, le = node.start_point[0], node.end_point[0]
    if ls == le:
        return lines[ls][node.start_point[1]:node.end_point[1]] if ls < len(lines) else ""
    return "\n".join(lines[ls:le + 1])


def _node_body_preview(node, lines: list[str], limit: int = 8) -> str:
    body = _find_child_by_type(node, "block")
    if not body:
        return ""
    b = body[0]
    start = b.start_point[0]
    end = min(b.end_point[0], start + limit)
    return "\n".join(lines[start:end + 1])


def _named_child_text(node, child_type: str, lines: list[str]) -> str:
    for child in node.children:
        if child.type == child_type:
            return _node_text(child, lines)
    return ""


def _find_child_by_type(node, child_type: str):
    return [c for c in node.children if c.type == child_type]


def _find_class_body(node):
    for child in node.children:
        if child.type in ("class_body", "interface_body", "enum_body"):
            return child
    return None


def _find_enum_body(node):
    for child in node.children:
        if child.type == "enum_body":
            return child
    return None


def _visibility(node) -> str:
    for child in node.children:
        if child.type == "modifiers":
            for mc in child.children:
                if mc.type in ("public", "private", "protected"):
                    return _node_text_raw(mc)
    return "package"


def _gather_annotations(node) -> list[str]:
    """Extract @Annotation names from modifiers list."""
    annotations = []
    for child in node.children:
        if child.type == "modifiers":
            for mc in child.children:
                if mc.type in ("marker_annotation", "annotation"):
                    text = _node_text_raw(mc)[:120]
                    if text.startswith("@"):
                        annotations.append(text.strip())
    return annotations


def _gather_javadoc(node, lines: list[str]) -> str:
    """Collect /** ... */ Javadoc from lines before the node."""
    sl = node.start_point[0]
    if sl == 0:
        return ""
    for line_idx in range(sl - 1, max(sl - 15, -1), -1):
        line = lines[line_idx].strip()
        if "*/" in line or line.startswith("*"):
            # Walk backward to find /** opener
            start_idx = line_idx
            for j in range(line_idx, max(line_idx - 10, -1), -1):
                if "/**" in lines[j]:
                    return "\n".join(lines[j:start_idx + 1])
        elif line:
            break
    return ""


# ---------------------------------------------------------------------------
# Regex fallback
# ---------------------------------------------------------------------------


def _regex_fallback(content: str) -> tuple[list[Symbol], list[str]]:
    symbols: list[Symbol] = []
    imports: list[str] = []

    for match in re.finditer(r"(public|private|protected)?\s*(class|interface|enum)\s+(\w+)", content):
        vis = match.group(1) or "package"
        kind = match.group(2)
        if kind == "interface":
            symbols.append(Symbol(name=match.group(3), kind="interface", signature=match.group(0).strip(), visibility=vis))
        elif kind == "enum":
            symbols.append(Symbol(name=match.group(3), kind="enum", signature=match.group(0).strip(), visibility=vis))
        else:
            symbols.append(Symbol(name=match.group(3), kind="class", signature=match.group(0).strip(), visibility=vis))

    for match in re.finditer(r"(public|private|protected)\s+.*?\s+(\w+)\s*\([^)]*\)", content):
        symbols.append(Symbol(name=match.group(2), kind="method", signature=match.group(0).strip(), visibility=match.group(1)))

    for match in re.finditer(r"import\s+(.+);", content):
        imports.append(match.group(0).strip())

    return symbols, imports


__all__ = ["parse_java"]