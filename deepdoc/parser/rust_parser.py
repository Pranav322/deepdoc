"""Rust parser using tree-sitter.

Extracts: functions, structs (with fields), enums (with variants), traits
(with method signatures), impl blocks (associated functions/methods), type
aliases, constants/statics — with doc comments, body previews, visibility
tracking, and attribute extraction (derive macros, framework attributes).

Covers Actix-web, Axum, Rocket patterns via attribute recording (route
detection comes later).
"""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedFile, Symbol

try:
    from tree_sitter import Language, Parser
    import tree_sitter_rust as tsrust

    RUST_LANGUAGE = Language(tsrust.language())
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False


def parse_rust(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE:
        parser = Parser(RUST_LANGUAGE)
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
    """Walk the tree, collecting preceding attribute items for each declaration."""
    _walk_with_attrs(node, lines, symbols, imports, [])


def _walk_with_attrs(node, lines: list[str], symbols: list[Symbol], imports: list[str], pending_attrs: list[str]) -> None:
    t = node.type

    if t == "use_declaration":
        imports.append(_node_text(node, lines)[:200])
        return

    if t == "attribute_item":
        pending_attrs.append(_node_text(node, lines)[:120])
        return

    if t == "function_item":
        _add_fn(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t == "struct_item":
        _add_struct(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t == "enum_item":
        _add_enum(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t == "trait_item":
        _add_trait(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t == "impl_item":
        _add_impl(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t == "type_item":
        _add_type(node, lines, symbols, pending_attrs)
        pending_attrs.clear()
        return

    if t in ("const_item", "static_item"):
        _add_const_static(node, lines, symbols, t, pending_attrs)
        pending_attrs.clear()
        return

    for child in node.children:
        _walk_with_attrs(child, lines, symbols, imports, pending_attrs)


# ---------------------------------------------------------------------------
# Extractors
# ---------------------------------------------------------------------------


def _add_fn(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    name = _named_child_text(node, "identifier", lines)
    if not name:
        return
    pub = _has_visibility(node)
    doc = _gather_doc_comments(node, lines)
    sig = _node_text(node, lines)[:300]
    body = _node_body_preview(node, lines, 8)
    symbols.append(Symbol(
        name=name, kind="function", signature=sig, docstring=doc,
        body_preview=body, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility="public" if pub else "", is_exported=pub,
    ))


def _add_struct(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    name = _named_child_text(node, "type_identifier", lines)
    if not name:
        return
    pub = _has_visibility(node)
    doc = _gather_doc_comments(node, lines)
    sig = _node_text(node, lines)[:300]
    fields = _extract_fields(node, lines)
    symbols.append(Symbol(
        name=name, kind="class", signature=sig, docstring=doc,
        fields=fields, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility="public" if pub else "", is_exported=pub,
    ))


def _add_enum(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    name = _named_child_text(node, "type_identifier", lines)
    if not name:
        return
    pub = _has_visibility(node)
    doc = _gather_doc_comments(node, lines)
    sig = _node_text(node, lines)[:300]
    variants = _extract_enum_variants(node, lines)
    symbols.append(Symbol(
        name=name, kind="enum", signature=sig, docstring=doc,
        fields=variants, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility="public" if pub else "", is_exported=pub,
    ))


def _add_trait(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    name = _named_child_text(node, "type_identifier", lines)
    if not name:
        return
    pub = _has_visibility(node)
    doc = _gather_doc_comments(node, lines)
    sig = _node_text(node, lines)[:300]
    # Extract method signatures from trait body
    method_sigs = []
    for child in node.children:
        if child.type in ("declaration_list",):
            for item in child.children:
                if item.type == "function_item":
                    mname = _named_child_text(item, "name", lines) or "?"
                    msig = _node_text(item, lines)[:200]
                    method_sigs.append(f"fn {mname}{msig.split('fn ')[-1] if 'fn ' in msig else ''}"[:120])
    symbols.append(Symbol(
        name=name, kind="interface", signature=sig, docstring=doc,
        fields=method_sigs, start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1, decorators=list(attrs),
        visibility="public" if pub else "", is_exported=pub,
    ))


def _add_impl(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    """Extract the impl target name and any associated functions."""
    type_name = _impl_target_name(node, lines) or ""
    for child in node.children:
        if child.type == "function_item":
            name = _named_child_text(child, "identifier", lines)
            if not name:
                continue
            fn_attrs = list(attrs)  # inherit from impl block attrs
            sig = _node_text(child, lines)[:300]
            body = _node_body_preview(child, lines, 8)
            doc = _gather_doc_comments(child, lines)
            pub = _has_visibility(child)
            symbols.append(Symbol(
                name=name, kind="method", signature=sig, docstring=doc,
                body_preview=body, start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1, decorators=fn_attrs,
                visibility="public" if pub else "", is_exported=pub,
            ))


def _add_type(node, lines: list[str], symbols: list[Symbol], attrs: list[str]) -> None:
    name = _named_child_text(node, "type_identifier", lines)
    if not name:
        return
    sig = _node_text(node, lines)[:300]
    symbols.append(Symbol(
        name=name, kind="type", signature=sig,
        start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
        is_exported=_has_visibility(node),
    ))


def _add_const_static(node, lines: list[str], symbols: list[Symbol], kind: str, attrs: list[str]) -> None:
    name = _named_child_text(node, "name", lines)
    if not name:
        return
    sig = _node_text(node, lines)[:200]
    symbols.append(Symbol(
        name=name, kind="constant", signature=sig,
        start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
        is_exported=_has_visibility(node),
    ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(node, lines: list[str]) -> str:
    ls, le = node.start_point[0], node.end_point[0]
    if ls == le:
        return lines[ls][node.start_point[1]:node.end_point[1]] if ls < len(lines) else ""
    return "\n".join(lines[ls:le + 1])


def _node_body_preview(node, lines: list[str], limit: int = 8) -> str:
    body = _find_block_child(node)
    if not body:
        return ""
    start = body.start_point[0]
    end = min(body.end_point[0], start + limit)
    return "\n".join(lines[start:end + 1])


def _named_child_text(node, child_type: str, lines: list[str]) -> str:
    for child in node.children:
        if child.type == child_type:
            return _node_text(child, lines)
    return ""


def _find_block_child(node):
    for child in node.children:
        if child.type == "block":
            return child
    return None


def _has_visibility(node) -> bool:
    for child in node.children:
        if child.type == "visibility_modifier":
            return True
    return False


def _gather_attributes(node) -> list[str]:
    """Extract #[...] attributes from preceding siblings."""
    attrs = []
    for child in node.children:
        if child.type in ("attribute_item", "inner_attribute_item"):
            text = child.text.decode("utf-8") if hasattr(child, "text") else ""
            if text.startswith("#"):
                attrs.append(text.strip())
    return attrs


def _gather_doc_comments(node, lines: list[str]) -> str:
    """Collect /// and //! doc comments from the node's leading comments."""
    sl = node.start_point[0]
    if sl == 0:
        return ""
    docs = []
    for line_idx in range(sl - 1, max(sl - 15, -1), -1):
        line = lines[line_idx].strip()
        if line.startswith("///") or line.startswith("//!"):
            docs.append(line)
        elif docs:
            break
    return "\n".join(reversed(docs))


def _extract_fields(node, lines: list[str]) -> list[str]:
    """Extract struct field names from field_declaration_list."""
    fields = []
    for child in node.children:
        if child.type == "field_declaration_list":
            for fc in child.children:
                if fc.type == "field_declaration":
                    name = _named_child_text(fc, "identifier", lines)
                    if name:
                        fields.append(name)
    return fields


def _extract_enum_variants(node, lines: list[str]) -> list[str]:
    """Extract enum variant names."""
    variants = []
    for child in node.children:
        if child.type == "enum_variant_list":
            for vc in child.children:
                if vc.type == "enum_variant":
                    name = _named_child_text(vc, "identifier", lines) or _node_text(vc, lines)[:40]
                    if name:
                        variants.append(name)
    return variants


def _impl_target_name(node, lines: list[str]) -> str:
    """Extract the type being implemented (e.g., 'MyStruct' or 'MyTrait for MyStruct')."""
    parts = []
    for child in node.children:
        if child.type in ("type_identifier", "scoped_type_identifier"):
            parts.append(_node_text(child, lines))
    return " for ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Regex fallback
# ---------------------------------------------------------------------------


def _regex_fallback(content: str) -> tuple[list[Symbol], list[str]]:
    symbols: list[Symbol] = []
    imports: list[str] = []

    for match in re.finditer(r"^\s*pub\s+fn\s+(\w+)", content, re.MULTILINE):
        symbols.append(Symbol(name=match.group(1), kind="function", signature=match.group(0).strip(), is_exported=True))
    for match in re.finditer(r"^pub\s+struct\s+(\w+)", content, re.MULTILINE):
        symbols.append(Symbol(name=match.group(1), kind="class", signature=match.group(0).strip(), is_exported=True))
    for match in re.finditer(r"^pub\s+enum\s+(\w+)", content, re.MULTILINE):
        symbols.append(Symbol(name=match.group(1), kind="enum", signature=match.group(0).strip(), is_exported=True))
    for match in re.finditer(r"^pub\s+trait\s+(\w+)", content, re.MULTILINE):
        symbols.append(Symbol(name=match.group(1), kind="interface", signature=match.group(0).strip(), is_exported=True))
    for match in re.finditer(r"^use\s+(.+);", content, re.MULTILINE):
        imports.append(match.group(0).strip())

    return symbols, imports


__all__ = ["parse_rust"]