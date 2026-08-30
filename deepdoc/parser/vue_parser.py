"""Vue Single File Component (.vue) parser.

Extracts the <script> or <script setup> block from .vue files, then delegates
to the JS/TS parser for symbol extraction. Additionally detects Vue-specific
constructs:
  - defineProps() / withDefaults() for component props
  - defineEmits() for emitted events
  - defineExpose() for exposed methods
  - Composition API: ref, reactive, computed, watch, onMounted, etc.
  - Options API: data, methods, computed, watch, props, emits
  - Composables (useXxx imports)

Supports both <script setup> (Composition API) and <script> (Options API) blocks.
"""

from __future__ import annotations

from pathlib import Path
import re

from .base import ParsedFile, Symbol
from .js_ts_parser import parse_js_ts


def parse_vue(path: Path, content: str, language: str) -> ParsedFile:
    """Parse a Vue SFC by extracting and analyzing the script block."""
    script_content, script_lang, is_setup = _extract_script_block(content)
    component_name = _detect_component_name(path, content, script_content)

    if not script_content:
        # No script block — still return file with template/style info
        symbols = []
        if component_name:
            symbols.append(_make_component_symbol(component_name))
        return ParsedFile(
            path=path,
            language="vue",
            symbols=symbols,
            imports=[],
            raw_content=content[:12000],
        )

    # Determine the effective language for the script block
    effective_lang = "typescript" if script_lang in ("ts", "tsx") else "javascript"

    # Parse the script block using the JS/TS parser
    parsed = parse_js_ts(path, script_content, effective_lang)

    # Override language to "vue" for clarity
    parsed.language = "vue"

    if component_name and component_name not in {s.name for s in parsed.symbols}:
        parsed.symbols.insert(0, _make_component_symbol(component_name))

    # Extract Vue-specific constructs
    if is_setup:
        _extract_script_setup_constructs(script_content, parsed.symbols)
    else:
        _extract_options_api_constructs(script_content, parsed.symbols)

    _extract_vue_runtime_features(script_content, parsed.symbols)

    # Detect template refs and slots from the template block
    template_content = _extract_template_block(content)
    if template_content:
        _extract_template_info(template_content, parsed.symbols)

    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# Script block extraction
# ─────────────────────────────────────────────────────────────────────────────

_TEMPLATE_PATTERN = re.compile(
    r"<template\b[^>]*>(.*?)</template>",
    re.DOTALL | re.IGNORECASE,
)


_VUE_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_VUE_EXECUTABLE_SCRIPT_TYPES = frozenset(
    {
        "module",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
    }
)
_VUE_RUNTIME_LANGUAGES = frozenset(
    {"js", "jsx", "ts", "tsx", "javascript", "typescript"}
)


def _vue_attr_value(attrs: str, name: str) -> str:
    """A quoted or bare SFC attribute value, without HTML interpretation."""
    match = re.search(
        rf"(?<![\w:-]){re.escape(name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))",
        attrs,
        re.I,
    )
    if match is None:
        return ""
    return next((value for value in match.groups() if value is not None), "")


def _is_executable_vue_script(attrs: str) -> bool:
    """Whether an inline SFC script can contribute JS/TS runtime evidence."""
    if re.search(r"(?<![\w:-])src(?:\s*=|\s|$)", attrs, re.I):
        return False
    script_type = _vue_attr_value(attrs, "type").split(";", 1)[0].strip().lower()
    if script_type and script_type not in _VUE_EXECUTABLE_SCRIPT_TYPES:
        return False
    language = _vue_attr_value(attrs, "lang").lower() or "js"
    return language in _VUE_RUNTIME_LANGUAGES


def _extract_script_blocks(content: str) -> tuple[tuple[str, str, bool], ...]:
    """All executable top-level SFC scripts in document order."""
    blocks: list[tuple[str, str, bool]] = []
    for attrs, body in _top_level_vue_script_blocks(content):
        if not _is_executable_vue_script(attrs):
            continue
        lang = _vue_attr_value(attrs, "lang").lower() or "js"
        is_setup = bool(re.search(r"(?:^|\s)setup(?:\s|=|$)", attrs, re.I))
        body = body.strip()
        if body:
            blocks.append((body, lang, is_setup))
    return tuple(blocks)


def _extract_script_block(content: str) -> tuple[str, str, bool]:
    """Extract the preferred script for legacy single-script parser consumers.

    Runtime scanning uses ``_extract_script_blocks`` so a normal script and a
    script-setup block remain separate executable binding scopes.
    """
    blocks = _extract_script_blocks(content)
    setup_blocks = [block for block in blocks if block[2]]
    if setup_blocks:
        script, lang, _ = setup_blocks[-1]
        return script, lang, True
    if blocks:
        script, lang, _ = blocks[-1]
        return script, lang, False
    return "", "js", False


def _top_level_vue_script_blocks(content: str):
    """Yield ``(attrs, body)`` only for executable, top-level SFC scripts."""
    lowered = content.lower()
    stack: list[str] = []
    position = 0
    while position < len(content):
        interpolation_start = content.find("{{", position)
        tag_start = content.find("<", position)
        if interpolation_start >= 0 and (
            tag_start < 0 or interpolation_start < tag_start
        ):
            interpolation_end = content.find("}}", interpolation_start + 2)
            if interpolation_end >= 0 and (
                tag_start < 0 or interpolation_end >= tag_start
            ):
                position = interpolation_end + 2
                continue
        if tag_start < 0:
            return
        if lowered.startswith("<!--", tag_start):
            comment_end = lowered.find("-->", tag_start + 4)
            position = len(content) if comment_end < 0 else comment_end + 3
            continue
        if lowered.startswith("</", tag_start):
            name_match = re.match(r"</\s*([A-Za-z][\w:-]*)", content[tag_start:])
            tag_end = content.find(">", tag_start + 2)
            if name_match and stack:
                name = name_match.group(1).lower()
                if stack[-1] == name:
                    stack.pop()
            position = len(content) if tag_end < 0 else tag_end + 1
            continue
        if lowered.startswith("<!", tag_start) or lowered.startswith("<?", tag_start):
            tag_end = content.find(">", tag_start + 2)
            position = len(content) if tag_end < 0 else tag_end + 1
            continue
        name_match = re.match(r"<\s*([A-Za-z][\w:-]*)", content[tag_start:])
        if name_match is None:
            position = tag_start + 1
            continue
        name = name_match.group(1).lower()
        attrs_start = tag_start + name_match.end()
        tag_end = _vue_tag_end(content, attrs_start)
        if tag_end is None:
            return
        attrs = content[attrs_start:tag_end]
        if name in {"script", "style"}:
            close_start = lowered.find(f"</{name}", tag_end + 1)
            if close_start < 0:
                return
            close_end = content.find(">", close_start + len(name) + 2)
            if close_end < 0:
                return
            if name == "script" and not stack:
                yield attrs, content[tag_end + 1:close_start]
            position = close_end + 1
            continue
        if not attrs.rstrip().endswith("/") and name not in _VUE_VOID_TAGS:
            stack.append(name)
        position = tag_end + 1


def _vue_tag_end(content: str, start: int) -> int | None:
    """Closing ``>`` of a tag, respecting quoted attribute values."""
    quote = ""
    for index in range(start, len(content)):
        char = content[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in {"\"", "'"}:
            quote = char
        elif char == ">":
            return index
    return None


def _extract_template_block(content: str) -> str:
    """Extract the <template> block content."""
    m = _TEMPLATE_PATTERN.search(content)
    return m.group(1).strip() if m else ""


# ─────────────────────────────────────────────────────────────────────────────
# <script setup> constructs (Composition API)
# ─────────────────────────────────────────────────────────────────────────────


def _extract_script_setup_constructs(script: str, symbols: list[Symbol]) -> None:
    """Extract defineProps, defineEmits, defineExpose from <script setup>."""
    existing_names = {s.name for s in symbols}

    # defineProps<Type>() or defineProps({ ... })
    props_match = re.search(
        r"(?:const\s+(\w+)\s*=\s*)?(?:withDefaults\s*\(\s*)?defineProps\s*(?:<([^>]+)>)?\s*\(([^)]*)\)",
        script,
        re.DOTALL,
    )
    if props_match:
        props_var = props_match.group(1) or "props"
        type_param = props_match.group(2) or ""
        obj_param = props_match.group(3) or ""

        # Extract prop names
        prop_names = []
        if type_param:
            # defineProps<{ name: string; age: number }>()
            for pm in re.finditer(r"(\w+)\s*[?:]", type_param):
                prop_names.append(pm.group(1))
        elif obj_param:
            # defineProps({ name: String, age: { type: Number } })
            for pm in re.finditer(r"(\w+)\s*:", obj_param):
                prop_names.append(pm.group(1))

        if props_var not in existing_names:
            symbols.append(
                Symbol(
                    name=props_var,
                    kind="constant",
                    signature="defineProps()",
                    docstring=f"Component props: {', '.join(prop_names)}"
                    if prop_names
                    else "Component props",
                    props=prop_names,
                    is_exported=True,
                )
            )

    # defineEmits
    emits_match = re.search(
        r"(?:const\s+(\w+)\s*=\s*)?defineEmits\s*(?:<([^>]+)>)?\s*\(([^)]*)\)",
        script,
        re.DOTALL,
    )
    if emits_match:
        emits_var = emits_match.group(1) or "emit"
        events = []
        raw = (emits_match.group(2) or "") + (emits_match.group(3) or "")
        for em in re.finditer(r"['\"](\w+)['\"]", raw):
            events.append(em.group(1))

        if emits_var not in existing_names:
            symbols.append(
                Symbol(
                    name=emits_var,
                    kind="constant",
                    signature="defineEmits()",
                    docstring=f"Emitted events: {', '.join(events)}"
                    if events
                    else "Component emits",
                    fields=events,
                    is_exported=True,
                )
            )

    # defineExpose
    expose_match = re.search(r"defineExpose\s*\(\s*\{([^}]*)\}", script)
    if expose_match:
        exposed = []
        for em in re.finditer(r"(\w+)", expose_match.group(1)):
            exposed.append(em.group(1))
        if exposed:
            symbols.append(
                Symbol(
                    name="expose",
                    kind="constant",
                    signature="defineExpose()",
                    docstring=f"Exposed: {', '.join(exposed)}",
                    fields=exposed,
                )
            )

    # defineModel
    model_match = re.search(
        r"(?:const\s+(\w+)\s*=\s*)?defineModel\s*(?:<[^>]+>)?\s*\(([^)]*)\)",
        script,
        re.DOTALL,
    )
    if model_match:
        model_name = model_match.group(1) or "model"
        raw_args = model_match.group(2) or ""
        named_model = re.search(r"['\"](\w+)['\"]", raw_args)
        doc = (
            f"Two-way binding model: {named_model.group(1)}"
            if named_model
            else "Two-way binding model"
        )
        if model_name not in existing_names:
            symbols.append(
                Symbol(
                    name=model_name,
                    kind="constant",
                    signature="defineModel()",
                    docstring=doc,
                    is_exported=True,
                )
            )
            existing_names.add(model_name)

    # defineSlots
    slots_match = re.search(r"defineSlots\s*<\s*\{([^>]+)\}\s*>", script, re.DOTALL)
    if slots_match and "slots" not in existing_names:
        slot_names = [
            m.group(1) for m in re.finditer(r"(\w+)\s*\??\s*:", slots_match.group(1))
        ]
        symbols.append(
            Symbol(
                name="slots",
                kind="constant",
                signature="defineSlots()",
                docstring=f"Typed slots: {', '.join(slot_names)}"
                if slot_names
                else "Typed slots",
                fields=slot_names,
            )
        )
        existing_names.add("slots")

    # Composition API reactivity primitives
    _extract_composition_refs(script, symbols, existing_names)


def _extract_composition_refs(
    script: str, symbols: list[Symbol], existing_names: set[str]
) -> None:
    """Extract ref(), reactive(), computed() declarations."""
    # const name = ref(initialValue)
    for m in re.finditer(
        r"const\s+(\w+)\s*=\s*(ref|reactive|computed|shallowRef|shallowReactive)\s*[<(]",
        script,
    ):
        name = m.group(1)
        api = m.group(2)
        if name not in existing_names:
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=f"const {name} = {api}(...)",
                    docstring=f"Reactive state ({api})",
                )
            )
            existing_names.add(name)


# ─────────────────────────────────────────────────────────────────────────────
# Options API constructs
# ─────────────────────────────────────────────────────────────────────────────


def _extract_options_api_constructs(script: str, symbols: list[Symbol]) -> None:
    """Extract props/emits/methods from Options API export default { ... }."""
    existing_names = {s.name for s in symbols}

    # Try to find the default export object
    export_match = re.search(
        r"export\s+default\s*(?:defineComponent\s*\(\s*)?\{(.*)\}",
        script,
        re.DOTALL,
    )
    if not export_match:
        return

    body = export_match.group(1)

    # Extract props
    props_match = re.search(r"props\s*:\s*\{([^}]+)\}", body)
    if props_match:
        prop_names = re.findall(r"(\w+)\s*:", props_match.group(1))
        if "props" not in existing_names and prop_names:
            symbols.append(
                Symbol(
                    name="props",
                    kind="constant",
                    signature="props: { ... }",
                    docstring=f"Component props: {', '.join(prop_names)}",
                    props=prop_names,
                )
            )

    # Extract props as array
    props_arr_match = re.search(r"props\s*:\s*\[([^\]]+)\]", body)
    if props_arr_match and "props" not in existing_names:
        prop_names = re.findall(r"['\"](\w+)['\"]", props_arr_match.group(1))
        if prop_names:
            symbols.append(
                Symbol(
                    name="props",
                    kind="constant",
                    signature="props: [...]",
                    docstring=f"Component props: {', '.join(prop_names)}",
                    props=prop_names,
                )
            )

    # Extract emits
    emits_match = re.search(r"emits\s*:\s*\[([^\]]+)\]", body)
    if emits_match:
        events = re.findall(r"['\"](\w+)['\"]", emits_match.group(1))
        if events and "emits" not in existing_names:
            symbols.append(
                Symbol(
                    name="emits",
                    kind="constant",
                    signature="emits: [...]",
                    docstring=f"Emitted events: {', '.join(events)}",
                    fields=events,
                )
            )

    methods_match = re.search(r"methods\s*:\s*\{([^}]+)\}", body, re.DOTALL)
    if methods_match:
        for method_match in re.finditer(
            r"(\w+)\s*\([^)]*\)\s*\{", methods_match.group(1)
        ):
            method_name = method_match.group(1)
            if method_name not in existing_names:
                symbols.append(
                    Symbol(
                        name=method_name,
                        kind="method",
                        signature=f"{method_name}(...)",
                        docstring="Component method",
                    )
                )
                existing_names.add(method_name)


# ─────────────────────────────────────────────────────────────────────────────
# Template analysis
# ─────────────────────────────────────────────────────────────────────────────


def _extract_template_info(template: str, symbols: list[Symbol]) -> None:
    """Extract component usage and slot info from template block."""
    # Detect child component usage (PascalCase tags)
    components_used = set()
    for m in re.finditer(r"<([A-Z]\w+)", template):
        components_used.add(m.group(1))

    # Detect named slots
    slots = set()
    for m in re.finditer(r'<slot\s+name\s*=\s*["\'](\w+)["\']', template):
        slots.add(m.group(1))
    # Default slot
    if "<slot" in template and not re.search(r"<slot\s+name", template):
        slots.add("default")

    # Add slot info as a symbol if slots exist
    if slots:
        symbols.append(
            Symbol(
                name="slots",
                kind="constant",
                signature=f"slots: [{', '.join(sorted(slots))}]",
                docstring=f"Named slots: {', '.join(sorted(slots))}",
                fields=sorted(slots),
            )
        )

    if components_used:
        symbols.append(
            Symbol(
                name="components",
                kind="constant",
                signature=f"components: [{', '.join(sorted(components_used))}]",
                docstring=f"Child components used: {', '.join(sorted(components_used))}",
                fields=sorted(components_used),
            )
        )


def _detect_component_name(path: Path, content: str, script: str) -> str:
    for source in (script, content):
        if not source:
            continue
        options_match = re.search(r"name\s*:\s*['\"]([A-Za-z][\w-]*)['\"]", source)
        if options_match:
            return options_match.group(1)
        define_options_match = re.search(
            r"defineOptions\s*\(\s*\{[^}]*name\s*:\s*['\"]([A-Za-z][\w-]*)['\"]",
            source,
            re.DOTALL,
        )
        if define_options_match:
            return define_options_match.group(1)
    stem = path.stem.replace("-", " ").replace("_", " ")
    return "".join(part.capitalize() for part in stem.split()) or path.stem


def _make_component_symbol(component_name: str) -> Symbol:
    return Symbol(
        name=component_name,
        kind="component",
        signature=f"component {component_name}",
        docstring="Vue single-file component",
        is_exported=True,
    )


def _extract_vue_runtime_features(script: str, symbols: list[Symbol]) -> None:
    existing_names = {s.name for s in symbols}

    runtime_patterns = [
        (r"\buseRouter\s*\(", "router", "Vue Router instance"),
        (r"\buseRoute\s*\(", "route", "Current Vue Router route"),
        (r"\bdefineStore\s*\(", "store", "Pinia store definition"),
        (r"\bstoreToRefs\s*\(", "storeRefs", "Pinia store refs"),
    ]
    for pattern, name, doc in runtime_patterns:
        if re.search(pattern, script) and name not in existing_names:
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=f"{name}()",
                    docstring=doc,
                )
            )
            existing_names.add(name)

    import_sources = [
        (r"from\s+['\"]vue-router['\"]", "vue-router", "Uses vue-router"),
        (r"from\s+['\"]pinia['\"]", "pinia", "Uses Pinia state management"),
        (r"from\s+['\"].*stores?/.*['\"]", "stores", "Imports app store modules"),
        (
            r"from\s+['\"].*composables?/.*['\"]",
            "composables",
            "Imports local composables",
        ),
    ]
    for pattern, name, doc in import_sources:
        if re.search(pattern, script) and name not in existing_names:
            symbols.append(
                Symbol(
                    name=name,
                    kind="constant",
                    signature=name,
                    docstring=doc,
                )
            )
            existing_names.add(name)
