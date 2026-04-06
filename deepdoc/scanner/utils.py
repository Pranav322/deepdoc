from .common import *
from ..llm.json_utils import parse_llm_json

def _build_import_lookup(all_files: set[str]) -> dict[str, set[str]]:
    """Pre-index normalized file suffixes so import resolution avoids full scans."""
    lookup: dict[str, set[str]] = defaultdict(set)
    for file_path in all_files:
        normalized = FILE_EXT_RE.sub("", file_path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        for i in range(len(parts)):
            lookup["/".join(parts[i:])].add(file_path)
        if parts:
            lookup[parts[-1]].add(file_path)
    return lookup


def _resolve_imports_to_files(
    imports: list[str],
    current_file: str,
    import_lookup: dict[str, set[str]],
) -> set[str]:
    """Resolve import statements to actual repo files.

    Uses suffix matching — not perfect but works for 80%+ of cases.
    """
    resolved: set[str] = set()

    for imp in imports:
        # Normalize the import to a path hint
        hints = _normalize_import(imp)
        for hint in hints:
            hint_parts = hint.replace(".", "/").replace("\\", "/").strip("/").lower()
            if not hint_parts:
                continue
            for candidate in import_lookup.get(hint_parts, set()):
                if candidate != current_file:
                    resolved.add(candidate)

    return resolved


def _normalize_import(imp: str) -> list[str]:
    """Extract clean module path hints from an import statement."""
    hints = []

    # Python: from app.services.auth import X
    m = IMPORT_FROM_RE.match(imp)
    if m:
        hints.append(m.group(1).replace(".", "/"))
        return hints

    # Python: import app.services.auth
    m = IMPORT_PLAIN_RE.match(imp)
    if m:
        hints.append(m.group(1).replace(".", "/"))
        return hints

    # JS/TS: import { X } from '../models/user'
    m = JS_FROM_RE.search(imp)
    if m:
        path = m.group(1)
        # Remove ./ ../ prefixes for matching
        path = re.sub(r"^\.{1,2}/", "", path)
        hints.append(path)
        return hints

    # JS/TS: require('./services/payment')
    m = JS_REQUIRE_RE.search(imp)
    if m:
        path = m.group(1)
        path = re.sub(r"^\.{1,2}/", "", path)
        hints.append(path)
        return hints

    # Go: import "github.com/repo/pkg/auth"
    m = GO_IMPORT_RE.search(imp)
    if m:
        hints.append(m.group(1).split("/")[-1])  # just the package name
        return hints

    # PHP: use App\Services\AuthService
    m = PHP_USE_RE.match(imp)
    if m:
        hints.append(m.group(1).replace("\\", "/"))
        return hints

    return hints


def _classify_file_role(file_path: str, parsed: ParsedFile | None) -> str:
    """Classify a file's role based on its path and symbols."""
    path_lower = file_path.lower()

    role_patterns = [
        ("test", ["test", "spec", "__tests__"]),
        ("config", ["config", "settings", ".env"]),
        ("model", ["model", "schema", "entity"]),
        ("validator", ["validator", "validation", "serializer"]),
        ("middleware", ["middleware", "auth"]),
        ("task", ["task", "job", "queue", "worker", "celery"]),
        ("service", ["service"]),
        ("util", ["util", "helper", "lib", "common"]),
    ]

    for role, patterns in role_patterns:
        for p in patterns:
            if p in path_lower:
                return role

    # Check symbols for route decorators
    if parsed and parsed.symbols:
        for s in parsed.symbols:
            if (
                s.kind == "route"
                or "route" in s.name.lower()
                or "handler" in s.name.lower()
            ):
                return "handler"

    return "service"  # default


def endpoint_owned_files(endpoint: dict[str, Any]) -> list[str]:
    files = [
        endpoint.get("route_file", ""),
        endpoint.get("handler_file", ""),
        endpoint.get("file", ""),
    ]
    return sorted({f for f in files if f})


def fnmatch_simple(filename: str, pattern: str) -> bool:
    """Simple filename matching without glob."""
    return filename.lower() == pattern.lower() or pattern.lower() in filename.lower()


def _parse_json(response: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    return parse_llm_json(response)

