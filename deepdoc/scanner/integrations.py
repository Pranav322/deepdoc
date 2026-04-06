from .common import *

def discover_integrations(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    config_files: list[str],
    repo_root: Path,
    llm: LLMClient | None = None,
) -> list[IntegrationIdentity]:
    """Detect external integrations and normalize into identities.

    1. Static scan for integration signals
    2. LLM grouping to normalize aliases into identities
    """
    # Step 1: Collect raw candidates
    candidates = _collect_integration_candidates(
        parsed_files, file_contents, config_files, repo_root
    )

    if not candidates:
        return []

    console.print(
        f"  [dim]Found {len(candidates)} integration signals across {len(set(c.file_path for c in candidates))} files[/dim]"
    )

    # Step 2: If LLM available, normalize via LLM; otherwise use heuristic
    if llm:
        return _normalize_integrations_llm(candidates, llm, repo_root)
    else:
        return _normalize_integrations_heuristic(candidates, repo_root)


def _collect_integration_candidates(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    config_files: list[str],
    repo_root: Path,
) -> list[IntegrationCandidate]:
    """Scan code for integration signals."""
    candidates: list[IntegrationCandidate] = []

    # Patterns for outbound HTTP calls
    http_patterns = [
        re.compile(r"requests\.(get|post|put|patch|delete)\s*\("),
        re.compile(r"axios\.(get|post|put|patch|delete)\s*\("),
        re.compile(r"fetch\s*\(\s*['\"]https?://"),
        re.compile(r"http\.(?:Get|Post|Put|Delete)\s*\("),
        re.compile(r"httpx\.(?:get|post|put|patch|delete)\s*\("),
        re.compile(r"aiohttp\.ClientSession"),
        re.compile(r"urllib\.request"),
        re.compile(r"Http::(?:get|post|put|patch|delete)\s*\("),
    ]

    # Patterns for SDK/client class instantiation
    sdk_patterns = [
        re.compile(r"(\w+)Client\s*\("),
        re.compile(r"(\w+)SDK\s*\("),
        re.compile(r"(\w+)API\s*\("),
        re.compile(r"(\w+)Gateway\s*\("),
        re.compile(r"(\w+)Provider\s*\("),
        re.compile(r"(\w+)Adapter\s*\("),
    ]

    # Patterns for env vars that suggest integrations
    env_var_patterns = [
        re.compile(
            r"""(?:os\.environ|os\.getenv|process\.env|env\(|getenv)\s*[\[(]\s*['"](\w*(?:API|URL|KEY|SECRET|TOKEN|HOST|ENDPOINT|WEBHOOK|BASE_URL)\w*)['"]"""
        ),
        re.compile(r"""(\w+_API_(?:KEY|URL|SECRET|TOKEN|BASE_URL|ENDPOINT))"""),
    ]

    # Webhook handler patterns
    webhook_patterns = [
        re.compile(r"webhook", re.IGNORECASE),
        re.compile(r"callback.*(?:url|endpoint|handler)", re.IGNORECASE),
    ]

    for file_path, parsed in parsed_files.items():
        content = file_contents.get(file_path, "")
        if not content:
            continue
        lines = content.splitlines()
        line_starts = [0]
        for line in lines:
            line_starts.append(line_starts[-1] + len(line) + 1)

        # Check imports for client/SDK patterns
        for imp in parsed.imports:
            for pat in sdk_patterns:
                m = pat.search(imp)
                if m:
                    name = m.group(1)
                    if name.lower() not in ("http", "base", "abstract", "mock", "test"):
                        candidates.append(
                            IntegrationCandidate(
                                signal_type="sdk_import",
                                name_hint=name.lower(),
                                file_path=file_path,
                                evidence=imp.strip()[:200],
                                confidence=0.8,
                            )
                        )

        # Check content for outbound HTTP calls
        for pat in http_patterns:
            for m in pat.finditer(content):
                line_num = _line_number_for_offset(line_starts, m.start())
                line = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                # Try to extract URL or target name
                url_match = re.search(
                    r"""['"]https?://([^/'"\s]+)""",
                    content[m.start() : m.start() + 300],
                )
                name = url_match.group(1).split(".")[0] if url_match else "unknown_http"
                candidates.append(
                    IntegrationCandidate(
                        signal_type="http_client",
                        name_hint=name.lower(),
                        file_path=file_path,
                        evidence=line[:200],
                        confidence=0.6,
                    )
                )

        # Check for env vars suggesting integrations
        for pat in env_var_patterns:
            for m in pat.finditer(content):
                env_var = m.group(1)
                # Extract the integration name from the env var
                name = re.sub(
                    r"_(?:API|URL|KEY|SECRET|TOKEN|HOST|ENDPOINT|WEBHOOK|BASE_URL).*$",
                    "",
                    env_var,
                )
                if name and name.lower() not in (
                    "app",
                    "db",
                    "database",
                    "redis",
                    "secret",
                    "debug",
                ):
                    candidates.append(
                        IntegrationCandidate(
                            signal_type="env_var",
                            name_hint=name.lower(),
                            file_path=file_path,
                            evidence=env_var,
                            confidence=0.7,
                        )
                    )

        # Check for webhook handlers
        for pat in webhook_patterns:
            for m in pat.finditer(content):
                line_num = _line_number_for_offset(line_starts, m.start())
                line = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                candidates.append(
                    IntegrationCandidate(
                        signal_type="webhook",
                        name_hint="webhook",
                        file_path=file_path,
                        evidence=line[:200],
                        confidence=0.5,
                    )
                )

    # Check symbol names for integration hints
    for file_path, parsed in parsed_files.items():
        for sym in parsed.symbols:
            name_lower = sym.name.lower()
            for suffix in (
                "client",
                "gateway",
                "provider",
                "adapter",
                "connector",
                "sync",
                "webhook",
            ):
                if suffix in name_lower and name_lower != suffix:
                    prefix = name_lower.replace(suffix, "").strip("_")
                    if prefix and prefix not in (
                        "http",
                        "base",
                        "abstract",
                        "test",
                        "mock",
                    ):
                        candidates.append(
                            IntegrationCandidate(
                                signal_type="sdk_import",
                                name_hint=prefix,
                                file_path=file_path,
                                evidence=f"{sym.kind} {sym.name} (line {sym.start_line})",
                                confidence=0.7,
                            )
                        )

    return candidates


def _normalize_integrations_llm(
    candidates: list[IntegrationCandidate],
    llm: LLMClient,
    repo_root: Path,
) -> list[IntegrationIdentity]:
    """Use LLM to group integration candidates into normalized identities."""
    # Build candidate summary for the LLM
    candidate_lines = []
    for c in candidates:
        candidate_lines.append(
            f"- [{c.signal_type}] name_hint='{c.name_hint}' file={c.file_path} evidence='{c.evidence}'"
        )

    prompt = f"""Analyze these integration signals and group them into normalized integration identities.

## Raw Integration Signals ({len(candidates)} total)
{chr(10).join(candidate_lines[:80])}
{"... +" + str(len(candidates) - 80) + " more" if len(candidates) > 80 else ""}

---

Group these signals into distinct external integration identities. Merge aliases
(e.g., "vinculum", "warehouse_sync", "VINCULUM_API_URL" → one identity "vinculum").

For each identity, determine if it's substantial enough for a standalone doc page
(appears in multiple files, has meaningful setup/runtime behavior) or should be
embedded in feature docs only.

Return JSON:
{{
  "integrations": [
    {{
      "name": "vinculum",
      "display_name": "Vinculum Warehouse Management",
      "description": "Warehouse management system for inventory sync and order fulfillment",
      "is_substantial": true,
      "candidate_indices": [0, 3, 7, 12]
    }}
  ]
}}

candidate_indices = which signals (by 0-based index) belong to this identity."""

    system = "You are a code analysis expert. Normalize integration signals into identities. Respond with valid JSON only."

    try:
        response = llm.complete(system, prompt)
        result = _parse_json(response)
    except Exception as e:
        console.print(f"  [yellow]⚠ LLM integration normalization failed: {e}[/yellow]")
        return _normalize_integrations_heuristic(candidates, repo_root)

    identities = []
    for item in result.get("integrations", []):
        indices = item.get("candidate_indices", [])
        files: set[str] = set()
        evidence: list[str] = []

        for idx in indices:
            if 0 <= idx < len(candidates):
                files.add(candidates[idx].file_path)
                evidence.append(candidates[idx].evidence)

        # Also collect files by name match from all candidates
        name = item.get("name", "").lower()
        for c in candidates:
            if name in c.name_hint.lower() or c.name_hint.lower() in name:
                files.add(c.file_path)

        identities.append(
            IntegrationIdentity(
                name=name,
                display_name=item.get("display_name", name.title()),
                description=item.get("description", ""),
                files=sorted(files),
                evidence=evidence[:10],
                is_substantial=item.get("is_substantial", len(files) >= 3),
                party=classify_integration_party(name, repo_root),
            )
        )

    return identities


def _normalize_integrations_heuristic(
    candidates: list[IntegrationCandidate],
    repo_root: Path,
) -> list[IntegrationIdentity]:
    """Fallback: group candidates by name_hint similarity."""
    groups: dict[str, list[IntegrationCandidate]] = defaultdict(list)
    for c in candidates:
        groups[c.name_hint].append(c)

    identities = []
    for name, cands in sorted(groups.items(), key=lambda x: -len(x[1])):
        if name in ("unknown_http", "webhook", "unknown"):
            continue
        files = sorted(set(c.file_path for c in cands))
        identities.append(
            IntegrationIdentity(
                name=name,
                display_name=name.replace("_", " ").title(),
                description=f"External integration: {name}",
                files=files,
                evidence=[c.evidence for c in cands[:5]],
                is_substantial=len(files) >= 3,
                party=classify_integration_party(name, repo_root),
            )
        )

    return identities


def _line_number_for_offset(line_starts: list[int], offset: int) -> int:
    """Map a character offset to a 1-based line number using the cached line starts."""
    lo = 0
    hi = len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if line_starts[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid
    return max(1, lo)


def _detect_integration_edges_in_bundle(
    evidence: list[EvidenceUnit],
    parsed_files: dict[str, ParsedFile],
) -> list[str]:
    """Detect integration system names from the evidence files."""
    integration_hints: set[str] = set()

    for eu in evidence:
        parsed = parsed_files.get(eu.file_path)
        if not parsed:
            continue

        # Check imports for known SDK/client patterns
        for imp in parsed.imports:
            imp_lower = imp.lower()
            if any(
                kw in imp_lower for kw in ("client", "sdk", "api", "http", "request")
            ):
                # Extract a name hint
                parts = WORD_TOKEN_RE.findall(imp)
                for part in parts:
                    if part.lower() not in (
                        "import",
                        "from",
                        "client",
                        "sdk",
                        "api",
                        "http",
                        "request",
                        "requests",
                        "axios",
                        "fetch",
                        "self",
                    ) and len(part) > 2:
                        integration_hints.add(part.lower())

    return sorted(integration_hints)


from .utils import _parse_json
