"""PHP / Laravel parser using tree-sitter.

Extracts: functions, classes, methods, traits, interfaces, enums (PHP 8.1),
constants, class properties — with PHPDoc comments, body previews,
PHP 8 attribute extraction, visibility modifiers, and Laravel route detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from .base import ParsedFile, Symbol

try:
    from tree_sitter import Language, Parser
    import tree_sitter_php as tsphp

    PHP_LANGUAGE = Language(tsphp.language_php())
    _TS_AVAILABLE = True
except Exception:
    Parser = None  # type: ignore[assignment]
    _TS_AVAILABLE = False


@dataclass(frozen=True)
class PhpDispatch:
    """A Laravel helper/API target and its parser-proven relation."""

    target: str
    relation: str = "dispatch"


@dataclass(frozen=True)
class PhpClassDeclaration:
    """A parser-proven PHP class and its runtime-relevant structural metadata."""

    name: str
    target: str
    interfaces: tuple[str, ...] = ()
    queue: str = ""
    has_handle: bool = False
    handle_event: str = ""
    uses_dispatchable: bool = False


@dataclass(frozen=True)
class PhpSchedule:
    """One complete `$schedule` chain proven by the PHP grammar."""

    kind: str
    target: str
    cron: str


@lru_cache(maxsize=256)
def _php_root(content: str):
    """One bounded, complete PHP syntax tree shared by runtime extractors."""
    if not _TS_AVAILABLE or Parser is None:
        return None
    root = Parser(PHP_LANGUAGE).parse(content.encode("utf8")).root_node
    return None if root.has_error else root


def php_dispatches(content: str) -> tuple[PhpDispatch, ...]:
    """Return structural Laravel `dispatch`/`event` target expressions only.

    The helper deliberately accepts just the grammar shapes DeepDoc can prove:
    ``Class::dispatch(...)``, ``dispatch(Class::class)``, and
    ``dispatch/event(new Class(...))``. Comments, strings, dynamic values, and
    arbitrary methods never reach the runtime linker.
    """
    root = _php_root(content)
    # Error-recovery syntax does not prove a PHP dispatch, even when it happens
    # to contain a recognizable partial call subtree.
    if root is None:
        return ()
    found: list[PhpDispatch] = []

    def visit(
        node,
        import_aliases: dict[str, str],
        shadowed_helpers: frozenset[str],
        namespace: str,
    ) -> None:
        if node.type == "namespace_definition":
            body = node.child_by_field_name("body")
            if body is not None:
                scope_nodes = tuple(body.named_children)
                aliases = _php_import_aliases_from_nodes(scope_nodes)
                shadows = _php_shadowed_helpers_from_nodes(scope_nodes)
                nested_namespace = _php_namespace_name(node)
                for child in scope_nodes:
                    visit(child, aliases, shadows, nested_namespace)
            return
        if node.type == "scoped_call_expression":
            name = node.child_by_field_name("name")
            target = (
                _php_class_target(node.named_children[0], import_aliases, namespace)
                if node.named_children
                and name is not None
                and name.text.lower() == b"dispatch"
                else ""
            )
            if target:
                found.append(PhpDispatch(target, "dispatch"))
        elif node.type == "function_call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            helper = _php_unshadowed_helper_name(function, shadowed_helpers)
            if helper and arguments is not None and arguments.named_children:
                target = _php_dispatch_argument_target(
                    arguments.named_children[0], import_aliases, namespace
                )
                if target:
                    found.append(PhpDispatch(target, helper))
        for child in node.named_children:
            visit(child, import_aliases, shadowed_helpers, namespace)

    for namespace, scope_nodes in _php_top_level_scopes(root):
        aliases = _php_import_aliases_from_nodes(scope_nodes)
        shadows = _php_shadowed_helpers_from_nodes(scope_nodes)
        for node in scope_nodes:
            visit(node, aliases, shadows, namespace)
    return tuple(found)


def php_class_declarations(content: str) -> tuple[PhpClassDeclaration, ...]:
    """Return strict parser-proven PHP classes with structural runtime metadata."""
    root = _php_root(content)
    if root is None:
        return ()
    found: list[PhpClassDeclaration] = []
    for namespace, scope_nodes in _php_top_level_scopes(root):
        aliases = _php_import_aliases_from_nodes(scope_nodes)
        for node in scope_nodes:
            if node.type != "class_declaration":
                continue
            name = node.child_by_field_name("name")
            if name is None:
                continue
            target = _php_class_target(name, {}, namespace)
            if target:
                found.append(
                    PhpClassDeclaration(
                        name=name.text.decode("utf8", "replace"),
                        target=target,
                        interfaces=_php_class_interfaces(node, aliases, namespace),
                        queue=_php_class_queue(node),
                        has_handle=_php_has_handle(node),
                        handle_event=_php_handle_event(node, aliases, namespace),
                        uses_dispatchable=_php_class_uses_dispatchable(
                            node, aliases, namespace
                        ),
                    )
                )
    return tuple(found)


_LARAVEL_SCHEDULE_TYPE = r"Illuminate\Console\Scheduling\Schedule"
_LARAVEL_CONSOLE_KERNEL_TYPE = r"Illuminate\Foundation\Console\Kernel"


def php_schedules(content: str) -> tuple[PhpSchedule, ...]:
    """Return Laravel schedules from a parser-proven Kernel schedule method.

    A `$schedule` spelling alone proves nothing. Facts require a complete PHP
    tree, a class extending Laravel's Console Kernel, and a real `schedule()`
    parameter typed as Laravel's Scheduler. This keeps generic PHP APIs from
    manufacturing scheduler relationships.
    """
    root = _php_root(content)
    if root is None:
        return ()
    found: list[PhpSchedule] = []
    for namespace, scope_nodes in _php_top_level_scopes(root):
        aliases = _php_import_aliases_from_nodes(scope_nodes)
        for declaration in scope_nodes:
            if (
                declaration.type != "class_declaration"
                or _php_class_base(declaration, aliases, namespace).lower()
                != _LARAVEL_CONSOLE_KERNEL_TYPE.lower()
            ):
                continue
            for method in _php_laravel_schedule_methods(declaration, aliases, namespace):
                body = method.child_by_field_name("body")
                if body is not None:
                    _php_collect_schedule_calls(
                        body,
                        aliases,
                        namespace,
                        found,
                        _php_schedule_reassignment_positions(body),
                    )
    return tuple(found)


def _php_class_base(node, aliases: dict[str, str], namespace: str) -> str:
    """Canonical direct class base from one parser-proven `extends` clause."""
    clause = next(
        (child for child in node.named_children if child.type == "base_clause"), None
    )
    if clause is None:
        return ""
    base = next(
        (
            child
            for child in clause.named_children
            if child.type in {"name", "qualified_name"}
        ),
        None,
    )
    return _php_class_target(base, aliases, namespace) if base is not None else ""


def _php_laravel_schedule_methods(node, aliases: dict[str, str], namespace: str) -> tuple:
    """Kernel methods with an exact typed Laravel `$schedule` parameter."""
    methods = []
    for body in node.named_children:
        if body.type != "declaration_list":
            continue
        for method in body.named_children:
            if method.type != "method_declaration":
                continue
            name = method.child_by_field_name("name")
            if name is None or name.text.lower() != b"schedule":
                continue
            parameters = method.child_by_field_name("parameters")
            if parameters is None:
                continue
            for parameter in parameters.named_children:
                if parameter.type != "simple_parameter":
                    continue
                variable = parameter.child_by_field_name("name")
                type_node = parameter.child_by_field_name("type")
                named_type = (
                    type_node.named_children[0]
                    if type_node is not None and type_node.named_children
                    else None
                )
                schedule_type = (
                    _php_class_target(named_type, aliases, namespace)
                    if named_type is not None
                    else ""
                )
                if (
                    variable is not None
                    and variable.text.lower() == b"$schedule"
                    and schedule_type.lower() == _LARAVEL_SCHEDULE_TYPE.lower()
                ):
                    methods.append(method)
                    break
    return tuple(methods)


_PHP_NESTED_FUNCTION_TYPES = frozenset({"anonymous_function", "arrow_function"})


def _php_schedule_target_is_rebound(target) -> bool:
    """Whether one assignment target writes the trusted `$schedule` binding."""
    if target.type == "variable_name":
        return target.text.lower() == b"$schedule"
    if target.type in {"list_literal", "pair", "by_ref"}:
        return any(
            _php_schedule_target_is_rebound(child)
            for child in target.named_children
        )
    return False


def _php_invoked_by_ref_schedule_closure(node) -> bool:
    """An immediately invoked closure that can rebind the caller's `$schedule`.

    Only a `use (&$schedule)` capture reaches the outer binding; a by-value
    capture or an uninvoked closure leaves the typed parameter intact.
    """
    if node.type != "function_call_expression":
        return False
    callee = node.child_by_field_name("function")
    closure = _php_unwrap_anonymous_function(callee)
    if closure is None:
        return False
    return _php_by_ref_schedule_closure_rebinds(closure)


def _php_unwrap_anonymous_function(node):
    """The anonymous function behind any number of grouping parentheses."""
    current = node
    while current is not None and current.type == "parenthesized_expression":
        current = next(iter(current.named_children), None)
    return current if current is not None and current.type == "anonymous_function" else None


def _php_by_ref_schedule_closure_rebinds(closure) -> bool:
    """Whether an anonymous closure captures and rebinds outer ``$schedule``."""
    captured_by_ref = any(
        capture.type == "by_ref" and _php_schedule_target_is_rebound(capture)
        for clause in closure.named_children
        if clause.type == "anonymous_function_use_clause"
        for capture in clause.named_children
    )
    body = closure.child_by_field_name("body")
    if not captured_by_ref or body is None:
        return False
    return bool(_php_schedule_reassignment_positions(body))


def _php_schedule_reassignment_positions(node) -> tuple[int, ...]:
    """Direct-method writes that revoke the typed `$schedule` parameter."""
    positions: list[int] = []
    closure_bindings: set[bytes] = set()

    def visit(current) -> None:
        if current.type in _PHP_NESTED_FUNCTION_TYPES:
            return
        if _php_invoked_by_ref_schedule_closure(current):
            positions.append(current.start_byte)
        if current.type == "function_call_expression":
            function = current.child_by_field_name("function")
            if function is not None and function.type == "variable_name":
                if function.text.lower() in closure_bindings:
                    positions.append(current.start_byte)
            elif function is not None and function.text.lower() == b"call_user_func":
                arguments = current.child_by_field_name("arguments")
                first = arguments.named_children[0] if arguments and arguments.named_children else None
                candidate = (
                    first.named_children[0]
                    if first is not None and first.type == "argument" and first.named_children
                    else first
                )
                closure = _php_unwrap_anonymous_function(candidate)
                if closure is not None and _php_by_ref_schedule_closure_rebinds(closure):
                    positions.append(current.start_byte)
        if current.type == "foreach_statement":
            body = current.child_by_field_name("body")
            bindings = [
                child for child in current.named_children if child != body
            ]
            target = bindings[-1] if len(bindings) >= 2 else None
            if target is not None and _php_schedule_target_is_rebound(target):
                positions.append(current.start_byte)
        if current.type in {"assignment_expression", "reference_assignment_expression"}:
            target = current.child_by_field_name("left")
            if target is not None and _php_schedule_target_is_rebound(target):
                # The RHS executes before the assignment changes `$schedule`.
                positions.append(current.end_byte)
            value = current.child_by_field_name("right")
            closure = _php_unwrap_anonymous_function(value)
            if (
                target is not None
                and target.type == "variable_name"
                and closure is not None
                and _php_by_ref_schedule_closure_rebinds(closure)
            ):
                closure_bindings.add(target.text.lower())
        if current.type == "catch_clause":
            name = current.child_by_field_name("name")
            if name is not None and _php_schedule_target_is_rebound(name):
                positions.append(current.start_byte)
        if current.type in {"unset_statement", "global_declaration"} and any(
            _php_schedule_target_is_rebound(child) for child in current.named_children
        ):
            positions.append(current.start_byte)
        for child in current.named_children:
            visit(child)

    visit(node)
    return tuple(sorted(positions))


def _php_collect_schedule_calls(
    node,
    aliases: dict[str, str],
    namespace: str,
    found: list[PhpSchedule],
    reassignment_positions: tuple[int, ...],
) -> None:
    """Collect chains through the original, un-reassigned Kernel parameter."""
    if node.type in _PHP_NESTED_FUNCTION_TYPES:
        return
    if (
        node.type == "member_call_expression"
        and not _php_is_chained_member_call(node)
        and not any(position < node.start_byte for position in reassignment_positions)
    ):
        schedule = _php_schedule_from_call(node, aliases, namespace)
        if schedule is not None:
            found.append(schedule)
    for child in node.named_children:
        _php_collect_schedule_calls(
            child, aliases, namespace, found, reassignment_positions
        )


def _php_class_uses_dispatchable(node, aliases: dict[str, str], namespace: str) -> bool:
    """Whether a class uses Laravel's Dispatchable trait."""
    for body in node.named_children:
        if body.type != "declaration_list":
            continue
        for declaration in body.named_children:
            if declaration.type != "use_declaration":
                continue
            for trait in declaration.named_children:
                if (
                    _php_class_target(trait, aliases, namespace).lower()
                    == r"Illuminate\Foundation\Events\Dispatchable".lower()
                ):
                    return True
    return False


def _php_class_interfaces(node, aliases: dict[str, str], namespace: str) -> tuple[str, ...]:
    """Canonical interfaces named by one parser-proven class declaration."""
    interfaces: list[str] = []
    for clause in node.named_children:
        if clause.type != "class_interface_clause":
            continue
        for interface in clause.named_children:
            target = _php_class_target(interface, aliases, namespace)
            if target:
                interfaces.append(target)
    return tuple(interfaces)


def _php_class_queue(node) -> str:
    """Literal public/protected `$queue` property from one class AST."""
    for body in node.named_children:
        if body.type != "declaration_list":
            continue
        for declaration in body.named_children:
            if declaration.type != "property_declaration":
                continue
            visibility = {
                child.text.decode("utf8", "replace").lower()
                for child in declaration.named_children
                if child.type == "visibility_modifier"
            }
            if not visibility & {"public", "protected"}:
                continue
            for element in declaration.named_children:
                if element.type != "property_element":
                    continue
                parts = element.named_children
                variable = next(
                    (part for part in parts if part.type == "variable_name"), None
                )
                value = next((part for part in parts if part.type == "string"), None)
                if (
                    variable is not None
                    and variable.text == b"$queue"
                    and value is not None
                ):
                    return _php_string_literal(value)
    return ""


def _php_has_handle(node) -> bool:
    """Whether a class has a real method declaration named `handle`."""
    for body in node.named_children:
        if body.type != "declaration_list":
            continue
        for method in body.named_children:
            if method.type != "method_declaration":
                continue
            name = method.child_by_field_name("name")
            if name is not None and name.text.lower() == b"handle":
                return True
    return False


def _php_handle_event(node, aliases: dict[str, str], namespace: str) -> str:
    """Canonical first parameter type of a real `handle` method, if present."""
    for body in node.named_children:
        if body.type != "declaration_list":
            continue
        for method in body.named_children:
            if method.type != "method_declaration":
                continue
            name = method.child_by_field_name("name")
            if name is None or name.text.lower() != b"handle":
                continue
            parameters = next(
                (child for child in method.named_children if child.type == "formal_parameters"),
                None,
            )
            if parameters is None:
                continue
            parameter = next(
                (child for child in parameters.named_children if child.type == "simple_parameter"),
                None,
            )
            if parameter is None:
                continue
            named_type = next(
                (child for child in parameter.named_children if child.type == "named_type"),
                None,
            )
            type_name = (
                named_type.named_children[0]
                if named_type is not None and named_type.named_children
                else None
            )
            target = (
                _php_class_target(type_name, aliases, namespace)
                if type_name is not None
                else ""
            )
            return target
    return ""


def _php_is_chained_member_call(node) -> bool:
    """Whether `node` is the object of a larger member-call chain."""
    parent = node.parent
    return (
        parent is not None
        and parent.type == "member_call_expression"
        and parent.child_by_field_name("object") is node
    )


def _php_schedule_from_call(node, aliases: dict[str, str], namespace: str) -> PhpSchedule | None:
    """Interpret one complete parsed `$schedule` method chain, or fail closed."""
    chain: list[tuple[str, object]] = []
    current = node
    while current is not None and current.type == "member_call_expression":
        name = current.child_by_field_name("name")
        arguments = current.child_by_field_name("arguments")
        if name is None or arguments is None:
            return None
        chain.append((name.text.decode("utf8", "replace").lower(), arguments))
        current = current.child_by_field_name("object")
    if (
        current is None
        or current.type != "variable_name"
        or current.text.lower() != b"$schedule"
        or len(chain) < 2
    ):
        return None
    chain.reverse()
    kind, arguments = chain[0]
    if kind not in {"command", "job", "call"}:
        return None
    cadence = _php_schedule_cadence(chain[1:])
    if not cadence:
        return None
    argument = _php_first_argument(arguments)
    if kind == "command":
        target = _php_string_literal(argument)
    elif kind == "job":
        target = _php_schedule_job_target(argument, aliases, namespace)
    else:
        target = "closure"
    return PhpSchedule(kind, target, cadence) if target else None


def _php_first_argument(arguments):
    """First grammar argument expression, never text-scanned source."""
    if arguments is None or not arguments.named_children:
        return None
    argument = arguments.named_children[0]
    return argument.named_children[0] if argument.type == "argument" and argument.named_children else argument


def _php_string_literal(node) -> str:
    """One parser-proven static PHP string literal, without delimiters."""
    if node is None or node.type not in {"string", "encapsed_string"}:
        return ""
    if node.type == "encapsed_string" and any(
        child.type != "string_content" for child in node.named_children
    ):
        return ""
    text = node.text.decode("utf8", "replace")
    return text[1:-1] if len(text) >= 2 and text[0] in "\"'" else ""


def _php_schedule_job_target(node, aliases: dict[str, str], namespace: str) -> str:
    """Canonical target of `$schedule->job(new Job(...))`, or empty."""
    if node is None or node.type != "object_creation_expression" or not node.named_children:
        return ""
    return _php_class_target(node.named_children[0], aliases, namespace)


_LARAVEL_CADENCE_METHODS = frozenset(
    {
        "cron",
        "everysecond",
        "everytwoseconds",
        "everyfiveseconds",
        "everytenseconds",
        "everyfifteenseconds",
        "everytwentyseconds",
        "everythirtyseconds",
        "everyminute",
        "everytwominutes",
        "everythreeminutes",
        "everyfourminutes",
        "everyfiveminutes",
        "everytenminutes",
        "everyfifteenminutes",
        "everythirtyminutes",
        "hourly",
        "hourlyat",
        "daily",
        "dailyat",
        "twicedaily",
        "twicedailyat",
        "weekly",
        "weeklyon",
        "monthly",
        "monthlyon",
        "twicemonthly",
        "lastdayofmonth",
        "quarterly",
        "quarterlyon",
        "yearly",
        "yearlyon",
    }
)


def _php_schedule_cadence(chain: list[tuple[str, object]]) -> str:
    """Stable summary of an explicit, parser-proven Laravel cadence method."""
    for method, arguments in chain:
        if method not in _LARAVEL_CADENCE_METHODS:
            continue
        value = _php_string_literal(_php_first_argument(arguments))
        if method == "cron":
            return value
        return f"{method}({value})" if value else method
    return ""


_LARAVEL_HELPER_NAMES = frozenset({"dispatch", "event"})


def _php_scope_children(scope):
    """Immediate declarations belonging to one global or namespace scope."""
    if scope.type == "namespace_definition":
        body = scope.child_by_field_name("body")
        return body.named_children if body is not None else scope.named_children
    return scope.named_children


def _php_namespace_name(node) -> str:
    """Canonical namespace text for one tree-sitter namespace definition."""
    name = node.child_by_field_name("name")
    return name.text.decode("utf8", "replace").strip().lstrip("\\") if name else ""


def _php_top_level_scopes(root) -> tuple[tuple[str, tuple], ...]:
    """Segment global, braced, and semicolon namespaces into lexical ranges."""
    scopes: list[tuple[str, tuple]] = []
    current_namespace = ""
    current: list = []
    for child in root.named_children:
        if child.type != "namespace_definition":
            current.append(child)
            continue
        body = child.child_by_field_name("body")
        if current:
            scopes.append((current_namespace, tuple(current)))
            current = []
        if body is not None:
            scopes.append((_php_namespace_name(child), tuple(body.named_children)))
            current_namespace = ""
        else:
            current_namespace = _php_namespace_name(child)
    if current:
        scopes.append((current_namespace, tuple(current)))
    return tuple(scopes)


def _php_import_aliases(scope) -> dict[str, str]:
    """Validated class-import aliases owned directly by one PHP namespace scope."""
    return _php_import_aliases_from_nodes(_php_scope_children(scope))


def _php_import_aliases_from_nodes(candidates) -> dict[str, str]:
    """Validated class-import aliases for an already-isolated lexical scope."""
    aliases: dict[str, str] = {}
    for node in candidates:
        if node.type != "namespace_use_declaration":
            continue
        declaration = node.text.decode("utf8", "replace")
        # `use function` and `use const` do not define dispatchable classes.
        if re.match(r"\s*use\s+(?:function|const)\b", declaration):
            continue
        children = node.named_children
        group = next(
            (child for child in children if child.type == "namespace_use_group"),
            None,
        )
        prefix_node = next(
            (child for child in children if child.type == "namespace_name"),
            None,
        )
        prefix = (
            prefix_node.text.decode("utf8", "replace").strip().lstrip("\\")
            if prefix_node is not None
            else ""
        )
        clauses = (
            group.named_children
            if group is not None
            else [
                child
                for child in children
                if child.type == "namespace_use_clause"
            ]
        )
        for clause in clauses:
            if clause.type != "namespace_use_clause":
                continue
            clause_text = clause.text.decode("utf8", "replace")
            if re.match(r"\s*(?:function|const)\b", clause_text):
                continue
            names = [
                child
                for child in clause.named_children
                if child.type in {"name", "qualified_name"}
            ]
            if not names:
                continue
            target = _php_class_target(names[0], {})
            if not target:
                continue
            if group is not None and prefix:
                target = f"{prefix}\\{target}"
            alias = (
                names[-1].text.decode("utf8", "replace")
                if len(names) > 1
                else target.rsplit("\\", 1)[-1]
            )
            if alias:
                aliases[alias.lower()] = target
    return aliases


def _php_shadowed_helpers(scope) -> frozenset[str]:
    """Laravel helper names rebound by imports or declarations in this namespace."""
    return _php_shadowed_helpers_from_nodes(_php_scope_children(scope))


def _php_shadowed_helpers_from_nodes(children) -> frozenset[str]:
    """Laravel helper shadows within an already-isolated lexical scope."""
    shadows: set[str] = set()
    for node in children:
        if node.type == "namespace_use_declaration":
            shadows.update(_php_function_import_aliases(node))
    stack = list(reversed(children))
    while stack:
        node = stack.pop()
        if node.type == "namespace_definition":
            continue
        if node.type == "function_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                helper = name.text.decode("utf8", "replace").strip().lower()
                if helper in _LARAVEL_HELPER_NAMES:
                    shadows.add(helper)
        stack.extend(reversed(node.named_children))
    return frozenset(shadows & _LARAVEL_HELPER_NAMES)


def _php_function_import_aliases(declaration) -> set[str]:
    """Local spellings established by a structural ``use function`` declaration."""
    declaration_text = declaration.text.decode("utf8", "replace")
    declaration_is_function = bool(
        re.match(r"\s*use\s+function\b", declaration_text)
    )
    children = declaration.named_children
    group = next(
        (child for child in children if child.type == "namespace_use_group"),
        None,
    )
    clauses = (
        group.named_children
        if group is not None
        else [
            child for child in children if child.type == "namespace_use_clause"
        ]
    )
    aliases: set[str] = set()
    for clause in clauses:
        if clause.type != "namespace_use_clause":
            continue
        clause_text = clause.text.decode("utf8", "replace")
        if not declaration_is_function and not re.match(
            r"\s*function\b", clause_text
        ):
            continue
        names = [
            child
            for child in clause.named_children
            if child.type in {"name", "qualified_name"}
        ]
        if not names:
            continue
        alias = (
            names[-1].text.decode("utf8", "replace")
            if len(names) > 1
            else names[0].text.decode("utf8", "replace").rsplit("\\", 1)[-1]
        )
        if alias:
            aliases.add(alias.lower())
    return aliases


def _php_unshadowed_helper_name(function, shadows: frozenset[str]) -> str:
    """A bare unshadowed or explicitly rooted Laravel global helper name."""
    if function is None:
        return ""
    raw_name = function.text.decode("utf8", "replace").strip()
    if function.type == "qualified_name" and raw_name.startswith("\\"):
        rooted = raw_name.lstrip("\\").lower()
        return rooted if rooted in _LARAVEL_HELPER_NAMES else ""
    if function.type != "name":
        return ""
    name = raw_name.lower()
    return name if name in _LARAVEL_HELPER_NAMES and name not in shadows else ""


def _php_dispatch_argument_target(
    node, import_aliases: dict[str, str], namespace: str
) -> str:
    """Canonical class target in a Laravel helper's first argument."""
    while node.type == "argument" and node.named_children:
        node = node.named_children[0]
    if node.type == "class_constant_access_expression":
        children = node.named_children
        if len(children) >= 2 and children[-1].text.lower() == b"class":
            return _php_class_target(children[0], import_aliases, namespace)
    if node.type == "object_creation_expression" and node.named_children:
        return _php_class_target(node.named_children[0], import_aliases, namespace)
    return ""


def _php_class_target(
    node, import_aliases: dict[str, str], namespace: str = ""
) -> str:
    """Canonical PHP class identity through imports and lexical namespace."""
    if node.type not in {"name", "qualified_name"}:
        return ""
    raw_target = node.text.decode("utf8", "replace").strip()
    absolute = raw_target.startswith("\\")
    target = raw_target.lstrip("\\")
    if not target:
        return ""
    parts = target.split("\\")
    alias_target = import_aliases.get(parts[0].lower())
    if alias_target:
        return "\\".join((alias_target, *parts[1:]))
    if absolute or not namespace:
        return target
    return f"{namespace}\\{target}"


def parse_php(path: Path, content: str, language: str) -> ParsedFile:
    symbols: list[Symbol] = []
    imports: list[str] = []

    if _TS_AVAILABLE and Parser is not None:
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
        raw_content=content[:12000],
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
            symbols.append(
                Symbol(
                    name=name,
                    kind="function",
                    signature=lines[node.start_point[0]].strip()
                    if node.start_point[0] < len(lines)
                    else "",
                    docstring=doc,
                    body_preview=_body_preview(node, lines),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    decorators=attrs,
                    is_exported=True,  # PHP functions are always accessible
                )
            )
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


def _extract_class_like(
    node, node_type: str, lines: list[str], symbols: list[Symbol]
) -> None:
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
                    prop_line = (
                        lines[member.start_point[0]].strip()
                        if member.start_point[0] < len(lines)
                        else ""
                    )
                    if prop_line:
                        class_fields.append(prop_line.rstrip(";"))

    symbols.append(
        Symbol(
            name=name,
            kind=kind,
            signature=lines[node.start_point[0]].strip()
            if node.start_point[0] < len(lines)
            else "",
            docstring=doc,
            body_preview=_body_preview(node, lines, max_lines=8),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            decorators=attrs,
            is_exported=True,
            fields=class_fields[:20],
        )
    )

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

    symbols.append(
        Symbol(
            name=name,
            kind="method",
            signature=lines[node.start_point[0]].strip()
            if node.start_point[0] < len(lines)
            else "",
            docstring=doc,
            body_preview=_body_preview(node, lines),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            decorators=attrs,
            visibility=visibility,
        )
    )


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
                        case_line = (
                            lines[member.start_point[0]].strip()
                            if member.start_point[0] < len(lines)
                            else ""
                        )
                        cases.append(case_line.rstrip(";"))

    symbols.append(
        Symbol(
            name=name,
            kind="enum",
            signature=lines[node.start_point[0]].strip()
            if node.start_point[0] < len(lines)
            else "",
            docstring=doc,
            body_preview=_body_preview(node, lines, max_lines=min(len(cases) + 3, 15)),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            decorators=attrs,
            is_exported=True,
            fields=cases[:30],
        )
    )

    # Also extract methods inside the enum
    for child in node.children:
        if child.type in ("enum_declaration_list", "declaration_list"):
            for member in child.children:
                if member.type == "method_declaration":
                    _extract_method(member, lines, symbols)


# ─────────────────────────────────────────────────────────────────────────────
# Constant extraction
# ─────────────────────────────────────────────────────────────────────────────


def _extract_const_declaration(
    node, lines: list[str], symbols: list[Symbol], visibility: str = ""
) -> None:
    """Extract class constants or global constants."""
    doc = _get_phpdoc(node, lines)
    if not visibility:
        visibility = _get_visibility(node, lines)

    for child in node.children:
        if child.type == "const_element":
            name_node = child.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, lines)
                sig = (
                    lines[node.start_point[0]].strip()
                    if node.start_point[0] < len(lines)
                    else ""
                )
                symbols.append(
                    Symbol(
                        name=name,
                        kind="constant",
                        signature=sig.rstrip(";"),
                        docstring=doc,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        visibility=visibility or "public",
                        is_exported=True,
                    )
                )


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
            elif (
                line == ""
                or line.startswith("*")
                or line.startswith("/**")
                or line.endswith("*/")
            ):
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
    content.splitlines()
    for m in pattern.finditer(content):
        method, uri = m.group(1).upper(), m.group(2)
        line_num = content[: m.start()].count("\n") + 1

        # Try to extract middleware from chained ->middleware() call
        middleware = []
        region = content[m.start() : m.start() + 500]
        mw_match = re.search(r"->middleware\s*\(\s*\[?([^\])\n]+)", region)
        if mw_match:
            middleware = [
                mw.strip().strip("'\"") for mw in mw_match.group(1).split(",")
            ]

        routes.append(
            Symbol(
                name=f"{method} {uri}",
                kind="route",
                signature=m.group(0),
                start_line=line_num,
                end_line=line_num,
                decorators=middleware,  # Store middleware as "decorators" for display
            )
        )
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
            symbols.append(
                Symbol(
                    name=name,
                    kind="enum",
                    signature=stripped,
                    docstring=pending_doc,
                    body_preview="\n".join(lines[i : i + min(len(cases) + 3, 15)]),
                    start_line=i + 1,
                    decorators=pending_attrs,
                    fields=cases[:20],
                    is_exported=True,
                )
            )
            pending_doc = ""
            pending_attrs = []
            continue

        # Class / trait / interface
        m = re.match(
            r"(?:abstract\s+)?(?:final\s+)?(class|trait|interface)\s+(\w+)", stripped
        )
        if m:
            kind_str = m.group(1)
            name = m.group(2)
            kind = (
                "class"
                if kind_str == "class"
                else ("interface" if kind_str == "interface" else "type")
            )
            symbols.append(
                Symbol(
                    name=name,
                    kind=kind,
                    signature=stripped,
                    docstring=pending_doc,
                    body_preview="\n".join(lines[i : i + 5]),
                    start_line=i + 1,
                    decorators=pending_attrs,
                    is_exported=True,
                )
            )
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
            symbols.append(
                Symbol(
                    name=name,
                    kind=kind,
                    signature=stripped,
                    docstring=pending_doc,
                    body_preview="\n".join(lines[i : i + 5]),
                    start_line=i + 1,
                    decorators=pending_attrs,
                    visibility=visibility,
                )
            )
            pending_doc = ""
            pending_attrs = []
            continue

        # Class constants
        m = re.match(r"(?:public|protected|private)?\s*const\s+(\w+)\s*=", stripped)
        if m and in_class:
            name = m.group(1)
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=stripped.rstrip(";"),
                    docstring=pending_doc,
                    start_line=i + 1,
                    end_line=i + 1,
                    is_exported=True,
                )
            )
            pending_doc = ""
            pending_attrs = []
            continue

        # Reset on non-comment non-blank non-attr lines
        if stripped and not stripped.startswith(("*", "//", "#[")):
            pending_doc = ""
            pending_attrs = []

    return symbols, imports
