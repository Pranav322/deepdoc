"""JavaScript / TypeScript parser using tree-sitter.

Extracts: functions, arrow functions, classes, methods, interfaces, type aliases,
enums, constants, React components, custom hooks — with JSDoc/TSDoc, body previews,
export tracking, and decorator extraction.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple
import re

from .base import ParsedFile, Symbol

try:
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts

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
        parser = Parser(_grammar_for(path, language))
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
        raw_content=content[:12000],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Library symbol binding
# ─────────────────────────────────────────────────────────────────────────────


class JsBoundCall(NamedTuple):
    """A call whose callee provably resolves to one of the requested modules.

    `module` is the matched module specifier and `symbol` the constructed member
    for `new Imported(...)`, otherwise the called method name. `receiver` is the
    *role* of the value being called on - which API of the module produced it -
    because a module is not one capability: BullMQ's `Queue` and `Worker` are
    different objects, and an AMQP connection is not the channel it opens. It is
    `""` for a call on the module's own export, an import member name for a call
    on an imported symbol, and otherwise a chain like `connect().createChannel()`
    naming the calls that produced the receiver. `args` holds one `(kind, value)`
    pair per argument in source order, where kind is "str" for a quoted literal,
    "name" for an identifier or a named function, and "" for anything with no
    usable name.
    """

    module: str
    symbol: str
    is_new: bool
    receiver: str
    args: tuple[tuple[str, str], ...]


# What a default import, a namespace import and `require()` all resolve to: the
# module export itself, so `amqplib.connect` and `amqp.connect` are one role.
_MODULE_EXPORT = "default"


def _produced_role(call: JsBoundCall) -> str:
    """Role of the value `call` returns, chained onto its receiver's role."""
    if call.receiver and call.receiver.endswith("()"):
        return f"{call.receiver}.{call.symbol}()"
    return f"{call.symbol}()"


def js_bound_calls(
    path: Path, content: str, language: str, modules: frozenset[str]
) -> tuple[JsBoundCall, ...] | None:
    """Executable calls bound to `modules`, resolved inside this file only.

    Returns None when tree-sitter cannot supply syntax nodes, so callers fail
    closed instead of matching raw text: library code quoted inside a template
    literal or a comment never runs and must not read as evidence. A call is
    reported only when its callee or receiver traces back, through local
    declarations, to a real import/require of one of `modules` - importing a
    library does not vouch for every other call in the same file - and each call
    carries the role of the value it was made on, so callers can require the API
    a library really documents instead of trusting the module name alone.
    """
    if not _TS_AVAILABLE:
        return None
    try:
        tree = Parser(_grammar_for(path, language)).parse(bytes(content, "utf8"))
    except Exception:
        return None
    root = tree.root_node
    if root.type == "ERROR":
        return None
    return _Binder(modules).run(root)


def _grammar_for(path: Path, language: str):
    if path.suffix == ".tsx":
        return TSX_LANGUAGE
    return TS_LANGUAGE if language == "typescript" else JS_LANGUAGE


# Node types that open a new name scope. A declaration governs the nearest
# enclosing one; resolving to a wider scope than the language would only make
# the shadow check below reject more, never less.
_SCOPE_TYPES = frozenset(
    {
        "program",
        "statement_block",
        "class_body",
        "class",
        "class_declaration",
        "catch_clause",
        "arrow_function",
        "function",
        "function_declaration",
        "function_expression",
        "generator_function",
        "generator_function_declaration",
        "method_definition",
        "for_statement",
        "for_in_statement",
        "switch_body",
    }
)
# Wrappers that pass a value through unchanged: `await x`, `(x)`, `x!`, `x as T`.
_VALUE_WRAPPERS = frozenset(
    {
        "await_expression",
        "parenthesized_expression",
        "non_null_expression",
        "as_expression",
        "satisfies_expression",
        "type_assertion",
    }
)
# Name-introducing node types, mapped to the field holding the bound pattern.
_DECL_FIELDS = {
    "variable_declarator": "name",
    "function_declaration": "name",
    "function_expression": "name",
    "generator_function_declaration": "name",
    "generator_function": "name",
    "class_declaration": "name",
    "class": "name",
    "catch_clause": "parameter",
    "arrow_function": "parameter",
}


class _Binder:
    """Resolves, within one file, which local names come from `modules`.

    Only the straight-line local flows real queue/broker APIs need are modelled:
    import/require bindings, then declarator and assignment chains derived from
    them. Anything else - a dynamic receiver, a value from another file, a name
    that a nested scope redeclares - resolves to nothing, so no call is
    reported for it.
    """

    def __init__(self, modules: frozenset[str]) -> None:
        self._modules = modules
        # name -> (module, member, declaring byte, scope range)
        self._bindings: dict[str, tuple[str, str, int, tuple[int, int]]] = {}
        # name -> [(declaring byte, scope range)] for every declaration of it
        self._decls: dict[str, list[tuple[int, tuple[int, int]]]] = {}
        self._calls: list = []

    def run(self, root) -> tuple[JsBoundCall, ...]:
        stack = [root]
        while stack:
            node = stack.pop()
            self._declare(node)
            if node.type in ("import_statement", "import_declaration"):
                self._bind_import(node)
            elif node.type in ("variable_declarator", "assignment_expression"):
                self._bind_value(node)
            elif node.type in ("new_expression", "call_expression"):
                self._calls.append(node)
            stack.extend(reversed(node.children))  # keep source order
        found = (self._bound_call(node) for node in self._calls)
        return tuple(call for call in found if call is not None)

    # ── declarations ────────────────────────────────────────────────────────

    def _declare(self, node) -> None:
        """Record every name this node introduces, bound to a library or not.

        Non-library declarations matter too: they are what proves a nested
        `Worker` is the local one rather than the imported queue class.
        """
        if node.type == "formal_parameters":
            targets = node.named_children
        elif node.type == "import_alias":
            # TypeScript `import local = namespace.member` introduces `local`
            # but does not bind it to one of the requested runtime modules.
            targets = node.named_children[:1]
        else:
            field = _DECL_FIELDS.get(node.type)
            target = node.child_by_field_name(field) if field else None
            targets = [target] if target is not None else []
        for target in targets:
            for name_node in _pattern_names(target):
                self._add_decl(name_node)

    def _add_decl(self, name_node) -> None:
        entry = (name_node.start_byte, _decl_scope(name_node))
        self._decls.setdefault(_text(name_node), []).append(entry)

    def _bind_name(
        self, name_node, module: str, member: str, declares: bool = True
    ) -> None:
        """Bind `name_node` to `module`, if it matched one.

        An assignment writes to a name that something else declared, so it takes
        that declaration's identity: `let channel; channel = ...` must still
        resolve, while a target with several declarations cannot be pinned down.
        """
        name = _text(name_node)
        if declares:
            self._add_decl(name_node)
        if not module:
            return
        declared = self._decls.get(name, ())
        if declares or not declared:
            declared_at, scope = name_node.start_byte, _decl_scope(name_node)
        elif len(declared) == 1:
            declared_at, scope = declared[0]
        else:
            return  # several declarations of the target - identity unprovable
        self._bindings[name] = (module, member, declared_at, scope)

    def _bind_import(self, node) -> None:
        source = node.child_by_field_name("source")
        module = self._match(_unquote(source)) if source is not None else ""
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for child in clause.named_children:
                if child.type == "identifier":  # import X from "m"
                    self._bind_name(child, module, _MODULE_EXPORT)
                elif child.type == "namespace_import":  # import * as X from "m"
                    for name_node in child.named_children:
                        self._bind_name(name_node, module, _MODULE_EXPORT)
                elif child.type == "named_imports":
                    for spec in child.named_children:
                        if spec.type != "import_specifier":
                            continue
                        name_node = spec.child_by_field_name("name")
                        alias = spec.child_by_field_name("alias")
                        if name_node is not None:
                            self._bind_name(
                                alias or name_node, module, _text(name_node)
                            )

    def _bind_value(self, node) -> None:
        """Bind `const x = <expr>` / `x = <expr>` when the value is library-derived."""
        declares = node.type == "variable_declarator"
        target = node.child_by_field_name("name" if declares else "left")
        value = node.child_by_field_name("value" if declares else "right")
        if target is None or value is None:
            return
        module = self._require_module(value)
        if target.type == "object_pattern":  # const { Worker } = require("m")
            if module:
                for name_node, member in _destructured_members(target):
                    self._bind_name(name_node, module, member, declares)
            return
        if target.type != "identifier":
            return
        if module:
            self._bind_name(target, module, _MODULE_EXPORT, declares)
            return
        resolved = self._resolve(value)
        if resolved is not None:
            self._bind_name(target, *resolved, declares=declares)

    # ── resolution ──────────────────────────────────────────────────────────

    def _match(self, spec: str) -> str:
        """The requested module `spec` names, subpath imports included."""
        for module in self._modules:
            if spec == module or spec.startswith(f"{module}/"):
                return module
        return ""

    def _require_module(self, node) -> str:
        """The global ``require(\"m\")`` module, if it is not shadowed locally."""
        while node.type in _VALUE_WRAPPERS and node.named_children:
            node = node.named_children[0]
        if node.type != "call_expression":
            return ""
        callee = node.child_by_field_name("function")
        if (
            callee is None
            or callee.type != "identifier"
            or _text(callee) != "require"
            or self._is_locally_declared(callee)
        ):
            return ""
        args = node.child_by_field_name("arguments")
        first = args.named_children[0] if args and args.named_children else None
        return (
            self._match(_unquote(first))
            if first is not None and first.type == "string"
            else ""
        )

    def _is_locally_declared(self, name_node) -> bool:
        """Whether a declaration shadows this otherwise global identifier."""
        position = name_node.start_byte
        return any(
            start <= position < end
            for _declared_at, (start, end) in self._decls.get(_text(name_node), ())
        )

    def _lookup(self, name_node) -> tuple[str, str] | None:
        """The binding `name_node` refers to at its own position, if provable."""
        binding = self._bindings.get(_text(name_node))
        if binding is None:
            return None
        module, member, declared_at, (start, end) = binding
        position = name_node.start_byte
        if not start <= position < end:
            return None
        for other_at, (other_start, other_end) in self._decls[_text(name_node)]:
            if other_at != declared_at and other_start <= position < other_end:
                return None  # a second declaration is in scope - fail closed
        return module, member

    def _resolve(self, node) -> tuple[str, str] | None:
        """(module, role) this expression evaluates to; see `JsBoundCall`."""
        if node.type in _VALUE_WRAPPERS:
            children = node.named_children
            return self._resolve(children[0]) if children else None
        if node.type == "identifier":
            return self._lookup(node)
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            base = self._resolve(obj) if obj is not None else None
            if base is None or prop is None:
                return None
            module, member = base
            # A literal requested module may expose a named export directly
            # (`require('bullmq').Worker`). Do not treat arbitrary members of
            # an already-produced value as new module bindings.
            return (module, _text(prop)) if member == _MODULE_EXPORT else None
        if node.type in ("new_expression", "call_expression"):
            module = self._require_module(node)
            if module:
                return module, _MODULE_EXPORT
            call = self._bound_call(node)
            return (call.module, _produced_role(call)) if call is not None else None
        return None

    def _bound_call(self, node) -> JsBoundCall | None:
        is_new = node.type == "new_expression"
        callee = node.child_by_field_name("constructor" if is_new else "function")
        if callee is None:
            return None
        if callee.type == "identifier":
            resolved = self._lookup(callee)
            if resolved is None:
                return None
            module, symbol, receiver = *resolved, ""
        elif callee.type == "member_expression":
            obj = callee.child_by_field_name("object")
            prop = callee.child_by_field_name("property")
            base = self._resolve(obj) if obj is not None else None
            if base is None or prop is None:
                return None
            module, member = base
            # A member of the module export is the imported symbol itself, so
            # `new amqp.Worker()` and an imported `new Worker()` are one role.
            symbol, receiver = _text(prop), "" if member == _MODULE_EXPORT else member
        elif callee.type == "call_expression":
            # Support direct module factories such as
            # `require("socket.io")(server)`, but not arbitrary nested calls:
            # only a literal, requested module can establish this binding.
            module = self._require_module(callee)
            if not module:
                return None
            symbol, receiver = _MODULE_EXPORT, ""
        else:
            return None
        return JsBoundCall(module, symbol, is_new, receiver, _arg_tokens(node))


def _decl_scope(name_node) -> tuple[int, int]:
    """Byte range of the lexical scope a declaration name governs."""
    var_scope = _var_function_scope(name_node)
    if var_scope is not None:
        return var_scope
    node = name_node.parent
    # Declaration names bind outside their own function/class body. Parameters
    # deliberately do not take this branch: they bind inside the function body.
    if node is not None and node.type in {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
    }:
        declared_name = node.child_by_field_name("name")
        if (
            declared_name is not None
            and declared_name.start_byte == name_node.start_byte
            and declared_name.end_byte == name_node.end_byte
        ):
            node = node.parent
    while node is not None and node.type not in _SCOPE_TYPES:
        node = node.parent
    return (node.start_byte, node.end_byte) if node is not None else (0, 0)


def _var_function_scope(name_node) -> tuple[int, int] | None:
    """The function/program scope of a JavaScript ``var`` declaration."""
    declaration = name_node.parent
    while declaration is not None and declaration.type != "variable_declaration":
        declaration = declaration.parent
    if declaration is None or not _text(declaration).lstrip().startswith("var "):
        return None
    node = declaration.parent
    while node is not None:
        if node.type in {
            "program",
            "arrow_function",
            "function",
            "function_declaration",
            "function_expression",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
        }:
            return node.start_byte, node.end_byte
        node = node.parent
    return None


def _pattern_names(node):
    """Identifier nodes a binding pattern introduces."""
    kind = node.type
    if kind in ("identifier", "shorthand_property_identifier_pattern"):
        yield node
    elif kind in ("required_parameter", "optional_parameter"):
        yield from _field_names(node, "pattern")
    elif kind == "assignment_pattern":
        yield from _field_names(node, "left")
    elif kind == "pair_pattern":
        yield from _field_names(node, "value")
    elif kind in ("object_pattern", "array_pattern", "rest_pattern"):
        for child in node.named_children:
            yield from _pattern_names(child)


def _field_names(node, field: str):
    child = node.child_by_field_name(field)
    if child is not None:
        yield from _pattern_names(child)


def _destructured_members(pattern):
    """(local name node, module member) per key of `{ a, b: c }`."""
    for child in pattern.named_children:
        if child.type == "shorthand_property_identifier_pattern":
            yield child, _text(child)
        elif child.type == "pair_pattern":
            key = child.child_by_field_name("key")
            value = child.child_by_field_name("value")
            if key is not None and value is not None and value.type == "identifier":
                yield value, _text(key)


def _arg_tokens(node) -> tuple[tuple[str, str], ...]:
    args = node.child_by_field_name("arguments")
    if args is None:
        return ()
    return tuple(_arg_token(c) for c in args.named_children if c.type != "comment")


def _arg_token(node) -> tuple[str, str]:
    if node.type == "string":
        return ("str", _unquote(node))
    if node.type == "identifier":
        return ("name", _text(node))
    if node.type in ("function_expression", "function_declaration"):
        child = node.child_by_field_name("name")
        return ("name", _text(child) if child is not None else "")
    return ("", "")


def _text(node) -> str:
    return node.text.decode("utf8", "replace")


def _unquote(node) -> str:
    text = _text(node)
    return text[1:-1] if len(text) >= 2 and text[0] in "\"'" else text


# ─────────────────────────────────────────────────────────────────────────────
# Tree-sitter walk
# ─────────────────────────────────────────────────────────────────────────────


def _walk(
    node,
    lines: list[str],
    symbols: list[Symbol],
    imports: list[str],
    exported: bool = False,
) -> None:
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
                    elif member.type in (
                        "public_field_definition",
                        "property_definition",
                        "field_definition",
                    ):
                        # Class fields/properties
                        pass
        return

    # TypeScript interfaces
    if t == "interface_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            fields = _extract_interface_fields(node, lines)
            symbols.append(
                Symbol(
                    name=_node_text(name_node, lines),
                    kind="interface",
                    signature=lines[node.start_point[0]].strip()
                    if node.start_point[0] < len(lines)
                    else "",
                    docstring=doc,
                    body_preview=_body_preview(node, lines),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported,
                    fields=fields,
                )
            )
        return

    # TypeScript type aliases
    if t == "type_alias_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            symbols.append(
                Symbol(
                    name=_node_text(name_node, lines),
                    kind="type",
                    signature=lines[node.start_point[0]].strip()
                    if node.start_point[0] < len(lines)
                    else "",
                    docstring=doc,
                    body_preview=_body_preview(node, lines),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported,
                )
            )
        return

    # TypeScript enums
    if t == "enum_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            doc = _get_jsdoc(node, lines)
            members = _extract_enum_members(node, lines)
            symbols.append(
                Symbol(
                    name=_node_text(name_node, lines),
                    kind="enum",
                    signature=lines[node.start_point[0]].strip()
                    if node.start_point[0] < len(lines)
                    else "",
                    docstring=doc,
                    body_preview=_body_preview(node, lines, max_lines=10),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported,
                    fields=members,
                )
            )
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
        signature=lines[node.start_point[0]].strip()
        if node.start_point[0] < len(lines)
        else "",
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

    if value_node and value_node.type in (
        "arrow_function",
        "function",
        "function_expression",
    ):
        doc = _get_jsdoc(parent_node, lines)
        symbols.append(
            Symbol(
                name=name,
                kind="function",
                signature=lines[parent_node.start_point[0]].strip()
                if parent_node.start_point[0] < len(lines)
                else "",
                docstring=doc,
                body_preview=_body_preview(value_node, lines),
                start_line=parent_node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                is_exported=exported,
            )
        )
    elif value_node and value_node.type in ("call_expression",):
        # e.g. const router = express.Router() — detect as constant
        doc = _get_jsdoc(parent_node, lines)
        sig = (
            lines[parent_node.start_point[0]].strip()
            if parent_node.start_point[0] < len(lines)
            else ""
        )
        # Only record if it looks meaningful (not just a temp variable)
        if re.match(r"(?:export\s+)?const\s+", sig):
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=sig,
                    docstring=doc,
                    start_line=parent_node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported,
                )
            )
    elif value_node and value_node.type in (
        "string",
        "number",
        "true",
        "false",
        "template_string",
        "object",
        "array",
        "new_expression",
    ):
        # const FOO = "bar" or const config = { ... }
        sig = (
            lines[parent_node.start_point[0]].strip()
            if parent_node.start_point[0] < len(lines)
            else ""
        )
        if re.match(r"(?:export\s+)?const\s+[A-Z_]", sig) or name.isupper():
            doc = _get_jsdoc(parent_node, lines)
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=sig,
                    docstring=doc,
                    body_preview=_body_preview(parent_node, lines, max_lines=3),
                    start_line=parent_node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported,
                )
            )


def _class_symbol(node, lines, exported=False) -> Symbol | None:
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None
    doc = _get_jsdoc(node, lines)
    decorators = _get_decorators(node, lines)
    return Symbol(
        name=_node_text(name_node, lines),
        kind="class",
        signature=lines[node.start_point[0]].strip()
        if node.start_point[0] < len(lines)
        else "",
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
        signature=lines[node.start_point[0]].strip()
        if node.start_point[0] < len(lines)
        else "",
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
                        sig = (
                            lines[member.start_point[0]].strip()
                            if member.start_point[0] < len(lines)
                            else ""
                        )
                        fields.append(sig.rstrip(";,").strip())
    return fields[:30]


# ─────────────────────────────────────────────────────────────────────────────
# React component & hook detection
# ─────────────────────────────────────────────────────────────────────────────


def _tag_react_symbols(symbols: list[Symbol], content: str) -> None:
    """Post-process symbols to detect React components and hooks."""
    has_react = (
        "react" in content.lower()
        or "from 'react'" in content
        or 'from "react"' in content
    )

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
            if any(
                indicator in body
                for indicator in (
                    "<",
                    "jsx",
                    "tsx",
                    "React.FC",
                    "React.Component",
                    "return (",
                    "useState",
                    "useEffect",
                    "props",
                )
            ):
                sym.kind = "component"
                # Try to extract props from signature
                props = _extract_react_props(sym.signature, content)
                if props:
                    sym.props = props
            elif any(
                indicator in content
                for indicator in ("React.FC", "JSX.Element", "<div", "<>")
            ):
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
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="function",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    body_preview="\n".join(lines[i : i + 5]),
                    start_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Class declaration
        m = re.match(r"class\s+(\w+)", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="class",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    body_preview="\n".join(lines[i : i + 5]),
                    start_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Arrow function / const assignment
        m = re.match(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="function",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    body_preview="\n".join(lines[i : i + 5]),
                    start_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Enum
        m = re.match(r"(?:const\s+)?enum\s+(\w+)", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="enum",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    body_preview="\n".join(lines[i : i + 8]),
                    start_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Interface
        m = re.match(r"interface\s+(\w+)", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="interface",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    body_preview="\n".join(lines[i : i + 8]),
                    start_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Type alias
        m = re.match(r"type\s+(\w+)", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="type",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    start_line=i + 1,
                    end_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # UPPER_CASE constants
        m = re.match(r"(?:const|let|var)\s+([A-Z][A-Z_0-9]+)\s*=", clean)
        if m:
            symbols.append(
                Symbol(
                    name=m.group(1),
                    kind="constant",
                    signature=stripped,
                    docstring=pending_jsdoc,
                    start_line=i + 1,
                    end_line=i + 1,
                    is_exported=is_exported,
                )
            )
            pending_jsdoc = ""
            continue

        # Reset pending jsdoc if we hit a non-comment, non-blank line
        if stripped and not stripped.startswith(("*", "//")):
            pending_jsdoc = ""

    return symbols, imports
