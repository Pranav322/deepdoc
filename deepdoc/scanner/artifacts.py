from .common import *

def discover_config_impacts(
    file_contents: dict[str, str],
    api_endpoints: list[dict[str, Any]],
) -> list[ConfigImpact]:
    """Detect env/config keys and map them to related files and endpoints."""
    impacts: dict[tuple[str, str, str], ConfigImpact] = {}
    endpoint_records = [
        (
            f"{str(ep.get('method', 'GET')).upper()} {ep.get('path', '')}",
            {path for path in endpoint_owned_files(ep)},
        )
        for ep in api_endpoints
    ]

    env_patterns = [
        re.compile(r"""os\.environ\s*\[\s*['\"]([A-Z][A-Z0-9_]+)['\"]\s*\]"""),
        re.compile(
            r"""os\.(?:getenv|environ\.get)\s*\(\s*['\"]([A-Z][A-Z0-9_]+)['\"](?:\s*,\s*([^\)]*))?\)"""
        ),
        re.compile(r"""process\.env\.([A-Z][A-Z0-9_]+)"""),
        re.compile(r"""env\s*\(\s*['\"]([A-Z][A-Z0-9_]+)['\"](?:\s*,\s*([^\)]*))?\)"""),
        re.compile(
            r"""getenv\s*\(\s*['\"]([A-Z][A-Z0-9_]+)['\"](?:\s*,\s*([^\)]*))?\)"""
        ),
    ]
    setting_patterns = [
        re.compile(r"""settings\.([A-Z][A-Z0-9_]+)"""),
        re.compile(
            r"""config\.(?:get|has)\s*\(\s*['\"]([A-Za-z0-9_.-]+)['\"](?:\s*,\s*([^\)]*))?\)"""
        ),
        re.compile(r"""config\[['\"]([A-Za-z0-9_.-]+)['\"]\]"""),
        re.compile(
            r"""Config::(?:get|has)\s*\(\s*['\"]([A-Za-z0-9_.-]+)['\"](?:\s*,\s*([^\)]*))?\)"""
        ),
    ]

    for file_path, content in file_contents.items():
        if not content:
            continue
        nearby_files = _config_related_files(content, file_path, file_contents)
        related_endpoints = sorted(
            key
            for key, owned_files in endpoint_records
            if file_path in owned_files or (nearby_files & owned_files)
        )
        for pattern in env_patterns:
            for match in pattern.finditer(content):
                key = match.group(1)
                default_value = _clean_default_value(
                    match.group(2) if match.lastindex and match.lastindex >= 2 else ""
                )
                impact_key = (key, "env_var")
                impact = impacts.setdefault(
                    impact_key,
                    ConfigImpact(
                        key=key,
                        kind="env_var",
                        file_path=file_path,
                    ),
                )
                if default_value and not impact.default_value:
                    impact.default_value = default_value
                impact.related_files = sorted(set(impact.related_files) | nearby_files)
                impact.related_endpoints = sorted(
                    set(impact.related_endpoints) | set(related_endpoints)
                )
        for pattern in setting_patterns:
            for match in pattern.finditer(content):
                key = match.group(1)
                kind = "setting" if key.isupper() else "config_key"
                default_value = _clean_default_value(
                    match.group(2) if match.lastindex and match.lastindex >= 2 else ""
                )
                impact_key = (key, kind)
                impact = impacts.setdefault(
                    impact_key,
                    ConfigImpact(
                        key=key,
                        kind=kind,
                        file_path=file_path,
                    ),
                )
                if default_value and not impact.default_value:
                    impact.default_value = default_value
                impact.related_files = sorted(set(impact.related_files) | nearby_files)
                impact.related_endpoints = sorted(
                    set(impact.related_endpoints) | set(related_endpoints)
                )

    return sorted(
        impacts.values(), key=lambda item: (item.kind, item.key, item.file_path)
    )


def _config_related_files(
    content: str,
    file_path: str,
    file_contents: dict[str, str],
) -> set[str]:
    related = {file_path}
    for path_hint in re.findall(
        r"""['\"]([^'\"]+\.(?:py|js|ts|php|go|json|ya?ml|toml|env))['\"]""", content
    ):
        normalized = path_hint.strip().lstrip("./")
        if normalized in file_contents:
            related.add(normalized)
    return related


def _clean_default_value(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.strip()
    if len(text) > 80:
        text = text[:77] + "..."
    return text


def discover_artifacts(
    repo_root: Path,
    file_tree: dict[str, list[str]],
    parsed_files: dict[str, ParsedFile] | None = None,
    file_contents: dict[str, str] | None = None,
) -> ArtifactScan:
    """Scan the file tree for setup, deploy, test, CI, ops artifacts AND database schema."""
    result = ArtifactScan()

    all_files: list[str] = []
    for dir_path, files in file_tree.items():
        for f in files:
            rel = f"{dir_path}/{f}" if dir_path != "." else f
            all_files.append(rel)

    for rel in all_files:
        fname = rel.split("/")[-1]
        rel_lower = rel.lower()

        for pat in SETUP_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.setup_artifacts.append(rel)
                break

        for pat in DEPLOY_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.deploy_artifacts.append(rel)
                break

        for pat in CI_PATTERNS:
            if pat.lower() in rel_lower:
                result.ci_artifacts.append(rel)
                break

        for pat in TEST_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.test_artifacts.append(rel)
                break

        for pat in OPS_PATTERNS:
            if pat.lower() in rel_lower:
                result.ops_artifacts.append(rel)
                break

    # Database/schema discovery
    if parsed_files and file_contents:
        result.database_scan = discover_database_schema(
            parsed_files, file_contents, file_tree, repo_root
        )

    return result


def discover_debug_signals(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    api_endpoints: list[Any] = None,
) -> list[DebugSignal]:
    """Scan the repository for debugging and observability signals.

    Used by the planner to decide whether to generate a Debugging & Observability
    runbook page.  Returns a flat list of DebugSignal objects covering loggers,
    exception patterns, health endpoints, monitoring hooks, cache keys, and
    retry/circuit-breaker patterns.
    """
    signals: list[DebugSignal] = []

    def _endpoint_value(endpoint: Any, key: str, default: str = "") -> str:
        if isinstance(endpoint, dict):
            value = endpoint.get(key, default)
        else:
            value = getattr(endpoint, key, default)
        return value or default

    # ── Health endpoints ──────────────────────────────────────────────────
    if api_endpoints:
        health_eps = [
            ep
            for ep in api_endpoints
            if any(hp in _endpoint_value(ep, "path").lower() for hp in _HEALTH_PATHS)
        ]
        if health_eps:
            signals.append(
                DebugSignal(
                    signal_type="health_endpoint",
                    name="health_endpoints",
                    file_path=(
                        _endpoint_value(health_eps[0], "file_path")
                        or _endpoint_value(health_eps[0], "handler_file")
                        or _endpoint_value(health_eps[0], "file")
                        or _endpoint_value(health_eps[0], "route_file")
                    ),
                    description=f"{len(health_eps)} health/readiness endpoint(s) detected",
                    patterns=[_endpoint_value(ep, "path") for ep in health_eps[:6]],
                    files=list(
                        {
                            _endpoint_value(ep, "file_path")
                            or _endpoint_value(ep, "handler_file")
                            or _endpoint_value(ep, "file")
                            or _endpoint_value(ep, "route_file")
                            for ep in health_eps
                        }
                    ),
                )
            )

    # ── Per-file signals ─────────────────────────────────────────────────
    logger_files: list[str] = []
    logger_levels: set[str] = set()
    exception_patterns: list[str] = []
    monitoring_files: list[str] = []
    retry_files: list[str] = []
    cache_key_patterns: list[str] = []
    circuit_files: list[str] = []

    for file_path, content in file_contents.items():
        if not content:
            continue

        # Logger usage
        lvls = {m.group(1).lower() for m in _LOG_RE.finditer(content)}
        if lvls:
            logger_files.append(file_path)
            logger_levels |= lvls

        # Exception handlers — capture non-trivial ones
        for m in _EXCEPT_RE.finditer(content):
            exc = m.group(1).strip()
            if exc.lower() not in (
                "exception",
                "baseexception",
                "e",
                "err",
                "ex",
                "error",
            ):
                exception_patterns.append(exc[:80])

        # Monitoring hooks
        if _MONITORING_RE.search(content):
            monitoring_files.append(file_path)

        # Cache/Redis key patterns
        for m in _REDIS_KEY_RE.finditer(content):
            cache_key_patterns.append(m.group(1)[:60])

        # Retry patterns
        if _RETRY_RE.search(content):
            retry_files.append(file_path)

        # Circuit breaker
        if _CIRCUIT_RE.search(content):
            circuit_files.append(file_path)

    if logger_files:
        error_files = [
            f
            for f, c in file_contents.items()
            if c
            and _LOG_RE.search(c)
            and any(
                m.group(1).lower() in ("error", "critical", "exception")
                for m in _LOG_RE.finditer(c)
            )
        ]
        signals.append(
            DebugSignal(
                signal_type="logger",
                name="application_logging",
                file_path=error_files[0] if error_files else logger_files[0],
                description=(
                    f"Structured logging across {len(logger_files)} files; "
                    f"levels used: {', '.join(sorted(logger_levels))}; "
                    f"{len(error_files)} file(s) log errors/criticals"
                ),
                patterns=sorted(logger_levels),
                files=logger_files[:10],
            )
        )

    if exception_patterns:
        unique_excs = list(dict.fromkeys(exception_patterns))[:12]
        signals.append(
            DebugSignal(
                signal_type="exception_handler",
                name="exception_handling",
                file_path="",
                description=f"{len(unique_excs)} distinct exception types handled across the codebase",
                patterns=unique_excs,
            )
        )

    if monitoring_files:
        signals.append(
            DebugSignal(
                signal_type="monitoring",
                name="observability_instrumentation",
                file_path=monitoring_files[0],
                description=f"Monitoring/metrics instrumentation found in {len(monitoring_files)} file(s)",
                files=monitoring_files[:8],
            )
        )

    if cache_key_patterns:
        unique_keys = list(dict.fromkeys(cache_key_patterns))[:12]
        signals.append(
            DebugSignal(
                signal_type="cache_keys",
                name="redis_cache_keys",
                file_path="",
                description=f"{len(unique_keys)} Redis/cache key pattern(s) detected",
                patterns=unique_keys,
            )
        )

    if retry_files:
        signals.append(
            DebugSignal(
                signal_type="retry",
                name="retry_patterns",
                file_path=retry_files[0],
                description=f"Retry/backoff configuration found in {len(retry_files)} file(s)",
                files=retry_files[:6],
            )
        )

    if circuit_files:
        signals.append(
            DebugSignal(
                signal_type="circuit_breaker",
                name="circuit_breakers",
                file_path=circuit_files[0],
                description=f"Circuit-breaker / fallback patterns in {len(circuit_files)} file(s)",
                files=circuit_files[:6],
            )
        )

    return signals


from .utils import endpoint_owned_files, fnmatch_simple
from .database import discover_database_schema
