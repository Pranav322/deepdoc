"""JavaScript / TypeScript parser using tree-sitter.

Extracts: functions, arrow functions, classes, methods, interfaces, type aliases,
enums, constants, React components, custom hooks — with JSDoc/TSDoc, body previews,
export tracking, and decorator extraction.
"""

from __future__ import annotations

from bisect import bisect_right
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
    Parser = None  # type: ignore[assignment]
    _TS_AVAILABLE = False


def parse_js_ts(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE and Parser is not None:
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
    a usable name. `receiver_identity` is a literal identity carried by a
    proven produced receiver (for example the queue name supplied to
    `new Queue('emails')`); callers may use it only with an allowed API role.
    """

    module: str
    symbol: str
    is_new: bool
    receiver: str
    args: tuple[tuple[str, str], ...]
    receiver_identity: str = ""


# What a default import, a namespace import and `require()` all resolve to: the
# module export itself, so `amqplib.connect` and `amqp.connect` are one role.
_MODULE_EXPORT = "default"


def _produced_role(call: JsBoundCall) -> str:
    """Role of the value `call` returns, chained onto its receiver's role."""
    if call.receiver and call.receiver.endswith("()"):
        return f"{call.receiver}.{call.symbol}()"
    return f"{call.symbol}()"


class _Declaration(NamedTuple):
    """One lexical binding identity plus the function/program execution region."""

    start: int
    scope: tuple[int, int]
    execution_scope: tuple[int, int]


class _ResolvedValue(NamedTuple):
    """A proven module value plus an optional literal produced-object identity.

    ``origin`` distinguishes separately constructed objects that share a
    literal identity (two ``new Queue('orders')`` calls) so a mutation of
    one cannot taint the other.
    """

    module: str
    member: str
    identity: str = ""
    origin: int = 0


class _BindingWrite(NamedTuple):
    """The value (or explicit invalidation) assigned to one declaration."""

    at: int
    value: _ResolvedValue | None


def _produced_value(call: JsBoundCall, origin: int = 0) -> _ResolvedValue:
    """Value a trusted call/new expression produces for a later local binding."""
    identity = _literal_arg(call.args, 0) if not call.receiver else ""
    return _ResolvedValue(call.module, _produced_role(call), identity, origin)


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
    if not _TS_AVAILABLE or Parser is None:
        return None
    try:
        tree = Parser(_grammar_for(path, language)).parse(bytes(content, "utf8"))
    except Exception:
        return None
    root = tree.root_node
    if root.type == "ERROR" or root.has_error:
        return None
    try:
        return _Binder(modules).run(root)
    except RecursionError:
        return None


def _grammar_for(path: Path, language: str):
    if path.suffix.lower() == ".tsx":
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
# A binding can be established only by a direct write in the same executable
# program/function region. A conditional or nested closure write may happen,
# but cannot prove the receiver's role at a later unrelated call.
_EXECUTION_SCOPE_TYPES = frozenset(
    {
        "program",
        "arrow_function",
        "function",
        "function_declaration",
        "function_expression",
        "generator_function",
        "generator_function_declaration",
        "method_definition",
    }
)
_UNCERTAIN_WRITE_ANCESTORS = frozenset(
    {
        "if_statement",
        "switch_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "try_statement",
        "catch_clause",
        "finally_clause",
        "with_statement",
        "ternary_expression",
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


def _unwrap_value(node):
    """Strip wrappers that do not change the proven runtime value."""
    current = node
    while current is not None and current.type in _VALUE_WRAPPERS:
        children = current.named_children
        current = children[0] if children else None
    return current


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
    """Resolves one file's literal-module bindings without cross-scope guesses.

    Declarations are collected before values are resolved so hoisted names shadow
    the global CommonJS loader. Each declaration then owns an ordered write
    history: a dynamic write is an explicit invalidation, while a later proven
    write may safely establish a new local value. A lookup always chooses the
    narrowest visible declaration and its most recent prior write.
    """

    def __init__(self, modules: frozenset[str]) -> None:
        self._modules = modules
        self._decls: dict[str, list[_Declaration]] = {}
        self._writes: dict[_Declaration, list[_BindingWrite]] = {}
        self._write_positions: dict[_Declaration, list[int]] = {}
        self._binding_lookup_probes = 0
        self._binding_history_steps = 0
        self._cross_scope_invalidations: set[_Declaration] = set()
        self._global_writes: dict[str, list[int]] = {}
        self._nested_global_writes: set[str] = set()
        self._value_mutation_positions: dict[_ResolvedValue, list[int]] = {}
        self._object_assign_alias_positions: dict[_Declaration, list[int]] = {}
        self._object_assign_alias_values: dict[_Declaration, list[bool]] = {}
        self._dynamic_scope_positions: dict[tuple[int, int], list[int]] = {}
        self._nested_direct_eval_positions: list[int] = []
        self._calls: list = []

    def run(self, root) -> tuple[JsBoundCall, ...]:
        nodes = self._nodes_in_source_order(root)
        # Collect every declaration first so a hoisted/lexical shadow makes a
        # later `require(...)` fail closed even when the declaration appears
        # after the call site in source text.
        for node in nodes:
            self._declare(node)
        # Before any RHS can establish a module role, mark closure/global writes
        # that make a source-order-only binding unsafe.
        for node in nodes:
            self._pre_mark_cross_scope_writes(node)
        # Static ESM/TypeScript imports are initialized before module body code,
        # even when their declaration appears textually later.
        for node in nodes:
            if node.type in ("import_statement", "import_declaration"):
                self._bind_import(node)
        for node in nodes:
            if node.type in ("import_statement", "import_declaration"):
                continue
            if node.type in (
                "variable_declarator",
                "assignment_expression",
                "augmented_assignment_expression",
            ):
                self._bind_value(node)
            elif node.type == "for_in_statement":
                target = node.child_by_field_name("left")
                if target is not None and not _loop_binding_keyword(node):
                    for name_node in _pattern_names(target):
                        self._record_write(name_node, None)
            elif node.type == "update_expression":
                target = node.child_by_field_name("argument")
                if target is not None:
                    self._record_member_mutation(target)
                    for name_node in _pattern_names(target):
                        self._record_write(name_node, None)
            elif (
                node.type == "unary_expression"
                and _text(node.child_by_field_name("operator") or node).strip()
                == "delete"
                and _is_proven_top_level_execution(node)
            ):
                argument = node.child_by_field_name("argument")
                if argument is not None:
                    self._record_member_mutation(argument)
            elif node.type == "call_expression":
                if _is_proven_top_level_execution(node):
                    self._record_reflective_mutation(node)
                    self._record_direct_eval(node)
                self._calls.append(node)
            elif node.type == "new_expression":
                self._calls.append(node)
        self._record_hoisted_direct_eval_invocations(nodes)
        self._record_hoisted_nested_mutations(nodes)
        found = (self._bound_call(node) for node in self._calls)
        return tuple(call for call in found if call is not None)

    @staticmethod
    def _nodes_in_source_order(root) -> list:
        stack = [root]
        nodes = []
        while stack:
            node = stack.pop()
            nodes.append(node)
            stack.extend(reversed(node.children))
        # Parents run before children at one byte offset, so a declarator write
        # is available while its nested executable call is evaluated later.
        return sorted(nodes, key=lambda node: (node.start_byte, -node.end_byte))

    # ── declarations and writes ─────────────────────────────────────────────

    def _declare(self, node) -> None:
        """Record every lexical name, including names unrelated to a library."""
        if node.type == "for_in_statement":
            keyword = _loop_binding_keyword(node)
            target = node.child_by_field_name("left")
            if keyword and target is not None:
                scope = _loop_binding_scope(node, keyword)
                for name_node in _pattern_names(target):
                    self._add_decl(name_node, scope=scope)
            return
        if node.type in ("import_statement", "import_declaration"):
            if _is_type_only_import(node):
                return
            targets = _runtime_import_names(node)
        elif node.type == "formal_parameters":
            targets = node.named_children
        elif node.type == "import_alias":
            # TypeScript `import local = namespace.member` shadows `local` but
            # cannot establish one of the requested literal module bindings.
            targets = node.named_children[:1]
        else:
            field = _DECL_FIELDS.get(node.type)
            target = node.child_by_field_name(field) if field else None
            targets = [target] if target is not None else []
        for target in targets:
            for name_node in _pattern_names(target):
                self._add_decl(name_node)

    def _pre_mark_cross_scope_writes(self, node) -> None:
        """Record closure/global mutations before resolving any RHS values."""
        if node.type == "variable_declarator":
            target = node.child_by_field_name("name")
        elif node.type in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            target = node.child_by_field_name("left")
        elif node.type == "update_expression":
            target = node.child_by_field_name("argument")
        elif node.type == "for_in_statement" and not _loop_binding_keyword(node):
            target = node.child_by_field_name("left")
        else:
            return
        if target is not None:
            for name_node in _written_binding_names(target):
                self._mark_cross_scope_write(name_node)

    def _mark_cross_scope_write(self, name_node) -> None:
        declaration = self._declaration_for(name_node)
        if declaration is None:
            if not _execution_scope_is_program(name_node):
                self._nested_global_writes.add(_text(name_node))
        elif _execution_scope(name_node) != declaration.execution_scope:
            self._cross_scope_invalidations.add(declaration)

    def _add_decl(
        self, name_node, *, scope: tuple[int, int] | None = None
    ) -> None:
        name = _text(name_node)
        declaration = _Declaration(
            name_node.start_byte,
            scope if scope is not None else _decl_scope(name_node),
            _execution_scope(name_node),
        )
        entries = self._decls.setdefault(name, [])
        if declaration not in entries:
            entries.append(declaration)

    def _declaration_for(self, name_node) -> _Declaration | None:
        """The narrowest unambiguous declaration visible at this identifier."""
        position = name_node.start_byte
        visible = [
            declaration
            for declaration in self._decls.get(_text(name_node), ())
            if declaration.scope[0] <= position < declaration.scope[1]
        ]
        if not visible:
            return None
        narrowest_span = min(end - start for start, end in (item.scope for item in visible))
        narrowest = [
            item
            for item in visible
            if item.scope[1] - item.scope[0] == narrowest_span
        ]
        return narrowest[0] if len(narrowest) == 1 else None

    def _record_write(
        self,
        name_node,
        value: _ResolvedValue | None,
        *,
        at: int | None = None,
    ) -> None:
        """Record a trusted value or explicit invalidation for one local name."""
        write_at = name_node.start_byte if at is None else at
        self._mark_cross_scope_write(name_node)
        declaration = self._declaration_for(name_node)
        if declaration is None:
            # `require = customLoader` mutates the global loader binding. A
            # top-level write retains normal source ordering; nested writes were
            # already marked as unconditionally unsafe by the prepass.
            self._global_writes.setdefault(_text(name_node), []).append(write_at)
            return
        if value is not None and not _is_definite_binding_write(
            name_node, declaration
        ):
            # Preserve the write's source-order invalidation, but never turn a
            # conditional or nested-closure assignment into role proof.
            value = None
        write = _BindingWrite(write_at, value)
        writes = self._writes.setdefault(declaration, [])
        positions = self._write_positions.setdefault(declaration, [])
        if not positions or write_at >= positions[-1]:
            positions.append(write_at)
            writes.append(write)
            return
        # Static imports are hoisted and use -1 even when their declaration is
        # textually later; retain a sorted index without scanning at lookup.
        index = bisect_right(positions, write_at)
        positions.insert(index, write_at)
        writes.insert(index, write)

    def _record_member_mutation(self, target) -> None:
        """Taint every resolved object/module behind a write target."""
        for base in _member_write_bases(target):
            self._record_value_mutation(base, target.start_byte)

    def _is_unshadowed_global_name(self, node, name: str) -> bool:
        """Whether one identifier is the built-in global binding `name`."""
        return bool(
            node is not None
            and node.type == "identifier"
            and _text(node) == name
            and not self._is_locally_declared(node)
            and not self._global_name_was_written(node)
        )

    def _is_unshadowed_global_object(self, node) -> bool:
        """Whether one identifier is the built-in global `Object` binding."""
        return self._is_unshadowed_global_name(node, "Object")

    def _is_object_assign_expression(self, node) -> bool:
        """Whether one expression is unshadowed static `Object.assign`."""
        if node is None:
            return False
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            member = _text(prop) if prop is not None else ""
        elif node.type == "subscript_expression":
            obj = node.child_by_field_name("object")
            index = node.child_by_field_name("index")
            member = _unquote(index) if index is not None and index.type == "string" else ""
        else:
            return False
        return self._is_unshadowed_global_object(obj) and member == "assign"

    def _record_object_assign_alias(self, target, value) -> None:
        """Track a lexical alias of static `Object.assign` in source order."""
        value_is_alias = self._is_object_assign_expression(value) or (
            value is not None
            and value.type == "identifier"
            and self._is_object_assign_alias(value)
        )
        self._record_object_assign_alias_value(target, value_is_alias)

    def _record_object_assign_alias_value(self, target, value_is_alias: bool) -> None:
        """Record one source-ordered truth value for an assign-alias binding."""
        declaration = self._declaration_for(target)
        if declaration is None:
            return
        position = target.start_byte
        value_is_alias = value_is_alias and _is_definite_binding_write(
            target, declaration
        )
        positions = self._object_assign_alias_positions.setdefault(declaration, [])
        values = self._object_assign_alias_values.setdefault(declaration, [])
        index = bisect_right(positions, position)
        positions.insert(index, position)
        values.insert(index, value_is_alias)

    def _is_object_assign_alias(self, node) -> bool:
        """Whether an identifier currently resolves to a static assign alias."""
        declaration = self._declaration_for(node)
        if declaration is None:
            return False
        positions = self._object_assign_alias_positions.get(declaration, ())
        values = self._object_assign_alias_values.get(declaration, ())
        index = bisect_right(positions, node.start_byte) - 1
        return bool(index >= 0 and values[index])

    def _is_static_mutation_call(self, callee) -> bool:
        """Whether a callee is a static object-mutation API or Object.assign alias."""
        callee = _unwrap_value(callee)
        if callee is None:
            return False
        if callee.type == "identifier" and self._is_object_assign_alias(callee):
            return True
        if callee.type not in ("member_expression", "subscript_expression"):
            return False
        obj = callee.child_by_field_name("object")
        if callee.type == "member_expression":
            prop = callee.child_by_field_name("property")
            member = _text(prop) if prop is not None else ""
        else:
            index = callee.child_by_field_name("index")
            member = (
                _unquote(index) if index is not None and index.type == "string" else ""
            )
        if self._is_unshadowed_global_name(obj, "Object") and member in {
            "assign",
            "defineProperty",
            "defineProperties",
        }:
            return True
        return self._is_unshadowed_global_name(obj, "Reflect") and member in {
            "set",
            "defineProperty",
            "deleteProperty",
        }

    def _record_reflective_mutation(self, node) -> None:
        """Taint a receiver mutated through static object-mutation APIs."""
        callee = node.child_by_field_name("function")
        if callee is None or not self._is_static_mutation_call(callee):
            return
        args = node.child_by_field_name("arguments")
        target = args.named_children[0] if args is not None and args.named_children else None
        if target is not None:
            self._record_value_mutation(target, node.start_byte)

    def _record_value_mutation(self, base, position: int) -> None:
        """Record that the resolved value behind `base` was mutated at `position`.

        Nested mutation effects are applied at the proven invocation byte, so
        lookup of an identifier target uses that position rather than the
        function-body text offset of the mutation spelling.
        """
        value = (
            self._lookup_at(base, position)
            if base is not None and base.type == "identifier"
            else self._resolve(base)
        )
        if value is None:
            return
        positions = self._value_mutation_positions.setdefault(value, [])
        if not positions or position >= positions[-1]:
            positions.append(position)
            return
        positions.insert(bisect_right(positions, position), position)

    def _value_was_mutated(self, value: _ResolvedValue, position: int) -> bool:
        """Whether a prior member write invalidated this resolved object value."""
        return bisect_right(self._value_mutation_positions.get(value, ()), position) > 0

    def _is_unshadowed_direct_eval(self, node) -> bool:
        """Whether a call is the built-in direct `eval`, not a local lookalike."""
        callee = node.child_by_field_name("function")
        return bool(
            callee is not None
            and callee.type == "identifier"
            and _text(callee) == "eval"
            and not self._is_locally_declared(callee)
            and not self._global_name_was_written(callee)
        )

    def _record_direct_eval(self, node) -> None:
        """Fail closed after an unshadowed direct `eval` in one execution scope."""
        if not self._is_unshadowed_direct_eval(node):
            return
        scope = _execution_scope(node)
        positions = self._dynamic_scope_positions.setdefault(scope, [])
        position = node.start_byte
        if not positions or position >= positions[-1]:
            positions.append(position)
        else:
            positions.insert(bisect_right(positions, position), position)

    def _record_nested_eval_effect(self, position: int) -> None:
        """Record where a nested direct eval actually alters the module scope."""
        nested = self._nested_direct_eval_positions
        if not nested or position >= nested[-1]:
            nested.append(position)
        else:
            nested.insert(bisect_right(nested, position), position)

    def _record_hoisted_direct_eval_invocations(self, nodes) -> None:
        """Place each nested direct-eval effect at its proven invocation position.

        A function body's text position is not when its eval runs, so effects are
        summarized per named function declaration, propagated through
        parser-proven synchronous named calls in the same file, and applied at
        unconditional top-level call sites. A nested eval that cannot be tied to
        such a call site is unknowable and taints the whole module instead.
        """
        functions_by_scope: dict[tuple[int, int], _Declaration] = {}
        for function in nodes:
            if function.type not in {
                "function_declaration",
                "generator_function_declaration",
            }:
                continue
            name = function.child_by_field_name("name")
            declaration = self._declaration_for(name) if name is not None else None
            if declaration is not None:
                functions_by_scope[_execution_scope(function)] = declaration
        # Callee -> enclosing named functions that synchronously call it.
        callers: dict[_Declaration, set[_Declaration]] = {}
        reaches_eval: set[_Declaration] = set()
        unresolved_eval = False
        for call in nodes:
            if call.type != "call_expression":
                continue
            scope = _execution_scope(call)
            enclosing = functions_by_scope.get(scope)
            if self._is_unshadowed_direct_eval(call) and not _execution_scope_is_program(
                call
            ):
                if enclosing is None:
                    unresolved_eval = True
                else:
                    reaches_eval.add(enclosing)
                continue
            callee = call.child_by_field_name("function")
            if callee is None or callee.type != "identifier" or enclosing is None:
                continue
            target = self._declaration_for(callee)
            if target is not None and target in functions_by_scope.values():
                callers.setdefault(target, set()).add(enclosing)
        # Bounded backwards fixpoint over the intrafile named-call edges.
        pending = list(reaches_eval)
        while pending:
            target = pending.pop()
            for caller in callers.get(target, ()):
                if caller not in reaches_eval:
                    reaches_eval.add(caller)
                    pending.append(caller)
        invoked: set[_Declaration] = set()
        for call in nodes:
            if call.type != "call_expression" or not _is_proven_top_level_execution(call):
                continue
            callee = call.child_by_field_name("function")
            if callee is None or callee.type != "identifier":
                continue
            declaration = self._declaration_for(callee)
            if declaration is None or declaration not in reaches_eval:
                continue
            invoked.add(declaration)
            self._record_nested_eval_effect(call.start_byte)
        if unresolved_eval:
            # A nested eval that cannot be tied to a named function declaration
            # may run at an unknown time, so the file is unsafe.
            self._record_nested_eval_effect(0)

    def _named_functions_by_scope(self, nodes) -> dict[tuple[int, int], _Declaration]:
        functions_by_scope: dict[tuple[int, int], _Declaration] = {}
        for function in nodes:
            if function.type not in {
                "function_declaration",
                "generator_function_declaration",
            }:
                continue
            name = function.child_by_field_name("name")
            declaration = self._declaration_for(name) if name is not None else None
            if declaration is not None:
                functions_by_scope[_execution_scope(function)] = declaration
        return functions_by_scope

    def _record_hoisted_nested_mutations(self, nodes) -> None:
        """Apply nested Object.assign/delete mutations at proven invocation sites."""
        functions_by_scope = self._named_functions_by_scope(nodes)
        callers: dict[_Declaration, set[_Declaration]] = {}
        mutates: set[_Declaration] = set()
        pending_effects: dict[_Declaration, list] = {}
        for node in nodes:
            scope = _execution_scope(node)
            enclosing = functions_by_scope.get(scope)
            if enclosing is None:
                continue
            is_mutation = False
            if node.type == "call_expression" and self._is_static_mutation_call(
                node.child_by_field_name("function")
            ):
                is_mutation = True
            elif (
                node.type == "unary_expression"
                and _text(node.child_by_field_name("operator") or node).strip()
                == "delete"
            ):
                is_mutation = True
            if is_mutation:
                mutates.add(enclosing)
                pending_effects.setdefault(enclosing, []).append(node)
            if node.type != "call_expression":
                continue
            callee = node.child_by_field_name("function")
            if callee is None or callee.type != "identifier":
                continue
            target = self._declaration_for(callee)
            if target is not None and target in functions_by_scope.values():
                callers.setdefault(target, set()).add(enclosing)
        pending = list(mutates)
        while pending:
            target = pending.pop()
            for caller in callers.get(target, ()):
                if caller not in mutates:
                    mutates.add(caller)
                    pending.append(caller)
        for call in nodes:
            if call.type != "call_expression" or not _is_proven_top_level_execution(call):
                continue
            callee = call.child_by_field_name("function")
            if callee is None or callee.type != "identifier":
                continue
            declaration = self._declaration_for(callee)
            if declaration is None or declaration not in mutates:
                continue
            for effect in pending_effects.get(declaration, ()):
                if effect.type == "call_expression":
                    self._record_reflective_mutation_at(effect, call.start_byte)
                else:
                    argument = effect.child_by_field_name("argument")
                    if argument is not None:
                        self._record_value_mutation(argument, call.start_byte)

    def _record_reflective_mutation_at(self, node, position: int) -> None:
        callee = node.child_by_field_name("function")
        if callee is None or not self._is_static_mutation_call(callee):
            return
        args = node.child_by_field_name("arguments")
        target = args.named_children[0] if args is not None and args.named_children else None
        if target is not None:
            self._record_value_mutation(target, position)

    def _scope_has_direct_eval(self, node) -> bool:
        """Whether an earlier direct eval can alter this node's lexical scope."""
        return (
            bisect_right(self._nested_direct_eval_positions, node.start_byte) > 0
            or bisect_right(
                self._dynamic_scope_positions.get(_execution_scope(node), ()),
                node.start_byte,
            )
            > 0
        )

    def _bind_import(self, node) -> None:
        if _is_type_only_import(node):
            return
        require_clause = next(
            (
                child
                for child in node.named_children
                if child.type == "import_require_clause"
            ),
            None,
        )
        if require_clause is not None:
            children = require_clause.named_children
            if (
                len(children) == 2
                and children[0].type == "identifier"
                and children[1].type == "string"
            ):
                module = self._match(_unquote(children[1]))
                if module:
                    self._record_write(
                        children[0], _ResolvedValue(module, _MODULE_EXPORT)
                    )
            return
        source = node.child_by_field_name("source")
        module = self._match(_unquote(source)) if source is not None else ""
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for child in clause.named_children:
                if child.type == "identifier":  # import X from "m"
                    self._record_write(
                        child, _ResolvedValue(module, _MODULE_EXPORT), at=-1
                    )
                elif child.type == "namespace_import":  # import * as X from "m"
                    for name_node in child.named_children:
                        self._record_write(
                            name_node, _ResolvedValue(module, _MODULE_EXPORT), at=-1
                        )
                elif child.type == "named_imports":
                    for spec in child.named_children:
                        if (
                            spec.type != "import_specifier"
                            or _is_type_only_import_specifier(spec)
                        ):
                            continue
                        name_node = spec.child_by_field_name("name")
                        alias = spec.child_by_field_name("alias")
                        if name_node is not None:
                            self._record_write(
                                alias or name_node,
                                _ResolvedValue(module, _text(name_node)),
                                at=-1,
                            )

    def _bind_value(self, node) -> None:
        """Track one declarator/assignment write when its value is provable."""
        declares = node.type == "variable_declarator"
        target = node.child_by_field_name("name" if declares else "left")
        if target is None:
            return
        if node.type == "augmented_assignment_expression":
            self._record_member_mutation(target)
            for name_node in _written_binding_names(target):
                self._record_write(name_node, None)
            return
        value = node.child_by_field_name("value" if declares else "right")
        if value is None:
            return
        module = self._require_module(value)
        if target.type == "object_pattern":  # const { Worker } = require("m")
            if not declares:
                self._record_member_mutation(target)
            if self._is_unshadowed_global_object(value):
                for name_node, member in _destructured_members(target):
                    self._record_object_assign_alias_value(
                        name_node, member == "assign"
                    )
                    if not declares:
                        self._record_write(name_node, None)
                return
            source_value = (
                _ResolvedValue(module, _MODULE_EXPORT)
                if module
                else self._resolve(value)
            )
            if source_value is not None and source_value.member == _MODULE_EXPORT:
                for name_node, member in _destructured_members(target):
                    self._record_write(
                        name_node, _ResolvedValue(source_value.module, member)
                    )
            elif not declares:
                for name_node in _pattern_names(target):
                    self._record_write(name_node, None)
            return
        if target.type != "identifier":
            self._record_member_mutation(target)
            if not declares:
                for name_node in _written_binding_names(target):
                    self._record_write(name_node, None)
            return
        if module:
            resolved = _ResolvedValue(module, _MODULE_EXPORT)
        else:
            resolved = self._resolve(value)
        # A None value is not ignored: it revokes a previous trusted write to
        # this same declaration, preventing stale queue/socket evidence.
        self._record_object_assign_alias(target, value)
        self._record_write(target, resolved)

    # ── resolution ──────────────────────────────────────────────────────────

    def _match(self, spec: str) -> str:
        """The requested module `spec` names, subpath imports included."""
        for module in self._modules:
            if spec == module or spec.startswith(f"{module}/"):
                return module
        return ""

    def _require_module(self, node) -> str:
        """The unshadowed, unmodified global ``require("m")`` module."""
        while node.type in _VALUE_WRAPPERS and node.named_children:
            node = node.named_children[0]
        if node.type != "call_expression":
            return ""
        callee = node.child_by_field_name("function")
        if (
            callee is None
            or callee.type != "identifier"
            or _text(callee) != "require"
            or self._scope_has_direct_eval(node)
            or _is_in_dynamic_scope(node)
            or self._is_locally_declared(callee)
            or self._global_name_was_written(callee)
        ):
            return ""
        args = node.child_by_field_name("arguments")
        first = args.named_children[0] if args and args.named_children else None
        module = (
            self._match(_unquote(first))
            if first is not None and first.type == "string"
            else ""
        )
        return (
            module
            if module
            and not self._value_was_mutated(
                _ResolvedValue(module, _MODULE_EXPORT), node.start_byte
            )
            else ""
        )

    def _global_name_was_written(self, name_node) -> bool:
        name = _text(name_node)
        writes = self._global_writes.get(name, ())
        return name in self._nested_global_writes or bisect_right(
            writes, name_node.start_byte
        ) > 0

    def _is_locally_declared(self, name_node) -> bool:
        """Whether a declaration shadows this otherwise global identifier."""
        return self._declaration_for(name_node) is not None

    def _lookup(self, name_node) -> _ResolvedValue | None:
        """The most recent proven write for this lexical declaration."""
        return self._lookup_at(name_node, name_node.start_byte)

    def _lookup_at(self, name_node, position: int) -> _ResolvedValue | None:
        """Lookup a lexical name as of `position` rather than the node's byte."""
        declaration = self._declaration_for(name_node)
        if (
            declaration is None
            or declaration in self._cross_scope_invalidations
            or self._scope_has_direct_eval(name_node)
            or _is_in_dynamic_scope(name_node)
        ):
            return None
        self._binding_lookup_probes += 1
        positions = self._write_positions.get(declaration, ())
        writes = self._writes.get(declaration, ())
        self._binding_history_steps += 1
        index = bisect_right(positions, position) - 1
        value = writes[index].value if index >= 0 else None
        if value is None or self._value_was_mutated(value, position):
            return None
        return value

    def _resolve(self, node) -> _ResolvedValue | None:
        """The proven module value this expression evaluates to, if any."""
        node = _unwrap_value(node)
        if node is None:
            return None
        if node.type == "identifier":
            return self._lookup(node)
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            base = self._resolve(obj) if obj is not None else None
            if base is None or prop is None:
                return None
            # A literal requested module may expose a named export directly
            # (`require('bullmq').Worker`). Arbitrary members of a produced
            # value never create a fresh module binding.
            return (
                _ResolvedValue(base.module, _text(prop))
                if base.member == _MODULE_EXPORT
                else None
            )
        if node.type in ("new_expression", "call_expression"):
            module = self._require_module(node)
            if module:
                return _ResolvedValue(module, _MODULE_EXPORT)
            call = self._bound_call(node)
            return (
                _produced_value(call, node.start_byte) if call is not None else None
            )
        return None

    def _bound_call(self, node) -> JsBoundCall | None:
        if _is_in_dynamic_scope(node) or not _is_proven_top_level_execution(node):
            return None
        is_new = node.type == "new_expression"
        callee = node.child_by_field_name("constructor" if is_new else "function")
        callee = _unwrap_value(callee)
        if callee is None:
            return None
        receiver_identity = ""
        if callee.type == "identifier":
            resolved = self._lookup(callee)
            if resolved is None:
                return None
            module, symbol, receiver = resolved.module, resolved.member, ""
        elif callee.type == "member_expression":
            obj = callee.child_by_field_name("object")
            prop = callee.child_by_field_name("property")
            base = self._resolve(obj) if obj is not None else None
            if base is None or prop is None:
                return None
            module, member = base.module, base.member
            # A member of the module export is the imported symbol itself, so
            # `new amqp.Worker()` and an imported `new Worker()` are one role.
            symbol = _text(prop)
            receiver = "" if member == _MODULE_EXPORT else member
            receiver_identity = base.identity if receiver else ""
        elif callee.type == "call_expression":
            # Support direct module factories such as `require('socket.io')()`;
            # only a literal, trusted requested module can establish this role.
            module = self._require_module(callee)
            if not module:
                return None
            symbol, receiver = _MODULE_EXPORT, ""
        else:
            return None
        return JsBoundCall(
            module,
            symbol,
            is_new,
            receiver,
            _arg_tokens(node),
            receiver_identity,
        )


def _execution_scope(name_node) -> tuple[int, int]:
    """Nearest program/function body whose statements share execution order."""
    node = name_node
    while node is not None:
        if node.type in _EXECUTION_SCOPE_TYPES:
            return node.start_byte, node.end_byte
        node = node.parent
    return (0, 0)


def _is_in_dynamic_scope(node) -> bool:
    """Whether a JavaScript `with` statement can intercept this lookup/call."""
    current = node
    while current is not None:
        if current.type == "with_statement":
            return True
        current = current.parent
    return False


_UNPROVEN_CALL_ANCESTORS = _UNCERTAIN_WRITE_ANCESTORS | frozenset(
    _EXECUTION_SCOPE_TYPES - {"program"}
) | frozenset({"class", "class_declaration", "class_static_block"})
_LAZY_BINARY_OPERATORS = frozenset({"&&", "||", "??"})


def _is_lazy_binary_rhs(node, binary) -> bool:
    """Whether a node sits in a short-circuiting binary expression's RHS."""
    operator = binary.child_by_field_name("operator")
    right = binary.child_by_field_name("right")
    return (
        operator is not None
        and _text(operator) in _LAZY_BINARY_OPERATORS
        and right is not None
        and right.start_byte <= node.start_byte
        and node.end_byte <= right.end_byte
    )


def _is_proven_top_level_execution(node) -> bool:
    """Whether a call is evaluated unconditionally during module initialization."""
    candidate = node
    current = node.parent
    while current is not None:
        if current.type in _UNPROVEN_CALL_ANCESTORS:
            return False
        if current.type == "binary_expression" and _is_lazy_binary_rhs(
            candidate, current
        ):
            return False
        if current.type == "program":
            return True
        current = current.parent
    return False


def _execution_scope_is_program(node) -> bool:
    """Whether a name is evaluated directly in the module program scope."""
    while node is not None:
        if node.type in _EXECUTION_SCOPE_TYPES:
            return node.type == "program"
        node = node.parent
    return False


def _is_definite_binding_write(name_node, declaration: _Declaration) -> bool:
    """Whether this source write can prove the declaration's role at lookup."""
    execution_scope = _execution_scope(name_node)
    if execution_scope != declaration.execution_scope:
        return False
    node = name_node.parent
    while node is not None:
        if (node.start_byte, node.end_byte) == execution_scope:
            return True
        if node.type in _UNCERTAIN_WRITE_ANCESTORS:
            return False
        if node.type == "binary_expression" and _is_lazy_binary_rhs(
            name_node, node
        ):
            return False
        node = node.parent
    return False


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
    if declaration is None or not re.match(r"\s*var\b", _text(declaration)):
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


def _loop_binding_keyword(node) -> str:
    """`const`/`let`/`var` token introducing a for-in/of loop target."""
    target = node.child_by_field_name("left")
    if target is None:
        return ""
    for child in node.children:
        if child.start_byte >= target.start_byte:
            break
        if child.type in {"const", "let", "var"}:
            return child.type
    return ""


def _loop_binding_scope(node, keyword: str) -> tuple[int, int]:
    """Lexical loop scope, or var's containing function/program scope."""
    if keyword != "var":
        return node.start_byte, node.end_byte
    parent = node.parent
    while parent is not None:
        if parent.type in {
            "program",
            "arrow_function",
            "function",
            "function_declaration",
            "function_expression",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
        }:
            return parent.start_byte, parent.end_byte
        parent = parent.parent
    return node.start_byte, node.end_byte


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


def _member_write_base(node):
    """Resolved base expression mutated by a member/subscript assignment target."""
    current = node
    saw_member = False
    while current is not None and current.type in {
        "member_expression",
        "subscript_expression",
    }:
        saw_member = True
        current = current.child_by_field_name("object")
    return current if saw_member else None


def _member_write_bases(node):
    """Resolved member roots nested anywhere in an assignment target pattern."""
    if node.type in {"member_expression", "subscript_expression"}:
        base = _member_write_base(node)
        if base is not None:
            yield base
        return
    for child in node.named_children:
        yield from _member_write_bases(child)


def _written_binding_names(node):
    """Binding roots invalidated by an assignment target.

    Patterns write their named bindings directly. A member/subscript write does
    not introduce a name, but mutates the root object; revoking that root keeps
    a replaced API method/export from impersonating a trusted runtime surface.
    """
    names = tuple(_pattern_names(node))
    if names:
        yield from names
        return
    root = node
    while root is not None and root.type in {"member_expression", "subscript_expression"}:
        root = root.child_by_field_name("object")
    if root is not None and root.type == "identifier":
        yield root


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


def _literal_arg(args: tuple[tuple[str, str], ...], index: int) -> str:
    """Quoted-literal value at `index`, or an empty string when it is dynamic."""
    if index >= len(args):
        return ""
    kind, value = args[index]
    return value if kind == "str" else ""


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


def _is_type_only_import(node) -> bool:
    """Whether a TypeScript import declaration is erased before runtime."""
    return bool(re.match(r"\s*import\s+type\b", _text(node)))


def _is_type_only_import_specifier(node) -> bool:
    """Whether one named import is prefixed with TypeScript's `type` modifier."""
    return bool(re.match(r"\s*type\b", _text(node)))


def _runtime_import_names(node) -> list:
    """Local value names introduced by a parsed, non-type import declaration."""
    names = []
    for clause in node.named_children:
        if clause.type == "import_require_clause":
            if clause.named_children and clause.named_children[0].type == "identifier":
                names.append(clause.named_children[0])
        if clause.type != "import_clause":
            continue
        for child in clause.named_children:
            if child.type == "identifier":
                names.append(child)
            elif child.type == "namespace_import":
                names.extend(child.named_children)
            elif child.type == "named_imports":
                for spec in child.named_children:
                    if (
                        spec.type != "import_specifier"
                        or _is_type_only_import_specifier(spec)
                    ):
                        continue
                    name_node = spec.child_by_field_name("name")
                    alias = spec.child_by_field_name("alias")
                    if name_node is not None:
                        names.append(alias or name_node)
    return names


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
